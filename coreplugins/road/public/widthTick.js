// Dónde se dibuja la regla del ancho: función **pura** de tramo a par de coordenadas.
//
// La regla materializa **una** cifra —el ancho total del camino— y se dibuja en el **punto medio
// del tramo**, repartida mitad y mitad a cada lado del eje. Ni el reparto real entre lados ni el
// punto donde se midió la mueven de ahí:
//
//   - de borde a borde salía descolgada del eje en una calzada volcada, y parecía un error de
//     trazado en vez del reparto asimétrico que es;
//   - plantada donde cayó la transversal mediana, saltaba de sitio entre tramos vecinos y el mapa
//     parecía descuadrado, cuando lo único que había cambiado era dónde se midió.
//
// Esto es **solo dibujo**. `offset_left` y `offset_right` se siguen midiendo por separado, y
// `section_midpoint`, `edge_left` y `edge_right` siguen señalando el punto real de medición; todo
// ello viaja al popup y a las exportaciones. Recolocar la línea no puede borrar de qué lado está
// el camino ni dónde se midió de verdad.
//
// El vector entre los dos bordes ya trae las dos cosas que hacen falta —la dirección de la
// transversal y su longitud exacta en grados— así que la regla es ese mismo vector plantado en el
// centro del tramo, sin trigonometría ni conversiones. Reconstruirla con metros no valdría: los
// puntos llegan en EPSG:4326, donde un metro no mide lo mismo en latitud que en longitud.

/**
 * Extremos de la regla del ancho, `[[lng, lat], [lng, lat]]`, o `null` si el tramo no tiene los
 * dos bordes. Sin `midpoint` se devuelve la transversal de borde a borde: es lo que hay, y es
 * preferible a una coordenada inventada.
 */
export function widthTickPoints(segment){
  if (!segment) return null;

  const left = segment.edge_left;
  const right = segment.edge_right;
  if (!left || !right) return null;

  const mid = segment.midpoint;
  if (!mid) return [left, right];

  // Media diferencia: `|left - right|` es el ancho, así que medio vector a cada lado del centro
  // reparte esa misma longitud en dos mitades iguales.
  const dx = (left[0] - right[0]) / 2;
  const dy = (left[1] - right[1]) / 2;
  return [[mid[0] + dx, mid[1] + dy], [mid[0] - dx, mid[1] - dy]];
}
