/* Decisiones de estado del panel que viven fuera del componente React para poder probarse aquí:
 * qué parámetros siembra el formulario al cargar, qué hacer con cada análisis que trae el sondeo
 * y qué eje queda seleccionado tras refrescar la lista.
 *
 * Los tres arreglos que cubren nacieron del mismo síntoma —"tengo que refrescar la página"—:
 * el formulario volvía a los defectos, el recálculo no se redibujaba (el servidor reutiliza el
 * `id` del análisis y `publish` se saltaba lo ya publicado) y una polilínea nueva de
 * `annotations` no aparecía como eje.
 */
const assert = require('assert');
const {loadModule, test, summary} = require('./harness');

const logic = loadModule('panelLogic.js', {});

// --- initialParams: el formulario arranca con lo último que se calculó -----------------------

const DEFAULTS = {
  segment_length: 5.0, search_half_width: 10.0, sample_step: 0.1,
  break_threshold: 15.0, min_consecutive_samples: 3, edge_mode: 'break',
  surface_tolerance: 0.06, coherence_window: 0
};

function analysis(overrides){
  return Object.assign({
    id: 'a', status: 'completed',
    created_at: '2026-07-28T10:00:00Z', updated_at: '2026-07-28T10:00:00Z',
    params: Object.assign({}, DEFAULTS)
  }, overrides);
}

test('sin análisis, initialParams devuelve una copia de los defectos', () => {
  const params = logic.initialParams(DEFAULTS, []);
  assert.deepStrictEqual(params, DEFAULTS);
  assert.notStrictEqual(params, DEFAULTS);   // copia, no la misma referencia
});

test('con análisis, gana el de updated_at más reciente', () => {
  const older = analysis({id: 'a', updated_at: '2026-07-28T10:00:00Z',
                          params: Object.assign({}, DEFAULTS, {search_half_width: 12})});
  const newer = analysis({id: 'b', updated_at: '2026-07-28T11:00:00Z',
                          params: Object.assign({}, DEFAULTS, {search_half_width: 18})});
  const params = logic.initialParams(DEFAULTS, [older, newer]);
  assert.strictEqual(params.search_half_width, 18);
});

test('una clave que el análisis no trae se rellena con su defecto', () => {
  const old = analysis({params: {segment_length: 8}});   // análisis anterior a que existieran más parámetros
  const params = logic.initialParams(DEFAULTS, [old]);
  assert.strictEqual(params.segment_length, 8);
  assert.strictEqual(params.edge_mode, 'break');
  assert.strictEqual(params.coherence_window, 0);
});

test('un análisis sin params se ignora y decide el anterior que sí los tenga', () => {
  const withParams = analysis({id: 'a', updated_at: '2026-07-28T10:00:00Z',
                               params: Object.assign({}, DEFAULTS, {break_threshold: 25})});
  const without = analysis({id: 'b', updated_at: '2026-07-28T11:00:00Z', params: undefined});
  const params = logic.initialParams(DEFAULTS, [withParams, without]);
  assert.strictEqual(params.break_threshold, 25);
});

test('sin updated_at se ordena por created_at', () => {
  const older = analysis({id: 'a', updated_at: undefined, created_at: '2026-07-28T10:00:00Z',
                          params: Object.assign({}, DEFAULTS, {sample_step: 0.5})});
  const newer = analysis({id: 'b', updated_at: undefined, created_at: '2026-07-28T11:00:00Z',
                          params: Object.assign({}, DEFAULTS, {sample_step: 1.0})});
  const params = logic.initialParams(DEFAULTS, [older, newer]);
  assert.strictEqual(params.sample_step, 1.0);
});

test('initialParams no muta los defectos', () => {
  const defaults = Object.assign({}, DEFAULTS);
  logic.initialParams(defaults, [analysis({params: {segment_length: 99}})]);
  assert.deepStrictEqual(defaults, DEFAULTS);
});

// --- publishAction: qué hacer con cada análisis del sondeo -----------------------------------
//
// El servidor reutiliza el `id` al recalcular sobre el mismo eje, así que "ya está publicado" no
// significa "ya está al día": un análisis publicado que vuelve a estar `running` es un recálculo
// en marcha y su dibujo viejo tiene que salir del mapa.

test('completed sin publicar -> publish', () => {
  assert.strictEqual(logic.publishAction(undefined, {status: 'completed'}), 'publish');
});

test('completed ya publicado -> none', () => {
  assert.strictEqual(logic.publishAction({}, {status: 'completed'}), 'none');
});

test('running publicado -> unpublish (recálculo pisando el mismo id)', () => {
  assert.strictEqual(logic.publishAction({}, {status: 'running'}), 'unpublish');
});

test('running sin publicar -> none (el sondeo espera al resultado)', () => {
  assert.strictEqual(logic.publishAction(undefined, {status: 'running'}), 'none');
});

test('failed o canceled publicados -> unpublish (los tramos viejos ya no existen en el servidor)', () => {
  assert.strictEqual(logic.publishAction({}, {status: 'failed'}), 'unpublish');
  assert.strictEqual(logic.publishAction({}, {status: 'canceled'}), 'unpublish');
});

test('la reserva en vuelo (true) cuenta como publicado', () => {
  assert.strictEqual(logic.publishAction(true, {status: 'running'}), 'unpublish');
  assert.strictEqual(logic.publishAction(true, {status: 'completed'}), 'none');
});

// --- axisSelection: qué eje queda elegido tras refrescar la lista ----------------------------

const AXES = [{id: 'ax1', name: 'camino'}, {id: 'ax2', name: 'rampa'}];

test('la selección vigente se conserva si el eje sigue en la lista', () => {
  assert.strictEqual(logic.axisSelection(AXES, 'ax2'), 'ax2');
});

test('si el eje elegido desapareció se pasa al primero', () => {
  assert.strictEqual(logic.axisSelection(AXES, 'borrado'), 'ax1');
});

test('sin ejes la selección queda vacía', () => {
  assert.strictEqual(logic.axisSelection([], 'ax1'), '');
  assert.strictEqual(logic.axisSelection(undefined, 'ax1'), '');
});

summary('panelLogic');
