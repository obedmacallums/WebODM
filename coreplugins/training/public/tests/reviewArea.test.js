/* Área revisada: la herramienta de la que depende la calidad del dataset (D18, FR-040).
 *
 * Lo que se protege aquí es una distinción que el usuario tiene que poder hacer sin pensar, y que
 * el código es capaz de romper en silencio: **fondo revisado (0) no es lo mismo que no revisado
 * (255), ni que ignorar (255 explícito)**. Las tres cosas se dibujan con la misma herramienta de
 * anillo y salen con cargas distintas, así que basta un `kind` mal puesto para que un área
 * revisada acabe pintando la clase 0 como si fuera un polígono de camino.
 *
 * También se comprueba que el área revisada hereda todo lo que ya funcionaba en el polígono
 * —doble clic para cerrar, goma elástica, marcadores de vértice—, porque se implementó
 * generalizando `MODE_POLYGON` y una generalización a medias habría dejado el modo nuevo sin la
 * mitad de la interacción.
 */
const {setupDom, loadModule, createMap, stubLayers, test, assert, summary} = require('./harness');

setupDom();
const RealL = require('leaflet');
const L = stubLayers(RealL);

const labelLayerModule = loadModule('labelLayer.js', {L});
const LabelEditor = loadModule('LabelEditor.js', {
  L,
  PluginsAPI: {Map: {onHandleClick: () => {}}},
  strokeWeightPx: labelLayerModule.strokeWeightPx,
  classColor: labelLayerModule.classColor,
  ERASER_COLOR: labelLayerModule.ERASER_COLOR,
  ERASER_DASH: labelLayerModule.ERASER_DASH,
  REVIEW_COLOR: labelLayerModule.REVIEW_COLOR,
  REVIEW_DASH: labelLayerModule.REVIEW_DASH
});

const classes = [
  {index: 0, name: 'background', color: '#4a4a4a'},
  {index: 1, name: 'road', color: '#1f78ff'}
];

function makeEditor(overrides = {}){
  const map = createMap(RealL);
  const created = [];
  const editor = new LabelEditor(Object.assign({
    L, map, classes, classIndex: 1,
    onCreate: label => created.push(label)
  }, overrides, {pluginsAPI: {Map: {onHandleClick: () => {}, offHandleClick: () => {}}}}));
  return {map, editor, created};
}

/** Dibuja un anillo de `n` clics y lo cierra con doble clic, como haría el usuario. */
function drawRing(map, editor, points){
  points.forEach(([x, y]) => {
    const latlng = map.containerPointToLatLng(RealL.point(x, y));
    editor._onClick({latlng});
  });
  // El navegador dispara dos `click` antes del `dblclick`, así que el último punto va repetido.
  const last = map.containerPointToLatLng(RealL.point(...points[points.length - 1]));
  editor._onClick({latlng: last});
  editor._onDoubleClick({latlng: last});
}

const SQUARE = [[100, 100], [300, 100], [300, 300], [100, 300]];

test('un área revisada sale con kind review y sin clase', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('review');
  drawRing(map, editor, SQUARE);

  assert(created.length === 1, 'debe crearse una etiqueta');
  assert(created[0].kind === 'review', 'el tipo es review, no polygon');
  assert(created[0].class_index === null,
         'un área revisada no dice qué hay, dice que alguien lo miró');
});

test('un área revisada NO pinta la clase 0', () => {
  // El error que arruinaría el dataset: si el área revisada saliera con `class_index: 0`, cada
  // zona marcada afirmaría «aquí no hay camino» encima de los caminos que contiene.
  const {map, editor, created} = makeEditor({classIndex: 0});
  editor.setMode('review');
  drawRing(map, editor, SQUARE);

  assert(created[0].class_index === null,
         'ni siquiera con la clase 0 seleccionada en el panel');
});

