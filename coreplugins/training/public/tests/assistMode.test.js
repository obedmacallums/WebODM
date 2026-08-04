/* Selección asistida: el modo del editor y la capa que habla con el servidor (`010`).
 *
 * Lo que se fija aquí es lo que no se ve mirando el código:
 *
 * - que el modo nuevo **no rompe** los que ya había, y en particular que `Shift` sigue siendo
 *   selección múltiple y nada más (FR-002);
 * - que un arrastre escribe **una** etiqueta al soltar y no una por región tocada;
 * - que una respuesta vieja no puede pisar a una nueva, que es el fallo que convierte una
 *   previsualización en un parpadeo hacia atrás.
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
const AssistLayer = loadModule('assistLayer.js', {
  L,
  classColor: labelLayerModule.classColor
});
const selection = loadModule('selection.js', {});

const classes = [
  {index: 0, name: 'background', color: '#4a4a4a'},
  {index: 1, name: 'road', color: '#1f78ff'}
];

/** Un `MultiPolygon` cuadrado alrededor de un punto, como el que devuelve el servidor. */
function squareAround(lng, lat, size){
  const s = size || 0.0002;
  return {type: 'MultiPolygon', coordinates: [[[
    [lng - s, lat - s], [lng + s, lat - s], [lng + s, lat + s], [lng - s, lat + s],
    [lng - s, lat - s]
  ]]]};
}

function makeEditor(overrides = {}){
  const map = createMap(RealL);
  const assisted = [];
  const previews = [];
  const editor = new LabelEditor(Object.assign({
    L, map, classes, classIndex: 1,
    onAssist: points => assisted.push(points),
    onAssistPreview: points => previews.push(points),
    pluginsAPI: {Map: {onHandleClick: () => {}, offHandleClick: () => {}}}
  }, overrides));
  return {map, editor, assisted, previews};
}

const at = (map, x, y) => ({latlng: map.containerPointToLatLng(RealL.point(x, y))});

// --- El modo del editor -----------------------------------------------------------------

test('el modo asistido está activo y toma el control del mapa', () => {
  const {map, editor} = makeEditor();
  editor.setMode('assist');

  assert(editor.isActive(), 'el modo asistido debe contar como activo');
  assert(editor.isAssist(), 'isAssist() lo reconoce');
  assert(!editor.isBrush(), 'no es el pincel: no produce un trazo con radio');
  assert(!editor.isRing(), 'no es un anillo: no se cierra a doble clic');
  assert(!map.dragging.enabled(), 'el mapa no debe desplazarse mientras se selecciona');
});

test('salir del modo devuelve el mapa como estaba', () => {
  const {map, editor} = makeEditor();
  editor.setMode('assist');
  editor.setMode(null);
  assert(map.dragging.enabled(), 'el arrastre del mapa vuelve');
});

test('un clic suelto entrega un punto', () => {
  const {map, editor, assisted} = makeEditor();
  editor.setMode('assist');

  map.fire('mousedown', at(map, 200, 200));
  map.fire('mouseup', at(map, 200, 200));

  assert(assisted.length === 1, 'un clic entrega el gesto una sola vez; salió ' + assisted.length);
  assert(assisted[0].length === 1, 'con un punto');
});

test('un arrastre acumula puntos y entrega una sola vez al soltar', () => {
  const {map, editor, assisted, previews} = makeEditor();
  editor.setMode('assist');

  map.fire('mousedown', at(map, 100, 100));
  [140, 180, 220, 260].forEach(x => map.fire('mousemove', at(map, x, 100)));
  map.fire('mouseup', at(map, 260, 100));

  assert(assisted.length === 1, 'una sola entrega, no una por región tocada; salió ' +
    assisted.length);
  assert(assisted[0].length >= 4, 'con los puntos del arrastre; salieron ' + assisted[0].length);
  assert(previews.length >= 4, 'y previsualizando durante el gesto');
});

test('mover el ratón sin pulsar no selecciona nada', () => {
  const {map, editor, assisted, previews} = makeEditor();
  editor.setMode('assist');
  map.fire('mousemove', at(map, 200, 200));
  assert(previews.length === 0 && assisted.length === 0,
    'sin botón pulsado no hay gesto que previsualizar');
});

