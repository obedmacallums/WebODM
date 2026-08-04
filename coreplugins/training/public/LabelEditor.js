import L from 'leaflet';
import PluginsAPI from 'webodm/classes/plugins/API';
import { strokeWeightPx, classColor, ERASER_COLOR, ERASER_DASH,
         REVIEW_COLOR, REVIEW_DASH } from './labelLayer';

/**
 * Dibujo de etiquetas sobre la ortofoto: polígonos, línea central, ignorar y área revisada.
 *
 * Extiende el enfoque de `coreplugins/annotations/public/PolylineEditor.js` en Leaflet puro, sin
 * librerías nuevas (FR-037, D10). Un polígono es una polilínea cerrada; un trazo de pincel es una
 * polilínea con un radio en metros.
 *
 * Lo que sí es nuevo aquí y no tiene precedente en el repositorio (D10):
 *
 * 1. **Arrastre continuo.** El pincel captura `mousemove` con el botón pulsado, no clics sueltos.
 * 2. **Radio sobre el terreno.** El grosor se recalcula con `strokeWeightPx` en cada zoom, para
 *    que el trazo represente siempre los mismos metros (FR-010).
 * 3. **El mapa no se desplaza mientras se pinta.** Sin desactivar `dragging`, el primer arrastre
 *    movería el mapa en vez de dibujar.
 *
 * El popup de la ortofoto del core se silencia durante el trazado vía `PluginsAPI.Map.onHandleClick`,
 * que es lo que más caro habría salido descubrir por cuenta propia.
 */

// Separación mínima entre puntos capturados de un trazo, en píxeles de pantalla. Sin ella, un
// arrastre de unos segundos genera miles de vértices que no aportan nada: la simplificación del
// backend (FR-015) los descartaría igual, pero antes habrían viajado por la red.
const MIN_POINT_DISTANCE_PX = 4;

// Radio en píxeles para clicar la línea e insertar un vértice: el trazo es fino, así que sin
// tolerancia habría que acertarlo al píxel.
const INSERT_TOLERANCE_PX = 12;
// Un click pegado a un vértice existente es un intento de arrastrarlo o de borrarlo, no de
// insertar uno nuevo encima.
const VERTEX_GRAB_PX = 10;

const VERTEX_ICON = L.divIcon({className: 'training-vertex-marker', iconSize: [10, 10]});

export const MODE_NONE = null;
export const MODE_POLYGON = 'polygon';
export const MODE_BRUSH = 'brush';
export const MODE_ERASER = 'eraser';
// Marcar terreno como revisado es dibujar un polígono, pero lo que afirma no es «aquí hay esto»
// sino «esto lo he mirado». De ahí que sea un modo propio y no una clase más: dentro de un área
// revisada, lo que no lleve etiqueta pasa a ser fondo real (0) en vez de «no lo sé» (255).
export const MODE_REVIEW = 'review';
export const MODE_SELECT = 'select';
// Selección asistida (`010`). El gesto es el del pincel —pulsar, arrastrar, soltar— pero lo que
// produce no es geometría: son los puntos del terreno que el usuario ha señalado. La región que
// corresponde a cada punto la calcula el servidor, así que este editor **no** construye la etiqueta;
// emite el gesto y `assistLayer.js` se encarga del resto. Mezclar aquí la red habría hecho que el
// editor dependiera de un dataset y de una tarea, que es justo lo que no sabe.
export const MODE_ASSIST = 'assist';

/**
 * Vértices de una capa, sea polígono o polilínea.
 *
 * `getLatLngs()` de un `L.Polygon` devuelve un array de **anillos** y el de una `L.Polyline` un
 * array plano. Sin esta distinción, editar un polígono devolvería el anillo entero como si fuera
 * un vértice.
 */
function ringOf(layer){
  const latlngs = layer.getLatLngs();
  return Array.isArray(latlngs[0]) ? latlngs[0] : latlngs;
}

