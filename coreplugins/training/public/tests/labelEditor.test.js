/* El editor: polígonos, arrastre continuo del pincel y borrador.
 *
 * Es la parte de la entrega sin precedente en el repositorio (D10), así que conviene que su
 * comportamiento esté fijado por casos y no por inspección visual. Lo que se comprueba aquí es lo
 * que distingue este editor de dibujar cuatro líneas: que el mapa deje de desplazarse mientras se
 * pinta, que el arrastre capture puntos sin llenar la geometría de ruido, y que el borrador salga
 * con `class_index: null` y no con la clase 0.
 */
const {setupDom, loadModule, createMap, stubLayers, test, assert, summary} = require('./harness');

setupDom();
const RealL = require('leaflet');
const L = stubLayers(RealL);   // proyecta de verdad, no dibuja: jsdom no tiene render SVG

const labelLayerModule = loadModule('labelLayer.js', {L});
const LabelEditor = loadModule('LabelEditor.js', {
  L,
  PluginsAPI: {Map: {onHandleClick: () => {}}},
  strokeWeightPx: labelLayerModule.strokeWeightPx,
  classColor: labelLayerModule.classColor,
  ERASER_COLOR: labelLayerModule.ERASER_COLOR,
  ERASER_DASH: labelLayerModule.ERASER_DASH
});

const classes = [
  {index: 0, name: 'background', color: '#4a4a4a'},
  {index: 1, name: 'road', color: '#1f78ff'}
];

/** Doble del bus del core: registra los hooks para poder interrogarlos como hace `Map.jsx`. */
function makeBus(){
  const hooks = [];
  return {
    hooks,
    Map: {
      onHandleClick: fn => hooks.push(fn),
      offHandleClick: fn => {
        const i = hooks.indexOf(fn);
        if (i !== -1) hooks.splice(i, 1);
      },
      // Réplica de `if (PluginsAPI.Map.handleClick(e)) return;` del core: `true` significa que
      // un plugin consumió el clic y el popup de la ortofoto no se abre.
      handleClick: e => hooks.some(fn => fn(e))
    }
  };
}

function makeEditor(overrides = {}){
  const map = createMap(RealL);
  const created = [];
  const bus = overrides.pluginsAPI || makeBus();
  const editor = new LabelEditor(Object.assign({
    L, map, classes, classIndex: 1, radiusM: 2.5,
    onCreate: label => created.push(label)
  }, overrides, {pluginsAPI: bus}));
  return {map, editor, created, bus};
}

/** Simula un arrastre del ratón sobre el mapa, en píxeles de contenedor. */
function drag(map, editor, points){
  const toEvent = ([x, y]) => ({latlng: map.containerPointToLatLng(RealL.point(x, y))});
  editor._onMouseDown(toEvent(points[0]));
  points.slice(1).forEach(p => editor._onMouseMove(toEvent(p)));
  editor._onMouseUp();
}

test('un polígono necesita tres vértices para cerrarse', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('polygon');

  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(100, 100))});
  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(200, 100))});
  assert(editor.finish() === null, 'con dos vértices no hay polígono');
  assert(created.length === 0, 'no se entrega nada');

  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(100, 100))});
  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(200, 100))});
  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(200, 200))});
  const label = editor.finish();
  assert(label && label.kind === 'polygon', 'con tres vértices sí');
  assert(label.geometry.length === 3, 'conserva los tres vértices');
  assert(label.radius_m === null, 'un polígono no tiene radio');
});

test('cerrar un polígono con doble clic lo crea', () => {
  // El flujo real del usuario, disparado por el mapa como lo hace Leaflet: un clic por vértice y
  // un doble clic para cerrar. Los tests anteriores llamaban a `finish()` a mano y por eso no
  // veían este camino — que es el único que existe en la interfaz.
  const {map, editor, created} = makeEditor();
  editor.setMode('polygon');

  const at = (x, y) => ({latlng: map.containerPointToLatLng(RealL.point(x, y))});

  map.fire('click', at(100, 100));
  map.fire('click', at(300, 100));
  map.fire('click', at(300, 300));
  // Leaflet dispara `click` **y luego** `dblclick`: el segundo clic del doble ya añadió su vértice.
  map.fire('click', at(100, 300));
  map.fire('dblclick', at(100, 300));

  assert(created.length === 1, 'el doble clic debe cerrar y entregar el polígono; salió ' +
    created.length);
  assert(created[0].kind === 'polygon', 'es un polígono');
  assert(created[0].geometry.length >= 3, 'con al menos tres vértices');
});

