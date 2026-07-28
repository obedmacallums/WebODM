# Feature Specification: Detección del ancho de calle por criterio de superficie y coherencia entre tramos

**Feature Branch**: `006-street-width`

**Created**: 2026-07-28

**Status**: Draft

**Input**: User description: "El detector de bordes actual del plugin `road` busca el arranque de la primera racha de pendiente local por encima de un umbral, caminando desde el eje hacia afuera. Funciona en caminos rurales, donde el borde es un talud. Falla en calles urbanas con bordillo, y está medido sobre una tarea real (`Polideportivo María Puebla Vásquez`, proyecto `marcoleta`, DTM y DSM a 5 cm, eje de 135 m = 27 tramos):

- Un bordillo de ~15 cm NO aparece como escalón vertical en el DEM: la fotogrametría a 5 cm de GSD lo redondea a una rampa de ~25 cm repartida en ~1 m, es decir un 20–30 %.
- El ruido de reconstrucción produce picos AISLADOS de una sola muestra mucho más afilados que el propio bordillo: mediana de la pendiente local máxima a menos de 3 m del eje = 86 % (DTM) y 134 % (DSM). En esta escala el ruido es más afilado que la señal, así que afinar el detector hacia lo vertical lo aleja del objetivo.
- Consecuencia medida: umbral 100 % con racha 2 da 0 de 27 tramos; 40 % con racha 2 da 0–1 de 27; subir el paso de muestreo a 0,25 m da 0 de 27, porque promedia la rampa por debajo del umbral.
- Con los parámetros por defecto (15 %, racha 3, paso = resolución, DTM) sí mide 22 de 27, pero con ancho medio 6,25 m, desviación típica 2,21 m y rango 0,70–10,55 m. Los offsets del lado acera: media 1,24 m, desviación 1,29, rango 0,10–7,25.
- La ortofoto explica buena parte de esa dispersión y NO es culpa del algoritmo: la calle tiene solera, acera y parque en el lado oeste, pero el lado este son palmeras y terreno suelto hasta la vía del tren. No hay dos bordillos en todo el trazado, y el eje dibujado a mano va descentrado.
- Donde la calle sí tiene bordillo a ambos lados, el detector actual ya es repetible: progresivas 75/80/85 m dan 6,50 / 6,70 / 6,80 m, y 120/125/130 m dan 6,60 / 6,70 / 6,80 m.
- Un criterio de nivel ingenuo (+8 cm sobre el plano de calzada ajustado cerca del eje) da 6,75 ± 2,00 m: la misma dispersión, porque el límite no está en cómo se busca el borde sino en que en media calle no hay borde que buscar.

El fallo más grave del comportamiento actual no es la dispersión sino que no hay cota de cordura: cuando el bordillo se escapa, el recorrido sigue hasta el semiancho de búsqueda y engancha la fachada, un muro o un arbusto, y eso se publica como tramo medido con un número plausible y equivocado (10,55 m en la progresiva 45).

Se pide un modo de detección alternativo pensado para calles: el borde deja de buscarse por lo afilado y pasa a buscarse por lo alto — la calzada termina donde la superficie deja de ser plana respecto de sí misma. Más una pasada de coherencia entre tramos vecinos que corrija atípicos y huecos cortos, declarando siempre qué bordes son medidos y cuáles inferidos.

Fuera de alcance: cualquier uso de la ortofoto o análisis de imagen; ajuste global del borde como línea a lo largo de todo el trazado; cambiar el detector por defecto o el resultado de análisis ya guardados; dependencias nuevas."

## Convención de referencias

Los requisitos de la feature `005-road-metrics` se citan como `005/FR-0xx` para no confundirlos con
la numeración propia de esta spec, que empieza de nuevo en `FR-001`.

## Clarifications

### Session 2026-07-28