function setRing(layer, ring){
  const latlngs = layer.getLatLngs();
  if (Array.isArray(latlngs[0])) layer.setLatLngs([ring]);
  else layer.setLatLngs(ring);
}

export default class LabelEditor {
  constructor(options = {}){
    this.L = options.L || L;
    this.map = options.map;
    this.classes = options.classes || [];
    this.classIndex = options.classIndex !== undefined ? options.classIndex : null;
    this.radiusM = options.radiusM || 6;   // 12 m de ancho total, la pista minera típica
    this.hardNegative = !!options.hardNegative;
    this.onCreate = options.onCreate || function(){};
    this.onSelect = options.onSelect || function(){};
    this.onExitMode = options.onExitMode || function(){};
    // Gesto de selección asistida: `onAssistPreview` va llegando mientras se arrastra y `onAssist`
    // una sola vez al soltar. Los dos reciben la lista de puntos `[lon, lat]` acumulada.
    this.onAssist = options.onAssist || function(){};
    this.onAssistPreview = options.onAssistPreview || function(){};
    this.pluginsAPI = options.pluginsAPI || (typeof PluginsAPI !== 'undefined' ? PluginsAPI : null);

    this.mode = MODE_NONE;
    this.points = [];        // [lon, lat], el orden en que se guarda (D4)
    this.preview = null;
    this.drawing = false;
    this._handlers = {};
    this._suppressClicks = false;

    this._drawVertexMarkers = [];
    this.rubberBand = null;
    this.editingLayer = null;
    this._editVertexMarkers = [];
    this._coreClickHooked = false;
    this._handleCoreClick = this._handleCoreClick.bind(this);

    this._bind();
  }

  // --- Ciclo de vida ------------------------------------------------------------------

  _bind(){
    this._handlers = {
      click: e => this._onClick(e),
      dblclick: e => this._onDoubleClick(e),
      mousedown: e => this._onMouseDown(e),
      mousemove: e => this._onMouseMove(e),
      mouseup: e => this._onMouseUp(e),
      zoomend: () => this._restyle()
    };
    Object.keys(this._handlers).forEach(name => this.map.on(name, this._handlers[name]));

    // Escape en dos tiempos: primero descarta el trazo a medias y, si no hay ninguno, suelta la
    // herramienta. Así una sola tecla sirve tanto para «este polígono no» como para «ya no quiero
    // dibujar», que es lo que hace falta para volver a poder seleccionar etiquetas.
    this._onKeyDown = e => {
      if (e.key !== 'Escape') return;
      if (this.points.length){ this.cancel(); return; }
      if (this.isActive()) this.onExitMode();
    };
    document.addEventListener('keydown', this._onKeyDown);
  }

  remove(){
    Object.keys(this._handlers).forEach(name => this.map.off(name, this._handlers[name]));
    document.removeEventListener('keydown', this._onKeyDown);
    this.stopEditing();
    this._discardPreview();
    // El modo se apaga **antes** de sincronizar el hook: `_syncCoreClickHook` decide por
    // `isActive()`, así que con el modo todavía puesto concluiría que el hook hace falta y lo
    // dejaría enganchado a un editor ya destruido.
    this.mode = MODE_NONE;
    this._restoreMap();
    this._syncCoreClickHook();
  }

  // --- El popup de la ortofoto del core -------------------------------------------------

  /**
   * Se registra un **único** hook, y solo mientras hace falta.
   *
   * El core hace `if (PluginsAPI.Map.handleClick(e)) return;` en su manejador de clic
   * (`app/static/app/js/components/Map.jsx`), así que devolver `true` significa «me lo quedo, no
   * abras el popup de la ortofoto» y `false` «no es mío, sigue tu curso».
   *
   * **La regla del bus manda**: fuera de dibujo o edición hay que devolver `false`, o ningún otro
   * plugin —ni el propio core— volvería a ver un clic del mapa mientras el panel esté abierto.
   * Mismo patrón que `coreplugins/annotations/public/PolylineEditor.js:136-162`.
   */
  _syncCoreClickHook(){
    const api = this.pluginsAPI && this.pluginsAPI.Map;
    if (!api || !api.onHandleClick) return;

    const wanted = this.isActive() || !!this.editingLayer;
    if (wanted === this._coreClickHooked) return;
    if (wanted) api.onHandleClick(this._handleCoreClick);
    else if (api.offHandleClick) api.offHandleClick(this._handleCoreClick);
    this._coreClickHooked = wanted;
  }

