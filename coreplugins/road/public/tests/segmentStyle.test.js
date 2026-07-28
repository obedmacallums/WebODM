/* El semáforo de pendiente (`research.md` D15).
 *
 * Es una función pura y es la regla que el usuario mueve con dos deslizadores esperando ver el
 * efecto al instante, así que aquí se comprueba contra los bordes exactos de cada rango: un `<`
 * donde debía ir un `<=` pinta de amarillo un tramo que el usuario configuró como aceptable.
 */
const assert = require('assert');
const {setupDom, loadModule, test, summary} = require('./harness');

setupDom();

const style = loadModule('segmentStyle.js', {});
const palette = style.colors();
const THRESHOLDS = [8.0, 12.0];

// --- Rangos del semáforo -----------------------------------------------------------------------

test('por debajo del aviso es verde', () => {
  assert.strictEqual(style.colorForGrade(0, THRESHOLDS), palette.ok);
  assert.strictEqual(style.colorForGrade(7.99, THRESHOLDS), palette.ok);
});

test('el propio umbral de aviso todavía es verde', () => {
  assert.strictEqual(style.colorForGrade(8.0, THRESHOLDS), palette.ok);
});

test('entre aviso y alerta es amarillo, alerta incluida', () => {
  assert.strictEqual(style.colorForGrade(8.01, THRESHOLDS), palette.warn);
  assert.strictEqual(style.colorForGrade(12.0, THRESHOLDS), palette.warn);
});

test('por encima de la alerta es rojo', () => {
  assert.strictEqual(style.colorForGrade(12.01, THRESHOLDS), palette.alert);
  assert.strictEqual(style.colorForGrade(45, THRESHOLDS), palette.alert);
});

test('la pendiente se juzga en valor absoluto', () => {
  // Bajar al 15 % es tan exigente para un camino como subirlo: el signo solo dice hacia dónde.
  assert.strictEqual(style.colorForGrade(-15, THRESHOLDS), style.colorForGrade(15, THRESHOLDS));
  assert.strictEqual(style.colorForGrade(-3, THRESHOLDS), palette.ok);
});

test('sin pendiente el color es el de "sin datos", nunca el verde', () => {
  // Pintar de verde un tramo sin medir diría que es suave, que es exactamente lo que no se sabe.
  assert.strictEqual(style.colorForGrade(null, THRESHOLDS), palette.unknown);
  assert.strictEqual(style.colorForGrade(undefined, THRESHOLDS), palette.unknown);
  assert.strictEqual(style.colorForGrade(NaN, THRESHOLDS), palette.unknown);
});

test('unos umbrales más estrictos recolorean el mismo tramo', () => {
  assert.strictEqual(style.colorForGrade(6, [8, 12]), palette.ok);
  assert.strictEqual(style.colorForGrade(6, [4, 5]), palette.alert);
});

test('sin umbrales se usan los de por defecto', () => {
  assert.strictEqual(style.colorForGrade(6, null), palette.ok);
  assert.strictEqual(style.colorForGrade(20, undefined), palette.alert);
});

// --- Estilo completo del tramo -----------------------------------------------------------------

test('un tramo medido va con trazo continuo', () => {
  const s = style.styleForSegment({status: 'measured', grade: 3}, THRESHOLDS);
  assert.strictEqual(s.color, palette.ok);
  assert.strictEqual(s.dashArray, null);
});

test('un tramo sin borde conserva el color de su pendiente pero va discontinuo', () => {
  // Tiene rasante medida; lo que no tiene es ancho. Pintarlo gris tiraría información real.
  const s = style.styleForSegment({status: 'no_edge', grade: 14}, THRESHOLDS);
  assert.strictEqual(s.color, palette.alert);
  assert.ok(s.dashArray, 'debe distinguirse de un tramo medido');
});

test('un tramo sin cobertura va gris y discontinuo', () => {
  const s = style.styleForSegment({status: 'no_coverage', grade: null}, THRESHOLDS);
  assert.strictEqual(s.color, palette.unknown);
  assert.ok(s.dashArray);
});

// --- Motivos por lado --------------------------------------------------------------------------

test('cada motivo de "sin borde" tiene su etiqueta y todas son distintas', () => {
  // FR-021: los tres motivos son problemas distintos con soluciones distintas —retocar el umbral,
  // volar de nuevo, o corregir el trazado del eje—, así que ninguna etiqueta puede repetirse.
  const labels = ['no_break', 'no_data', 'break_at_axis'].map(style.reasonLabel);
  labels.forEach(l => assert.ok(l, 'falta una etiqueta'));
  assert.strictEqual(new Set(labels).size, 3, 'hay etiquetas repetidas: ' + labels.join(' / '));
  assert.strictEqual(style.reasonLabel(null), null);
  assert.strictEqual(style.reasonLabel('inventado'), null);
});

summary('segmentStyle');
