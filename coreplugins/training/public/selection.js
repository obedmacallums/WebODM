/**
 * Qué queda seleccionado tras un clic.
 *
 * Vive fuera del panel por lo mismo que `deleteShortcut.js`: de aquí cuelga qué se borra, y una
 * selección que arrastra una etiqueta de más borra una etiqueta de más. Aquí se puede probar sin
 * navegador.
 *
 * El convenio es el de cualquier gestor de archivos, que es lo que el usuario ya sabe sin que se lo
 * expliquen:
 *
 * - **clic** — la selección pasa a ser solo esa etiqueta.
 * - **Shift + clic** — la añade, o la quita si ya estaba.
 *
 * El orden se conserva —se añade al final— para que la lista del panel no baile al seleccionar.
 */

/** ¿Trae el evento de Leaflet la mayúscula pulsada? */
export function isAdditive(event){
  return !!(event && event.originalEvent && event.originalEvent.shiftKey);
}

/**
 * La selección resultante, como array de identificadores.
 *
 * Un clic normal **no** deselecciona lo que ya estaba seleccionado solo: quien vuelve a clicar el
 * mismo polígono quiere seguir trabajando con él, no soltarlo. Para soltar están Shift + clic y el
 * botón de deseleccionar.
 */
export function nextSelection(current, labelId, additive){
  const selection = (current || []).slice();
  if (!labelId) return selection;

  if (!additive) return [labelId];

  const at = selection.indexOf(labelId);
  if (at === -1) selection.push(labelId);
  else selection.splice(at, 1);
  return selection;
}

/**
 * La selección sin los identificadores que ya no existen.
 *
 * Se aplica al recargar las etiquetas: una selección que apunta a una etiqueta ausente deja el
 * botón de borrar sin hacer nada y sin decir por qué.
 */
export function pruneSelection(current, labels){
  const alive = {};
  (labels || []).forEach(label => { alive[label.id] = true; });
  return (current || []).filter(id => alive[id]);
}

/** Las etiquetas seleccionadas, en el orden en que están en la lista. */
export function selectedLabels(current, labels){
  const chosen = {};
  (current || []).forEach(id => { chosen[id] = true; });
  return (labels || []).filter(label => chosen[label.id]);
}

/**
 * ¿Se pueden editar vértices?
 *
 * Solo con exactamente una etiqueta seleccionada. Con varias no hay una geometría que arrastrar, y
 * dejar los manejadores de la primera sobre el mapa haría creer que se está editando el conjunto.
 */
export function canEditVertices(current){
  return (current || []).length === 1;
}

export function sameSelection(a, b){
  const first = a || [];
  const second = b || [];
  if (first.length !== second.length) return false;
  return first.every((id, index) => id === second[index]);
}