  _handleCoreClick(e){
    // Dibujando se consume todo: cada clic dejaría si no un popup, y su `autoPan` movería el mapa
    // a mitad del trazo.
    if (this.isActive()) return true;
    // Editando solo se consume el clic que va a insertar un vértice; el resto del mapa sigue
    // abriendo el popup de la ortofoto como siempre.
    return !!this.editingLayer && !!this._hitTestLine(e);
  }

  // --- Configuración ------------------------------------------------------------------

  setMode(mode){
    if (this.mode === mode) return;
    this._cancel();
    // Salir del modo selección deja de editar: los manejadores de vértices de una etiqueta que ya
    // no se está editando quedarían flotando sobre el mapa.
    if (mode !== MODE_SELECT) this.stopEditing();
    this.mode = mode;
    if (this.isActive()) this._takeOverMap();
    else this._restoreMap();
    this._syncCoreClickHook();
  }

  setClassIndex(index){ this.classIndex = index; }
  setRadius(meters){
    this.radiusM = meters;
    this._restyle();
  }
  setClasses(classes){ this.classes = classes || []; }

  isActive(){
    return this.mode === MODE_POLYGON || this.mode === MODE_BRUSH ||
           this.mode === MODE_ERASER || this.mode === MODE_REVIEW ||
           this.mode === MODE_ASSIST;
  }

  isBrush(){ return this.mode === MODE_BRUSH || this.mode === MODE_ERASER; }

  /**
   * Selección asistida.
   *
   * **No** es `isBrush()` aunque el gesto se parezca: el pincel produce una polilínea con radio y
   * este produce una lista de puntos que el servidor convierte en regiones. Meterlo en `isBrush()`
   * habría hecho que `finish()` fabricara un `stroke` con el rastro del cursor.
   */
  isAssist(){ return this.mode === MODE_ASSIST; }

  /** Los dos modos que se dibujan clic a clic cerrando un anillo. */
  isRing(){ return this.mode === MODE_POLYGON || this.mode === MODE_REVIEW; }

  /**
   * La clase que se asignará.
   *
   * `null` en «ignorar» y en «área revisada», pero por motivos distintos: la primera manda esos
   * píxeles a 255 y la segunda no pinta clase ninguna, solo declara el terreno mirado. Lo que
   * ninguna de las dos hace es pintar la clase 0, que sería afirmar «aquí no hay camino»
   * (FR-014, FR-026).
   */
  activeClassIndex(){
    return (this.mode === MODE_ERASER || this.mode === MODE_REVIEW) ? null : this.classIndex;
  }

  /** Marca el área revisada en curso como negativo difícil (FR-043). */
  setHardNegative(value){ this.hardNegative = !!value; }

  // --- El mapa cede el control mientras se dibuja --------------------------------------

  _takeOverMap(){
    if (this.map.dragging && this.map.dragging.enabled()){
      this._draggingWasEnabled = true;
      this.map.dragging.disable();
    }
    if (this.map.doubleClickZoom && this.map.doubleClickZoom.enabled()){
      this._dblClickZoomWasEnabled = true;
      this.map.doubleClickZoom.disable();
    }
    if (this.map.getContainer) this.map.getContainer().style.cursor = 'crosshair';
  }

  _restoreMap(){
    if (this._draggingWasEnabled && this.map.dragging) this.map.dragging.enable();
    if (this._dblClickZoomWasEnabled && this.map.doubleClickZoom) this.map.doubleClickZoom.enable();
    this._draggingWasEnabled = false;
    this._dblClickZoomWasEnabled = false;
    if (this.map.getContainer) this.map.getContainer().style.cursor = '';
  }

