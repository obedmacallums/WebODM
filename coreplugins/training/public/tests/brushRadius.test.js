/* FR-010: el radio del pincel es una medida sobre el terreno y se mantiene constante al hacer zoom.
 *
 * Es el requisito que más fácil se incumple sin que nadie lo note: un grosor en píxeles se ve
 * perfectamente razonable a un zoom y cubre decenas de metros a otro. La comprobación es que los
 * **metros** representados no cambien, no que los píxeles sí cambien —eso solo sería un síntoma.
 */
const {setupDom, loadModule, createMap, test, assert, assertClose, summary} = require('./harness');

setupDom();
const L = require('leaflet');

const labelLayer = loadModule('labelLayer.js', {L});
const map = createMap(L);

test('un píxel mide menos metros cuanto más cerca está el zoom', () => {
  map.setZoom(18);
  const far = labelLayer.metersPerPixel(map, -33.35);
  map.setZoom(20);
  const near = labelLayer.metersPerPixel(map, -33.35);

  assert(near < far, 'acercar el zoom debe reducir los metros por píxel');
  assertClose(far / near, 4, 0.001, 'dos niveles de zoom son un factor 4');
});

test('el grosor en píxeles representa los mismos metros a cualquier zoom', () => {
  const radiusM = 2.5;
  const lat = -33.35;

  const measured = [17, 18, 19, 20, 21].map(zoom => {
    map.setZoom(zoom);
    const weightPx = labelLayer.strokeWeightPx(map, radiusM, lat);
    return weightPx * labelLayer.metersPerPixel(map, lat);   // metros que cubre el trazo dibujado
  });

  measured.forEach(meters => {
    assertClose(meters, 2 * radiusM, 0.001,
      'el trazo debe cubrir el diámetro en metros a todos los zooms');
  });
});

test('el grosor es el diámetro, no el radio', () => {
  map.setZoom(19);
  const lat = -33.35;
  const perPixel = labelLayer.metersPerPixel(map, lat);
  const weight = labelLayer.strokeWeightPx(map, 3, lat);

  assertClose(weight * perPixel, 6, 0.001, 'un radio de 3 m debe pintar 6 m de ancho');
});

test('un trazo minúsculo sigue siendo visible', () => {
  map.setZoom(12);
  assert(labelLayer.strokeWeightPx(map, 0.5, -33.35) >= 1,
    'a zoom muy alejado el trazo no puede desaparecer del todo');
});

test('el color del borrador no es el de ninguna clase', () => {
  const classes = [{index: 0, name: 'bg', color: '#4a4a4a'}, {index: 1, name: 'road', color: '#1f78ff'}];
  assert(labelLayer.classColor(classes, 1) === '#1f78ff', 'la clase 1 usa su color');
  assert(labelLayer.classColor(classes, null) === labelLayer.ERASER_COLOR,
    'el borrador tiene color propio');
  assert(classes.every(c => c.color !== labelLayer.ERASER_COLOR),
    'el color del borrador no puede coincidir con el de una clase');
});

summary('brushRadius');
