import L from 'leaflet';
import { classColor } from './labelLayer';

/**
 * Selección asistida: pide al servidor la región del punto señalado, la previsualiza y la
 * convierte en etiquetas al soltar (`010`, US1 y US2).
 *
 * Vive aparte de `LabelEditor` porque son dos responsabilidades distintas y ninguna necesita a la
 * otra: el editor sabe de gestos sobre el mapa y no sabe en qué dataset ni sobre qué tarea se está
 * etiquetando; esto sabe de la API y no sabe nada de ratones.
 *
 * ## Tres decisiones que gobiernan este módulo
 *
 * 1. **Una petición en vuelo como mucho.** Un arrastre genera un evento cada pocos píxeles. Sin
 *    freno serían decenas de peticiones simultáneas, y las respuestas llegarían desordenadas: la
 *    previsualización parpadearía hacia atrás cada vez que ganase una respuesta vieja. Se manda una,
 *    se guarda la última petición pendiente y se lanza al terminar la anterior.
 *
 * 2. **Las respuestas viejas se descartan.** Cada petición lleva un número de secuencia; una
 *    respuesta con número menor que la última pintada se tira. El freno de arriba lo hace raro, pero
 *    «raro» sobre un arrastre de diez segundos ocurre a diario.
 *
 * 3. **Una etiqueta por anillo exterior, y se escribe al soltar.** No una por región tocada: un
 *    arrastre a lo largo de una pista produciría treinta etiquetas encadenadas que el usuario
 *    tendría que borrar de una en una.
 *
 * **Limitación conocida**: los anillos interiores se pierden. Una etiqueta del plugin es un anillo
 * simple (`models.validate_geometry`), así que un hueco dentro de una selección —un afloramiento en
 * mitad de una explanada, por ejemplo— queda incluido. Es poco frecuente a escala de superpíxel y el
 * borrador lo corrige; la alternativa era cambiar el formato de etiqueta, y con él el contrato del
 * paquete exportado, que es el más caro de tocar del plugin (FR-020).
 */

// Color de la previsualización: el de la clase activa, pero con trazo discontinuo y relleno flojo,
// para que no se confunda con una etiqueta ya guardada. Mismo criterio que la banda elástica del
// polígono: lo que se ve es una previsión, no una decisión.
export const PREVIEW_DASH = '6 4';
export const PREVIEW_FILL_OPACITY = 0.35;
export const PREVIEW_WEIGHT = 2;

/** Anillos exteriores de una geometría `MultiPolygon` de GeoJSON, en `[lon, lat]`. */
export function outerRings(geometry){
  if (!geometry || geometry.type !== 'MultiPolygon') return [];
  return (geometry.coordinates || [])
    .map(polygon => polygon && polygon[0])
    .filter(ring => ring && ring.length >= 4)
    // GeoJSON cierra el anillo repitiendo el primer vértice; el plugin lo guarda abierto
    // (`models.validate_geometry` lo normaliza igual, pero mandarlo ya abierto evita que el
    // recuento de vértices signifique dos cosas distintas según de dónde venga la etiqueta).
    .map(ring => ring.slice(0, -1));
}

/** Todos los anillos, exteriores e interiores, en el orden `[lat, lng]` que quiere Leaflet. */
export function toLeafletRings(geometry){
  if (!geometry || geometry.type !== 'MultiPolygon') return [];
  return (geometry.coordinates || []).map(
    polygon => polygon.map(ring => ring.map(point => [point[1], point[0]])));
}

export default class AssistLayer {
  constructor(options = {}){
    this.L = options.L || L;
    this.map = options.map;
    this.regionsUrl = options.regionsUrl;        // () => url
    this.settings = options.settings || (() => ({}));
    this.classes = options.classes || [];
    this.classIndex = options.classIndex !== undefined ? options.classIndex : null;
    this.onCreate = options.onCreate || function(){};
    this.onStatus = options.onStatus || function(){};
    this.onError = options.onError || function(){};
    this.request = options.request || defaultRequest;

    this.preview = null;
    this._sequence = 0;
    this._painted = 0;
    this._inFlight = false;
    this._queued = null;
    this.status = {busy: false};
  }

  /**
   * Publica un cambio de estado **fusionándolo** con el anterior.
   *
   * Que sea una fusión y no un reemplazo es la diferencia entre avisar y parpadear: el aviso de
   * «se alcanzó el tope» o el mensaje de «ahí no hay vuelo» llegan con la respuesta, y justo
   * después el ciclo publica `busy: false`. Reemplazando, ese segundo aviso borraría el primero
   * antes de que el usuario llegara a leerlo.
   */
  _emit(partial){
    this.status = Object.assign({}, this.status, partial);
    this.onStatus(Object.assign({}, this.status));
  }

