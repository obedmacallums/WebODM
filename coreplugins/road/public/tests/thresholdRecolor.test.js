/* Recoloreado por umbrales sobre un análisis grande (SC-005, FR-030).
 *
 * La promesa que se verifica aquí es concreta: mover un umbral recolorea **el grupo entero** y
 * **no pide nada al servidor**. Si el recoloreado necesitara volver a bajar el análisis, cada
 * arrastre del deslizador costaría una petición y varios megabytes, y la respuesta inmediata que
 * el usuario espera de un control de color se convertiría en una espera.
 *
 * El segundo invariante es que los tramos sin medir **no** se cuelan en el semáforo: por muchos
 * umbrales que se muevan, siguen grises y discontinuos.
 */
const assert = require('assert');
const {setupDom, loadModule, test, summary} = require('./harness');

setupDom();
const L = require('leaflet');

const handlers = {};
const PluginsAPI = {Map: {
  onToggleAnnotation: (fn) => { handlers.toggle = fn; },
  onDeleteAnnotation: (fn) => { handlers.del = fn; },
  onDownloadAnnotations: (fn) => { handlers.download = fn; },
  onAddAnnotation: () => {},
  addAnnotation: () => {},
  updateAnnotation: () => {},
  annotationDeleted: () => {}
}};

// Cualquier petición durante un recoloreado es un fallo: se registran todas para poder afirmarlo.
const requests = [];
const $ = {
  ajax: (opts) => {
    requests.push(opts.url);
    return {done(){ return this; }, fail(){ return this; }};
  },
  getJSON: (url) => { requests.push(url); return {done(){ return this; }, fail(){ return this; }}; }
};

const style = loadModule('segmentStyle.js', {});
const bridge = loadModule('roadBridge.js', {
  L, PluginsAPI, $, _: (s) => s,
  styleForSegment: style.styleForSegment,
  reasonLabel: style.reasonLabel,
  hitStyle: style.hitStyle,
  widthTickStyle: style.widthTickStyle
});
bridge.initBridge();

const palette = style.colors();
const map = {addLayer(){}, hasLayer(){ return true; }, removeLayer(){}};

// 200 tramos: el orden de magnitud de un camino de 1 km con los valores por defecto.
const GRADES = [2, 6, 9, 11, 14, 25, -3, -9, -13];
function buildSegments(count = 200){
  const segments = [];
  for (let i = 0; i < count; i++){
    const measured = i % 10 !== 0;              // uno de cada diez sin medir
    segments.push({
      index: i,
      status: measured ? 'measured' : (i % 20 === 0 ? 'no_coverage' : 'no_edge'),
      grade: (measured || i % 20 !== 0) ? GRADES[i % GRADES.length] : null,
      geometry: [[0, i * 0.0001], [0.0001, i * 0.0001]]
    });
  }
  return segments;
}

const segments = buildSegments();
const analysis = {id: 'a1', name: 'Camino largo', color_thresholds: [8, 12]};
const group = bridge.publishAnalysis(map, {id: 'task-1'}, analysis, segments, {stored: true});

// Dos capas por tramo: la visible y su área de captura invisible, que es la interactiva y la que
// lleva el `_roadSegment`. El color vive en la visible.
function lines(){
  return group.getLayers().filter(l => !l._roadSegment);
}

function colorsOf(){
  return lines().map(l => l.options.color);
}

test('el grupo se dibuja con un trazo y un área de captura por tramo', () => {
  assert.strictEqual(lines().length, segments.length);
  assert.strictEqual(group.getLayers().length, segments.length * 2);
});

test('recolorear no dispara ninguna petición', () => {
  requests.length = 0;
  assert.strictEqual(bridge.applyThresholds('a1', [4, 6]), true);
  assert.deepStrictEqual(requests, [],
    'el recoloreado pidió datos al servidor: ' + JSON.stringify(requests));
});

test('el recoloreado alcanza al grupo entero, no solo a lo visible', () => {
  bridge.applyThresholds('a1', [8, 12]);
  const before = colorsOf();
  // Por debajo de la pendiente más suave del juego de prueba (2 %), y estrictamente: el rango
  // amarillo incluye su propio techo, así que con [1, 2] un tramo del 2 % seguiría amarillo.
  bridge.applyThresholds('a1', [0.5, 1]);
  const after = colorsOf();

  const measuredIdx = segments
    .map((s, i) => s.status === 'measured' ? i : -1).filter(i => i >= 0);
  measuredIdx.forEach(i => assert.strictEqual(after[i], palette.alert,
    'el tramo ' + i + ' no se recoloreó'));
  assert.notDeepStrictEqual(before, after);
});

test('cada rango del semáforo se aplica al tramo que le toca', () => {
  bridge.applyThresholds('a1', [8, 12]);
  const applied = colorsOf();

  segments.forEach((s, i) => {
    if (s.status !== 'measured') return;
    const magnitude = Math.abs(s.grade);
    const expected = magnitude <= 8 ? palette.ok : magnitude <= 12 ? palette.warn : palette.alert;
    assert.strictEqual(applied[i], expected,
      'tramo ' + i + ' con pendiente ' + s.grade + '%');
  });
});

test('los tramos sin medir conservan su estilo distinguible tras cualquier umbral', () => {
  [[1, 2], [8, 12], [20, 40]].forEach(thresholds => {
    bridge.applyThresholds('a1', thresholds);
    lines().forEach((layer, i) => {
      if (segments[i].status === 'measured') return;
      assert.ok(layer.options.dashArray,
        'el tramo ' + i + ' perdió su trazo discontinuo con umbrales ' + thresholds);
      if (segments[i].status === 'no_coverage'){
        assert.strictEqual(layer.options.color, palette.unknown,
          'un tramo sin cobertura se pintó como si tuviera pendiente medida');
      }
    });
  });
});

test('los umbrales quedan registrados para el siguiente recoloreado', () => {
  bridge.applyThresholds('a1', [5, 9]);
  const meta = bridge.registry.get(group);
  assert.deepStrictEqual(meta.thresholds, [5, 9]);
});

test('SC-005: el recoloreado completo tarda menos de 2 segundos', () => {
  // El presupuesto es el del criterio de éxito, no el tiempo esperado: en jsdom, sin renderer de
  // Leaflet, esto tarda milisegundos. El aserto está para que un cambio futuro que convierta el
  // recoloreado en algo caro —recrear las polilíneas en vez de hacer setStyle, por ejemplo— falle
  // aquí y no en las manos del usuario.
  const started = Date.now();
  for (let i = 0; i < 10; i++) bridge.applyThresholds('a1', [4 + i * 0.1, 12]);
  const perPass = (Date.now() - started) / 10;

  assert.ok(perPass < 2000, 'un recoloreado de ' + segments.length +
    ' tramos tardó ' + perPass.toFixed(1) + ' ms');
});

summary('thresholdRecolor');
