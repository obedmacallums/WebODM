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
//   no_edge      -> color por pendiente, trazo **discontinuo**: hay rasante pero no hay ancho
//   no_coverage  -> gris y discontinuo: no hay ni cota
//
// El trazo discontinuo es lo que distingue a simple vista un tramo medido de uno que no lo está
// (quickstart, escenario 2) sin tirar a la basura la pendiente, que en un tramo `no_edge` está
// perfectamente medida.

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
  const measured = segment && segment.status === 'measured';
  return {
    color: colorForGrade(segment ? segment.grade : null, thresholds),
    weight: measured ? 6 : 5,
    opacity: measured ? 0.95 : 0.75,
    dashArray: measured ? null : '6,6',
    lineCap: 'butt'
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
