/* La capa de máscara del modelo (`008` US1/US2/US3, `research.md` D39).
 *
 * Se prueba el archivo real de `public/`, no una copia. Lo que se fija aquí son las tres cosas que
 * si se rompen dejan la feature inservible o mentirosa: que no capture eventos, que deje ver la
 * ortofoto debajo, y que no confunda «el modelo no vio calzada» con «no hay máscara guardada».
 */
const assert = require('assert');
const {setupDom, loadModule, test, summary} = require('./harness');

setupDom();

const L = require('leaflet');
const style = loadModule('segmentStyle.js', {});
// El harness inyecta por **nombre de binding**, no por ruta de módulo: `import L from 'leaflet'`
// entra como `L`, e `import { _ } from '...gettext'` como `_`.
const mask = loadModule('maskLayer.js', {L, _: (s) => s});

const POLYGON = {
  type: 'Feature',
  properties: {class: 'road'},
  geometry: {type: 'Polygon',
             coordinates: [[[-93.0, 45.0], [-92.9, 45.0], [-92.9, 45.1], [-93.0, 45.0]]]}
};

// --- Estilo -------------------------------------------------------------------------------

test('no captura eventos de ratón', () => {
  // Sin esto, un polígono encima de los tramos rompe los popups y el resaltado que `roadBridge`
  // monta con su polilínea `hit` invisible.
  assert.strictEqual(mask.maskStyle().interactive, false);
});

test('el relleno es translúcido, no opaco', () => {
  // La capa existe para COMPARAR con la ortofoto de debajo: opaca no sirve de nada.
  const opacity = mask.maskStyle().fillOpacity;
  assert.ok(opacity > 0 && opacity < 0.6, 'fillOpacity fuera de rango legible: ' + opacity);
});

test('el color no es ninguno del semáforo de pendiente', () => {
  // Verde/amarillo/rojo significan pendiente en el eje y ancho en las reglas. Reutilizar uno
  // aquí leería como una tercera métrica inexistente.
  const palette = style.colors();
  const used = Object.values(palette).map(c => c.toLowerCase());
  assert.ok(!used.includes(mask.MASK_COLOR.toLowerCase()),
            'la máscara usa un color del semáforo: ' + mask.MASK_COLOR);
});

// --- Construcción de la capa --------------------------------------------------------------

test('construye una capa con los polígonos recibidos', () => {
  const layer = mask.buildMaskLayer([POLYGON]);
  assert.ok(layer, 'debería devolver una capa');
  assert.strictEqual(Object.keys(layer._layers).length, 1);
});

test('sin polígonos no construye capa', () => {
  assert.strictEqual(mask.buildMaskLayer([]), null);
  assert.strictEqual(mask.buildMaskLayer(null), null);
});

// --- Los tres estados de FR-017 -------------------------------------------------------------

test('máscara con calzada -> ready', () => {
  assert.strictEqual(mask.maskState({features: [POLYGON]}), mask.MASK_STATE.READY);
});

test('máscara vacía -> empty, que es un RESULTADO', () => {
  // El modelo corrió y no vio calzada. Explica por qué los tramos salieron sin borde.
  assert.strictEqual(mask.maskState({features: []}), mask.MASK_STATE.EMPTY);
});

test('sin documento -> missing, que NO es un resultado', () => {
  assert.strictEqual(mask.maskState(null), mask.MASK_STATE.MISSING);
  assert.strictEqual(mask.maskState(undefined), mask.MASK_STATE.MISSING);
});

test('vacía y ausente no dan el mismo mensaje', () => {
  // Este es el test que impide mentirle al usuario sobre su calle.
  const empty = mask.maskMessage(mask.MASK_STATE.EMPTY, 0.2);
  const missing = mask.maskMessage(mask.MASK_STATE.MISSING, 0.2);
  assert.notStrictEqual(empty, missing);
  assert.ok(/recalcular|calcularlo|calcular/i.test(missing),
            'el mensaje de máscara ausente debe ofrecer recalcular: ' + missing);
});

// --- Aviso de precisión (FR-016) ------------------------------------------------------------

test('el aviso usa la resolución recibida, no una constante', () => {
  assert.ok(mask.resolutionAdvice(0.2).includes('20'));
  assert.ok(mask.resolutionAdvice(0.5).includes('50'));
});

test('sin resolución válida sigue avisando de que es aproximado', () => {
  for (const bad of [null, undefined, 0, -1, NaN, 'x']){
    const text = mask.resolutionAdvice(bad);
    assert.ok(/aproxima/i.test(text), 'debe seguir avisando con ' + String(bad) + ': ' + text);
  }
});

summary();
