/**
 * Página global de gestión de datasets (D1).
 *
 * Va en JS plano y no en React porque `app_mount_points()` sirve una plantilla de Django, no el
 * bundle de la aplicación: es el mismo reparto que usa `task-manager`.
 *
 * Un dataset agrupa varias tareas (FR-002) y por eso no puede vivir en el panel de ninguna: se
 * crea aquí, y el etiquetado ocurre luego sobre el mapa de cada tarea.
 */
(function () {
  'use strict';

  var API = '/api/plugins/training/';

  var state = {
    datasets: [],
    projects: [],
    exports: {},        // dataset_id -> lista de exportaciones
    polling: {},        // dataset_id -> id del temporizador de sondeo
    classes: [
      {index: 0, name: 'background'},
      {index: 1, name: 'road'}
    ]
  };

  // Cada cuánto se pregunta por el progreso de una exportación en curso. Dos segundos es
  // suficiente para que la barra se mueva y lo bastante espaciado para no castigar al servidor
  // mientras el worker hace el trabajo de verdad.
  var POLL_MS = 2000;

  function el(id){ return document.getElementById(id); }

  function showError(message){
    var box = el('tr-error');
    if (!box) return;
    box.textContent = message;
    box.style.display = message ? 'block' : 'none';
  }

  function escapeHtml(text){
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(text == null ? '' : String(text)));
    return div.innerHTML;
  }

  // --- Carga ---------------------------------------------------------------------------

  function loadDatasets(){
    return $.ajax({url: API + 'datasets', type: 'GET'})
      .done(function (datasets) {
        state.datasets = datasets || [];
        renderDatasets();
        state.datasets.forEach(function (d) { loadExports(d.id); });
      })
      .fail(function () { showError('No se pudieron cargar los datasets.'); });
  }

  // --- Exportación ---------------------------------------------------------------------

  function loadExports(datasetId){
    return $.ajax({url: API + 'datasets/' + datasetId + '/exports', type: 'GET'})
      .done(function (exports) {
        state.exports[datasetId] = exports || [];
        renderExports(datasetId);

        // El sondeo se mantiene solo mientras algo corre: en cuanto todo termina se para, para no
        // dejar una petición cada dos segundos en una pestaña abierta y olvidada.
        var running = (exports || []).some(function (e) { return e.status === 'running'; });
        if (running && !state.polling[datasetId]){
          state.polling[datasetId] = setInterval(function () {
            loadExports(datasetId);
          }, POLL_MS);
        } else if (!running && state.polling[datasetId]){
          clearInterval(state.polling[datasetId]);
          delete state.polling[datasetId];
        }
      });
  }

  function startExport(datasetId){
    showError('');
    $.ajax({url: API + 'datasets/' + datasetId + '/exports', type: 'POST',
            contentType: 'application/json', data: '{}'})
      .done(function () { loadExports(datasetId); })
      .fail(function (xhr) {
        var body = xhr.responseJSON || {};
        // `nothing_to_export` y `all_tiles_filtered` se distinguen a propósito: uno se arregla
        // etiquetando y el otro bajando el umbral, y decir lo mismo a ambos dejaría al usuario
        // adivinando cuál de las dos cosas hacer.
        if (body.code === 'all_tiles_filtered'){
          showError('Todas las teselas quedaron descartadas por los umbrales del dataset. ' +
                    'Etiqueta más superficie o baja el mínimo etiquetado.');
        } else {
          showError(body.error || 'No se pudo lanzar la exportación.');
        }
      });
  }

  function cancelExport(datasetId, exportId){
    $.ajax({url: API + 'datasets/' + datasetId + '/exports/' + exportId, type: 'DELETE'})
      .done(function () { loadExports(datasetId); })
      .fail(function () { showError('No se pudo cancelar la exportación.'); });
  }

  function formatSize(bytes){
    if (!bytes) return '-';
    var units = ['B', 'KB', 'MB', 'GB'];
    var i = 0;
    var value = bytes;
    while (value >= 1024 && i < units.length - 1){ value /= 1024; i++; }
    return value.toFixed(i ? 1 : 0) + ' ' + units[i];
  }

  function renderExports(datasetId){
    var host = document.querySelector('.tr-exports[data-id="' + datasetId + '"]');
    if (!host) return;

    var exports = state.exports[datasetId] || [];
    host.innerHTML = exports.map(function (e) {
      if (e.status === 'running'){
        return '<div class="tr-export">' +
          '<div class="progress tr-progress"><div class="progress-bar" style="width:' +
            (e.progress || 0) + '%"></div></div>' +
          '<span>' + (e.progress || 0) + ' %</span> ' +
          '<button class="btn btn-xs btn-default tr-cancel" data-export="' + escapeHtml(e.id) +
          '">Cancelar</button>' +
        '</div>';
      }
      if (e.status === 'failed'){
        return '<div class="tr-export text-danger">Falló: ' + escapeHtml(e.error || '') +
          ' <button class="btn btn-xs btn-default tr-cancel" data-export="' + escapeHtml(e.id) +
          '">Quitar</button></div>';
      }
      if (e.status === 'canceled'){
        return '<div class="tr-export text-muted">Cancelada</div>';
      }
      return '<div class="tr-export">' +
        '<a class="btn btn-xs btn-primary" href="' + API + 'datasets/' + datasetId +
          '/exports/' + escapeHtml(e.id) + '/download">Descargar</a> ' +
        '<span class="text-muted">' + e.tile_count + ' teselas · ' + formatSize(e.size_bytes) +
        '</span> ' +
        '<button class="btn btn-xs btn-default tr-cancel" data-export="' + escapeHtml(e.id) +
        '">Borrar</button>' +
      '</div>';
    }).join('');

    Array.prototype.forEach.call(host.querySelectorAll('.tr-cancel'), function (button) {
      button.addEventListener('click', function () {
        cancelExport(datasetId, button.getAttribute('data-export'));
      });
    });
  }

  /**
   * ¿Esta tarea tiene ortofoto?
   *
   * Se mira `available_assets` y **no** `orthophoto_extent`: ese campo existe en el modelo pero el
   * serializer del core no lo expone, así que comprobarlo daba siempre `undefined` y el desplegable
   * de tareas salía vacío sin ningún error que lo explicara. El backend sí valida por
   * `orthophoto_extent` (responde `no_orthophoto`), de modo que en el caso raro en que ambos
   * discrepen el usuario recibe el motivo exacto en vez de una lista silenciosamente incompleta.
   */
  function hasOrthophoto(task){
    return !!task && Array.isArray(task.available_assets) &&
           task.available_assets.indexOf('orthophoto.tif') !== -1;
  }

  /**
   * Desenvuelve una respuesta de lista del core.
   *
   * `/api/projects/` devuelve un array plano y otras rutas devuelven `{count, results}` según
   * estén paginadas o no. Suponer una sola forma es lo que dejó el desplegable vacío: `results`
   * sobre un array da `undefined`, y el error se traga en silencio porque `|| []` parece
   * defensivo cuando en realidad está ocultando el problema.
   */
  function asList(response){
    if (Array.isArray(response)) return response;
    return (response && response.results) || [];
  }

  /**
   * `$.ajax` como Promise nativa.
   *
   * WebODM trae **jQuery 1.11.2**, anterior a Promises/A+: sus Deferred no tienen `.catch()` y su
   * `.then()` no desenvuelve una promesa devuelta, así que la devuelve tal cual al siguiente
   * eslabón. Encadenar `.then()` de jQuery con `Promise.all` producía dos fallos seguidos —
   * `.catch is not a function` y `projects.filter is not a function`— que dejaban el desplegable
   * de tareas vacío.
   *
   * Envolver aquí y usar Promises nativas a partir de este punto evita mezclar las dos
   * semánticas. El resto del fichero usa `.done()`/`.fail()`, que sí son de jQuery 1.11.
   */
  function getJSON(url){
    return new Promise(function (resolve, reject) {
      $.ajax({url: url, type: 'GET'}).done(resolve).fail(reject);
    });
  }

  /** Tareas con ortofoto que el usuario puede ver, agrupadas por proyecto (API del core). */
  function loadTasks(){
    return getJSON('/api/projects/?page_size=100')
      .then(function (page) {
        return Promise.all(asList(page).map(function (project) {
          return getJSON('/api/projects/' + project.id + '/tasks/')
            .then(function (tasks) {
              return {
                id: project.id,
                name: project.name,
                tasks: asList(tasks).filter(hasOrthophoto)
              };
            });
        }));
      })
      .then(function (projects) {
        state.projects = projects.filter(function (p) { return p.tasks.length; });
        renderTaskPicker();
        if (!state.projects.length){
          showError('No se encontró ninguna tarea con ortofoto procesada.');
        }
      })
      .catch(function () {
        showError('No se pudieron cargar las tareas.');
      });
  }

  // --- Render --------------------------------------------------------------------------

  function renderDatasets(){
    var host = el('tr-datasets');
    if (!host) return;

    if (!state.datasets.length){
      host.innerHTML = '<p class="text-muted">Todavía no hay datasets. Crea el primero abajo.</p>';
      return;
    }

    var rows = state.datasets.map(function (d) {
      var unavailable = (d.tasks || []).filter(function (t) { return !t.available; }).length;
      return '<tr>' +
        '<td>' + escapeHtml(d.name) + '</td>' +
        '<td>' + (d.classes || []).map(function (c) {
          return '<span class="tr-swatch" style="background:' + escapeHtml(c.color) + '"></span>' +
                 escapeHtml(c.index + ' ' + c.name);
        }).join(' ') + '</td>' +
        '<td>' + d.resolution_cm_px + ' cm/px</td>' +
        '<td>' + d.tile_size_px + ' px</td>' +
        '<td>' + (d.tasks || []).length +
          (unavailable ? ' <span class="text-warning" title="Tareas ya no disponibles">(' +
            unavailable + ' no disponibles)</span>' : '') + '</td>' +
        '<td class="tr-exports" data-id="' + escapeHtml(d.id) + '"></td>' +
        '<td class="tr-actions" data-id="' + escapeHtml(d.id) + '">' +
          '<button class="btn btn-xs btn-primary tr-export-btn">Exportar</button> ' +
          '<button class="btn btn-xs btn-danger tr-delete">Borrar</button>' +
        '</td>' +
      '</tr>';
    }).join('');

    host.innerHTML =
      '<table class="table table-striped table-condensed">' +
        '<thead><tr><th>Nombre</th><th>Clases</th><th>Resolución</th><th>Tesela</th>' +
        '<th>Tareas</th><th>Exportaciones</th><th></th></tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>';

    Array.prototype.forEach.call(host.querySelectorAll('.tr-delete'), function (button) {
      button.addEventListener('click', function () {
        var id = button.parentNode.getAttribute('data-id');
        if (!window.confirm('¿Borrar el dataset y todas sus etiquetas?')) return;
        $.ajax({url: API + 'datasets/' + id, type: 'DELETE'})
          .done(loadDatasets)
          .fail(function () { showError('No se pudo borrar el dataset.'); });
      });
    });

    Array.prototype.forEach.call(host.querySelectorAll('.tr-export-btn'), function (button) {
      button.addEventListener('click', function () {
        startExport(button.parentNode.getAttribute('data-id'));
      });
    });

    Object.keys(state.exports).forEach(renderExports);
  }

  function renderClasses(){
    var host = el('tr-classes');
    if (!host) return;
    host.innerHTML = state.classes.map(function (c, i) {
      return '<div class="tr-class-row">' +
        '<span class="tr-index">' + c.index + '</span>' +
        '<input type="text" class="form-control tr-class-name" data-i="' + i + '" value="' +
          escapeHtml(c.name) + '">' +
        (c.index === 0 ? '<span class="text-muted">fondo</span>' :
          '<button class="btn btn-xs btn-default tr-class-remove" data-i="' + i + '">×</button>') +
      '</div>';
    }).join('');

    Array.prototype.forEach.call(host.querySelectorAll('.tr-class-name'), function (input) {
      input.addEventListener('input', function () {
        state.classes[parseInt(input.getAttribute('data-i'), 10)].name = input.value;
      });
    });
    Array.prototype.forEach.call(host.querySelectorAll('.tr-class-remove'), function (button) {
      button.addEventListener('click', function () {
        state.classes.splice(parseInt(button.getAttribute('data-i'), 10), 1);
        reindexClasses();
        renderClasses();
      });
    });
  }

  /** Los índices deben quedar consecutivos desde 0: es lo que exige el backend (FR-003). */
  function reindexClasses(){
    state.classes.forEach(function (c, i) { c.index = i; });
  }

  function renderTaskPicker(){
    var host = el('tr-tasks');
    if (!host) return;
    host.innerHTML = state.projects.map(function (project) {
      return '<optgroup label="' + escapeHtml(project.name) + '">' +
        project.tasks.map(function (task) {
          return '<option value="' + escapeHtml(task.id) + '" data-project="' + project.id + '">' +
            escapeHtml(task.name || task.id) + '</option>';
        }).join('') +
      '</optgroup>';
    }).join('');
  }

  // --- Alta ----------------------------------------------------------------------------

  function createDataset(){
    var selected = Array.prototype.filter.call(el('tr-tasks').options, function (o) {
      return o.selected;
    }).map(function (o) {
      return {task_id: o.value, project_id: parseInt(o.getAttribute('data-project'), 10)};
    });

    if (!selected.length){
      showError('Elige al menos una tarea con ortofoto.');
      return;
    }

    reindexClasses();
    showError('');

    $.ajax({
      url: API + 'datasets', type: 'POST', contentType: 'application/json',
      data: JSON.stringify({
        name: el('tr-name').value,
        classes: state.classes,
        tasks: selected,
        resolution_cm_px: parseFloat(el('tr-resolution').value),
        tile_size_px: parseInt(el('tr-tile-size').value, 10)
      })
    })
      .done(function () {
        el('tr-name').value = '';
        loadDatasets();
      })
      .fail(function (xhr) {
        var body = xhr.responseJSON || {};
        showError(body.error || 'No se pudo crear el dataset.');
      });
  }

  function init(){
    var loading = el('tr-loading');
    if (loading) loading.style.display = 'none';

    renderClasses();

    var addClass = el('tr-add-class');
    if (addClass) addClass.addEventListener('click', function () {
      state.classes.push({index: state.classes.length, name: 'clase' + state.classes.length});
      renderClasses();
    });

    var create = el('tr-create');
    if (create) create.addEventListener('click', createDataset);

    loadDatasets();
    loadTasks();
  }

  window.TrainingDatasets = {api: API, state: state, init: init, loadDatasets: loadDatasets,
                            hasOrthophoto: hasOrthophoto, asList: asList,
                            loadTasks: loadTasks};

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
