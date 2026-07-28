/* Resaltado del tramo bajo el cursor.
 *
 * Un análisis de 1 km son ~200 polilíneas contiguas y dos tramos del mismo color parecen una sola
 * línea: sin resaltado no se ve dónde acaba uno y empieza el siguiente, ni qué tramo va a
 * responder al click.
 *
 * Lo que más importa comprobar aquí no es que el contorno aparezca, sino sus dos condiciones de
 * corrección: que **no sea interactivo** —o se coloca bajo el cursor y se come el click, que es lo
 * único que ya funcionaba— y que haya **uno solo** reutilizado, no un contorno por tramo.
 */
const assert = require('assert');
const {setupDom, loadModule, createMap, test, summary} = require('./harness');

setupDom();
const L = require('leaflet');

// Leaflet detecta soporte de SVG con `createSVGRect`, que jsdom no implementa, así que su fábrica
// de renderers devuelve `null` y **cualquier `Path` revienta al añadirse al mapa**. Forzar
// `L.Browser.svg` no sirve: la fábrica consulta una variable interna del módulo, no esa bandera.
// Lo que sí funciona es darle al mapa un renderer explícito, que `getRenderer` respeta antes de
// intentar crear uno. El resto del DOM SVG sí existe en jsdom, así que el renderer real funciona
// — y con él `bringToFront`, que es de donde sale la separación visible entre tramos.
function mapWithRenderer(){
  const m = createMap(L);
  m.options.renderer = new L.SVG();
  return m;
}

const PluginsAPI = {Map: {
  onToggleAnnotation: () => {},
  onDeleteAnnotation: () => {},
  onDownloadAnnotations: () => {},
  addAnnotation: () => {},
  updateAnnotation: () => {},
  annotationDeleted: () => {}
}};

const $ = {ajax: () => ({done(){ return this; }, fail(){ return this; }})};

const style = loadModule('segmentStyle.js', {});
const bridge = loadModule('roadBridge.js', {
  L, PluginsAPI, $, _: (s) => s,
  styleForSegment: style.styleForSegment,
  reasonLabel: style.reasonLabel,
  haloStyleFor: style.haloStyleFor
});
bridge.initBridge();

const map = mapWithRenderer();

function segment(index, overrides = {}){
  const lat = 45 + index * 0.00005;
  return Object.assign({
    index,
    station_start: index * 5, station_end: (index + 1) * 5, length: 5,
    geometry: [[-122, lat], [-122 + 0.00005, lat]],
    midpoint: [-122 + 0.000025, lat],
    elevation: 100, grade: 3, grade_deg: 1.7,
    width: 8, offset_left: 4, offset_right: 4, cross_slope: 2,
    status: 'measured', left_reason: null, right_reason: null,
    cross_section: [[-122, lat], [-122, lat]], edge_left: null, edge_right: null
  }, overrides);
}

let seq = 0;
function publish(segments){
  seq++;
  return bridge.publishAnalysis(map, {id: 'task-1'},
    {id: 'a' + seq, name: 'Camino ' + seq, color_thresholds: [8, 12]}, segments, {stored: true});
}

const segments = [segment(0), segment(1, {grade: 20}),
                  segment(2, {status: 'no_edge', left_reason: 'no_break'})];
const group = publish(segments);
const layers = group.getLayers();

function halo(){ return bridge.currentHalo(); }

// --- Aparecer y desaparecer ------------------------------------------------------------------

test('pasar el cursor coloca el contorno sobre ese tramo', () => {
  layers[0].fire('mouseover');
  const h = halo();

  assert.ok(h, 'no apareció ningún contorno');
  assert.deepStrictEqual(h.getLatLngs().map(ll => [ll.lng, ll.lat]),
                         segments[0].geometry,
                         'el contorno no tomó la geometría del tramo bajo el cursor');
});

test('sacar el cursor lo retira', () => {
  layers[0].fire('mouseover');
  layers[0].fire('mouseout');
  assert.strictEqual(halo(), null);
});

