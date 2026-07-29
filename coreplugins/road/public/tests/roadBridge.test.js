/* Diálogo con el bus de anotaciones del core (`contracts/consumed-contracts.md` §3).
 *
 * `road` es el **segundo** productor del bus. Lo que más importa aquí no es que sus propias
 * acciones funcionen, sino que **no se coma los eventos de nadie más**: el bus se detiene en el
 * primer manejador que devuelve un valor truthy, así que un `return true` de más sobre un layer
 * ajeno dejaría a `annotations` sin poder borrar ni descargar nada.
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
  onAddAnnotation: (fn) => { handlers.add = fn; },
  addAnnotation: (...args) => busCalls.push(['addAnnotation', ...args]),
  updateAnnotation: () => {},
  annotationDeleted: (layer) => busCalls.push(['annotationDeleted', layer])
}};

let ajaxOutcome = {ok: true, responseJSON: null};
const ajaxUrls = [];
const $ = {
  ajax: (opts) => {
    ajaxUrls.push(opts.url);
    const chain = {
      done(fn){ if (ajaxOutcome.ok) fn(); return chain; },
      fail(fn){ if (!ajaxOutcome.ok) fn({responseJSON: ajaxOutcome.responseJSON}); return chain; }
    };
    return chain;
  }
};

const style = loadModule('segmentStyle.js', {});
const bridge = loadModule('roadBridge.js', {
  L, PluginsAPI, $, _: (s) => s,
  styleForSegment: style.styleForSegment,
  reasonLabel: style.reasonLabel,
  hitStyle: style.hitStyle,
  widthTickStyle: style.widthTickStyle
});

const map = {addLayer(){}, hasLayer(){ return true; }, removeLayer(){}};
bridge.initBridge();

const notified = [];
const deleted = [];
bridge.setErrorNotifier((msg) => notified.push(msg));
bridge.setDeletionNotifier((id) => deleted.push(id));

function segment(index, overrides = {}){
  return Object.assign({
    index,
    station_start: index * 5, station_end: (index + 1) * 5, length: 5,
    geometry: [[0, index * 0.001], [0.001, index * 0.001]],
    midpoint: [0.0005, index * 0.001],
    elevation: 100 + index, grade: 3, grade_deg: 1.7,
    width: 8, offset_left: 4, offset_right: 4, cross_slope: 2,
    status: 'measured', left_reason: null, right_reason: null,
    cross_section: [[0, 0], [0, 0]], edge_left: [0, 0], edge_right: [0, 0]
  }, overrides);
}

// Cada tramo son dos capas —el trazo visible y su área de captura invisible e interactiva, que
// lleva el `_roadSegment`— más la regla del ancho cuando tiene los dos bordes. El color y el
// trazo discontinuo viven en la visible.
function lines(group){
  return group.getLayers().filter(l => !l._roadSegment && !l._roadWidthTick);
}

function ticks(group){
  return group.getLayers().filter(l => l._roadWidthTick);
}

let seq = 0;
function publish(taskId = 'task-1', segments = [segment(0), segment(1), segment(2)]){
  seq++;
  const analysis = {id: 'a' + seq, name: 'Camino ' + seq, color_thresholds: [8, 12]};
  return {analysis, group: bridge.publishAnalysis(map, {id: taskId}, analysis, segments,
                                                  {stored: true})};
}

// --- Publicación -------------------------------------------------------------------------------

test('un análisis se publica como un solo grupo con una polilínea por tramo', () => {
  busCalls.length = 0;
  const {analysis, group} = publish();

  assert.strictEqual(lines(group).length, 3, 'un trazo visible por tramo');
  const added = busCalls.filter(c => c[0] === 'addAnnotation');
  assert.strictEqual(added.length, 1, 'el análisis entero es UNA anotación para el core');
  // addAnnotation(layer, name, task, stored) -> ['addAnnotation', layer, name, task, stored]
  assert.strictEqual(added[0][1], group, 'la anotación es el grupo, no una polilínea suelta');
  assert.strictEqual(added[0][2], analysis.name);
});

test('cada polilínea nace con el color de su pendiente', () => {
  const palette = style.colors();
  const {group} = publish('task-1', [segment(0, {grade: 3}), segment(1, {grade: 20})]);
  const applied = lines(group).map(l => l.options.color);

  assert.deepStrictEqual(applied, [palette.ok, palette.alert]);
});

// --- La regla del ancho ------------------------------------------------------------------------

test('cada tramo con dos bordes dibuja su regla de borde a borde, bajo el eje', () => {
  const {group} = publish();
  const rules = ticks(group);

  assert.strictEqual(rules.length, 3, 'una regla por tramo con ancho');
  assert.ok(group.getLayers()[0]._roadWidthTick,
    'las reglas van primero: pintadas bajo el eje, como en una regla graduada');
  rules.forEach(rule => {
    assert.strictEqual(rule.options.interactive, false, 'la regla no puede robar el click');
    assert.strictEqual(rule.getLatLngs().length, 2, 'de borde a borde, sin puntos intermedios');
  });
});

test('la regla une exactamente los dos puntos de borde del tramo', () => {
  const seg = segment(0, {edge_left: [0.004, 0.001], edge_right: [-0.004, 0.001]});
  const {group} = publish('task-1', [seg]);
  const coords = ticks(group)[0].getLatLngs().map(ll => [ll.lng, ll.lat]);

  assert.deepStrictEqual(coords, [seg.edge_left, seg.edge_right]);
});

test('sin uno de los bordes no hay regla: la ausencia es información', () => {
  const {group} = publish('task-1', [
    segment(0),
    segment(1, {status: 'no_edge', width: null, offset_right: null,
                right_reason: 'no_break', edge_right: null}),
  ]);

  assert.strictEqual(ticks(group).length, 1, 'solo el tramo con ambos bordes lleva regla');
});

test('recolorear por umbrales no toca las reglas', () => {
  const {analysis, group} = publish();
  const before = ticks(group).map(t => t.options.color);

  bridge.applyThresholds(analysis.id, [1, 2]);

  assert.deepStrictEqual(ticks(group).map(t => t.options.color), before,
    'la regla habla de ancho: el semáforo de pendiente no debe alcanzarla');
});

// --- Recoloreado sin recálculo -----------------------------------------------------------------

test('cambiar los umbrales recolorea sin ninguna petición de datos', () => {
  const palette = style.colors();
  const {analysis, group} = publish('task-1', [segment(0, {grade: 6})]);
  ajaxUrls.length = 0;

  assert.strictEqual(lines(group)[0].options.color, palette.ok);
  assert.strictEqual(bridge.applyThresholds(analysis.id, [4, 5]), true);

  assert.strictEqual(lines(group)[0].options.color, palette.alert);
  assert.deepStrictEqual(ajaxUrls, [], 'recolorear no debe pedir nada al servidor (SC-005)');
});

test('los tramos sin medir conservan su trazo distinguible tras recolorear', () => {
  const {analysis, group} = publish('task-1', [segment(0, {status: 'no_coverage', grade: null})]);
  bridge.applyThresholds(analysis.id, [2, 3]);

  assert.ok(lines(group)[0].options.dashArray, 'sigue discontinuo');
  assert.strictEqual(lines(group)[0].options.color, style.colors().unknown);
});

test('recolorear un análisis que no está publicado no revienta', () => {
  assert.strictEqual(bridge.applyThresholds('no-existe', [4, 5]), false);
});

// --- Convivencia en el bus ---------------------------------------------------------------------

test('un layer ajeno se rechaza en todos los manejadores', () => {
  const foreign = {};
  assert.strictEqual(handlers.toggle(foreign, true), false);
  assert.strictEqual(handlers.del(foreign), false);
});

test('la descarga genérica del panel de capas nunca la atiende este plugin', () => {
  // La exportación de `road` es CSV y GeoJSON con su propio esquema y se pide desde su panel.
  // Devolver true aquí secuestraría el botón y dejaría a `annotations` sin su descarga.
  assert.strictEqual(handlers.download('geojson'), false);
  assert.strictEqual(handlers.download('kml'), false);
});

test('mostrar y ocultar solo actúa sobre los grupos propios', () => {
  const {group} = publish();
  assert.strictEqual(handlers.toggle(group, false), true);
  assert.strictEqual(handlers.toggle(group, true), true);
});

// --- Anotaciones nuevas de otros productores ---------------------------------------------------
//
// Una polilínea recién trazada en `annotations` es un eje candidato: el panel necesita enterarse
// para refrescar su lista sin que el usuario recargue la página. El bridge escucha `addAnnotation`
// pero NUNCA lo consume — es un evento informativo cuyo destinatario real es el panel de capas.

test('una anotación ajena dispara el aviso de eje nuevo y no se consume el evento', () => {
  const added = [];
  bridge.setAnnotationAddedNotifier(() => added.push(1));

  assert.strictEqual(handlers.add({}, 'camino nuevo', {id: 'task-1'}, false), false,
    'el evento debe seguir su curso hacia el resto de manejadores');
  assert.strictEqual(added.length, 1, 'el panel recibe el aviso para refrescar los ejes');

  bridge.setAnnotationAddedNotifier(null);
});

test('publicar un análisis propio no dispara el aviso de eje nuevo', () => {
  const added = [];
  bridge.setAnnotationAddedNotifier(() => added.push(1));

  const {group} = publish();
  assert.strictEqual(handlers.add(group, 'Camino', {id: 'task-1'}, true), false,
    'tampoco sobre lo propio se consume el evento');
  assert.strictEqual(added.length, 0,
    'un análisis de road no es un eje nuevo: refrescar aquí sería un bucle');

  bridge.setAnnotationAddedNotifier(null);
});

test('sin panel montado el aviso simplemente no ocurre', () => {
  bridge.setAnnotationAddedNotifier(null);
  assert.strictEqual(handlers.add({}, 'camino', {id: 'task-1'}, false), false);
});

// --- Borrado desde el panel de capas del core --------------------------------------------------

test('un borrado correcto despublica, avisa al core y avisa al panel', () => {
  notified.length = 0;
  deleted.length = 0;
  busCalls.length = 0;
  ajaxOutcome = {ok: true};
  const {analysis, group} = publish();

  assert.strictEqual(handlers.del(group), true);
  assert.ok(!bridge.isOwned(group), 'el grupo se despublica');
  assert.ok(busCalls.some(c => c[0] === 'annotationDeleted' && c[1] === group));
  assert.deepStrictEqual(deleted, [analysis.id], 'el panel se entera para quitarlo de su lista');
  assert.deepStrictEqual(notified, []);
});

test('un borrado rechazado avisa y no despublica', () => {
  notified.length = 0;
  busCalls.length = 0;
  ajaxOutcome = {ok: false, responseJSON: {error: 'No tienes permiso.'}};
  const {group} = publish();

  assert.strictEqual(handlers.del(group), true, 'el handler sigue consumiendo el evento');
  assert.deepStrictEqual(notified, ['No tienes permiso.']);
  assert.ok(bridge.isOwned(group), 'el análisis sigue publicado');
  assert.ok(!busCalls.some(c => c[0] === 'annotationDeleted'),
    'sin annotationDeleted el core conserva la anotación y el estado visible es el correcto');
});

test('un fallo sin cuerpo JSON usa el mensaje por defecto, nunca silencio', () => {
  notified.length = 0;
  ajaxOutcome = {ok: false, responseJSON: null};
  handlers.del(publish().group);

  assert.strictEqual(notified.length, 1);
  assert.ok(/No se pudo eliminar/.test(notified[0]), 'mensaje inesperado: ' + notified[0]);
});

// --- Popup de tramo ----------------------------------------------------------------------------

test('el popup lleva las cuatro métricas del tramo', () => {
  const html = bridge.popupHtml(segment(0));
  ['Progresiva', 'Cota', 'Pendiente', 'Ancho', 'Pendiente transversal']
    .forEach(label => assert.ok(html.includes(label), 'falta ' + label));
  assert.ok(html.includes('8.00 m'), 'el ancho medido debe aparecer');
});

test('el popup marca el lado inferido sin borrar el motivo', () => {
  // `006` FR-031 y FR-020: la distancia existe Y el motivo original se conserva. Las dos cosas
  // se muestran juntas — "no se pudo medir aquí, el valor viene de los vecinos".
  const html = bridge.popupHtml(segment(0, {
    status: 'inferred', width: 9.8, offset_left: 4.0, offset_right: 5.8,
    left_edge_source: 'measured', right_edge_source: 'inferred',
    right_reason: 'no_break'
  }));

  assert.ok(html.includes('5.80 m'), 'la distancia inferida se muestra');
  assert.ok(html.includes('inferido'), 'y se declara como inferida');
  assert.ok(html.includes('sin quiebre'), 'el motivo original la acompaña');
  assert.ok(!/4\.00 m[^<]*inferido/.test(html), 'el lado medido no lleva la marca');
});

test('un tramo medido no lleva ninguna marca de inferido', () => {
  assert.ok(!bridge.popupHtml(segment(0)).includes('inferido'));
});

test('un tramo sin borde muestra el motivo por lado, no un ancho inventado', () => {
  const html = bridge.popupHtml(segment(0, {
    status: 'no_edge', width: null, cross_slope: null,
    offset_left: 4, offset_right: null,
    left_reason: null, right_reason: 'no_data'
  }));

  assert.ok(html.includes('sin datos de elevación'), 'el motivo del lado sin borde');
  assert.ok(html.includes('4.00 m'), 'el lado que sí midió conserva su distancia');
  assert.ok(html.includes('—'), 'el ancho ausente se muestra vacío, no como cero');
});

summary('roadBridge');
