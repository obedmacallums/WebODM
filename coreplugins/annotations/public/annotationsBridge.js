import L from 'leaflet';
import PluginsAPI from 'webodm/classes/plugins/API';
import { _ } from 'webodm/classes/gettext';

// Diálogo con el bus de anotaciones del core (`contracts/plugin-contract.md` §2). El core define
// este contrato y no lo implementa nadie más (`research.md` D2): este plugin es el primer
// productor. Regla crítica (§2.3): todo manejador debe devolver `false` sobre layers ajenos, o
// rompe a cualquier otro futuro productor (el bus se detiene en el primer valor *truthy*).

const registry = new Map(); // L.Polyline -> {taskId, polylineId, map}
let initialized = false;

// El bridge atiende acciones que nacen en el panel de capas del core, donde no hay sitio para
// mostrar un error: el panel del plugin presta el suyo mientras está montado.
let errorNotifier = null;

function setErrorNotifier(fn){
  errorNotifier = fn || null;
}

function reportError(message){
  if (errorNotifier) errorNotifier(message);
}

function apiBase(taskId){
  return `/api/plugins/annotations/task/${taskId}`;
}

function toLatLngs(vertices){
  return vertices.map(v => L.latLng(v[1], v[0]));
}

function toVertices(latlngs){
  return latlngs.map(ll => [ll.lng, ll.lat]);
}

function buildLayer(polyline){
  return L.polyline(toLatLngs(polyline.vertices), {color: '#ff5722', weight: 3});
}

function publishPolyline(map, task, polyline, opts = {}){
  const layer = buildLayer(polyline);
  layer.addTo(map);
  registry.set(layer, {taskId: task.id, polylineId: polyline.id, map});
  PluginsAPI.Map.addAnnotation(layer, polyline.name, task, !!opts.stored);
  return layer;
}

function unpublishPolyline(layer){
  const meta = registry.get(layer);
  registry.delete(layer);
  const map = (meta && meta.map) || layer._map || layer._hiddenFromMap;
  if (map && map.hasLayer(layer)) map.removeLayer(layer);
}

function renamePolyline(layer, name){
  PluginsAPI.Map.updateAnnotation(layer, name);
}

function isOwned(layer){
  return registry.has(layer);
}

// `window.location.href` solo puede atender una descarga a la vez: cada asignación cancela la
// anterior, así que el botón del core sobre un mapa con varias tareas se traía un único archivo.
// Un enlace por descarga sí las encadena, y el nombre lo sigue poniendo el `Content-Disposition`.
function triggerDownload(url){
  const link = document.createElement('a');
  link.href = url;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

// Sin `polylineId` baja el grupo entero de la tarea: es lo que necesita el botón de descarga del
// panel de capas del core. El panel del plugin siempre pasa una polilínea concreta.
function downloadExport(taskId, geometryMode = 'vertices', polylineId = null){
  const path = polylineId ? `polylines/${polylineId}/export` : 'polylines/export';
  triggerDownload(`${apiBase(taskId)}/${path}?geometry=${geometryMode}`);
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
      url: `${apiBase(meta.taskId)}/polylines/${meta.polylineId}`,
      type: 'DELETE'
    }).done(() => {
      unpublishPolyline(layer);
      PluginsAPI.Map.annotationDeleted(layer);
    }).fail(req => {
      // Sin `annotationDeleted` el core conserva la anotación en su panel y el layer sigue en
      // el mapa, así que el estado visible ya es el correcto: lo que faltaba era avisar, o el
      // usuario daba por hecho un borrado que nunca ocurrió.
      const data = req.responseJSON || {};
      reportError(data.error || _("No se pudo eliminar la polilínea."));
    });
    return true;
  });

  PluginsAPI.Map.onDownloadAnnotations((format) => {
    // Rellena el `// TODO?` de `LayersControlAnnotations.jsx:127` (`research.md` D2, FR-032).
    if (format !== 'geojson') return false;
    const taskIds = new Set();
    registry.forEach(meta => taskIds.add(meta.taskId));
    taskIds.forEach(taskId => downloadExport(taskId));
    return taskIds.size > 0;
  });
}

export default {
  initBridge,
  setErrorNotifier,
  publishPolyline,
  unpublishPolyline,
  renamePolyline,
  isOwned,
  toVertices,
  toLatLngs,
  downloadExport,
  registry
};