  // --- Polígono ------------------------------------------------------------------------

  _onClick(e){
    if (this.mode === MODE_SELECT){
      this.onSelect(e);
      return;
    }
    if (!this.isRing() || this._suppressClicks) return;
    this._pushPoint(e.latlng);
    this._updatePreview();
  }

  _onDoubleClick(e){
    if (!this.isRing()) return;
    // Un doble clic del navegador dispara dos `click` antes que este evento, así que el último
    // vértice está puesto dos veces: se descarta el sobrante y se cierra. Sin esto el polígono
    // guardaría dos vértices idénticos y el lado que forman mediría cero (mismo caso que
    // `PolylineEditor._handleDblClick` de `annotations`).
    if (this.points.length > 1){
      const last = this.points[this.points.length - 1];
      const previous = this.points[this.points.length - 2];
      if (last[0] === previous[0] && last[1] === previous[1]){
        this.points.pop();
        this._popVertexMarker();
      }
    }
    this.finish();
  }

  // --- Pincel y borrador ---------------------------------------------------------------

  _onMouseDown(e){
    // La selección asistida usa el mismo gesto que el pincel, así que un clic suelto también pasa
    // por aquí y por `_onMouseUp`: no hace falta tocar `_onClick`, y de hecho no debe tocarse, o un
    // clic contaría dos veces.
    if (this.isAssist()){
      this.drawing = true;
      this.points = [];
      this._pushPoint(e.latlng);
      this.onAssistPreview(this.points.slice());
      return;
    }
    if (!this.isBrush()) return;
    this.drawing = true;
    this.points = [];
    this._pushPoint(e.latlng);
    this._updatePreview();
  }

  _onMouseMove(e){
    if (this.drawing && this.isAssist()){
      if (this._farEnough(e.latlng)){
        this._pushPoint(e.latlng);
        this.onAssistPreview(this.points.slice());
      }
      return;
    }
    if (this.drawing && this.isBrush()){
      if (this._farEnough(e.latlng)) {
        this._pushPoint(e.latlng);
        this._updatePreview();
      }
      return;
    }
    // Trazando un polígono, el cursor arrastra una línea elástica que enseña dónde caería el
    // tramo siguiente. Sin ella hay que clicar para descubrir el resultado, y corregir un vértice
    // mal puesto cuesta cerrar la figura y volver a empezar.
    if (this.isRing() && this.points.length) this._updateRubberBand(e.latlng);
  }

  /**
   * Línea elástica: del último vértice al cursor y, con dos o más vértices, de vuelta al primero.
   *
   * El segundo tramo es lo que hace útil la ayuda en un polígono: lo que se está dibujando es una
   * superficie cerrada, así que la pregunta no es solo «por dónde sigue la línea» sino «qué
   * superficie encierra si cierro aquí».
   */
  _updateRubberBand(latlng){
    const last = this.points[this.points.length - 1];
    const first = this.points[0];

    const path = [[last[1], last[0]], [latlng.lat, latlng.lng]];
    if (this.points.length >= 2) path.push([first[1], first[0]]);

    const style = {
      color: classColor(this.classes, this.activeClassIndex()),
      weight: 2,
      opacity: 0.7,
      // Discontinua y sin relleno para que no se confunda con lo ya trazado: es una previsión,
      // no parte de la etiqueta todavía.
      dashArray: '5 5',
      // No debe capturar el ratón: se dibuja justo bajo el cursor, y si lo capturara el clic
      // siguiente caería en ella en vez de en el mapa.
      interactive: false
    };

    if (!this.rubberBand){
      this.rubberBand = this.L.polyline(path, style);
      this.rubberBand.addTo(this.map);
    } else {
      this.rubberBand.setLatLngs(path);
      if (this.rubberBand.setStyle) this.rubberBand.setStyle(style);
    }
  }

