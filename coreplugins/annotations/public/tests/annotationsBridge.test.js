/* Diálogo con el bus de anotaciones del core: borrado y descarga del grupo.
 *
 * Las dos acciones nacen en el panel de capas del core, donde el plugin no tiene interfaz: un
 * fallo que no se propague al panel deja al usuario creyendo que borró algo que sigue ahí.
 */
const assert = require('assert');
const {setupDom, loadModule, test, summary} = require('./harness');

setupDom();
const L = require('leaflet');

// --- Stubs del entorno que en producción pone webpack ------------------------------------------
const handlers = {};
const busCalls = [];
const PluginsAPI = {Map: {
  onToggleAnnotation: (fn) => { handlers.toggle = fn; },
  onDeleteAnnotation: (fn) => { handlers.del = fn; },
  onDownloadAnnotations: (fn) => { handlers.download = fn; },
  addAnnotation: (...args) => busCalls.push(['addAnnotation', ...args]),
  updateAnnotation: () => {},
  annotationDeleted: (layer) => busCalls.push(['annotationDeleted', layer])
}};

let ajaxOutcome = {ok: true, responseJSON: null};
const $ = {
  ajax: () => {
    const chain = {
      done(fn){ if (ajaxOutcome.ok) fn(); return chain; },
      fail(fn){ if (!ajaxOutcome.ok) fn({responseJSON: ajaxOutcome.responseJSON}); return chain; }
    };
    return chain;
  }
};

const bridge = loadModule('annotationsBridge.js', {L, PluginsAPI, $, _: (s) => s});

const map = {addLayer(){}, hasLayer(){ return true; }, removeLayer(){}};
bridge.initBridge();

const notified = [];
bridge.setErrorNotifier((msg) => notified.push(msg));

let seq = 0;
function publish(taskId = 'task-1'){
  seq++;
  return bridge.publishPolyline(
    map, {id: taskId}, {id: 'p' + seq, name: 'una', vertices: [[0, 0], [1, 1]]}, {stored: true});
}

// --- Borrado -----------------------------------------------------------------------------------

test('un borrado rechazado por el servidor avisa y no despublica', () => {
  notified.length = 0;
  busCalls.length = 0;
  ajaxOutcome = {ok: false, responseJSON: {error: 'No tienes permiso.'}};
  const layer = publish();

  assert.strictEqual(handlers.del(layer), true, 'el handler sigue consumiendo el evento del bus');
  assert.deepStrictEqual(notified, ['No tienes permiso.'], 'el error del servidor llega al panel');
  assert.ok(bridge.isOwned(layer), 'la polilínea sigue publicada');
  assert.ok(!busCalls.some(c => c[0] === 'annotationDeleted'),
    'sin annotationDeleted el core conserva la anotación en su panel');
});

test('un fallo sin cuerpo JSON usa el mensaje por defecto, nunca silencio', () => {
  notified.length = 0;
  ajaxOutcome = {ok: false, responseJSON: null};
  handlers.del(publish());
  assert.strictEqual(notified.length, 1);
  assert.ok(/No se pudo eliminar/.test(notified[0]), 'mensaje inesperado: ' + notified[0]);
});

test('un borrado correcto despublica y avisa al core sin ruido de error', () => {
  notified.length = 0;
  busCalls.length = 0;
  ajaxOutcome = {ok: true};
  const layer = publish();

  assert.strictEqual(handlers.del(layer), true);
  assert.deepStrictEqual(notified, []);
  assert.ok(!bridge.isOwned(layer), 'la polilínea se despublica');
  assert.ok(busCalls.some(c => c[0] === 'annotationDeleted' && c[1] === layer));
});

test('sin panel montado el borrado no revienta', () => {
  bridge.setErrorNotifier(null);
  ajaxOutcome = {ok: false, responseJSON: {error: 'x'}};
  assert.strictEqual(handlers.del(publish()), true);
  bridge.setErrorNotifier((msg) => notified.push(msg));
});

test('un layer ajeno se rechaza antes de actuar', () => {
  // Regla del bus (`plugin-contract.md` §2.3): se detiene en el primer valor truthy, así que
  // devolver algo distinto de false aquí dejaría sin eventos a cualquier otro productor.
  assert.strictEqual(handlers.del({}), false);
});

// --- Descarga del grupo desde el panel de capas del core ---------------------------------------

const downloads = [];
window.HTMLAnchorElement.prototype.click = function(){ downloads.push(this.href); };

test('con varias tareas se descarga un archivo por tarea', () => {
  publish('task-A');
  publish('task-B');
  downloads.length = 0;

  assert.strictEqual(handlers.download('geojson'), true, 'el formato geojson lo atiende el plugin');
  // El conjunto esperado sale del registro: ahí están también las polilíneas cuyo borrado falló.
  const expected = [...new Set([...bridge.registry.values()].map(m => m.taskId))].sort();
  assert.ok(expected.length > 1, 'el escenario necesita varias tareas publicadas');
  const requested = downloads.map(url => (url.match(/task\/([^/]+)\//) || [])[1]).sort();
  assert.deepStrictEqual(requested, expected,
    'hubo ' + downloads.length + ' descargas: ' + JSON.stringify(downloads));
});

test('un formato ajeno se rechaza y no descarga nada', () => {
  downloads.length = 0;
  assert.strictEqual(handlers.download('kml'), false);
  assert.deepStrictEqual(downloads, []);
});

summary('annotationsBridge');