- Q: ¿Puede el borde de un tramo apoyarse en los tramos vecinos, o cada tramo debe decidir solo con sus propias muestras? → A: Sí, pero declarándolo: el origen del borde (medido o inferido) viaja en el modelo de datos, en la consulta del tramo y en la exportación. Es la concesión mínima al principio `005/FR-022` ("nada se rellena, nada se estima con lo que haya").
- Q: ¿El detector nuevo convive con el actual o lo sustituye? → A: Convive como modo seleccionable y el defecto NO se toca. Los análisis rurales ya validados no pueden cambiar de resultado.
- Q: ¿Hasta dónde puede alcanzar la inferencia entre tramos? → A: Solo reparación local con ventana corta. Nada de ajuste global del borde como línea: extrapolar un bordillo que físicamente no existe es justo lo que no se quiere.
- Q: ¿Se admite usar la ortofoto para hallar el borde? → A: No. Solo DEM. En la calle medida las palmeras tapan el borde este, así que el análisis radiométrico no compra lo que cuesta.
- Q: ¿Se mide antes si de verdad hacen falta dos detectores? → A: No; se acepta el diseño de dos modos sin prototipo previo, asumiendo que el criterio de superficie puede fallar en cunetas suaves sin escalón.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Medir el ancho de una calle con bordillo (Priority: P1)

Un usuario ha trazado el eje de una calle urbana y lanza el análisis con los parámetros por
defecto. Obtiene anchos dispersos y sin sentido físico: una calle no mide 0,70 m en un tramo y
10,55 m en el siguiente. Cambia el modo de detección de borde a **superficie**, relanza, y ahora
los tramos donde la calle tiene bordillo a ambos lados le dan anchos consistentes entre sí.

**Why this priority**: es el motivo de existir de la feature. Sin esto, el plugin no sirve en
entorno urbano, que es la mitad de los vuelos del usuario.

**Independent Test**: se puede probar de principio a fin lanzando un análisis en modo superficie
sobre una calle con bordillo y comprobando que los anchos de tramos contiguos con bordillo a ambos
lados no dispersan más de lo admitido, sin necesidad de ninguna otra historia.

**Acceptance Scenarios**:

1. **Given** un eje trazado sobre una calle con bordillo a ambos lados y un modelo de elevación que
   la cubre, **When** el usuario lanza el análisis en modo superficie, **Then** los tramos
   contiguos que tienen bordillo a ambos lados reportan anchos cuya desviación típica no supera
   0,25 m.
2. **Given** una calzada con peralte marcado y bordillo a ambos lados, **When** se analiza en modo
   superficie, **Then** los bordes se sitúan en el bordillo y no en un punto intermedio de la
   calzada, porque el peralte no cuenta como separación de la superficie.
3. **Given** un bordillo cuyo escalón aparece difuminado en el modelo de elevación a lo largo de
   aproximadamente un metro, **When** se analiza en modo superficie, **Then** el borde se detecta,
   mientras que el modo de quiebre sobre el mismo perfil no lo detecta o lo sitúa en otro lugar.
4. **Given** un modelo de elevación con picos de ruido aislados más pronunciados que el propio
   bordillo, **When** se analiza en modo superficie, **Then** el borde reportado es el bordillo y
   no el pico de ruido.

---

### User Story 2 - No recibir anchos inventados donde no hay borde (Priority: P2)

La misma calle no tiene bordillo en el lado este durante un tramo largo: hay vegetación y terreno
suelto hasta una vía de tren. El usuario espera que el sistema le diga que ahí no puede medir el
ancho, en lugar de darle un número que parece razonable y no lo es.

**Why this priority**: un número equivocado que parece correcto hace más daño que un hueco
declarado. Es la aplicación directa de `005/FR-022` y lo que separa una medición de una
estimación.

**Independent Test**: se prueba analizando un eje cuyo lado carece de borde durante varios tramos
seguidos y comprobando que esos tramos no reportan ancho, con el motivo por lado visible.

**Acceptance Scenarios**:

