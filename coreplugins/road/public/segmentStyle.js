// Semáforo de pendiente: función **pura** de (tramo, umbrales) a estilo de Leaflet
// (`research.md` D15).
//
// Vive separada del dibujo a propósito. El color es la regla que el usuario mueve con dos
// deslizadores y espera ver aplicada al instante; tenerla aquí, sin depender de Leaflet ni del
// DOM, permite probarla contra valores exactos y recolorear con un `setStyle` sobre las
// polilíneas ya dibujadas, sin volver a pedir el análisis.
//
// Convenio de estilos:
//
//   measured     -> color por pendiente, trazo continuo
//   inferred     -> color por pendiente, trazo a rayas LARGAS (`12,4`): hay ancho, pero al menos
//                   un borde viene de los vecinos (`006` FR-032)
//   no_edge      -> color por pendiente, trazo discontinuo corto (`6,6`): hay rasante, no hay ancho
//   no_coverage  -> gris y discontinuo: no hay ni cota
//
// El trazo discontinuo es lo que distingue a simple vista un tramo medido de uno que no lo está
// (quickstart, escenario 2) sin tirar a la basura la pendiente, que en un tramo `no_edge` está
// perfectamente medida. La raya larga del `inferred` queda a medio camino a propósito: más
// continua que un `no_edge` —el ancho existe— y menos que un `measured` —no todo se midió aquí.

export function colors(){
  return {
    ok: '#2e9e4f',
    warn: '#e8b900',
    alert: '#d9422b',
    unknown: '#8a8a8a'
  };
}

// `[aviso, alerta]` en %. Verde hasta el aviso, amarillo hasta la alerta, rojo por encima.
export function colorForGrade(grade, thresholds){
  const palette = colors();
  if (grade === null || grade === undefined || isNaN(grade)) return palette.unknown;
  const [warn, alert] = thresholds || [8.0, 12.0];
  const magnitude = Math.abs(grade);
  if (magnitude <= warn) return palette.ok;
  if (magnitude <= alert) return palette.warn;
  return palette.alert;
}

export function styleForSegment(segment, thresholds){
  const status = segment ? segment.status : null;
  const hasWidth = status === 'measured' || status === 'inferred';
  return {
    color: colorForGrade(segment ? segment.grade : null, thresholds),
    weight: hasWidth ? 6 : 5,
    opacity: hasWidth ? 0.95 : 0.75,
    dashArray: status === 'measured' ? null : (status === 'inferred' ? '12,4' : '6,6'),
    lineCap: 'butt'
  };
}

// Contorno blanco del tramo bajo el cursor.
//
// Leaflet no sabe dibujar un borde alrededor de un trazo, así que el contorno es una línea blanca
// más ancha que se coloca **entre los tramos vecinos y el tramo activo**: por encima de los
// primeros —para que su blanco los recorte y se vea dónde empieza y acaba el tramo— y por debajo
// del segundo, para no taparle su color del semáforo.
//
// `lineCap: 'round'` es lo que produce esa separación: sin él el contorno terminaría justo en los
// extremos del tramo, el blanco solo asomaría por los flancos, y dos tramos verdes seguidos
// seguirían pareciendo una sola línea — que es el problema que esto viene a resolver.
export function haloStyleFor(segment){
  const base = styleForSegment(segment, null);
  return {
    color: '#ffffff',
    weight: base.weight + 5,
    opacity: 0.95,
    // Continuo aunque el tramo sea discontinuo: el contorno marca su extensión, y el trazo
    // discontinuo del tramo sigue viéndose encima porque se dibuja después.
    dashArray: null,
    lineCap: 'round',
    // Sin esto el contorno queda bajo el cursor y **se come el click**, que es justo lo que no
    // se quería tocar.
    interactive: false
  };
}

// Área de captura del cursor: una línea invisible y ancha por tramo.
//
// El tramo visible es un trazo de 6 px y, medido en el navegador sobre un análisis real, solo
// responde al cursor a ±2 px de su eje. Los tramos sin medir son peor: su trazo es discontinuo y
// **los huecos no reciben eventos** —el hit testing de SVG solo cuenta lo pintado—, así que 10 de
// cada 24 px del propio eje son zona muerta. Con tramos de ~40 px de largo a un zoom de trabajo,
// pasar el cursor por encima es cuestión de puntería.
//
// Un trazo con `stroke-opacity: 0` sigue recibiendo el cursor: lo que cuenta es que tenga `stroke`,
// no que se vea. Medido: ±10 px con ancho 20, cinco veces el blanco actual.
export function hitStyle(){
  return {
    color: '#ffffff',
    weight: 20,
    opacity: 0,
    // Continua aunque el tramo sea discontinuo: es justo el caso que hoy no se puede señalar.
    dashArray: null,
    // `butt` y no `round`: con extremos redondeados cada área rebasaría ~10 px sobre el tramo
    // vecino y quién se queda la junta lo decidiría el orden en el DOM. Los tramos son contiguos,
    // así que a tope encajan sin solaparse ni dejar hueco.
    lineCap: 'butt',
    interactive: true
  };
}

// Etiqueta legible del motivo por el que un lado no tiene borde (FR-021).
//
// Los tres motivos describen problemas distintos con soluciones distintas: retocar el umbral de
// quiebre, volar de nuevo, o corregir el trazado del eje. Una etiqueta genérica los borraría.
export function reasonLabel(reason){
  if (reason === 'no_break') return 'sin quiebre';
  if (reason === 'no_data') return 'sin datos de elevación';
  if (reason === 'break_at_axis') return 'el terreno se quiebra sobre el eje';
  return null;
}
