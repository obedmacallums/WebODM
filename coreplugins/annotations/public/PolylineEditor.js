import L from 'leaflet';
import PluginsAPI from 'webodm/classes/plugins/API';

const VERTEX_ICON = L.divIcon({className: 'annotations-vertex-marker', iconSize: [10, 10]});
const MIN_VERTICES = 2;
// Radio en píxeles para clicar la línea e insertar un vértice: el trazo mide 3 px, así que sin
// tolerancia habría que acertarlo al píxel.
const INSERT_TOLERANCE_PX = 12;
// Un click pegado a un vértice existente es un intento de arrastrarlo o de borrarlo, no de
// insertar uno nuevo encima.
const VERTEX_GRAB_PX = 10;

// Trazado y edición de vértices sobre Leaflet puro (sin React), sin dependencias nuevas
// (`research.md` D1, precedente: `coreplugins/realign/public/RealignPanel.jsx:249-289`).
export default class PolylineEditor {
  constructor(map){
    this.map = map;
    this.active = false;
    this.latlngs = [];
    this.line = null;
    this.vertexMarkers = [];

    this.editingLayer = null;
    this._editVertexMarkers = [];
    this._coreClickHooked = false;

    this._handleClick = this._handleClick.bind(this);
    this._handleDblClick = this._handleDblClick.bind(this);
    this._handleKeyDown = this._handleKeyDown.bind(this);
    this._handleCoreClick = this._handleCoreClick.bind(this);
    this._handlePopupOpen = this._handlePopupOpen.bind(this);
    this._handleEditLayerRemoved = this._handleEditLayerRemoved.bind(this);
    this._handleEditClick = this._handleEditClick.bind(this);
    this._handleLineHover = this._handleLineHover.bind(this);
    this._handleLineOut = this._handleLineOut.bind(this);
  }

  isActive(){
    return this.active;
  }

  // --- Trazado (FR-001, FR-006) ------------------------------------------------------------

  start({onProgress, onComplete, onCancel, onInsufficient} = {}){
    if (this.active) this.cancel();

    this.active = true;
    this.latlngs = [];
    this.onProgress = onProgress || (() => {});
    this.onComplete = onComplete || (() => {});
    this.onCancel = onCancel || (() => {});
    this.onInsufficient = onInsufficient || (() => {});

    this.line = L.polyline([], {color: '#ff5722', weight: 3}).addTo(this.map);
    this._silencePopups();
    this.map.on('click', this._handleClick);
    this.map.on('dblclick', this._handleDblClick);
    document.addEventListener('keydown', this._handleKeyDown);
    this.map.doubleClickZoom.disable();
    this.map.getContainer().style.cursor = 'crosshair';
  }

  finish(){
    if (!this.active) return;
    const latlngs = this.latlngs.slice();
    const completed = latlngs.length >= MIN_VERTICES;
    this._teardownDrawing();
    if (completed) this.onComplete(latlngs);
    else this.onInsufficient(latlngs.length); // FR-002, escenario 5 de la US1
  }

  cancel(){
    if (!this.active) return;
    this._teardownDrawing();
    this.onCancel();
  }

  _addVertex(latlng){
    this.latlngs.push(latlng);
    this.line.setLatLngs(this.latlngs);
    const marker = L.marker(latlng, {icon: VERTEX_ICON, interactive: false}).addTo(this.map);
    this.vertexMarkers.push(marker);
    this.onProgress(this._length(), this.latlngs.length);
  }

  _handleClick(e){
    this._addVertex(e.latlng);
  }

  _handleDblClick(e){
    // El segundo click de un dblclick ya agregó un vértice vía _handleClick: se descarta el
    // duplicado y se finaliza el trazado (FR-001).
    if (this.latlngs.length > 1){
      this.latlngs.pop();
      const m = this.vertexMarkers.pop();
      if (m) this.map.removeLayer(m);
      this.line.setLatLngs(this.latlngs);
    }
    this.finish();
  }

  _handleKeyDown(e){
    if (e.key === 'Escape') this.cancel();
  }

  _length(){
    let total = 0;
    for (let i = 1; i < this.latlngs.length; i++){
      total += this.latlngs[i - 1].distanceTo(this.latlngs[i]);
    }
    return total;
  }

  _teardownDrawing(){
    this.active = false;
    this.map.off('click', this._handleClick);
    this.map.off('dblclick', this._handleDblClick);
    document.removeEventListener('keydown', this._handleKeyDown);
    this.map.doubleClickZoom.enable();
    this.map.getContainer().style.cursor = '';
    this._unsilencePopups();
    if (this.line){ this.map.removeLayer(this.line); this.line = null; }
    this.vertexMarkers.forEach(m => this.map.removeLayer(m));
    this.vertexMarkers = [];
    this.latlngs = [];
  }

  // --- Popups del mapa durante el trazado --------------------------------------------------

  // El core abre el popup de la ortofoto en cada click del mapa que caiga dentro de sus bounds
  // (`app/static/app/js/components/Map.jsx`, handler `map.on('click')`), así que trazar dejaba
  // un popup por vértice y su `autoPan` desplazaba el mapa a mitad del recorrido. El propio core
  // ofrece la salida en ese handler: `if (PluginsAPI.Map.handleClick(e)) return;`.
  // Regla del bus, igual que en `annotationsBridge`: devolver `false` cuando no estamos trazando,
  // o ningún otro plugin volvería a ver un click del mapa.
  _silencePopups(){
    this.map.closePopup();
    this._syncCoreClickHook();
    this.map.on('popupopen', this._handlePopupOpen);
  }