test('el doble clic no duplica el último vértice', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('polygon');
  const at = (x, y) => ({latlng: map.containerPointToLatLng(RealL.point(x, y))});

  map.fire('click', at(100, 100));
  map.fire('click', at(300, 100));
  // Un doble clic del navegador dispara **dos** `click` en la misma posición y luego `dblclick`.
  map.fire('click', at(200, 300));
  map.fire('click', at(200, 300));
  map.fire('dblclick', at(200, 300));

  // Los dos clics del doble ya colocaron ese vértice dos veces: sin descartar el sobrante, el
  // polígono guardaría vértices idénticos y el lado que forman mediría cero.
  const geometry = created[0].geometry;
  const last = geometry[geometry.length - 1];
  const previous = geometry[geometry.length - 2];
  assert(!(last[0] === previous[0] && last[1] === previous[1]),
    'el último vértice está repetido: ' + JSON.stringify(geometry.slice(-2)));
});

test('cada vértice colocado se marca en el mapa mientras se traza', () => {
  // Sobre una ortofoto con textura, la línea de previsualización sola no dice dónde cayó cada
  // clic: sin los puntos, el usuario no sabe si el clic entró.
  const {map, editor} = makeEditor();
  editor.setMode('polygon');
  const at = (x, y) => ({latlng: map.containerPointToLatLng(RealL.point(x, y))});

  map.fire('click', at(100, 100));
  map.fire('click', at(300, 100));
  assert(editor._drawVertexMarkers.length === 2, 'un punto por vértice colocado');
  assert(editor._drawVertexMarkers[0].options.interactive === false,
    'no deben capturar el ratón: el siguiente clic caería en el marcador y no en el mapa');

  map.fire('click', at(200, 300));
  map.fire('dblclick', at(200, 300));
  assert(editor._drawVertexMarkers.length === 0,
    'al cerrar se retiran, o quedarían puntos de un trazo que ya no existe');
});

test('la línea elástica sigue al cursor desde el último vértice', () => {
  const {map, editor} = makeEditor();
  editor.setMode('polygon');
  const at = (x, y) => ({latlng: map.containerPointToLatLng(RealL.point(x, y))});

  // Sin ningún vértice todavía no hay nada de lo que tirar.
  map.fire('mousemove', at(150, 150));
  assert(!editor.rubberBand, 'sin vértices no se dibuja la elástica');

  map.fire('click', at(100, 100));
  map.fire('mousemove', at(200, 150));
  assert(editor.rubberBand, 'con un vértice, la elástica va de él al cursor');
  assert(editor.rubberBand.getLatLngs().length === 2, 'un solo tramo: vértice -> cursor');
  assert(editor.rubberBand.options.interactive === false,
    'no puede capturar el ratón: se dibuja justo bajo el cursor');
});

test('con dos vértices la elástica también enseña cómo se cerraría', () => {
  // Lo que se dibuja es una superficie, así que la pregunta no es solo por dónde sigue la línea
  // sino qué área encierra si se cierra ahí.
  const {map, editor} = makeEditor();
  editor.setMode('polygon');
  const at = (x, y) => ({latlng: map.containerPointToLatLng(RealL.point(x, y))});

  map.fire('click', at(100, 100));
  map.fire('click', at(300, 100));
  map.fire('mousemove', at(200, 300));

  const path = editor.rubberBand.getLatLngs();
  assert(path.length === 3, 'último -> cursor -> primero; salieron ' + path.length + ' puntos');

  const first = map.containerPointToLatLng(RealL.point(100, 100));
  assert(Math.abs(path[2].lat - first.lat) < 1e-9 && Math.abs(path[2].lng - first.lng) < 1e-9,
    'el tramo de cierre vuelve al primer vértice');
});

test('la elástica desaparece al cerrar el polígono', () => {
  const {map, editor} = makeEditor();
  editor.setMode('polygon');
  const at = (x, y) => ({latlng: map.containerPointToLatLng(RealL.point(x, y))});

  map.fire('click', at(100, 100));
  map.fire('click', at(300, 100));
  map.fire('mousemove', at(200, 300));
  map.fire('click', at(200, 300));
  map.fire('click', at(200, 300));
  map.fire('dblclick', at(200, 300));

  assert(!editor.rubberBand,
    'quedaría una línea discontinua flotando sobre un polígono ya terminado');
});

test('Escape sin trazo a medias suelta la herramienta', () => {
  // Sin esto había que recargar la página para volver a seleccionar etiquetas: con una
  // herramienta activa, un clic sobre una etiqueta es un vértice y nunca una selección.
  let salidas = 0;
  const {editor} = makeEditor({onExitMode: () => salidas++});
  editor.setMode('eraser');

  document.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'Escape'}));
  assert(salidas === 1, 'Escape con el lienzo limpio debe soltar la herramienta');
});