test('ignorar y área revisada se distinguen por el tipo, no por la clase', () => {
  const {map, editor, created} = makeEditor();

  editor.setMode('eraser');
  const a = map.containerPointToLatLng(RealL.point(100, 100));
  const b = map.containerPointToLatLng(RealL.point(200, 200));
  editor._onMouseDown({latlng: a, originalEvent: {}});
  editor._onMouseMove({latlng: b, originalEvent: {}});
  editor._onMouseUp();

  editor.setMode('review');
  drawRing(map, editor, SQUARE);

  assert(created.length === 2, 'las dos etiquetas se crean');
  assert(created[0].class_index === null && created[1].class_index === null,
         'las dos van sin clase');
  assert(created[0].kind === 'stroke' && created[1].kind === 'review',
         'y solo el kind las separa: el backend manda una a 255 y la otra a fondo');
});

test('el negativo difícil viaja con el área revisada', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('review');
  editor.setHardNegative(true);
  drawRing(map, editor, SQUARE);

  assert(created[0].hard_negative === true, 'la marca tiene que llegar al backend');
});

test('sin marcar, el área revisada no es negativo difícil', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('review');
  drawRing(map, editor, SQUARE);

  assert(created[0].hard_negative === false, 'y va explícita, no ausente');
});

test('un área revisada de menos de tres vértices se descarta', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('review');

  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(100, 100))});
  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(200, 100))});
  assert(editor.finish() === null, 'dos vértices no forman superficie');
  assert(created.length === 0, 'y no se entrega nada al panel');
});

test('el área revisada hereda los marcadores de vértice del polígono', () => {
  const {map, editor} = makeEditor();
  editor.setMode('review');

  SQUARE.forEach(([x, y]) => {
    editor._onClick({latlng: map.containerPointToLatLng(RealL.point(x, y))});
  });

  assert(editor._drawVertexMarkers.length === 4,
         'sin los nodos blancos no se ve dónde se ha clicado, igual que en el polígono');
});

test('el área revisada hereda la goma elástica', () => {
  const {map, editor} = makeEditor();
  editor.setMode('review');
  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(100, 100))});
  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(200, 100))});

  editor._onMouseMove({latlng: map.containerPointToLatLng(RealL.point(250, 250))});
  assert(!!editor.rubberBand, 'hay que ver por dónde iría el siguiente tramo');
});

test('el área revisada toma el control del mapa como cualquier otro modo de dibujo', () => {
  const {map, editor} = makeEditor();
  editor.setMode('review');

  assert(editor.isActive(), 'dibujar un área revisada es dibujar');
  assert(!map.dragging.enabled(), 'sin esto el primer arrastre movería el mapa en vez de dibujar');

  editor.setMode(null);
  assert(map.dragging.enabled(), 'y al salir se devuelve');
});

test('la capa dibuja el área revisada sin taparlo todo', () => {
  // Un área revisada abarca media pantalla: con el relleno de un polígono normal (0,4) las
  // etiquetas de dentro dejarían de verse, que es justo cuando hay que revisarlas.
  const map = createMap(RealL);
  const layer = labelLayerModule.createLabelLayer(map, {L});
  layer.setClasses(classes);
  const ring = [[-70.71, -33.35], [-70.709, -33.35], [-70.709, -33.349]];
  layer.setLabels([
    {id: 'plain', order: 0, kind: 'review', geometry: ring},
    {id: 'hard', order: 1, kind: 'review', hard_negative: true, geometry: ring},
    {id: 'road', order: 2, kind: 'polygon', class_index: 1, geometry: ring}
  ]);

  const plain = layer.layerFor('plain');
  const hard = layer.layerFor('hard');
  const road = layer.layerFor('road');

  assert(plain.options.dashArray === labelLayerModule.REVIEW_DASH, 'el área va discontinua');
  assert(plain.options.fillOpacity < road.options.fillOpacity,
         'un área revisada abarca media pantalla: con el relleno de un polígono taparía justo las '
         + 'etiquetas que hay que revisar dentro de ella');
  assert(hard.options.fillOpacity > plain.options.fillOpacity,
         'el negativo difícil se distingue por el relleno, para contarlos de un vistazo');
  assert(plain.options.color !== road.options.color, 'y nunca con el color de una clase');
  layer.remove();
});

summary('reviewArea');