  _unsilencePopups(){
    this._syncCoreClickHook();
    this.map.off('popupopen', this._handlePopupOpen);
  }

  // Trazado y edición comparten el hook: registrarlo dos veces dejaría una suscripción huérfana
  // en el bus del core al terminar la primera de las dos.
  _syncCoreClickHook(){
    const wanted = this.active || !!this.editingLayer;
    if (wanted === this._coreClickHooked) return;
    if (wanted) PluginsAPI.Map.onHandleClick(this._handleCoreClick);
    else PluginsAPI.Map.offHandleClick(this._handleCoreClick);
    this._coreClickHooked = wanted;
  }

  _handleCoreClick(e){
    if (this.active) return true;
    // Editando solo se consume el click que va a insertar un vértice; el resto del mapa sigue
    // abriendo el popup de la ortofoto como siempre.
    return !!this.editingLayer && !!this._hitTestLine(e);
  }

  // Red de seguridad para los popups que no pasan por `handleClick`: los marcadores de fotos y
  // GCP del core abren el suyo directamente al clicarlos.
  _handlePopupOpen(e){
    this.map.closePopup(e.popup);
  }

  // --- Edición de geometría existente (US4, FR-004) -----------------------------------------

  startEditing(layer, {onChange, onStop} = {}){
    this.stopEditing();
    this.editingLayer = layer;
    this.onChange = onChange || (() => {});
    this.onStop = onStop || (() => {});
    // Los manejadores de vértices son marcadores del mapa, no hijos del layer: si la polilínea
    // se borra o se oculta desde el panel de capas del core, Leaflet retira la línea pero deja
    // los puntos flotando sobre el mapa (y apuntando a un layer que ya no existe).
    layer.on('remove', this._handleEditLayerRemoved);
    layer.on('mouseover', this._handleLineHover);
    layer.on('mouseout', this._handleLineOut);
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

  _handleEditLayerRemoved(){
    const notify = this.onStop || (() => {});
    this.stopEditing();
    notify();
  }

  isEditing(){
    return !!this.editingLayer;
  }

  _redrawEditHandles(){
    this._clearEditHandles();
    if (!this.editingLayer) return;
    const latlngs = this.editingLayer.getLatLngs();

    latlngs.forEach((latlng, i) => {
      const marker = L.marker(latlng, {icon: VERTEX_ICON, draggable: true}).addTo(this.map);
      marker.on('drag', () => {
        const ll = this.editingLayer.getLatLngs();
        ll[i] = marker.getLatLng();
        this.editingLayer.setLatLngs(ll);
      });
      marker.on('dragend', () => {
        this.onChange(this.editingLayer.getLatLngs());
        this._redrawEditHandles();
      });
      // Botón derecho sobre un vértice: lo elimina (FR-004).
      marker.on('contextmenu', (e) => {
        L.DomEvent.stop(e);
        const ll = this.editingLayer.getLatLngs();
        if (ll.length <= MIN_VERTICES) return; // FR-004: nunca por debajo de 2 vértices
        ll.splice(i, 1);
        this.editingLayer.setLatLngs(ll);
        this.onChange(ll);
        this._redrawEditHandles();
      });
      // El click sobre el manejador no debe llegar ni a `_handleEditClick` (insertaría un vértice
      // duplicado encima del que se acaba de soltar) ni al popup de la ortofoto del core.
      marker.on('click', (e) => L.DomEvent.stop(e));
      this._editVertexMarkers.push(marker);
    });
  }

  _clearEditHandles(){
    this._editVertexMarkers.forEach(m => this.map.removeLayer(m));
    this._editVertexMarkers = [];
  }

  // Botón izquierdo sobre la línea: inserta un vértice en el punto clicado, dentro del tramo
  // correspondiente (FR-004).
  _handleEditClick(e){
    const hit = this._hitTestLine(e);
    if (!hit) return;
    const ll = this.editingLayer.getLatLngs();
    ll.splice(hit.index + 1, 0, hit.latlng);
    this.editingLayer.setLatLngs(ll);
    this.onChange(ll);
    this._redrawEditHandles();
  }

  // Devuelve `{index, latlng}` con el tramo bajo el cursor (el vértice nuevo va en `index + 1`) y
  // el punto de ese tramo más próximo al click, o `null` si el click no cae sobre la línea. Se
  // trabaja en píxeles y no en grados para que la tolerancia sea la misma a cualquier zoom.
  _hitTestLine(e){
    if (!this.editingLayer || !this.map.hasLayer(this.editingLayer)) return null;
    const latlngs = this.editingLayer.getLatLngs();
    if (latlngs.length < MIN_VERTICES) return null;

    const p = e.layerPoint || this.map.mouseEventToLayerPoint(e.originalEvent);
    const points = latlngs.map(ll => this.map.latLngToLayerPoint(ll));
    if (points.some(pt => pt.distanceTo(p) <= VERTEX_GRAB_PX)) return null;

    let best = null;
    for (let i = 0; i < points.length - 1; i++){
      const d = L.LineUtil.pointToSegmentDistance(p, points[i], points[i + 1]);
      if (d <= INSERT_TOLERANCE_PX && (!best || d < best.d)) best = {i, d};
    }
    if (!best) return null;

    const onLine = L.LineUtil.closestPointOnSegment(p, points[best.i], points[best.i + 1]);
    return {index: best.i, latlng: this.map.layerPointToLatLng(onLine)};
  }

  _handleLineHover(){
    if (this.editingLayer) this.map.getContainer().style.cursor = 'copy';
  }

  _handleLineOut(){
    if (this.editingLayer) this.map.getContainer().style.cursor = '';
  }
}