  _clearRubberBand(){
    if (this.rubberBand){
      this.map.removeLayer(this.rubberBand);
      this.rubberBand = null;
    }
  }

  _onMouseUp(){
    if (!this.drawing || !(this.isBrush() || this.isAssist())) return;
    this.drawing = false;
    this.finish();
  }

  /**
   * ¿Está el punto lo bastante lejos del anterior para merecer un vértice?
   *
   * Se mide en píxeles de pantalla y no en metros a propósito: es una decisión sobre cuánto ha
   * movido el usuario el ratón, no sobre el terreno.
   */
  _farEnough(latlng){
    if (!this.points.length) return true;
    const last = this.points[this.points.length - 1];
    const a = this.map.latLngToContainerPoint(latlng);
    const b = this.map.latLngToContainerPoint(this.L.latLng(last[1], last[0]));
    return Math.abs(a.x - b.x) + Math.abs(a.y - b.y) >= MIN_POINT_DISTANCE_PX;
  }

  // --- Común ---------------------------------------------------------------------------

  /**
   * Añade un vértice y lo marca en el mapa.
   *
   * El punto blanco no es decoración: mientras se traza, la línea de previsualización sola no
   * dice dónde quedó cada clic —sobre una ortofoto con textura, un vértice a media pendiente es
   * invisible— y el usuario no sabe si el clic entró. `interactive: false` porque son un apoyo
   * visual, no manejadores: durante el trazado no hay nada que arrastrar todavía, y capturar el
   * ratón haría que el siguiente clic cayera en el marcador en vez de en el mapa.
   * Mismo recurso que `PolylineEditor._addVertex` de `annotations`.
   */
  _pushPoint(latlng){
    this.points.push([latlng.lng, latlng.lat]);
    if (this.isRing()){
      const marker = this.L.marker(latlng, {icon: VERTEX_ICON, interactive: false});
      marker.addTo(this.map);
      this._drawVertexMarkers.push(marker);
    }
  }

  _popVertexMarker(){
    const marker = this._drawVertexMarkers.pop();
    if (marker) this.map.removeLayer(marker);
  }

  _clearVertexMarkers(){
    this._drawVertexMarkers.forEach(m => this.map.removeLayer(m));
    this._drawVertexMarkers = [];
  }

  _style(){
    const isEraser = this.mode === MODE_ERASER;
    const isReview = this.mode === MODE_REVIEW;
    const lat = this.points.length ? this.points[0][1] : this.map.getCenter().lat;

    if (isReview){
      // Sin relleno apenas y con trazo discontinuo: un área revisada suele abarcar media pantalla
      // y con relleno opaco taparía justo las etiquetas que hay que ver dentro de ella.
      return {color: REVIEW_COLOR, weight: 2, fillColor: REVIEW_COLOR, fillOpacity: 0.05,
              dashArray: REVIEW_DASH};
    }

    const color = isEraser ? ERASER_COLOR : classColor(this.classes, this.classIndex);
    if (this.isBrush()){
      return {color: color, opacity: 0.7, lineCap: 'round', lineJoin: 'round',
              dashArray: isEraser ? ERASER_DASH : null,
              weight: strokeWeightPx(this.map, this.radiusM, lat)};
    }
    return {color: color, weight: 2, fillColor: color, fillOpacity: 0.3,
            dashArray: isEraser ? ERASER_DASH : null};
  }

  _updatePreview(){
    // En selección asistida la previsualización es la región que devuelve el servidor, y la pinta
    // `assistLayer`. Dibujar además el rastro del cursor sería enseñar dos cosas distintas a la vez
    // y sugerir que lo que se etiqueta es la línea.
    if (this.isAssist()) return;

    const latlngs = this.points.map(p => [p[1], p[0]]);
    if (latlngs.length < 2) return;

    if (!this.preview){
      this.preview = this.isBrush()
        ? this.L.polyline(latlngs, this._style())
        : this.L.polyline(latlngs, this._style());
      this.preview.addTo(this.map);
    } else {
      this.preview.setLatLngs(latlngs);
      if (this.preview.setStyle) this.preview.setStyle(this._style());
    }
  }