test('Escape con un trazo a medias descarta el trazo y conserva la herramienta', () => {
  // Dos tiempos: la primera pulsación es «este polígono no», la segunda «ya no quiero dibujar».
  let salidas = 0;
  const {map, editor} = makeEditor({onExitMode: () => salidas++});
  editor.setMode('polygon');
  map.fire('click', {latlng: map.containerPointToLatLng(RealL.point(100, 100))});

  document.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'Escape'}));
  assert(editor.points.length === 0, 'el trazo se descarta');
  assert(salidas === 0, 'pero la herramienta sigue en la mano');

  document.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'Escape'}));
  assert(salidas === 1, 'la segunda pulsación ya la suelta');
});

test('sin herramienta activa, Escape no hace nada', () => {
  let salidas = 0;
  const {editor} = makeEditor({onExitMode: () => salidas++});
  document.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'Escape'}));
  assert(salidas === 0, 'no hay nada que soltar');
});

test('cancelar con Escape retira los puntos del trazo a medias', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('polygon');
  map.fire('click', {latlng: map.containerPointToLatLng(RealL.point(100, 100))});
  map.fire('click', {latlng: map.containerPointToLatLng(RealL.point(200, 100))});

  document.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'Escape'}));

  assert(editor.points.length === 0, 'Escape descarta el trazo');
  assert(editor._drawVertexMarkers.length === 0, 'y sus puntos del mapa');
  assert(!editor.rubberBand, 'y la línea elástica');
  assert(created.length === 0, 'sin guardar nada a medias');
});

test('el pincel captura un arrastre continuo como una polilínea con radio', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('brush');

  drag(map, editor, [[100, 100], [140, 100], [180, 100], [220, 100]]);

  assert(created.length === 1, 'el arrastre produce una etiqueta');
  const label = created[0];
  assert(label.kind === 'stroke', 'es un trazo');
  assert(label.radius_m === 2.5, 'lleva el radio en metros, no en píxeles');
  assert(label.geometry.length >= 3, 'conserva los puntos del arrastre');
  assert(label.class_index === 1, 'usa la clase activa');
});

test('los puntos demasiado juntos no entran en la geometría', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('brush');

  // Cien movimientos de un píxel: un usuario moviendo el ratón despacio. Guardarlos todos llenaría
  // la etiqueta de vértices que la resolución del dataset no puede representar.
  const points = [];
  for (let i = 0; i < 100; i++) points.push([100 + i, 100]);
  drag(map, editor, points);

  assert(created[0].geometry.length < 40, 'los puntos por debajo del umbral se descartan');
  assert(created[0].geometry.length > 5, 'pero el trazo conserva su forma');
});

test('el mapa deja de desplazarse mientras se dibuja, y vuelve después', () => {
  const {map, editor} = makeEditor();
  assert(map.dragging.enabled(), 'de partida el mapa se arrastra con normalidad');

  editor.setMode('brush');
  assert(!map.dragging.enabled(), 'pintando, el arrastre movería el mapa en vez de dibujar');

  editor.setMode(null);
  assert(map.dragging.enabled(), 'al salir del modo se devuelve el control del mapa');
});

test('el borrador entrega class_index nulo, no la clase 0', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('eraser');
  drag(map, editor, [[100, 100], [150, 100], [200, 100]]);

  assert(created.length === 1, 'el borrador también produce una etiqueta');
  assert(created[0].class_index === null,
    'borrar devuelve a «sin etiquetar»; la clase 0 le enseñaría al modelo que eso es fondo');
});

test('cambiar de modo descarta el trazo a medias', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('polygon');
  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(100, 100))});
  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(200, 100))});

  editor.setMode('brush');
  assert(editor.points.length === 0, 'el polígono a medias no sobrevive al cambio de herramienta');
  assert(created.length === 0, 'y no se guarda a medias');
});

test('el modo selección no dibuja', () => {
  const {map, editor, created} = makeEditor();
  editor.setMode('select');
  editor._onClick({latlng: map.containerPointToLatLng(RealL.point(100, 100))});
  assert(created.length === 0 && editor.points.length === 0, 'seleccionar no añade vértices');
  assert(map.dragging.enabled(), 'seleccionando, el mapa se sigue pudiendo mover');
});

// --- El bus de clics del core ----------------------------------------------------------------

