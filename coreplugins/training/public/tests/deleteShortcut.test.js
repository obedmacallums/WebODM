/* El atajo de borrado (`deleteShortcut.js`).
 *
 * Borrar una etiqueta es irreversible —el store sobrescribe el fichero con `os.replace` y no hay
 * historial—, así que lo que se prueba aquí no es que la tecla funcione, que es lo fácil, sino
 * **todos los casos en que no debe funcionar**. El peor con diferencia es escribir el nombre de un
 * dataset: sin la guarda del foco, cada `Backspace` corrigiendo una letra se llevaría una etiqueta.
 */
const {setupDom, loadModule, test, assert, summary} = require('./harness');

setupDom();
const shortcut = loadModule('deleteShortcut.js', {});

/** El contexto en el que el atajo SÍ debe disparar; cada test estropea una cosa. */
function ready(overrides = {}){
  return Object.assign({
    isShowed: true,
    hasSelection: true,
    isDrawing: false,
    activeElement: document.body
  }, overrides);
}

function element(tagName, props = {}){
  const el = document.createElement(tagName);
  Object.keys(props).forEach(k => { el[k] = props[k]; });
  return el;
}

test('Supr borra la etiqueta seleccionada', () => {
  assert(shortcut.shouldDeleteSelected({key: 'Delete'}, ready()) === true,
         'es lo que pidió el usuario');
});

test('Backspace también borra', () => {
  // En el Mac del usuario la tecla grande de borrar emite `Backspace`; el `Delete` de verdad exige
  // `Fn`. Atender solo a `Delete` habría dejado el atajo sin funcionar en su propio teclado.
  assert(shortcut.shouldDeleteSelected({key: 'Backspace'}, ready()) === true);
});

test('ninguna otra tecla borra', () => {
  ['Escape', 'Enter', 'd', 'D', 'Suprimir', 'Del', ' ', 'ArrowLeft'].forEach(key => {
    assert(shortcut.shouldDeleteSelected({key}, ready()) === false,
           'la tecla ' + key + ' no puede borrar');
  });
});

test('sin selección no hay nada que borrar', () => {
  assert(shortcut.shouldDeleteSelected({key: 'Delete'},
                                       ready({hasSelection: false})) === false);
});

test('con el panel cerrado no borra', () => {
  // El manejador vive en `document` y sigue oyendo con el panel cerrado: sin esta guarda, borrar
  // texto en cualquier otra parte de WebODM se llevaría una etiqueta por delante.
  assert(shortcut.shouldDeleteSelected({key: 'Delete'}, ready({isShowed: false})) === false);
});

test('mientras se dibuja no borra', () => {
  // Para abandonar un trazo a medias está Escape. La tecla de borrar no puede tocar una etiqueta ya
  // guardada mientras el usuario está pintando otra.
  assert(shortcut.shouldDeleteSelected({key: 'Delete'}, ready({isDrawing: true})) === false);
});

test('escribiendo en un campo de texto NO borra la etiqueta', () => {
  // La guarda que de verdad importa: con el foco en el nombre del dataset, `Backspace` significa
  // «borra un carácter».
  ['input', 'textarea', 'select'].forEach(tag => {
    assert(shortcut.shouldDeleteSelected(
      {key: 'Backspace'}, ready({activeElement: element(tag)})) === false,
      'con el foco en <' + tag + '> la tecla es del campo, no del mapa');
  });
});

test('tampoco en un contenedor editable', () => {
  assert(shortcut.shouldDeleteSelected(
    {key: 'Backspace'},
    ready({activeElement: element('div', {isContentEditable: true})})) === false);
});

test('el rango del ancho no bloquea el atajo', () => {
  // Un `input[type=range]` es un campo, así que queda bloqueado por la regla del foco. Es lo
  // correcto aunque ahí no se escriba: el usuario que acaba de mover el ancho no espera que la
  // siguiente tecla borre nada.
  assert(shortcut.shouldDeleteSelected(
    {key: 'Delete'}, ready({activeElement: element('input', {type: 'range'})})) === false);
});

test('sin foco en ningún sitio sí borra', () => {
  // Es el caso real: tras clicar un polígono el foco queda en el contenedor del mapa o en `body`.
  assert(shortcut.shouldDeleteSelected({key: 'Delete'},
                                       ready({activeElement: null})) === true);
  assert(shortcut.shouldDeleteSelected(
    {key: 'Delete'}, ready({activeElement: element('div')})) === true);
});

test('un evento vacío no borra', () => {
  assert(shortcut.shouldDeleteSelected(null, ready()) === false);
  assert(shortcut.shouldDeleteSelected({}, ready()) === false);
});

summary('deleteShortcut');
