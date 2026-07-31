/* La capa dibuja lo que la exportación va a rasterizar: mismo orden, mismos colores.
 *
 * Si el mapa no respetara el `order`, el usuario vería una composición distinta de la que acabará
 * en las máscaras (FR-012) y no tendría forma de darse cuenta hasta abrir el paquete exportado.
 */
const {setupDom, loadModule, createMap, stubLayers, test, assert, summary} = require('./harness');

setupDom();
const RealL = require('leaflet');
const L = stubLayers(RealL);   // proyecta de verdad, no dibuja: jsdom no tiene render SVG

const labelLayer = loadModule('labelLayer.js', {L});
const map = createMap(RealL);

const classes = [
  {index: 0, name: 'background', color: '#4a4a4a'},
  {index: 1, name: 'road', color: '#1f78ff'}
];

function square(lon, lat, side){
  return [[lon, lat], [lon + side, lat], [lon + side, lat + side], [lon, lat + side]];
}

test('las etiquetas se dibujan en orden ascendente de composición', () => {
  const unordered = [
    {id: 'c', order: 2, kind: 'polygon', class_index: 1, geometry: square(-70.71, -33.35, 0.0001)},
    {id: 'a', order: 0, kind: 'polygon', class_index: 0, geometry: square(-70.71, -33.35, 0.0002)},
    {id: 'b', order: 1, kind: 'polygon', class_index: 1, geometry: square(-70.71, -33.35, 0.0003)}
  ];
  assert(labelLayer.sortByOrder(unordered).map(l => l.id).join('') === 'abc',
    'la última dibujada debe quedar encima');
});

test('sortByOrder no muta la lista recibida', () => {
  const labels = [{id: 'b', order: 1}, {id: 'a', order: 0}];
  labelLayer.sortByOrder(labels);
  assert(labels[0].id === 'b', 'la lista original no se reordena');
});

test('cada etiqueta se dibuja con el color de su clase', () => {
  const layer = labelLayer.createLabelLayer(map, {L});
  layer.setClasses(classes);
  layer.setLabels([
    {id: 'x', order: 0, kind: 'polygon', class_index: 1, geometry: square(-70.71, -33.35, 0.0001)}
  ]);

  const drawn = layer.layerFor('x');
  assert(drawn, 'la etiqueta debe estar dibujada');
  assert(drawn.options.color === '#1f78ff', 'usa el color de la clase 1');
  layer.remove();
});

test('un trazo se dibuja como polilínea y un polígono como polígono', () => {
  const layer = labelLayer.createLabelLayer(map, {L});
  layer.setClasses(classes);
  layer.setLabels([
    {id: 'poly', order: 0, kind: 'polygon', class_index: 1, geometry: square(-70.71, -33.35, 0.0001)},
    {id: 'line', order: 1, kind: 'stroke', class_index: 1, radius_m: 2,
     geometry: [[-70.71, -33.35], [-70.709, -33.35]]}
  ]);

  assert(layer.layerFor('poly') instanceof L.Polygon, 'el polígono se dibuja como polígono');
  assert(layer.layerFor('line') instanceof L.Polyline, 'el trazo se dibuja como polilínea');
  assert(!(layer.layerFor('line') instanceof L.Polygon),
    'un trazo no se cierra como polígono: uniría sus extremos y pintaría área que nadie dibujó');
  layer.remove();
});

test('el borrador se distingue visualmente de la clase 0', () => {
  const layer = labelLayer.createLabelLayer(map, {L});
  layer.setClasses(classes);
  layer.setLabels([
    {id: 'bg', order: 0, kind: 'polygon', class_index: 0, geometry: square(-70.71, -33.35, 0.0001)},
    {id: 'gum', order: 1, kind: 'polygon', class_index: null, geometry: square(-70.71, -33.35, 0.0002)}
  ]);

  const background = layer.layerFor('bg');
  const eraser = layer.layerFor('gum');
  assert(background.options.color !== eraser.options.color, 'colores distintos');
  assert(eraser.options.dashArray && !background.options.dashArray,
    'el borrador va discontinuo para no confundirse con el fondo');
  layer.remove();
});

test('el trazo se repinta al cambiar el zoom', () => {
  const layer = labelLayer.createLabelLayer(map, {L});
  layer.setClasses(classes);
  map.setZoom(19);
  layer.setLabels([
    {id: 'line', order: 0, kind: 'stroke', class_index: 1, radius_m: 3,
     geometry: [[-70.71, -33.35], [-70.709, -33.35]]}
  ]);
  const before = layer.layerFor('line').options.weight;

  map.setZoom(17);
  map.fire('zoomend');
  const after = layer.layerFor('line').options.weight;

  assert(Math.abs(before / after - 4) < 0.01,
    'dos niveles de zoom cambian el grosor por 4, para representar los mismos metros');
  layer.remove();
});

summary('labelLayer');