1. **Given** un tramo cuyo lado carece de cualquier borde dentro del semiancho de búsqueda y cuyos
   vecinos tampoco lo tienen, **When** se analiza en modo superficie con la coherencia activada,
   **Then** ese tramo no reporta ancho y registra el motivo por lado.
2. **Given** una secuencia de al menos diez tramos consecutivos sin borde en un lado, **When** se
   analiza con una ventana de coherencia corta, **Then** ninguno de ellos recibe un borde inferido.
3. **Given** un tramo con borde inferido junto a otro tramo sin borde, **When** se aplica la
   coherencia, **Then** el borde inferido no sirve de evidencia para inferir el del vecino.

---

### User Story 3 - Saber de dónde sale cada número (Priority: P3)

El usuario consulta un tramo en el mapa y ve que su borde izquierdo mide 1,20 m. Necesita saber si
esa cifra la midió el sistema en ese tramo o la dedujo de los tramos vecinos, tanto en pantalla
como en el archivo que se lleva a QGIS.

**Why this priority**: es la condición que hace aceptable la inferencia. Sin ella la feature
violaría el principio de no rellenar; con ella el usuario decide qué hacer con cada cifra.

**Independent Test**: se prueba consultando un tramo con borde inferido y comprobando que tanto la
consulta como la exportación distinguen el origen de cada lado.

**Acceptance Scenarios**:

1. **Given** un tramo cuyo borde derecho fue inferido de sus vecinos, **When** el usuario consulta
   sus métricas, **Then** ve la distancia al borde derecho marcada como inferida, y la del
   izquierdo, medida, sin marca.
2. **Given** ese mismo tramo, **When** el usuario exporta el análisis, **Then** el archivo contiene
   el origen de cada borde como dato, no solo la distancia.
3. **Given** un tramo cuyo borde derecho fue inferido porque no había ninguno medido allí, **When**
   se consulta, **Then** conserva además el motivo original por el que no se pudo medir.
4. **Given** un análisis con tramos de origen mixto, **When** se dibuja en el mapa, **Then** los
   tramos con algún borde inferido se distinguen a simple vista tanto de los medidos por completo
   como de los que no tienen ancho.

---

### User Story 4 - Que los análisis rurales sigan exactamente igual (Priority: P4)

El usuario tiene análisis de caminos rurales ya validados. Tras la actualización, los reabre y los
recalcula con los mismos parámetros, y obtiene exactamente los mismos números que antes.

**Why this priority**: la confianza en la herramienta se pierde una sola vez. Un cambio silencioso
de resultados en trabajos ya entregados es peor que no tener la feature.

**Independent Test**: se prueba recalculando un análisis rural existente con sus parámetros
originales y comparando tramo a tramo con el resultado anterior.

**Acceptance Scenarios**:

1. **Given** un análisis existente calculado antes de esta feature, **When** se recalcula sin
   cambiar ningún parámetro, **Then** todos los tramos reportan valores idénticos a los anteriores.
2. **Given** un análisis guardado antes de esta feature, **When** se abre sin recalcular, **Then**
   se muestra sin error y sus bordes existentes aparecen como medidos.
3. **Given** cualquier análisis, **When** la ventana de coherencia vale cero, **Then** ningún borde
   cambia respecto del resultado de la detección.

---

### Edge Cases

- **El eje pasa más cerca del borde que el ancho de la zona de ajuste inicial**: la referencia de
  calzada se toma inicialmente de una franja estrecha en torno al eje, que en ese caso incluye
  acera. El sistema debe corregirlo reajustando la referencia sobre la calzada ya acotada; si ni
  aun así hay calzada que medir, el tramo se reporta con el motivo de que el terreno se rompe sobre
  el propio eje.
- **Calzada no plana**: lomos de burro, badenes o roderas profundas hacen que la superficie se
  aparte de su propia referencia sin que haya borde. El sistema producirá bordes falsos ahí; es un
  límite conocido del método que debe quedar documentado, no resuelto.
