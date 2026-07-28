import L from 'leaflet';
import PluginsAPI from 'webodm/classes/plugins/API';
import { _ } from 'webodm/classes/gettext';
import { styleForSegment, reasonLabel, haloStyleFor, hitStyle } from './segmentStyle';

// Diálogo con el bus de anotaciones del core (`contracts/consumed-contracts.md` §3).
//
// `road` es el **segundo** productor del bus —el primero es `annotations`—, lo que convierte en
// crítica la regla que aquel dejó documentada: el bus se detiene en el primer manejador que
// devuelve un valor *truthy*, así que **todo manejador debe devolver `false` sobre layers que no
// le pertenecen**. Sin eso, tocar una anotación de `annotations` la borraría a través de este
// plugin, o al revés.
//
// Cada análisis se publica como **un** `L.FeatureGroup` con una polilínea por tramo: así el
// usuario obtiene mostrar/ocultar y borrar nativos sobre el análisis entero, y el resultado
// aparece junto al resto de capas de la tarea en vez de vivir escondido en el panel del plugin.

const registry = new Map(); // L.FeatureGroup -> {taskId, analysisId, map, segments, thresholds}
let initialized = false;

let errorNotifier = null;
let deletionNotifier = null;

function setErrorNotifier(fn){
  errorNotifier = fn || null;
}

// El panel necesita enterarse de un borrado nacido en el panel de capas del core para quitar el
// análisis de su propia lista.
function setDeletionNotifier(fn){
  deletionNotifier = fn || null;
}

function reportError(message){
  if (errorNotifier) errorNotifier(message);
}

function apiBase(taskId){
  return `/api/plugins/road/task/${taskId}`;
}

function toLatLngs(coords){
  return coords.map(c => L.latLng(c[1], c[0]));
}

function fmt(value, digits = 2, suffix = ''){
  if (value === null || value === undefined) return '—';
  return value.toFixed(digits) + suffix;
}

// Popup con **todas** las métricas del tramo (FR-020): el usuario que hace clic quiere el número,
// no una etiqueta de color.
function popupHtml(segment){
  const sides = ['left', 'right'].map(side => {
    const reason = reasonLabel(segment[`${side}_reason`]);
    const offset = segment[`offset_${side}`];
    const source = segment[`${side}_edge_source`];
    const label = side === 'left' ? _('Izquierda') : _('Derecha');
    // Un lado puede llevar distancia Y motivo a la vez (`006` FR-020): "no se pudo medir aquí,
    // el valor viene de los vecinos". Las dos cosas se muestran, no compiten.
    let cell;
    if (offset !== null && offset !== undefined){
      cell = fmt(offset, 2, ' m');
      if (source === 'inferred'){
        cell += ` <em>(${_('inferido')}${reason ? ': ' + reason : ''})</em>`;
      }
    }else{
      cell = reason ? reason : '—';
    }
    return `<tr><th>${label}</th><td>${cell}</td></tr>`;
  }).join('');

  return `<div class="road-segment-popup">
    <h4>${_('Tramo')} ${segment.index + 1}</h4>
    <table>
      <tr><th>${_('Progresiva')}</th><td>${fmt(segment.station_start, 1, ' m')} – ${fmt(segment.station_end, 1, ' m')}</td></tr>
      <tr><th>${_('Longitud')}</th><td>${fmt(segment.length, 2, ' m')}</td></tr>
      <tr><th>${_('Cota')}</th><td>${fmt(segment.elevation, 2, ' m')}</td></tr>
      <tr><th>${_('Pendiente')}</th><td>${fmt(segment.grade, 2, ' %')} (${fmt(segment.grade_deg, 2, '°')})</td></tr>
      <tr><th>${_('Ancho')}</th><td>${fmt(segment.width, 2, ' m')}</td></tr>
      ${sides}
      <tr><th>${_('Pendiente transversal')}</th><td>${fmt(segment.cross_slope, 2, ' %')}</td></tr>
    </table>
  </div>`;
}

// Cada tramo son **dos** capas: la que se ve y un área de captura invisible y mucho más ancha
// (`hitStyle`, con el porqué medido). La interactiva es la segunda —el hover, el click y el popup
// van por ella—, así que es también la que lleva el `_roadSegment` con el que el resto del bridge
// reconoce lo suyo; la visible se dibuja ya sin interacción y se alcanza desde `_roadLine`.
function buildGroup(segments, thresholds){
  const layers = [];
  segments.forEach(segment => {
    const latlngs = toLatLngs(segment.geometry);

    const line = L.polyline(latlngs, Object.assign({}, styleForSegment(segment, thresholds),
                                                   {interactive: false}));

    const hit = L.polyline(latlngs, hitStyle());
    hit.bindPopup(popupHtml(segment));
    hit._roadSegment = segment;
    hit._roadLine = line;

    layers.push(line, hit);
  });
  return L.featureGroup(layers);
}

