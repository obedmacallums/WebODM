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

test('un tramo inferido se distingue del medido y del sin-ancho a la vez', () => {
  // `006` FR-032: tiene ancho —peso y color de tramo completo— pero no todo se midió aquí, y
  // eso debe verse sin abrir el popup. Su raya es distinta de la del no_edge.
  const inferred = style.styleForSegment({status: 'inferred', grade: 3}, THRESHOLDS);
  const measured = style.styleForSegment({status: 'measured', grade: 3}, THRESHOLDS);
  const noEdge = style.styleForSegment({status: 'no_edge', grade: 3}, THRESHOLDS);

  assert.strictEqual(inferred.color, palette.ok, 'el semáforo no cambia por el origen');
  assert.strictEqual(inferred.weight, measured.weight, 'peso de tramo con ancho');
  assert.ok(inferred.dashArray, 'algo debe marcar que no todo se midió aquí');
  assert.notStrictEqual(inferred.dashArray, noEdge.dashArray,
    'con la misma raya que un no_edge, un ancho inferido pasaría por ausente');
  assert.strictEqual(measured.dashArray, null);
});

// --- Regla del ancho -----------------------------------------------------------------------------

test('sin umbrales de ancho la regla conserva su verde neutro y nunca es interactiva', () => {
  // Un análisis sin ancho medio del que deducirlos, o guardado antes de que existiera el control.
  const tick = style.widthTickStyle({status: 'measured', width: 8});

  assert.notStrictEqual(tick.color, palette.ok,
    'sin criterio de ancho no puede fingir el verde del semáforo, que habla de pendiente');
  assert.strictEqual(tick.interactive, false);
  assert.strictEqual(tick.dashArray, null, 'un ancho medido se dibuja con trazo rotundo');
});

// --- Semáforo del ancho --------------------------------------------------------------------------
//
// Al revés que el de pendiente: aquí lo malo es quedarse corto. `[mínimo, holgado]`.

test('el ancho pinta de rojo por debajo del mínimo y de verde por encima del holgado', () => {
  const t = [15.0, 20.0];

  assert.strictEqual(style.colorForWidth(12.0, t), palette.alert, 'estrecho es el problema');
  assert.strictEqual(style.colorForWidth(18.0, t), palette.warn);
  assert.strictEqual(style.colorForWidth(25.0, t), palette.ok, 'de sobra ancho');
});

test('los umbrales del ancho son inclusivos por arriba, como los de pendiente', () => {
  const t = [15.0, 20.0];

  assert.strictEqual(style.colorForWidth(15.0, t), palette.warn, 'justo en el mínimo, ya no es rojo');
  assert.strictEqual(style.colorForWidth(20.0, t), palette.ok, 'justo en el holgado, ya es verde');
});

test('un ancho ausente no se pinta de ningún juicio', () => {
  assert.strictEqual(style.colorForWidth(null, [15.0, 20.0]), palette.unknown);
  assert.strictEqual(style.colorForWidth(undefined, [15.0, 20.0]), palette.unknown);
});

test('a la regla la colorea el ancho, nunca la pendiente', () => {
  // La confusión que esto evita: un tramo empinado y ancho tiene el eje rojo y la regla verde, y
  // las dos cosas son ciertas. Compartir paleta no puede significar compartir criterio.
  const steepAndWide = {status: 'measured', grade: 40, width: 25};
  const flatAndNarrow = {status: 'measured', grade: 1, width: 12};

  assert.strictEqual(style.widthTickStyle(steepAndWide, [15.0, 20.0]).color, palette.ok);
  assert.strictEqual(style.widthTickStyle(flatAndNarrow, [15.0, 20.0]).color, palette.alert);
});

test('la regla de un ancho inferido va discontinua', () => {
  // La convención de honestidad alcanza también a la regla: lo deducido no se dibuja igual que
  // lo medido.
  assert.ok(style.widthTickStyle({status: 'inferred'}).dashArray);
});

// --- Área de captura del cursor ------------------------------------------------------------------

test('el área de captura es invisible, ancha y continua', () => {
  // Sus tres propiedades responden cada una a algo medido en el navegador: el trazo visible solo
  // responde a ±2 px de su eje, los huecos de un trazo discontinuo no reciben nada, y un trazo con
  // opacidad 0 sí recibe el cursor.
  const hit = style.hitStyle();
  const visible = style.styleForSegment({status: 'measured', grade: 3}, THRESHOLDS);

  assert.strictEqual(hit.opacity, 0, 'si se viera, taparía el mapa a lo largo de toda la ruta');
  assert.ok(hit.weight >= visible.weight * 3,
    'ancho ' + hit.weight + ' frente a los ' + visible.weight + ' del trazo: no basta');
  assert.strictEqual(hit.dashArray, null, 'discontinua dejaría los huecos como zona muerta');
  assert.strictEqual(hit.lineCap, 'butt', 'con extremos redondeados invadiría al tramo vecino');
  assert.strictEqual(hit.interactive, true);
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
