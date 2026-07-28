/* Convivencia de `road` y `annotations` como productores del mismo bus del core (T058).
 *
 * El bus de `PluginsAPI.Map` se detiene en el **primer manejador que devuelve un valor truthy**.
 * Con un solo productor eso da igual; con dos, un `return true` de más sobre un layer ajeno deja
 * al otro plugin sin poder borrar ni descargar, y el síntoma que ve el usuario es "el botón de
 * borrar de Anotaciones ya no hace nada" — sin ningún error en ninguna parte.
 *
 * Este test carga **los dos bridges reales**, no dobles, y reproduce la semántica del bus.
 */
const assert = require('assert');
const {setupDom, loadModule, test, summary} = require('./harness');

setupDom();
const L = require('leaflet');

// --- Bus del core, con su regla de parada -------------------------------------------------
const bus = {toggle: [], del: [], download: []};

function dispatch(channel, ...args){
  for (const {owner, fn} of bus[channel]){
    const result = fn(...args);
    if (result) return owner;   // el bus se detiene aquí
  }
  return null;
}

let currentOwner = null;
const PluginsAPI = {Map: {
  onToggleAnnotation: (fn) => bus.toggle.push({owner: currentOwner, fn}),
  onDeleteAnnotation: (fn) => bus.del.push({owner: currentOwner, fn}),
  onDownloadAnnotations: (fn) => bus.download.push({owner: currentOwner, fn}),
  addAnnotation: () => {},
  updateAnnotation: () => {},
  annotationDeleted: () => {}
}};

const ajaxUrls = [];
const $ = {
  ajax: (opts) => {
    ajaxUrls.push(opts.url);
    return {done(fn){ fn(); return this; }, fail(){ return this; }};
  }
};

const style = loadModule('segmentStyle.js', {});

currentOwner = 'annotations';
const annotations = loadModule('../../annotations/public/annotationsBridge.js',
                               {L, PluginsAPI, $, _: (s) => s});
annotations.initBridge();

currentOwner = 'road';
const road = loadModule('roadBridge.js', {
  L, PluginsAPI, $, _: (s) => s,
  styleForSegment: style.styleForSegment,
  reasonLabel: style.reasonLabel,
  hitStyle: style.hitStyle
});
road.initBridge();

const map = {addLayer(){}, hasLayer(){ return true; }, removeLayer(){}};

function annotationLayer(){
  return annotations.publishPolyline(
    map, {id: 'task-1'}, {id: 'p1', name: 'Polilínea', vertices: [[0, 0], [0.001, 0.001]]},
    {stored: true});
}

function roadGroup(){
  return road.publishAnalysis(map, {id: 'task-1'},
    {id: 'a1', name: 'Camino', color_thresholds: [8, 12]},
    [{index: 0, status: 'measured', grade: 3, geometry: [[0, 0], [0.001, 0]]}],
    {stored: true});
}

// --- Registro ------------------------------------------------------------------------------

test('los dos plugins se registran en los mismos canales', () => {
  ['toggle', 'del', 'download'].forEach(channel => {
    const owners = bus[channel].map(h => h.owner);
    assert.ok(owners.includes('annotations'), 'falta annotations en ' + channel);
    assert.ok(owners.includes('road'), 'falta road en ' + channel);
  });
});

// --- Borrado -------------------------------------------------------------------------------

test('borrar una anotación de annotations no pasa por road', () => {
  const layer = annotationLayer();
  ajaxUrls.length = 0;

  assert.strictEqual(dispatch('del', layer), 'annotations');
  assert.strictEqual(ajaxUrls.length, 1);
  assert.ok(/\/plugins\/annotations\//.test(ajaxUrls[0]),
    'la petición salió del plugin equivocado: ' + ajaxUrls[0]);
  assert.ok(!road.isOwned(layer));
});

test('borrar un análisis de road no pasa por annotations', () => {
  const group = roadGroup();
  ajaxUrls.length = 0;

  assert.strictEqual(dispatch('del', group), 'road');
  assert.strictEqual(ajaxUrls.length, 1);
  assert.ok(/\/plugins\/road\//.test(ajaxUrls[0]),
    'la petición salió del plugin equivocado: ' + ajaxUrls[0]);
});

test('un layer que no es de nadie recorre el bus entero sin efecto', () => {
  ajaxUrls.length = 0;
  assert.strictEqual(dispatch('del', {}), null);
  assert.deepStrictEqual(ajaxUrls, []);
});

// --- Mostrar y ocultar ---------------------------------------------------------------------

test('mostrar y ocultar lo atiende el dueño del layer', () => {
  assert.strictEqual(dispatch('toggle', annotationLayer(), false), 'annotations');
  assert.strictEqual(dispatch('toggle', roadGroup(), false), 'road');
  assert.strictEqual(dispatch('toggle', {}, false), null);
});

// --- Descarga genérica del panel de capas ---------------------------------------------------

test('la descarga genérica sigue siendo de annotations pese a que road está en el bus', () => {
  // `road` devuelve false siempre en este canal. Si devolviera true, el botón de descarga del
  // panel de capas dejaría de bajar las polilíneas de `annotations` y nadie sabría por qué.
  annotationLayer();
  const downloads = [];
  window.HTMLAnchorElement.prototype.click = function(){ downloads.push(this.href); };

  assert.strictEqual(dispatch('download', 'geojson'), 'annotations');
  assert.ok(downloads.length > 0);
  assert.ok(downloads.every(url => /\/plugins\/annotations\//.test(url)),
    'road secuestró la descarga: ' + JSON.stringify(downloads));
});

test('road no atiende la descarga genérica en ningún formato', () => {
  const roadHandler = bus.download.find(h => h.owner === 'road').fn;
  ['geojson', 'csv', 'kml', undefined].forEach(format => {
    assert.strictEqual(roadHandler(format), false, 'road atendió el formato ' + format);
  });
});

summary('busCoexistence');