  /** Repinta la previsualización al cambiar el zoom o el radio: el grosor está en metros. */
  _restyle(){
    if (this.preview && this.preview.setStyle) this.preview.setStyle(this._style());
  }

  _discardPreview(){
    if (this.preview){
      this.map.removeLayer(this.preview);
      this.preview = null;
    }
  }

  _cancel(){
    this.drawing = false;
    this.points = [];
    this._clearVertexMarkers();
    this._clearRubberBand();
    this._discardPreview();
  }

  /**
   * Cierra la etiqueta en curso y la entrega. Devuelve el objeto entregado, o `null` si la
   * geometría no llegaba al mínimo de vértices de su tipo — abandonar un trazo de un solo punto
   * es lo normal cuando el usuario hace clic sin arrastrar.
   */
  finish(){
    if (this.isAssist()){
      // Un solo punto ya vale: el gesto normal de esta herramienta es un clic, no un arrastre.
      const points = this.points.slice();
      this._cancel();
      if (!points.length) return null;
      this.onAssist(points);
      return {kind: 'assist', points: points};
    }

    const kind = this.isBrush() ? 'stroke' : (this.mode === MODE_REVIEW ? 'review' : 'polygon');
    const minimum = kind === 'stroke' ? 2 : 3;

    if (this.points.length < minimum){
      this._cancel();
      return null;
    }

    const label = {
      kind: kind,
      class_index: this.activeClassIndex(),
      geometry: this.points.slice(),
      radius_m: kind === 'stroke' ? this.radiusM : null
    };
    if (kind === 'review') label.hard_negative = !!this.hardNegative;

    this._cancel();
    this.onCreate(label);
    return label;
  }

  cancel(){ this._cancel(); }

  // --- Edición de una etiqueta ya dibujada (FR-013) --------------------------------------
  //
  // Copia del patrón de `coreplugins/annotations/public/PolylineEditor.js:172-291`, adaptado a
  // que aquí una etiqueta puede ser un polígono (anillo, mínimo 3 vértices) o un trazo
  // (polilínea, mínimo 2).

  startEditing(layer, {onChange, onStop} = {}){
    this.stopEditing();
    if (!layer) return;

    this.editingLayer = layer;
    this.onChange = onChange || (() => {});
    this.onStop = onStop || (() => {});

    // Los manejadores de vértices son marcadores del mapa, no hijos de la capa: si la etiqueta se
    // borra o se redibuja, Leaflet retira su geometría pero dejaría los puntos flotando sobre el
    // mapa, apuntando a una capa que ya no existe.
    layer.on('remove', this._handleEditLayerRemoved = () => {
      const notify = this.onStop;
      this.stopEditing();
      notify();
    });
    this._handleLineHover = () => { this.map.getContainer().style.cursor = 'copy'; };
    this._handleLineOut = () => { this.map.getContainer().style.cursor = ''; };
    layer.on('mouseover', this._handleLineHover);
    layer.on('mouseout', this._handleLineOut);

    this._handleEditClick = e => this._onEditClick(e);
    this.map.on('click', this._handleEditClick);

    this._syncCoreClickHook();
    this._redrawEditHandles();
  }

  stopEditing(){
    this._clearEditHandles();
    if (this.editingLayer){
      this.editingLayer.off('remove', this._handleEditLayerRemoved);
      this.editingLayer.off('mouseover', this._handleLineHover);
      this.editingLayer.off('mouseout', this._handleLineOut);
      this.map.off('click', this._handleEditClick);
      this.map.getContainer().style.cursor = '';
    }
    this.editingLayer = null;
    this._syncCoreClickHook();
  }

  isEditing(){ return !!this.editingLayer; }