test('el modo asistido no dibuja la línea del cursor', () => {
  // La previsualización es la región que devuelve el servidor. Pintar además el rastro sugeriría
  // que lo que se etiqueta es la línea, que es justo lo que esta herramienta no hace.
  const {map, editor} = makeEditor();
  editor.setMode('assist');
  map.fire('mousedown', at(map, 100, 100));
  map.fire('mousemove', at(map, 200, 100));
  assert(editor.preview === null, 'el editor no debe pintar previsualización propia');
});

test('los modos de siempre siguen funcionando después de usar el asistido', () => {
  const created = [];
  const {map, editor} = makeEditor({onCreate: label => created.push(label)});

  editor.setMode('assist');
  editor.setMode('polygon');
  map.fire('click', at(map, 100, 100));
  map.fire('click', at(map, 300, 100));
  map.fire('click', at(map, 300, 300));
  map.fire('dblclick', at(map, 300, 300));

  assert(created.length === 1 && created[0].kind === 'polygon',
    'el polígono debe seguir cerrándose con doble clic');
});

test('Shift sigue siendo selección múltiple, no un modificador del asistido', () => {
  // FR-002. La herramienta se activa desde la barra, nunca con una tecla: `Shift` ya significa
  // «añade a la selección» en toda la interfaz, y darle un segundo significado aquí lo rompería.
  assert(selection.isAdditive({originalEvent: {shiftKey: true}}) === true,
    'Shift sigue añadiendo a la selección');
  assert(selection.isAdditive({originalEvent: {shiftKey: false}}) === false,
    'sin Shift, la selección se reemplaza');

  const {map, editor, assisted} = makeEditor();
  editor.setMode('assist');
  const event = at(map, 200, 200);
  event.originalEvent = {shiftKey: true};
  map.fire('mousedown', event);
  map.fire('mouseup', event);
  assert(assisted.length === 1, 'con Shift el gesto asistido se comporta igual que sin él');
});

// --- La capa que habla con el servidor ---------------------------------------------------

function makeLayer(overrides = {}){
  const map = createMap(RealL);
  const created = [];
  const statuses = [];
  const calls = [];
  const layer = new AssistLayer(Object.assign({
    L, map, classes, classIndex: 1,
    regionsUrl: () => '/api/regions',
    settings: () => ({granularity: 'medium', tolerance: 0, elevation_weight: 1}),
    onCreate: label => created.push(label),
    onStatus: status => statuses.push(status),
    request: (url, payload) => {
      calls.push(payload);
      return Promise.resolve({
        geometry: squareAround(payload.points[0].lon, payload.points[0].lat),
        region_count: payload.points.length,
        elevation_source: 'dtm',
        band_count: 5,
        truncated: false,
        prepared_cells: 1
      });
    }
  }, overrides));
  return {map, layer, created, statuses, calls};
}

test('confirmar crea una etiqueta de polígono marcada como asistida', () => {
  const {layer, created} = makeLayer();
  layer.commitPoints([[-70.71, -33.35]]);

  return Promise.resolve().then(() => new Promise(r => setTimeout(r, 0))).then(() => {
    assert(created.length === 1, 'una etiqueta por anillo exterior; salieron ' + created.length);
    assert(created[0].kind === 'polygon', 'es un polígono corriente: el exportador ni se entera');
    assert(created[0].source === 'assisted', 'marcada como asistida');
    assert(created[0].class_index === 1, 'con la clase activa');
    assert(created[0].geometry.length === 4,
      'el anillo llega abierto, sin repetir el primer vértice; salieron ' +
      created[0].geometry.length);
  });
});

test('previsualizar no crea ninguna etiqueta', () => {
  const {layer, created} = makeLayer();
  layer.previewPoints([[-70.71, -33.35]]);
  return new Promise(r => setTimeout(r, 0)).then(() => {
    assert(created.length === 0, 'previsualizar no escribe nada');
    assert(layer.preview !== null, 'pero sí dibuja la región');
  });
});