// --- Resaltado del tramo bajo el cursor ---------------------------------------------------
//
// Un análisis de 1 km son ~200 polilíneas contiguas, y dos tramos del mismo color parecen una sola
// línea: sin resaltado no se ve dónde acaba uno y empieza el siguiente, ni qué tramo va a
// responder al click. Se resuelve con **una sola** línea de realce reutilizable que adopta la
// geometría del tramo activo — no con un contorno por tramo, que multiplicaría los layers por dos.

// El realce son **dos** capas superpuestas y ninguna de ellas es el tramo:
//
//   contorno  blanco y ancho, por encima de todos los tramos -> recorta a los vecinos y hace
//             visible dónde empieza y acaba el tramo activo
//   calco     el color del tramo, encima del contorno -> devuelve el semáforo a la vista
//
// Ambas son `interactive: false`, así que no participan en el hit testing y el tramo de debajo
// sigue recibiendo el hover y el click.
//
// La versión anterior subía el propio tramo al frente con `bringToFront()` y **rompía el click**:
// eso reinserta en el DOM el mismo nodo que el usuario va a pulsar (medido: saltaba de la posición
// 30 a la 60 entre sus hermanos), el navegador dispara `mouseout`+`mouseover` al reinsertarlo —lo
// que reencadenaba el resalte en bucle— y un `click` no llega a formarse porque `mousedown` y
// `mouseup` caen sobre un nodo que se movió en medio. El elemento interactivo no se toca nunca.
let haloLayer = null;
let capLayer = null;
let hoveredLayer = null;
let pinnedLayer = null;   // tramo cuyo popup está abierto: conserva el realce al mover el ratón

function showHalo(map, layer){
  if (!layer || !layer._roadSegment) return false;
  if (hoveredLayer === layer && haloLayer && haloLayer._map) return true;

  const segment = layer._roadSegment;
  const latlngs = layer.getLatLngs();
  // El hover llega por el área de captura, que es invisible: el color del calco sale del tramo
  // visible al que representa.
  const visible = layer._roadLine || layer;

  if (!haloLayer) haloLayer = L.polyline([], haloStyleFor(segment));
  if (!capLayer) capLayer = L.polyline([], {interactive: false});

  haloLayer.setLatLngs(latlngs);
  haloLayer.setStyle(haloStyleFor(segment));
  capLayer.setLatLngs(latlngs);
  capLayer.setStyle(Object.assign({}, visible.options, {interactive: false}));

  if (!map.hasLayer(haloLayer)) haloLayer.addTo(map);
  if (!map.hasLayer(capLayer)) capLayer.addTo(map);

  // Contorno primero y calco después: invertirlas deja el blanco tapando el color.
  haloLayer.bringToFront();
  capLayer.bringToFront();

  hoveredLayer = layer;
  return true;
}

function hideHalo(){
  if (haloLayer && haloLayer._map) haloLayer.remove();
  if (capLayer && capLayer._map) capLayer.remove();
  hoveredLayer = null;
  return true;
}

function attachHighlight(map, group){
  group.eachLayer(layer => {
    // Solo las áreas de captura: la línea visible ya no recibe eventos.
    if (!layer._roadSegment) return;
    layer.on('mouseover', () => showHalo(map, layer));
    layer.on('mouseout', () => {
      // Con un popup abierto el contorno vuelve a su tramo en vez de desaparecer: si no, al mover
      // el ratón para leer el popup se pierde de vista de qué tramo hablaba.
      if (pinnedLayer) showHalo(map, pinnedLayer);
      else hideHalo();
    });
    layer.on('popupopen', () => {
      pinnedLayer = layer;
      showHalo(map, layer);
    });
    layer.on('popupclose', () => {
      if (pinnedLayer === layer) pinnedLayer = null;
      hideHalo();
    });
  });
}

function currentHalo(){
  return haloLayer && haloLayer._map ? haloLayer : null;
}

function publishAnalysis(map, task, analysis, segments, opts = {}){
  const thresholds = analysis.color_thresholds || [8.0, 12.0];
  const group = buildGroup(segments, thresholds);
  group.addTo(map);
  attachHighlight(map, group);
  registry.set(group, {taskId: task.id, analysisId: analysis.id, map, segments, thresholds});
  PluginsAPI.Map.addAnnotation(group, analysis.name, task, !!opts.stored);
  return group;
}

