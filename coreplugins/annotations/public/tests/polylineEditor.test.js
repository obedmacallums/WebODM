/* Inserción de vértices por click sobre la línea en modo edición (FR-004).
 *
 * El hit-test trabaja en píxeles para que la tolerancia sea la misma a cualquier zoom, así que
 * necesita un mapa Leaflet de verdad: las proyecciones son justamente lo que se está probando.
 */
const assert = require('assert');
const {setupDom, loadModule, createMap, test, summary} = require('./harness');

setupDom();
const L = require('leaflet');

const PluginsAPI = {Map: {onHandleClick(){}, offHandleClick(){}}};
const PolylineEditor = loadModule('PolylineEditor.js', {L, PluginsAPI});

const map = createMap(L);

// Polilínea en L: A-B horizontal, B-C vertical.
const A = L.latLng(45.0000, -122.0000);
const B = L.latLng(45.0000, -121.9990);
const C = L.latLng(44.9995, -121.9990);

let latlngs;
let changes;
let editor;

function reset(vertices = [A, B, C]){
  latlngs = vertices.slice();
  changes = 0;
  editor = new PolylineEditor(map);
  editor.editingLayer = {getLatLngs: () => latlngs, setLatLngs: (ll) => { latlngs = ll; }};
  editor.onChange = () => { changes++; };
  editor._redrawEditHandles = () => {}; // los marcadores son DOM; aquí se prueba la geometría
  map.hasLayer = () => true;
}

/** Click a `dx`/`dy` píxeles del punto indicado, en el formato que entrega Leaflet. */
function clickAt(latlng, dx = 0, dy = 0){
  const p = map.latLngToLayerPoint(latlng);
  return {layerPoint: L.point(p.x + dx, p.y + dy)};
}

const mid = (p, q) => L.latLng((p.lat + q.lat) / 2, (p.lng + q.lng) / 2);

test('un click sobre el primer tramo lo identifica', () => {
  reset();
  const hit = editor._hitTestLine(clickAt(mid(A, B)));
  assert.ok(hit, 'debería detectar el tramo A-B');
  assert.strictEqual(hit.index, 0);
});

test('un click sobre el segundo tramo lo identifica', () => {
  reset();
  const hit = editor._hitTestLine(clickAt(mid(B, C)));
  assert.ok(hit, 'debería detectar el tramo B-C');
  assert.strictEqual(hit.index, 1);
});

test('dentro de la tolerancia el vértice nuevo cae sobre la línea, no bajo el cursor', () => {
  reset();
  const hit = editor._hitTestLine(clickAt(mid(A, B), 0, -8));
  assert.ok(hit, '8 px de separación entran en la tolerancia');
  const snapped = map.latLngToLayerPoint(hit.latlng);
  const offLine = L.LineUtil.pointToSegmentDistance(
    snapped, map.latLngToLayerPoint(A), map.latLngToLayerPoint(B));
  assert.ok(offLine < 0.5, 'quedó a ' + offLine.toFixed(3) + ' px del tramo');
});

test('un click lejos de la línea no inserta nada', () => {
  reset();
  assert.strictEqual(editor._hitTestLine(clickAt(mid(A, B), 0, -40)), null);
});

test('un click pegado a un vértice existente no inserta encima', () => {
  reset();
  assert.strictEqual(editor._hitTestLine(clickAt(B, 3, 0)), null,
    'a 3 px de un vértice el gesto es arrastrar o borrar');
});

test('el click del mapa solo se consume cuando va a insertar', () => {
  reset();
  assert.strictEqual(editor._handleCoreClick(clickAt(mid(A, B))), true,
    'sobre la línea se consume, o el core abriría el popup de la ortofoto');
  assert.strictEqual(editor._handleCoreClick(clickAt(mid(A, B), 0, -40)), false,
    'fuera de la línea el resto del mapa debe seguir funcionando');
});

test('la inserción respeta el orden de los vértices y persiste una sola vez', () => {
  reset();
  editor._handleEditClick(clickAt(mid(B, C)));
  assert.strictEqual(latlngs.length, 4, 'la polilínea pasa de 3 a 4 vértices');
  assert.strictEqual(changes, 1, 'onChange dispara el PATCH una vez');
  assert.ok(latlngs[0].equals(A) && latlngs[1].equals(B) && latlngs[3].equals(C),
    'el vértice nuevo va entre B y C, no al final');
});

test('un click en el vacío no toca la geometría', () => {
  reset();
  editor._handleEditClick(clickAt(mid(A, B), 0, -40));
  assert.strictEqual(latlngs.length, 3);
  assert.strictEqual(changes, 0);
});

test('sin tramos no hay dónde insertar', () => {
  reset([A]);
  assert.strictEqual(editor._hitTestLine(clickAt(A, 20, 0)), null);
});

summary('PolylineEditor');