test('pasar a otro tramo lo mueve en vez de añadir uno nuevo', () => {
  // El contorno es uno solo y reutilizado: uno por tramo doblaría los layers del mapa.
  layers[0].fire('mouseover');
  const first = halo();
  layers[1].fire('mouseover');
  const second = halo();

  assert.strictEqual(first, second, 'se creó un contorno nuevo en vez de mover el existente');
  assert.deepStrictEqual(second.getLatLngs().map(ll => [ll.lng, ll.lat]), segments[1].geometry);
  layers[1].fire('mouseout');
});

// --- Las dos condiciones de corrección --------------------------------------------------------

test('el contorno NO es interactivo, o se comería el click', () => {
  layers[0].fire('mouseover');
  assert.strictEqual(halo().options.interactive, false);
  layers[0].fire('mouseout');
});

test('el contorno es blanco y más ancho que el tramo', () => {
  layers[0].fire('mouseover');
  const h = halo();
  const base = style.styleForSegment(segments[0], [8, 12]);

  assert.strictEqual(h.options.color, '#ffffff');
  assert.ok(h.options.weight > base.weight,
    'un contorno igual de ancho que el tramo no se ve: ' + h.options.weight);
  layers[0].fire('mouseout');
});

test('el contorno rebasa los extremos del tramo para separarlo de sus vecinos', () => {
  // Con `lineCap: butt` el blanco solo asomaría por los flancos y dos tramos verdes seguidos
  // seguirían pareciendo una sola línea, que es el problema que esto viene a resolver.
  layers[0].fire('mouseover');
  assert.strictEqual(halo().options.lineCap, 'round');
  layers[0].fire('mouseout');
});

test('sobre un tramo sin medir el contorno es continuo', () => {
  // El trazo discontinuo del tramo se sigue viendo encima; un contorno discontinuo solo lo
  // emborronaría.
  layers[2].fire('mouseover');
  assert.strictEqual(halo().options.dashArray, null);
  layers[2].fire('mouseout');
});

test('un layer ajeno no dispara el contorno', () => {
  assert.strictEqual(bridge.showHalo(map, L.polyline([[45, -122], [45.001, -122]])), false);
  assert.strictEqual(halo(), null);
});

// --- Persistencia con el popup abierto --------------------------------------------------------

test('con el popup abierto el contorno se queda al mover el ratón', () => {
  // Sin esto, al apartar el ratón para leer el popup se pierde de vista de qué tramo hablaba.
  layers[1].fire('mouseover');
  layers[1].fire('popupopen');
  layers[1].fire('mouseout');

  assert.ok(halo(), 'el contorno desapareció con el popup todavía abierto');
  assert.deepStrictEqual(halo().getLatLngs().map(ll => [ll.lng, ll.lat]), segments[1].geometry);
});

test('pasar por otro tramo con el popup abierto lo resalta, y al salir vuelve al fijado', () => {
  layers[0].fire('mouseover');
  assert.deepStrictEqual(halo().getLatLngs().map(ll => [ll.lng, ll.lat]), segments[0].geometry);

  layers[0].fire('mouseout');
  assert.deepStrictEqual(halo().getLatLngs().map(ll => [ll.lng, ll.lat]), segments[1].geometry,
    'al salir debería volver al tramo cuyo popup sigue abierto');
});

test('cerrar el popup libera el contorno', () => {
  layers[1].fire('popupclose');
  assert.strictEqual(halo(), null);
});

// --- Limpieza ---------------------------------------------------------------------------------

test('despublicar el análisis no deja el contorno flotando', () => {
  const other = publish([segment(0)]);
  other.getLayers()[0].fire('mouseover');
  assert.ok(halo());

  bridge.unpublishAnalysis(other);
  assert.strictEqual(halo(), null, 'el contorno sobrevivió al grupo que lo originó');
});

summary('hoverHighlight');