function unpublishAnalysis(group){
  const meta = registry.get(group);
  registry.delete(group);
  // El contorno sobreviviría al grupo que lo originó y quedaría flotando sobre el mapa señalando
  // un tramo que ya no existe.
  if (pinnedLayer && group.hasLayer && group.hasLayer(pinnedLayer)) pinnedLayer = null;
  hideHalo();
  const map = (meta && meta.map) || group._map;
  if (map && map.hasLayer(group)) map.removeLayer(group);
}

function isOwned(group){
  return registry.has(group);
}

function groupFor(analysisId){
  for (const [group, meta] of registry){
    if (meta.analysisId === analysisId) return group;
  }
  return null;
}

// Recoloreado inmediato (SC-005): `setStyle` sobre las polilíneas que ya están dibujadas, sin
// ninguna petición de datos. Los tramos sin medir conservan su trazo discontinuo porque el estilo
// lo decide `segmentStyle`, que ya lo contempla.
function applyThresholds(analysisId, thresholds){
  const group = groupFor(analysisId);
  if (!group) return false;
  const meta = registry.get(group);
  meta.thresholds = thresholds;
  group.eachLayer(layer => {
    // Se recolorea la línea visible; el área de captura es invisible y se queda como está.
    if (layer._roadLine) layer._roadLine.setStyle(styleForSegment(layer._roadSegment, thresholds));
  });
  // El calco lleva una copia del color del tramo, así que un recoloreado con el cursor encima lo
  // dejaría mostrando el color anterior sobre un tramo que ya cambió.
  if (hoveredLayer && group.hasLayer(hoveredLayer)){
    const layer = hoveredLayer;
    hoveredLayer = null;   // fuerza el refresco: si no, el guardia de `showHalo` lo daría por hecho
    showHalo(meta.map, layer);
  }
  return true;
}

function renameAnalysis(group, name){
  PluginsAPI.Map.updateAnnotation(group, name);
}

// `window.location.href` solo puede atender una descarga a la vez: cada asignación cancela la
// anterior. Un enlace por descarga sí las encadena, y el nombre lo sigue poniendo el
// `Content-Disposition`.
function triggerDownload(url){
  const link = document.createElement('a');
  link.href = url;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function downloadExport(taskId, analysisId, format){
  triggerDownload(`${apiBase(taskId)}/analyses/${analysisId}/export?format=${format}`);
}

function initBridge(){
  if (initialized) return;
  initialized = true;

  PluginsAPI.Map.onToggleAnnotation((layer, visible) => {
    if (!registry.has(layer)) return false;
    const meta = registry.get(layer);
    if (visible){
      if (!layer._map) layer.addTo(meta.map);
    }else{
      if (layer._map) layer.remove();
    }
    return true;
  });

  PluginsAPI.Map.onDeleteAnnotation((layer) => {
    const meta = registry.get(layer);
    if (!meta) return false;
    $.ajax({
      url: `${apiBase(meta.taskId)}/analyses/${meta.analysisId}`,
      type: 'DELETE'
    }).done(() => {
      unpublishAnalysis(layer);
      PluginsAPI.Map.annotationDeleted(layer);
      if (deletionNotifier) deletionNotifier(meta.analysisId);
    }).fail(req => {
      // Sin `annotationDeleted` el core conserva la anotación en su panel y el layer sigue en el
      // mapa, así que el estado visible ya es el correcto: lo que faltaba era avisar, o el
      // usuario daba por hecho un borrado que nunca ocurrió.
      const data = req.responseJSON || {};
      reportError(data.error || _("No se pudo eliminar el análisis."));
    });
    return true;
  });

  PluginsAPI.Map.onDownloadAnnotations(() => {
    // Siempre `false`: la exportación de `road` es CSV y GeoJSON con su propio esquema y se pide
    // desde su panel. Devolver `true` aquí secuestraría el botón genérico del panel de capas y
    // dejaría a `annotations` sin su descarga.
    return false;
  });
}

export default {
  initBridge,
  setErrorNotifier,
  setDeletionNotifier,
  publishAnalysis,
  unpublishAnalysis,
  renameAnalysis,
  applyThresholds,
  groupFor,
  isOwned,
  downloadExport,
  popupHtml,
  showHalo,
  hideHalo,
  currentHalo,
  registry
};