- **Tolerancia mayor que la altura del bordillo**: si el usuario configura una tolerancia por
  encima del escalón real, ningún punto se aparta lo suficiente y el lado se reporta sin borde. El
  comportamiento debe ser ese y no un borde arbitrario.
- **Calzada que se funde con el terreno**: una vía sin bordillo ni talud nunca se aparta de su
  referencia y se reporta sin borde, aunque el modo de quiebre sí habría encontrado algo.
- **Vecindad con variación legítima**: un borde que se abre gradualmente a lo largo de varios
  tramos (un ensanche, un aparcamiento en línea) no debe aplanarse a un valor único por la pasada
  de coherencia.
- **Vecindad insuficiente**: en los tramos inicial y final del eje, o cuando casi ningún vecino
  tiene borde, no hay evidencia con la que reparar y el tramo debe quedarse como estaba.
- **El perfil se queda sin dato antes de encontrar el borde**: se reporta sin borde con el motivo
  de falta de datos, igual que hoy.

## Requirements *(mandatory)*

### Functional Requirements

#### Modo de detección

- **FR-001**: El sistema DEBE ofrecer dos modos de detección de borde seleccionables por el
  usuario: **quiebre** (el actual, basado en la pendiente local sostenida) y **superficie** (nuevo).
- **FR-002**: El modo por defecto DEBE ser **quiebre**, y con él el sistema DEBE producir
  resultados idénticos a los de la versión anterior para los mismos parámetros y el mismo modelo de
  elevación.
- **FR-003**: El modo elegido DEBE quedar registrado junto al análisis, de forma que al consultarlo
  o exportarlo se sepa con qué criterio se obtuvieron sus bordes.
- **FR-004**: Un valor de modo no admitido DEBE rechazarse con un mensaje que enumere los valores
  válidos.

#### Criterio de superficie

- **FR-005**: En modo superficie, el sistema DEBE establecer una referencia de la superficie de
  calzada ajustada sobre las muestras próximas al eje dentro del propio perfil transversal.
- **FR-006**: El borde de cada lado DEBE ser el primer punto, avanzando desde el eje hacia afuera,
  cuya separación respecto de esa referencia supera una tolerancia configurable y **se mantiene**
  superándola durante el número mínimo de muestras consecutivas ya existente.
- **FR-007**: La referencia DEBE reajustarse usando únicamente las muestras comprendidas entre los
  dos bordes hallados, y la detección repetirse sobre la referencia reajustada, para que un eje
  descentrado no contamine la medida.
- **FR-008**: La referencia DEBE absorber la pendiente transversal de la calzada, de modo que un
  peralte marcado no se confunda con separación de la superficie. Comparar contra la cota del eje
  NO satisface este requisito.
- **FR-009**: En modo superficie, la pendiente transversal del tramo DEBE derivarse de la
  referencia ajustada sobre las muestras de calzada. En modo quiebre DEBE mantenerse el cálculo
  actual, sin cambios.
- **FR-010**: El modo superficie DEBE reutilizar los tres motivos de "sin borde" ya existentes, sin
  añadir valores nuevos al contrato: sin quiebre dentro del área de búsqueda, sin datos de
  elevación, y terreno roto sobre el propio eje.

#### Coherencia entre tramos

- **FR-011**: El sistema DEBE ofrecer una pasada de coherencia que, para cada lado por separado,
  corrija el borde de un tramo a partir de los bordes de sus vecinos dentro de una ventana
  configurable en número de tramos.
- **FR-012**: La ventana de coherencia por defecto DEBE ser cero, es decir, la pasada desactivada,
  de forma que ningún análisis existente cambie de resultado.
- **FR-013**: Solo los bordes **medidos** DEBEN contar como evidencia en la vecindad. Un borde
  inferido nunca puede servir para inferir otro.
- **FR-014**: Si en la vecindad hay menos de dos bordes medidos, el tramo DEBE quedarse exactamente
  como estaba.
