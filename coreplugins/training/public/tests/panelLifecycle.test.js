/* Cuándo se reconstruyen la capa y el editor del panel.
 *
 * El caso que da nombre a este fichero es el segundo: cerrar el panel y volver a abrirlo sobre el
 * mismo dataset. `teardownEditor` destruye el editor al cerrar, y la reconstrucción colgaba de que
 * cambiara el dataset — que al reabrir no cambia. El resultado era un panel que se abría con sus
 * controles pero sin etiquetas dibujadas y sin nada que seleccionar: parecía que el plugin había
 * dejado de funcionar, sin ningún error a la vista.
 */
const {setupDom, loadModule, test, assert, summary} = require('./harness');

setupDom();
const { shouldRebuildEditor } = loadModule('panelLifecycle.js');

test('con el panel cerrado no se construye nada', () => {
  assert(shouldRebuildEditor({isShowed: false, datasetId: 'a', hasEditor: false},
                             {previousDatasetId: 'a'}) === false);
});

test('sin dataset elegido tampoco', () => {
  assert(shouldRebuildEditor({isShowed: true, datasetId: null, hasEditor: false},
                             {previousDatasetId: null}) === false);
});

test('elegir el primer dataset construye el editor', () => {
  assert(shouldRebuildEditor({isShowed: true, datasetId: 'a', hasEditor: false},
                             {previousDatasetId: null}) === true);
});

test('cambiar de dataset lo reconstruye', () => {
  // Las clases, los colores y las etiquetas son otros: reutilizar la capa mostraría las del
  // dataset anterior con la paleta del nuevo.
  assert(shouldRebuildEditor({isShowed: true, datasetId: 'b', hasEditor: true},
                             {previousDatasetId: 'a'}) === true);
});

test('reabrir el panel sobre el mismo dataset lo reconstruye', () => {
  // **El bug**: al cerrar se destruyó el editor, y aquí el dataset no ha cambiado. Si esto
  // devolviera `false`, el panel se abriría vacío y sin poder editar.
  assert(shouldRebuildEditor({isShowed: true, datasetId: 'a', hasEditor: false},
                             {previousDatasetId: 'a'}) === true,
    'volver al panel debe devolver las etiquetas y su edición');
});

test('un render cualquiera con el editor ya montado no lo rehace', () => {
  // Reconstruir en cada render tiraría la selección en curso y volvería a pedir las etiquetas
  // en cada tecla que el usuario tocara en el panel.
  assert(shouldRebuildEditor({isShowed: true, datasetId: 'a', hasEditor: true},
                             {previousDatasetId: 'a'}) === false);
});

summary('panelLifecycle');
