/* El desplegable de tareas de la página global.
 *
 * Este test existe por un fallo concreto: el filtro miraba `task.orthophoto_extent`, que el
 * serializer del core **no expone**, así que descartaba todas las tareas y la lista salía vacía
 * sin error ni mensaje. El usuario no tenía forma de saber si es que no había tareas, si le
 * faltaban permisos o si estaba roto.
 *
 * Las tareas de ejemplo llevan la forma **real** que devuelve `/api/projects/<id>/tasks/`,
 * comprobada contra la instancia: por eso el test detecta el fallo y un doble inventado no lo
 * habría hecho.
 */
const {setupDom, test, assert, summary} = require('./harness');
const fs = require('fs');
const path = require('path');

setupDom();

/**
 * Doble de `$.ajax` con la semántica de **jQuery 1.11.2**, que es el que trae WebODM.
 *
 * Esto importa más de lo que parece. La primera versión de este test daba a `$` un doble con
 * `.then()` y `.catch()` encadenables, y **por eso pas��** mientras la página estaba rota en el
 * navegador: jQuery 1.11 es anterior a Promises/A+, no tiene `.catch()` en sus Deferred y su
 * `.then()` no desenvuelve una promesa devuelta. Un doble más moderno que la librería real no
 * prueba nada; prueba un mundo que no existe.
 *
 * Aquí solo se exponen `done` y `fail`, que es lo único con lo que se puede contar.
 */
function fakeAjax(responses){
  const calls = [];
  function ajax(options){
    const url = typeof options === 'string' ? options : options.url;
    calls.push(url);
    const body = responses[url];
    const deferred = {
      done: function(fn){ if (body !== undefined) fn(body); return deferred; },
      fail: function(){ return deferred; }
      // Sin `then` ni `catch` a propósito: jQuery 1.11 los tiene, pero con una semántica que no
      // es la de Promises/A+. Usarlos desde el plugin es el error que este doble debe delatar.
    };
    return deferred;
  }
  ajax.ajax = ajax;
  ajax.calls = calls;
  return ajax;
}

const RESPONSES = {
  // Forma real medida contra la instancia: array plano, no {count, results}.
  '/api/projects/?page_size=100': [
    {id: 15, name: 'mina'},
    {id: 14, name: 'marcoleta'},
    {id: 99, name: 'sin ortofoto'}
  ],
  '/api/projects/15/tasks/': [
    {id: 'aaa', name: 'Mina La Coipa - 5/2/2026',
     available_assets: ['all.zip', 'orthophoto.tif', 'dtm.tif']}
  ],
  '/api/projects/14/tasks/': [
    {id: 'bbb', name: 'Polideportivo María Puebla Vásquez',
     available_assets: ['orthophoto.tif']}
  ],
  '/api/projects/99/tasks/': [
    {id: 'ccc', name: 'Solo DEM', available_assets: ['dtm.tif']}
  ],
  '/api/plugins/training/datasets': []
};

// `datasets.js` es un IIFE que se sirve con <script>, no un módulo ES: se evalúa tal cual y se
// recoge lo que publica en `window`.
global.$ = fakeAjax(RESPONSES);
new Function('window', 'document', '$',
  fs.readFileSync(path.join(__dirname, '..', 'datasets.js'), 'utf8')
)(global.window, global.document, global.$);

const { hasOrthophoto, asList } = global.window.TrainingDatasets;

// Forma real de una tarea procesada, recortada de la respuesta de la API de la instancia.
const processedTask = {
  id: 'aaa2aad5-3cd7-4743-9b98-f618764bc697',
  name: 'Mina La Coipa - 5/2/2026',
  available_assets: ['all.zip', 'orthophoto.tif', 'georeferenced_model.laz', 'dtm.tif', 'dsm.tif'],
  extent: [-71.109, -32.657, -71.106, -32.653],
  status: 40
};

test('una tarea con ortofoto entra en la lista', () => {
  assert(hasOrthophoto(processedTask) === true);
});

test('el campo que decide es available_assets, no orthophoto_extent', () => {
  // El serializer del core no expone `orthophoto_extent`: si el filtro lo mirara, esta tarea
  // —que sí tiene ortofoto— quedaría fuera, que es exactamente el fallo que se corrigió.
  assert(!('orthophoto_extent' in processedTask),
    'la API real no trae este campo; el ejemplo debe reflejarlo');
  assert(hasOrthophoto(processedTask) === true,
    'la tarea debe listarse pese a no traer orthophoto_extent');
});

test('una tarea sin ortofoto queda fuera', () => {
  assert(hasOrthophoto({available_assets: ['dtm.tif', 'dsm.tif']}) === false);
});

test('una tarea aún en proceso queda fuera', () => {
  assert(hasOrthophoto({available_assets: []}) === false);
});

test('una respuesta inesperada no rompe el filtro', () => {
  assert(hasOrthophoto(null) === false);
  assert(hasOrthophoto({}) === false);
  assert(hasOrthophoto({available_assets: null}) === false);
});

test('las respuestas de lista del core se leen vengan como vengan', () => {
  // `/api/projects/` devuelve un array plano; otras rutas devuelven {count, results}. Suponer
  // solo la forma paginada dejaba el desplegable vacío: `results` sobre un array es undefined.
  assert(asList([{id: 1}, {id: 2}]).length === 2, 'array plano');
  assert(asList({count: 1, results: [{id: 1}]}).length === 1, 'respuesta paginada');
  assert(asList(null).length === 0, 'respuesta vacía');
  assert(asList(undefined).length === 0, 'sin respuesta');
});

test('el desplegable se llena con las tareas que tienen ortofoto', async () => {
  // El caso completo de extremo a extremo del filtro: dos peticiones encadenadas contra un
  // `$.ajax` con la semántica de jQuery 1.11. Si el código vuelve a encadenar `.then()` de
  // jQuery con `Promise.all`, este caso revienta igual que reventaba el navegador.
  document.body.innerHTML = '<select id="tr-tasks"></select><div id="tr-error"></div>';

  await global.window.TrainingDatasets.loadTasks();

  const select = document.getElementById('tr-tasks');
  const groups = Array.from(select.querySelectorAll('optgroup')).map(g => g.label);

  assert(select.querySelectorAll('option').length === 2,
    'las dos tareas con ortofoto, y solo esas: salieron ' +
    select.querySelectorAll('option').length);
  assert(groups.length === 2, 'agrupadas por proyecto');
  assert(groups.indexOf('sin ortofoto') === -1,
    'un proyecto sin ninguna tarea con ortofoto no aparece');
  assert(document.getElementById('tr-error').textContent === '',
    'con tareas encontradas no se muestra ningún error');
});

summary('datasetsPage');
