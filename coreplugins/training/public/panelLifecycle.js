/**
 * Cuándo hay que (re)construir la capa de etiquetas y el editor del panel.
 *
 * Vive fuera de `TrainingPanel.jsx` para poder probarse sin montar React, igual que
 * `coreplugins/road/public/panelLogic.js`.
 *
 * La regla existe por un fallo concreto: al cerrar el panel se destruyen el editor y la capa, pero
 * la reconstrucción colgaba de «¿cambió el dataset?». Al reabrir el panel sobre el **mismo**
 * dataset no cambiaba nada, así que nadie los recreaba: las etiquetas no se dibujaban y no había
 * forma de seleccionarlas ni editarlas. Desde fuera parecía que el plugin había dejado de
 * funcionar, sin ningún error que lo explicara.
 */

/**
 * @param {{isShowed: boolean, datasetId: ?string, hasEditor: boolean}} current estado actual
 * @param {{previousDatasetId: ?string}} previous estado del render anterior
 */
export function shouldRebuildEditor(current, previous){
  const {isShowed, datasetId, hasEditor} = current || {};
  const {previousDatasetId} = previous || {};

  // Sin panel visible o sin dataset elegido no hay nada que construir.
  if (!isShowed || !datasetId) return false;

  // Cambiar de dataset obliga a rehacerlo: las clases, los colores y las etiquetas son otros.
  if (datasetId !== previousDatasetId) return true;

  // Mismo dataset y sin editor: el panel se reabrió después de que `teardownEditor` lo destruyera.
  return !hasEditor;
}
