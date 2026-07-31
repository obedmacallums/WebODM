/* Selección múltiple (`selection.js`) y su reflejo en la capa.
 *
 * De aquí cuelga qué se borra, y una selección que arrastra una etiqueta de más borra una etiqueta
 * de más — sin deshacer. Así que lo que se fija aquí son las reglas exactas: qué hace Shift, qué
 * hace un clic normal, y qué pasa con una selección cuyas etiquetas han desaparecido.
 */
const {setupDom, loadModule, createMap, stubLayers, test, assert, summary} = require('./harness');

setupDom();
const RealL = require('leaflet');
const L = stubLayers(RealL);

const selection = loadModule('selection.js', {});
const labelLayerModule = loadModule('labelLayer.js', {L});

const classes = [
  {index: 0, name: 'background', color: '#4a4a4a'},
  {index: 1, name: 'road', color: '#1f78ff'}
];

function ring(offset){
  const lon = -70.71 + offset * 0.001;
  return [[lon, -33.35], [lon + 0.0005, -33.35], [lon + 0.0005, -33.3495]];
}

function labels(n){
  return Array.from({length: n}, (_, i) => ({
    id: 'l' + i, order: i, kind: 'polygon', class_index: 1, geometry: ring(i)
  }));
}

const shiftClick = {originalEvent: {shiftKey: true}};
const plainClick = {originalEvent: {shiftKey: false}};

// --- Qué cuenta como Shift ---------------------------------------------------------------

test('Shift se lee del evento original de Leaflet', () => {
  assert(selection.isAdditive(shiftClick) === true);
  assert(selection.isAdditive(plainClick) === false);
});

test('un evento sin originalEvent no es aditivo', () => {
  // Leaflet no siempre trae `originalEvent` —lo genera él en algunos casos sintéticos— y leerlo a
  // ciegas habría reventado el manejador de clic entero.
  assert(selection.isAdditive(undefined) === false);
  assert(selection.isAdditive({}) === false);
  assert(selection.isAdditive({originalEvent: {}}) === false);
});

// --- La regla de selección ---------------------------------------------------------------

test('un clic normal reemplaza la selección', () => {
  assert(selection.nextSelection(['a', 'b'], 'c', false).join() === 'c');
});

test('Shift añade al final', () => {
  assert(selection.nextSelection(['a'], 'b', true).join() === 'a,b');
  assert(selection.nextSelection(['a', 'b'], 'c', true).join() === 'a,b,c');
});

test('Shift sobre una ya seleccionada la quita', () => {
  assert(selection.nextSelection(['a', 'b', 'c'], 'b', true).join() === 'a,c',
         'es como se corrige un clic de más sin empezar de cero');
});

test('un clic normal sobre la ya seleccionada la mantiene', () => {
  // Volver a clicar el mismo polígono es querer seguir trabajando con él, no soltarlo. Para
  // soltarlo están Shift + clic y el botón de deseleccionar.
  assert(selection.nextSelection(['a'], 'a', false).join() === 'a');
});

test('Shift sobre la única seleccionada deja la selección vacía', () => {
  assert(selection.nextSelection(['a'], 'a', true).length === 0);
});

test('nextSelection no muta la lista recibida', () => {
  const before = ['a', 'b'];
  selection.nextSelection(before, 'c', true);
  assert(before.join() === 'a,b', 'el estado de React no se toca en el sitio');
});

test('partir de una selección vacía funciona', () => {
  assert(selection.nextSelection([], 'a', true).join() === 'a');
  assert(selection.nextSelection(null, 'a', false).join() === 'a');
});

// --- Vértices ----------------------------------------------------------------------------

test('los vértices solo se editan con una etiqueta', () => {
  assert(selection.canEditVertices(['a']) === true);
  assert(selection.canEditVertices([]) === false);
  assert(selection.canEditVertices(['a', 'b']) === false,
         'con dos no hay una geometría que arrastrar');
});

// --- Etiquetas desaparecidas -------------------------------------------------------------

test('una selección que apunta a etiquetas borradas se limpia', () => {
  const alive = labels(3);
  assert(selection.pruneSelection(['l0', 'fantasma', 'l2'], alive).join() === 'l0,l2',
         'dejarla apuntando a una ausente deja el botón de borrar sin hacer nada');
});

test('pruneSelection sobre una lista vacía deja la selección vacía', () => {
  assert(selection.pruneSelection(['l0'], []).length === 0);
});

test('sameSelection distingue orden y tamaño', () => {
  assert(selection.sameSelection(['a', 'b'], ['a', 'b']) === true);
  assert(selection.sameSelection(['a', 'b'], ['b', 'a']) === false);
  assert(selection.sameSelection(['a'], ['a', 'b']) === false);
  assert(selection.sameSelection([], []) === true);
});

test('selectedLabels devuelve las etiquetas en el orden de la lista', () => {
  const all = labels(4);
  const chosen = selection.selectedLabels(['l3', 'l1'], all);
  assert(chosen.map(l => l.id).join() === 'l1,l3',
         'el panel las muestra en su orden, no en el de clicado');
});

// --- La capa las resalta todas ------------------------------------------------------------

test('la capa resalta todas las etiquetas seleccionadas', () => {
  const map = createMap(RealL);
  const layer = labelLayerModule.createLabelLayer(map, {L});
  layer.setClasses(classes);
  layer.setLabels(labels(3));

  layer.setSelected(['l0', 'l2']);
  assert(layer.layerFor('l0').options.weight === 4, 'la primera va marcada');
  assert(layer.layerFor('l2').options.weight === 4, 'y la tercera también');
  assert(layer.layerFor('l1').options.weight === 2, 'la de en medio no');
  layer.remove();
});

