/**
 * ¿Debe esta pulsación borrar la etiqueta seleccionada?
 *
 * Vive fuera del panel porque es la decisión con más formas de salir mal de todo el editor, y aquí
 * se puede probar sin navegador. Borrar una etiqueta es **irreversible**: `store.write_labels`
 * sobrescribe el fichero con `os.replace` y no hay historial, así que el atajo tiene que estar
 * seguro antes de disparar.
 *
 * Se aceptan las dos teclas de borrado a propósito. En un teclado español `Supr` emite `Delete`,
 * pero en el Mac del usuario la tecla grande de borrar emite `Backspace` y el `Delete` de verdad
 * exige `Fn`. Atender solo a una de las dos habría dejado el atajo sin funcionar en la mitad de los
 * teclados.
 */

const DELETE_KEYS = ['Delete', 'Backspace'];

// Donde la tecla de borrar significa «borra un carácter» y nunca «borra la etiqueta». `select`
// entra porque escribir en él salta a la opción que empieza por esa letra, y en algunos navegadores
// borrar la revierte.
const TEXT_INPUTS = ['INPUT', 'TEXTAREA', 'SELECT'];

export function isDeleteKey(event){
  return !!event && DELETE_KEYS.indexOf(event.key) !== -1;
}

/** ¿Está el foco en algo donde el usuario está escribiendo? */
export function isTyping(element){
  if (!element) return false;
  if (element.isContentEditable) return true;
  return TEXT_INPUTS.indexOf(element.tagName) !== -1;
}

/**
 * `context`: `{isShowed, hasSelection, isDrawing, activeElement}`.
 *
 * Las cuatro condiciones son necesarias y ninguna es teórica:
 *
 * - **`isShowed`** — el manejador vive en `document`, así que sigue oyendo con el panel cerrado. Sin
 *   esto, borrar texto en cualquier otra parte de WebODM se llevaría una etiqueta por delante.
 * - **`hasSelection`** — sin nada seleccionado no hay nada que borrar.
 * - **`!isDrawing`** — durante un trazado la tecla no puede tocar una etiqueta guardada; para
 *   abandonar el trazo está Escape.
 * - **`!isTyping`** — es la que de verdad importa. Con el foco en el nombre del dataset o en el
 *   ancho del trazo, `Backspace` es «borra un carácter»: sin esta guarda, escribir el nombre de un
 *   dataset iría borrando etiquetas de una en una.
 */
export function shouldDeleteSelected(event, context){
  const {isShowed, hasSelection, isDrawing, activeElement} = context || {};
  if (!isDeleteKey(event)) return false;
  if (!isShowed || !hasSelection || isDrawing) return false;
  return !isTyping(activeElement);
}