  setClasses(classes){ this.classes = classes || []; }
  setClassIndex(index){ this.classIndex = index; }

  // --- Previsualización durante el gesto ------------------------------------------------

  previewPoints(points){
    this._enqueue(points, false);
  }

  commitPoints(points){
    this._enqueue(points, true);
  }

  /**
   * Encola una petición.
   *
   * Una confirmación **nunca** se pierde: si llega mientras hay otra en vuelo, se queda en la cola
   * y se manda después. Una previsualización sí puede perderse — es lo que se quiere, porque la
   * siguiente ya lleva los puntos acumulados hasta ese momento y la anterior no aporta nada.
   */
  _enqueue(points, commit){
    if (!points || !points.length) return;
    this._queued = {points: points, commit: commit};
    if (!this._inFlight) this._flush();
  }

  _flush(){
    const job = this._queued;
    this._queued = null;
    if (!job) return;

    const sequence = ++this._sequence;
    this._inFlight = true;
    this._emit({busy: true});

    const payload = Object.assign({}, this.settings(), {
      points: job.points.map(p => ({lon: p[0], lat: p[1]}))
    });

    this.request(this.regionsUrl(), payload)
      .then(response => this._onResponse(response, sequence, job.commit))
      .then(null, error => this._onFailure(error))
      // El `finally` va a mano porque jQuery 1.11.2 no lo tiene y `.then` de sus Deferred no es
      // conforme; `defaultRequest` devuelve una Promise nativa justamente para no depender de eso.
      .then(() => this._done(), () => this._done());
  }

  _done(){
    this._inFlight = false;
    this._emit({busy: !!this._queued});
    if (this._queued) this._flush();
  }

  _onResponse(response, sequence, commit){
    // Una respuesta vieja no puede pisar a una nueva: la previsualización daría un salto atrás.
    if (sequence < this._painted) return;
    this._painted = sequence;

    if (!response || !response.geometry){
      this._discardPreview();
      this._emit({
        busy: false,
        empty: true,
        truncated: false,
        regionCount: 0,
        message: (response && response.message) || null,
        preparedCells: response ? response.prepared_cells : 0
      });
      return;
    }

    this._drawPreview(response.geometry);
    this._emit({
      busy: false,
      empty: false,
      message: null,
      regionCount: response.region_count,
      truncated: !!response.truncated,
      elevationSource: response.elevation_source,
      bandCount: response.band_count,
      preparedCells: response.prepared_cells
    });

    if (commit){
      this._discardPreview();
      outerRings(response.geometry).forEach(ring => this.onCreate({
        kind: 'polygon',
        class_index: this.classIndex,
        source: 'assisted',
        geometry: ring
      }));
    }
  }

  _onFailure(error){
    this._discardPreview();
    this.onError(error);
  }

  // --- Dibujo ---------------------------------------------------------------------------

  _style(){
    const color = classColor(this.classes, this.classIndex);
    return {color: color, weight: PREVIEW_WEIGHT, fillColor: color,
            fillOpacity: PREVIEW_FILL_OPACITY, dashArray: PREVIEW_DASH,
            // No debe capturar el ratón: se dibuja bajo el cursor y, si lo capturara, el gesto se
            // interrumpiría en cuanto apareciese la primera previsualización.
            interactive: false};
  }

  _drawPreview(geometry){
    const rings = toLeafletRings(geometry);
    if (!rings.length){
      this._discardPreview();
      return;
    }
    // Un `L.Polygon` con varios anillos exteriores se dibuja igual que un multipolígono, así que no
    // hace falta una capa por parte ni un `featureGroup` que mantener.
    const latlngs = rings.reduce((all, polygon) => all.concat(polygon), []);

    if (!this.preview){
      this.preview = this.L.polygon(latlngs, this._style());
      this.preview.addTo(this.map);
    } else {
      this.preview.setLatLngs(latlngs);
      if (this.preview.setStyle) this.preview.setStyle(this._style());
    }
  }

  _discardPreview(){
    if (this.preview){
      this.map.removeLayer(this.preview);
      this.preview = null;
    }
  }

  remove(){
    this._queued = null;
    this._discardPreview();
  }
}

/**
 * `$.ajax` envuelto en una Promise nativa.
 *
 * Los Deferred de jQuery 1.11.2 —la versión que trae WebODM— no son conformes con Promises/A+ y no
 * tienen `.catch()`. Encadenar sobre ellos funciona hasta que falla, y entonces falla de una forma
 * que no se parece a un error. Mismo recurso que `datasets.js:getJSON`.
 */
function defaultRequest(url, payload){
  return new Promise((resolve, reject) => {
    $.ajax({url: url, type: 'POST', contentType: 'application/json',
            data: JSON.stringify(payload)})
      .done(resolve)
      .fail(xhr => reject((xhr && xhr.responseJSON) || {}));
  });
}