test('la capa acepta un identificador suelto además de una lista', () => {
  const map = createMap(RealL);
  const layer = labelLayerModule.createLabelLayer(map, {L});
  layer.setClasses(classes);
  layer.setLabels(labels(2));

  layer.setSelected('l1');
  assert(layer.getSelected().join() === 'l1');
  layer.remove();
});

test('deseleccionar del todo quita el resaltado', () => {
  const map = createMap(RealL);
  const layer = labelLayerModule.createLabelLayer(map, {L});
  layer.setClasses(classes);
  layer.setLabels(labels(2));

  layer.setSelected(['l0', 'l1']);
  layer.setSelected([]);
  assert(layer.getSelected().length === 0);
  assert(layer.layerFor('l0').options.weight === 2);
  layer.remove();
});

test('getSelected no deja tocar el estado interno de la capa', () => {
  const map = createMap(RealL);
  const layer = labelLayerModule.createLabelLayer(map, {L});
  layer.setClasses(classes);
  layer.setLabels(labels(2));

  layer.setSelected(['l0']);
  layer.getSelected().push('l1');
  assert(layer.getSelected().join() === 'l0', 'la copia protege al resaltado');
  layer.remove();
});

test('el clic entrega el evento para que el panel pueda leer Shift', () => {
  // Sin esto, el panel no tendría de dónde sacar si la mayúscula estaba pulsada y Shift + clic
  // se comportaría como un clic normal.
  const map = createMap(RealL);
  const seen = [];
  const layer = labelLayerModule.createLabelLayer(map, {
    L, onSelect: (label, drawn, event) => seen.push({id: label.id, event})
  });
  layer.setClasses(classes);
  layer.setLabels(labels(1));

  layer.layerFor('l0').fire('click', shiftClick);
  assert(seen.length === 1, 'el clic llega al panel');
  assert(selection.isAdditive(seen[0].event) === true, 'y con la mayúscula intacta');
  layer.remove();
});

// --- El orden entre soltar la edición y repintar -------------------------------------------

/* `TrainingPanel.applySelection` hace tres cosas y **el orden importa**: soltar la edición,
 * repintar la capa y volver a editar si queda una sola etiqueta. El panel es JSX y el harness no
 * lo carga, así que aquí se reproduce la secuencia con los módulos reales y se comprueba la
 * propiedad que el orden protege.
 *
 * La trampa: repintar retira del mapa la capa que se está editando, y esa capa lleva un manejador
 * de `remove` que llama a `onStop`. Con `onStop` cableado a «vaciar la selección», repintar antes
 * de soltar la edición vacía la selección que se acaba de poner.
 */
const LabelEditor = loadModule('LabelEditor.js', {
  L,
  PluginsAPI: {Map: {onHandleClick: () => {}, offHandleClick: () => {}}},
  strokeWeightPx: labelLayerModule.strokeWeightPx,
  classColor: labelLayerModule.classColor,
  ERASER_COLOR: labelLayerModule.ERASER_COLOR,
  ERASER_DASH: labelLayerModule.ERASER_DASH,
  REVIEW_COLOR: labelLayerModule.REVIEW_COLOR,
  REVIEW_DASH: labelLayerModule.REVIEW_DASH
});

function editingSetup(){
  const map = createMap(RealL);
  const layer = labelLayerModule.createLabelLayer(map, {L});
  layer.setClasses(classes);
  layer.setLabels(labels(3));

  const editor = new LabelEditor({
    L, map, classes, classIndex: 1,
    pluginsAPI: {Map: {onHandleClick: () => {}, offHandleClick: () => {}}}
  });
  return {map, layer, editor};
}

test('soltar la edición antes de repintar no dispara onStop', () => {
  const {layer, editor} = editingSetup();
  let stops = 0;
  editor.startEditing(layer.layerFor('l0'), {onStop: () => { stops += 1; }});

  // El orden de `applySelection`: primero soltar, luego repintar.
  editor.stopEditing();
  layer.setSelected(['l1']);

  assert(stops === 0,
         'con este orden nadie avisa de que la edición terminó, que es lo correcto: la soltamos '
         + 'nosotros a propósito');
  layer.remove();
});

test('repintar antes de soltar SÍ dispara onStop: el orden inverso rompe', () => {
  // Este test existe para que el orden de `applySelection` no se pueda cambiar sin que algo falle.
  const {layer, editor} = editingSetup();
  let stops = 0;
  editor.startEditing(layer.layerFor('l0'), {onStop: () => { stops += 1; }});

  layer.setSelected(['l1']);   // repintar primero
  editor.stopEditing();

  assert(stops === 1,
         'el manejador de `remove` de la capa editada llama a onStop; con onStop cableado a '
         + '«vaciar selección», esto se llevaría por delante la selección recién puesta');
  layer.remove();
});

test('editar sigue funcionando tras seleccionar otra etiqueta', () => {
  const {layer, editor} = editingSetup();
  editor.startEditing(layer.layerFor('l0'), {});

  editor.stopEditing();
  layer.setSelected(['l2']);
  editor.startEditing(layer.layerFor('l2'), {});

  assert(editor.isEditing(), 'la nueva etiqueta queda en edición');
  assert(editor._editVertexMarkers.length > 0, 'y con sus manejadores de vértice puestos');
  layer.remove();
});

summary('selection');