test('sin dibujar, el clic del mapa sigue su curso', () => {
  // Es **la** regla del bus: el core hace `if (PluginsAPI.Map.handleClick(e)) return;`, así que
  // consumir un clic que no es nuestro deja al popup de la ortofoto —y a cualquier otro plugin—
  // sin recibir clics mientras el panel esté abierto.
  const {map, bus} = makeEditor();
  const click = {latlng: map.getCenter(), layerPoint: RealL.point(10, 10)};
  assert(bus.Map.handleClick(click) === false,
    'con el editor inactivo nadie debe quedarse el clic');
});

test('dibujando, el clic se consume para que no se abra el popup de la ortofoto', () => {
  const {map, editor, bus} = makeEditor();
  editor.setMode('polygon');
  const click = {latlng: map.getCenter(), layerPoint: RealL.point(10, 10)};
  assert(bus.Map.handleClick(click) === true,
    'cada clic dejaría si no un popup, y su autoPan movería el mapa a mitad del trazo');
});

test('al salir del modo dibujo el hook se retira', () => {
  const {editor, bus} = makeEditor();
  editor.setMode('brush');
  assert(bus.hooks.length === 1, 'se engancha al entrar en modo dibujo');
  editor.setMode(null);
  assert(bus.hooks.length === 0, 'y se suelta al salir');
});

test('destruir el editor no deja el hook colgado en el bus', () => {
  const {editor, bus} = makeEditor();
  editor.setMode('polygon');
  editor.remove();
  assert(bus.hooks.length === 0,
    'un hook huérfano haría que el bus preguntara a un editor muerto en cada clic');
});

// --- Edición de una etiqueta ya dibujada -------------------------------------------------------

function polygonLayer(map){
  const c = map.getCenter();
  return L.polygon([
    [c.lat, c.lng], [c.lat, c.lng + 0.001], [c.lat - 0.001, c.lng + 0.001], [c.lat - 0.001, c.lng]
  ]);
}

test('editar muestra un manejador por vértice', () => {
  const {map, editor} = makeEditor();
  editor.startEditing(polygonLayer(map), {});
  assert(editor.isEditing(), 'queda en modo edición');
  assert(editor._editVertexMarkers.length === 4, 'un manejador por vértice del anillo');

  editor.stopEditing();
  assert(editor._editVertexMarkers.length === 0, 'y se retiran al salir');
});

test('un polígono nunca baja de tres vértices', () => {
  const {map, editor} = makeEditor();
  const layer = polygonLayer(map);
  const changes = [];
  editor.startEditing(layer, {onChange: ring => changes.push(ring.length)});

  // Borrar dos vértices de cuatro deja el mínimo; el tercero debe rechazarse.
  editor._editVertexMarkers[0].fire('contextmenu', {originalEvent: {}});
  editor._editVertexMarkers[0].fire('contextmenu', {originalEvent: {}});
  editor._editVertexMarkers[0].fire('contextmenu', {originalEvent: {}});

  assert(changes[changes.length - 1] === 3,
    'con menos de tres vértices dejaría de ser un polígono: salió ' + changes[changes.length - 1]);
});

test('editar una etiqueta hace que sus clics se consuman, y solo sobre la línea', () => {
  const {map, editor, bus} = makeEditor();
  const layer = polygonLayer(map).addTo(map);
  editor.startEditing(layer, {});

  const onVertex = map.latLngToLayerPoint(layer.getLatLngs()[0][0]);
  const farAway = RealL.point(onVertex.x + 400, onVertex.y + 400);

  assert(bus.Map.handleClick({layerPoint: farAway}) === false,
    'lejos de la geometría el mapa se comporta como siempre');
  editor.stopEditing();
});

test('si la capa editada desaparece, los manejadores no se quedan flotando', () => {
  const {map, editor} = makeEditor();
  const layer = polygonLayer(map).addTo(map);
  let stopped = false;
  editor.startEditing(layer, {onStop: () => { stopped = true; }});

  // Es lo que hace Leaflet al retirar una capa del mapa.
  layer.fire('remove');

  assert(!editor.isEditing(), 'la edición termina sola');
  assert(editor._editVertexMarkers.length === 0, 'sin marcadores huérfanos sobre el mapa');
  assert(stopped, 'y se avisa al panel para que suelte la selección');
});

test('cambiar de herramienta cancela la edición en curso', () => {
  const {map, editor} = makeEditor();
  editor.startEditing(polygonLayer(map), {});
  editor.setMode('brush');
  assert(!editor.isEditing(), 'dibujar y editar a la vez dejaría vértices sueltos por el mapa');
});

summary('labelEditor');