- **FR-015**: Un tramo sin borde propio cuya vecindad sí tiene evidencia suficiente DEBE recibir el
  valor representativo de esa vecindad, marcado como inferido.
- **FR-016**: Un tramo cuyo borde se aparta de su vecindad más de lo que la propia dispersión de
  esa vecindad admite DEBE sustituirse por el valor representativo y marcarse como inferido.
- **FR-017**: El umbral que decide si un borde se aparta demasiado DEBE derivarse de la dispersión
  medida en la vecindad, no de un parámetro configurable adicional, y DEBE tener un suelo mínimo
  tal que una desviación de hasta 0,30 m respecto del valor representativo nunca se considere
  atípica, por muy uniforme que sea la vecindad.
- **FR-018**: La pasada de coherencia DEBE poder aplicarse en ambos modos de detección.

#### Modelo de datos y trazabilidad

- **FR-019**: Cada tramo DEBE registrar, por lado, el origen de su borde: medido, inferido, o
  ninguno cuando no hay borde.
- **FR-020**: El motivo por lado DEBE conservar su significado actual —por qué no hay borde
  **medido** ahí—, de modo que un tramo pueda llevar a la vez un motivo, un origen inferido y una
  distancia al borde.
- **FR-021**: El sistema DEBE distinguir el estado de un tramo con ancho obtenido por completo de
  bordes medidos del de un tramo con ancho que depende de al menos un borde inferido.
- **FR-022**: El invariante del modelo de datos DEBE pasar a ser: existe ancho si y solo si el
  tramo tiene los dos bordes, con independencia del origen de cada uno.
- **FR-023**: La pendiente transversal DEBE calcularse también cuando algún borde es inferido, y el
  estado del tramo DEBE bastar para saber que su vano no está medido por completo.
- **FR-024**: Un análisis guardado antes de esta feature DEBE poder leerse sin migración de datos,
  interpretando como medido todo borde existente.

#### Parámetros

- **FR-025**: Los parámetros nuevos DEBEN ser tres: modo de detección de borde, tolerancia de
  separación de la superficie y ventana de coherencia.
- **FR-026**: Los tres DEBEN servirse junto con sus valores por defecto y rangos admitidos por el
  mismo mecanismo que ya publica el resto de parámetros, para que la interfaz no duplique
  constantes.
- **FR-027**: Los valores fuera de rango DEBEN rechazarse con un mensaje que indique el rango
  admitido, igual que los parámetros existentes.
- **FR-028**: El modo superficie NO DEBE introducir parámetros adicionales para el ajuste de la
  referencia de calzada.

#### Interfaz y exportación

- **FR-029**: El panel DEBE permitir elegir el modo de detección y ajustar los dos parámetros
  nuevos junto al resto de parámetros de cálculo.
- **FR-030**: Al elegir el modo superficie, la interfaz PUEDE proponer un valor de ventana de
  coherencia distinto de cero como conveniencia; esa propuesta NO DEBE ser una regla del servidor y
  el usuario DEBE poder cambiarla.
- **FR-031**: Al consultar un tramo, el sistema DEBE mostrar por lado la distancia al borde
  indicando si es inferida.
- **FR-032**: Los tramos con algún borde inferido DEBEN dibujarse en el mapa de forma distinguible
  tanto de los medidos por completo como de los que no tienen ancho.
- **FR-033**: Las exportaciones tabular y geoespacial DEBEN incluir el origen de cada borde y el
  modo de detección con el que se calculó el análisis.

### Key Entities

- **Modo de detección de borde**: criterio con el que se decide dónde termina la calzada. Dos
  valores: quiebre (pendiente local sostenida) y superficie (separación sostenida respecto de la
  referencia de calzada). Es un parámetro del análisis y viaja con él.
- **Referencia de calzada**: descripción de la superficie de la calzada dentro de un perfil
  transversal, obtenida de las propias muestras del tramo, que incorpora su pendiente transversal.
  Es interna al cálculo de un tramo; no se persiste.