  /** Vértices mínimos de la capa en edición: un anillo necesita 3, una polilínea 2. */
  _minVertices(){
    const latlngs = this.editingLayer ? this.editingLayer.getLatLngs() : [];
    return Array.isArray(latlngs[0]) ? 3 : 2;
  }

  _redrawEditHandles(){
    this._clearEditHandles();
    if (!this.editingLayer) return;

    ringOf(this.editingLayer).forEach((latlng, i) => {
      const marker = this.L.marker(latlng, {icon: VERTEX_ICON, draggable: true}).addTo(this.map);

      marker.on('drag', () => {
        const ring = ringOf(this.editingLayer);
        ring[i] = marker.getLatLng();
        setRing(this.editingLayer, ring);
      });
      // Se persiste al soltar, no en cada `drag`: guardar en cada píxel de arrastre dispararía
      // decenas de peticiones por vértice movido.
      marker.on('dragend', () => {
        this.onChange(ringOf(this.editingLayer));
        this._redrawEditHandles();
      });

      // Botón derecho sobre un vértice: lo elimina, nunca por debajo del mínimo de su tipo.
      marker.on('contextmenu', e => {
        this.L.DomEvent.stop(e);
        const ring = ringOf(this.editingLayer);
        if (ring.length <= this._minVertices()) return;
        ring.splice(i, 1);
        setRing(this.editingLayer, ring);
        this.onChange(ring);
        this._redrawEditHandles();
      });

      // El clic sobre el manejador no debe llegar ni a `_onEditClick` —insertaría un vértice
      // duplicado encima del que se acaba de soltar— ni al popup de la ortofoto del core.
      marker.on('click', e => this.L.DomEvent.stop(e));

      this._editVertexMarkers.push(marker);
    });
  }

  _clearEditHandles(){
    this._editVertexMarkers.forEach(m => this.map.removeLayer(m));
    this._editVertexMarkers = [];
  }

  /** Botón izquierdo sobre la línea: inserta un vértice en el tramo clicado. */
  _onEditClick(e){
    const hit = this._hitTestLine(e);
    if (!hit) return;
    const ring = ringOf(this.editingLayer);
    ring.splice(hit.index + 1, 0, hit.latlng);
    setRing(this.editingLayer, ring);
    this.onChange(ring);
    this._redrawEditHandles();
  }

  /**
   * `{index, latlng}` del tramo bajo el cursor, o `null` si el clic no cae sobre la geometría.
   *
   * Se trabaja en píxeles y no en grados para que la tolerancia sea la misma a cualquier zoom —
   * en grados, acertar la línea sería trivial de lejos e imposible de cerca.
   */
  _hitTestLine(e){
    if (!this.editingLayer || !this.map.hasLayer(this.editingLayer)) return null;
    const ring = ringOf(this.editingLayer);
    if (ring.length < 2) return null;

    const point = e.layerPoint || this.map.mouseEventToLayerPoint(e.originalEvent);
    const points = ring.map(ll => this.map.latLngToLayerPoint(ll));
    if (points.some(p => p.distanceTo(point) <= VERTEX_GRAB_PX)) return null;

    // Un anillo se cierra sobre sí mismo, así que su último tramo va del final al principio: sin
    // esto no se podría insertar un vértice en el lado que cierra el polígono.
    const closed = Array.isArray(this.editingLayer.getLatLngs()[0]);
    const segments = closed ? points.length : points.length - 1;

    let best = null;
    for (let i = 0; i < segments; i++){
      const next = points[(i + 1) % points.length];
      const d = this.L.LineUtil.pointToSegmentDistance(point, points[i], next);
      if (d <= INSERT_TOLERANCE_PX && (!best || d < best.d)) best = {i, d, next};
    }
    if (!best) return null;

    const onLine = this.L.LineUtil.closestPointOnSegment(point, points[best.i], best.next);
    return {index: best.i, latlng: this.map.layerPointToLatLng(onLine)};
  }
}
