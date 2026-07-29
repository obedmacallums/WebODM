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

/** Preset para rampas y caminos mineros anchos.
 *
 * La geometría base, validada sobre perfiles sintéticos de 25 m de calzada: semiancho 20 para que
 * los bordes quepan en el perfil (el defecto de 10 hace inmedible cualquier calzada de más de
 * 20 m), paso 0,5 para que la base de la derivada quede por encima del ruido, y umbral 25 entre
 * el bombeo (~2 %) y el talud o berma (40-60 %).
 *
 * Y el antirruido, ajustado sobre un DTM minero real donde las diez transversales de un tramo
 * devolvían anchos de 1,5 a 12 m en una calzada de ancho constante:
 *
 *   min_consecutive 4     a paso 0,5 son 2 m de quiebre sostenido. Es el único filtro antirruido
 *                         del criterio `break`, y es el que más rinde: con 2 muestras bastan dos
 *                         saltos ruidosos seguidos para inventar un borde.
 *   smooth_window 2       la mediana móvil necesita al menos 1,5 m a este paso para no ser
 *                         identidad; 2 m le dan cinco muestras de ventana.
 *   spacing 1             el ancho deja de salir de una única transversal en el punto medio, que
 *                         es donde un bache suelto se llevaba el tramo entero.
 *   mediana               con anchos dispersos la media arrastra con cada borde falso.
 *   coherencia 3          repara lo que aún quede suelto, declarándolo.
 *
 * Solo las claves que el criterio minero necesita: la longitud de tramo es una decisión de
 * reporte del usuario y los parámetros del otro modo se conservan por si vuelve a él.
 */
export const MINING_PRESET = {
  edge_mode: 'break',
  search_half_width: 20,
  sample_step: 0.5,
  break_threshold: 25,
  min_consecutive_samples: 4,
  coherence_window: 3,
  smooth_window: 2,
  cross_section_spacing: 1,
  width_aggregation: 'median'
};

/** Parámetros con el preset aplicado encima: nuevo objeto, sin mutar la entrada. */
export function applyPreset(params, preset){
  return Object.assign({}, params, preset);
}