- **Origen del borde**: por cada lado de cada tramo, de dónde procede la distancia reportada.
  Medido (hallado en el propio perfil del tramo), inferido (deducido de tramos vecinos) o ninguno.
- **Vecindad de coherencia**: conjunto de tramos contiguos, dentro de una ventana en número de
  tramos, cuyos bordes medidos sirven de evidencia para corregir el borde de un tramo.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En los tramos del caso de referencia que tienen bordillo a ambos lados —las
  progresivas 75–85 m y 115–130 m, verificadas sobre la ortofoto— los anchos reportados no superan
  0,25 m de desviación típica.
- **SC-002**: En los tramos donde uno de los lados carece físicamente de borde, el sistema no
  reporta ningún ancho. Medido sobre el caso de referencia: donde hoy se publica un ancho de
  10,55 m junto a vegetación y terreno suelto, no se publica ninguno.
- **SC-003**: Las distancias del eje al borde del lado que sí tiene bordillo no varían más de
  0,40 m de desviación típica a lo largo del trazado, frente a 1,29 m con el comportamiento actual.
- **SC-004**: Un análisis calculado con el modo por defecto y la coherencia desactivada produce
  valores idénticos, tramo a tramo, a los de la versión anterior de la herramienta.
- **SC-005**: Para cualquier tramo con ancho, el usuario puede determinar en menos de cinco
  segundos, desde el mapa o desde la exportación, si cada uno de sus dos bordes fue medido o
  inferido.
- **SC-006**: Una secuencia de diez o más tramos consecutivos sin borde en un lado no recibe ningún
  borde inferido, con cualquier ventana de coherencia admitida.
- **SC-007**: El tiempo de cálculo de un análisis en modo superficie no supera en más del 25 % al
  del mismo análisis en modo quiebre con los mismos parámetros.

## Assumptions

- El caso de referencia para validar la feature es la calle ya medida (`Polideportivo María Puebla
  Vásquez`, 27 tramos sobre DTM a 5 cm), y los caminos rurales ya validados (`Noria`,
  `ruta de zona 1`) son el caso de referencia para la no regresión.
- El usuario traza el eje a mano y este puede ir descentrado respecto de la calzada; el sistema debe
  tolerarlo, no exigir un eje centrado.
- Una tolerancia por defecto del orden de 6 cm separa un bordillo típico del ruido de un modelo de
  elevación fotogramétrico a 5 cm de resolución. Es un valor de partida ajustable por el usuario, no
  una constante física.
- Una ventana de coherencia de 2 tramos a cada lado es suficiente para cubrir un paso de peatones o
  un acceso rebajado sin alcanzar una discontinuidad real de la calle.
- El modo superficie puede rendir peor que el de quiebre en caminos rurales con cunetas suaves. No
  se ha medido, y por eso el defecto no cambia.
- Los tres motivos de "sin borde" existentes bastan para describir también los fallos del modo
  superficie, sin ampliar el contrato que consume la interfaz.

## Dependencies

- Se apoya por completo en la feature `005-road-metrics`: tramificación, muestreo del modelo de
  elevación, perfil transversal, persistencia, exportación y capa de mapa se reutilizan sin cambios
  estructurales.
- No introduce dependencias de terceros: el cálculo se resuelve con las librerías numéricas ya
  presentes en la imagen.
- No requiere cambios en el core de upstream ni en los plugins `annotations` y `realign`.

## Fuera de alcance

- Cualquier uso de la ortofoto o de clasificación radiométrica para hallar el borde.
- Ajuste global del borde como línea o curva a lo largo de todo el trazado, y cualquier forma de
  extrapolación más allá de la ventana corta de reparación local.
- Cambiar el detector por defecto, o alterar el resultado de análisis ya guardados.
- Detección automática del eje, o corrección automática de un eje descentrado.
- Clasificación del tipo de vía y evaluación de cumplimiento normativo.
- Edición manual de los bordes detectados.
