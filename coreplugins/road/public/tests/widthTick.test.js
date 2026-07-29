/* Geometría de la regla del ancho: dónde se dibuja la transversal que materializa la medida.
 *
 * La regla mide el ancho **total** del camino, así que se dibuja centrada en el eje —la mitad a
 * cada lado— aunque los dos bordes estén a distancias distintas. Es una decisión de dibujo: el
 * reparto real izquierda/derecha se sigue midiendo, se sigue exportando y se sigue mostrando en
 * el popup; lo único que se recoloca es la línea.
 */
const assert = require('assert');
const {loadModule, test, summary} = require('./harness');

const {widthTickPoints} = loadModule('widthTick.js', {});

// Desplazamiento en grados que corresponde a un metro sobre la normal del tramo. Su valor da
// igual mientras los bordes se construyan con él: lo que se prueba es la proporción.
const U = [0.000003, 0.000004];

/** Tramo coherente: los bordes salen del midpoint por la normal, a sus offsets respectivos. */
function segment(offsetLeft, offsetRight, midpoint = [10, 20]){
  const along = (d) => [midpoint[0] + d * U[0], midpoint[1] + d * U[1]];
  return {
    midpoint,
    offset_left: offsetLeft,
    offset_right: offsetRight,
    width: offsetLeft + offsetRight,
    edge_left: along(offsetLeft),
    edge_right: along(-offsetRight),
    status: 'measured'
  };
}

// Tolerancias. El fixture construye los bordes sumando desplazamientos de ~1e-5 grados sobre
// coordenadas de dos dígitos, así que restarle el midpoint cancela ~11 cifras significativas: el
// ruido es de la aritmética del propio test, no del recorte. Se comparan micras, que es cinco
// órdenes por debajo de lo que cualquier pantalla puede distinguir.
const EPS_M = 1e-6;         // distancias, en metros
const EPS_DEG = 1e-11;      // coordenadas, en grados (~1 µm)

function assertClose(actual, expected, message, eps = EPS_M){
  assert.ok(Math.abs(actual - expected) < eps, `${message}: ${actual} != ${expected}`);
}

function assertPointClose(actual, expected, message){
  assertClose(actual[0], expected[0], message + ' (lng)', EPS_DEG);
  assertClose(actual[1], expected[1], message + ' (lat)', EPS_DEG);
}

/** Distancia en unidades de `U` entre dos puntos: la escala real no importa para comparar. */
function span(a, b){
  return Math.hypot(b[0] - a[0], b[1] - a[1]) / Math.hypot(U[0], U[1]);
}

test('con bordes asimétricos la regla queda centrada en el eje', () => {
  const seg = segment(15, 5);   // ancho 20, todo desplazado hacia la izquierda
  const [left, right] = widthTickPoints(seg);

  const center = [(left[0] + right[0]) / 2, (left[1] + right[1]) / 2];
  assertPointClose(center, seg.midpoint, 'el centro de la regla es el punto del eje');
  assertClose(span(seg.midpoint, left), 10, 'mitad del ancho a la izquierda');
  assertClose(span(seg.midpoint, right), 10, 'mitad del ancho a la derecha');
});

test('la regla sigue midiendo el ancho reportado, ni más ni corto', () => {
  const seg = segment(15, 5);
  const [left, right] = widthTickPoints(seg);

  assertClose(span(left, right), seg.width,
    'recolocarla no puede cambiar la longitud: es la cifra del popup');
});

test('la regla sigue siendo perpendicular al eje', () => {
  const seg = segment(15, 5);
  const [left, right] = widthTickPoints(seg);

  // Colineal con la transversal original: el seno del ángulo que forman es cero.
  const dx = left[0] - right[0], dy = left[1] - right[1];
  const sine = (dx * U[1] - dy * U[0]) / (Math.hypot(dx, dy) * Math.hypot(U[0], U[1]));
  assertClose(sine, 0, 'la regla no puede girar respecto de la transversal', 1e-9);
});

test('con bordes simétricos no se mueve nada', () => {
  const seg = segment(6, 6);
  const [left, right] = widthTickPoints(seg);

  assertPointClose(left, seg.edge_left, 'el borde izquierdo ya estaba centrado');
  assertPointClose(right, seg.edge_right, 'el borde derecho ya estaba centrado');
});

test('el desplazamiento va en la dirección del borde más lejano', () => {
  // Con la calzada volcada a la derecha, la regla se corre a la derecha respecto de los bordes.
  const seg = segment(2, 18);
  const [left, right] = widthTickPoints(seg);

  assert.ok(span(seg.midpoint, right) < seg.offset_right,
    'el extremo derecho se recoge hacia el eje');
  assert.ok(span(seg.midpoint, left) > seg.offset_left,
    'el izquierdo se estira hasta la mitad del ancho');
});

test('sin uno de los bordes no hay regla', () => {
  const seg = Object.assign(segment(5, 5), {edge_right: null, offset_right: null, width: null});

  assert.strictEqual(widthTickPoints(seg), null, 'la ausencia es información, no un hueco');
});

test('sin punto de eje la regla vuelve a ir de borde a borde', () => {
  // Un análisis guardado por una versión que no sellaba el midpoint: se dibuja lo que hay,
  // nunca NaN.
  const seg = Object.assign(segment(15, 5), {midpoint: null});

  assert.deepStrictEqual(widthTickPoints(seg), [seg.edge_left, seg.edge_right]);
});

test('un borde sobre el propio eje no produce coordenadas inválidas', () => {
  const seg = segment(15, 0);
  const points = widthTickPoints(seg);

  points.forEach(p => p.forEach(c => assert.ok(Number.isFinite(c), 'nada de NaN ni Infinity')));
  assertClose(span(points[0], points[1]), 15, 'la regla sigue midiendo el ancho');
});

// --- La regla se dibuja en el centro del tramo ----------------------------------------------------
//
// El ancho lo decide la transversal mediana, que puede estar en cualquier punto del tramo; el
// dibujo, en cambio, va siempre al punto medio. Si no, las reglas saltarían de sitio entre tramos
// vecinos y el mapa parecería descuadrado, cuando lo único que cambió fue dónde se midió.

test('la regla se dibuja en el punto medio del tramo, no donde se midió', () => {
  // Bordes medidos 3 m más adelante que el punto medio del tramo, sobre esa misma transversal.
  const mid = [10, 20];
  const ahead = [mid[0] + 3 * 0.000009, mid[1] - 3 * 0.000012];   // a lo largo del eje
  const along = (from, d) => [from[0] + d * U[0], from[1] + d * U[1]];
  const seg = {
    midpoint: mid,
    offset_left: 9, offset_right: 3, width: 12,
    edge_left: along(ahead, 9), edge_right: along(ahead, -3),
    status: 'measured'
  };

  const [left, right] = widthTickPoints(seg);
  const center = [(left[0] + right[0]) / 2, (left[1] + right[1]) / 2];

  assertPointClose(center, mid, 'la regla se planta en el centro del tramo');
  assertClose(span(left, right), 12, 'con la longitud que midió la sección mediana');
});

summary('widthTick');
