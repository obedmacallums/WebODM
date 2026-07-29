/* Decisiones de estado del panel, separadas del componente React para poder probarse en Node
 * (`tests/panelLogic.test.js`): el JSX del panel no pasa por el harness, así que todo lo que se
 * pueda equivocar en silencio vive aquí como función pura y el componente queda en cableado.
 */

/** Parámetros con los que arranca el formulario: los del último análisis lanzado, sobre los
 * defectos.
 *
 * "Último" se decide por `updated_at` (el POST lo sella al lanzar) con `created_at` de reserva.
 * Se superponen a los defectos, no los sustituyen: un análisis calculado antes de que existiera
 * un parámetro no lo trae, y ese hueco debe valer su defecto, no `undefined` en el formulario.
 */
export function initialParams(defaults, analyses){
  let latest = null;
  let latestStamp = '';
  (analyses || []).forEach(a => {
    if (!a || !a.params) return;
    const stamp = a.updated_at || a.created_at || '';
    if (latest === null || stamp >= latestStamp){
      latest = a;
      latestStamp = stamp;
    }
  });
  return Object.assign({}, defaults, latest ? latest.params : null);
}

/** Qué hacer con un análisis del sondeo: `'publish'`, `'unpublish'` o `'none'`.
 *
 * `published` es lo que el panel tenga anotado para ese id — un grupo Leaflet o la reserva
 * `true` de una publicación en vuelo; ambos cuentan como publicado. La asimetría importante: el
 * servidor **reutiliza el id** al recalcular sobre el mismo eje, así que un análisis publicado
 * que ya no está `completed` es un recálculo pisándolo (o un fallo que borró los tramos) y su
 * dibujo tiene que salir del mapa — quedarse esperando era el bug de "solo se ve al refrescar".
 */
export function publishAction(published, analysis){
  if (analysis.status === 'completed') return published ? 'none' : 'publish';
  return published ? 'unpublish' : 'none';
}

/** Eje seleccionado tras refrescar la lista: se respeta la elección del usuario mientras el eje
 * exista; si desapareció (lo borró en `annotations`) se cae al primero disponible. */
export function axisSelection(axes, current){
  const list = axes || [];
  if (list.some(axis => axis.id === current)) return current;
  return list.length ? list[0].id : '';
}