test('solo hay una petición en vuelo y la última gana', () => {
  // Sin freno, un arrastre de unos segundos manda decenas de peticiones a la vez y las respuestas
  // llegan desordenadas: la previsualización parpadea hacia atrás.
  let resolvers = [];
  const {layer, calls} = makeLayer({
    request: (url, payload) => {
      calls.push(payload);
      return new Promise(resolve => resolvers.push(() => resolve({
        geometry: squareAround(payload.points[0].lon, payload.points[0].lat),
        region_count: 1, elevation_source: 'none', band_count: 3,
        truncated: false, prepared_cells: 0
      })));
    }
  });

  layer.previewPoints([[-70.71, -33.35]]);
  layer.previewPoints([[-70.72, -33.35]]);
  layer.previewPoints([[-70.73, -33.35]]);

  assert(calls.length === 1, 'solo una petición en vuelo; salieron ' + calls.length);
  resolvers.shift()();

  return new Promise(r => setTimeout(r, 0)).then(() => {
    assert(calls.length === 2, 'al terminar sale la última encolada, no las intermedias');
    assert(calls[1].points[0].lon === -70.73,
      'y es la última, no la segunda: salió ' + calls[1].points[0].lon);
  });
});

test('una confirmación encolada no se pierde', () => {
  let resolvers = [];
  const {layer, created, calls} = makeLayer({
    request: (url, payload) => {
      calls.push(payload);
      return new Promise(resolve => resolvers.push(() => resolve({
        geometry: squareAround(payload.points[0].lon, payload.points[0].lat),
        region_count: 1, elevation_source: 'none', band_count: 3,
        truncated: false, prepared_cells: 0
      })));
    }
  });

  layer.previewPoints([[-70.71, -33.35]]);
  layer.commitPoints([[-70.71, -33.35], [-70.72, -33.35]]);
  resolvers.shift()();

  return new Promise(r => setTimeout(r, 0))
    .then(() => { resolvers.shift()(); return new Promise(r => setTimeout(r, 0)); })
    .then(() => {
      assert(created.length === 1, 'la confirmación acaba escribiendo; salieron ' + created.length);
    });
});

test('pinchar fuera del vuelo no crea nada y lo dice', () => {
  const {layer, created, statuses} = makeLayer({
    request: () => Promise.resolve({
      geometry: null, region_count: 0, reason: 'no_data',
      message: 'Ese punto está fuera de la zona cubierta por el vuelo.'
    })
  });

  layer.commitPoints([[-70.71, -33.35]]);
  return new Promise(r => setTimeout(r, 0)).then(() => {
    assert(created.length === 0, 'no se crea ninguna etiqueta');
    const last = statuses[statuses.length - 1];
    assert(last.empty === true, 'el estado lo declara vacío');
    assert(!!last.message, 'con un mensaje que la interfaz pueda enseñar');
  });
});

test('el tope de la tolerancia llega al estado para poder avisarlo', () => {
  const {layer, statuses} = makeLayer({
    request: () => Promise.resolve({
      geometry: squareAround(-70.71, -33.35), region_count: 2000,
      elevation_source: 'dtm', band_count: 5, truncated: true, prepared_cells: 3
    })
  });

  layer.previewPoints([[-70.71, -33.35]]);
  return new Promise(r => setTimeout(r, 0)).then(() => {
    const last = statuses[statuses.length - 1];
    assert(last.truncated === true, 'FR-018: el tope se declara, no se disimula');
  });
});

test('un fallo del servidor no deja la previsualización pegada al mapa', () => {
  const errors = [];
  const {layer} = makeLayer({
    onError: e => errors.push(e),
    request: () => Promise.reject({error: 'boom'})
  });

  layer.commitPoints([[-70.71, -33.35]]);
  return new Promise(r => setTimeout(r, 0)).then(() => {
    assert(errors.length === 1, 'el fallo se comunica');
    assert(layer.preview === null, 'y la previsualización se retira');
  });
});

test('los anillos interiores se dibujan aunque no lleguen a la etiqueta', () => {
  const donut = {type: 'MultiPolygon', coordinates: [[
    [[-70.72, -33.36], [-70.70, -33.36], [-70.70, -33.34], [-70.72, -33.34], [-70.72, -33.36]],
    [[-70.715, -33.355], [-70.705, -33.355], [-70.705, -33.345], [-70.715, -33.345],
     [-70.715, -33.355]]
  ]]};

  assert(AssistLayer.outerRings(donut).length === 1, 'un anillo exterior');
  assert(AssistLayer.outerRings(donut)[0].length === 4, 'abierto');
  assert(AssistLayer.toLeafletRings(donut)[0].length === 2,
    'pero la previsualización enseña los dos: el usuario ve el hueco que la etiqueta no guardará');
});

summary('assistMode');
