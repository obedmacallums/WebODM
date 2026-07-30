# Feature Specification: Detección de borde por segmentación semántica de la ortofoto

**Feature Branch**: `007-road-edge-segmentation`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Añadir un tercer criterio de detección de borde al plugin `road`, junto a `break` y `surface`
(006-street-width), basado en clasificación semántica de la ortofoto en vez de en el modelo de
elevación.

Los dos criterios actuales comparten una limitación de fondo: ambos buscan el borde como algo que
se nota en el DEM, ya sea como escalón sostenido (`break`) o como fin de una superficie plana
(`surface`). El propio spec de 006 lo deja como límite conocido y no resuelto en "Edge Cases":
"Calzada que se funde con el terreno: una vía sin bordillo ni talud nunca se aparta de su
referencia y se reporta sin borde". Eso pasa en calzadas donde el límite es solo un cambio de
textura o color —asfalto contra grava, pintura de carril, tierra compactada contra vegetación— sin
ningún relieve físico. Ahí ningún criterio basado en elevación puede funcionar porque no hay señal
que medir; hace falta una fuente de información distinta.

Se propone un tercer modo que use el modelo de segmentación semántica `roads` de la librería
`geodeep` (https://github.com/uav4geo/GeoDeep), la misma librería que ya usa el plugin `objdetect`
para detección de objetos (`coreplugins/objdetect/api.py`), con el mismo patrón de import diferido,
manejo de `ImportError` si la librería no está instalada, y caché de modelos en
`MEDIA_CACHE/detection_models`. A diferencia de `objdetect`, aquí no se usaría `geodeep.detect`
(cajas delimitadoras) sino `geodeep.segment`, que clasifica cada píxel de la ortofoto en las clases
`road` / `not_road` y admite salida como máscara ráster georreferenciada o como polígonos GeoJSON.

Datos conocidos del modelo, tomados de la documentación de GeoDeep, que la spec debe tratar como
restricciones reales y no como detalles de implementación a ignorar: resolución nativa de
entrenamiento 21 cm/px, muy por encima de los 5 cm de GSD habituales en las ortofotos de dron de
este proyecto; modelo marcado como `experimental`, entrenado sobre imágenes de Google Earth, no
sobre ortofotos de dron, con peor desempeño esperable en calles estrechas o con sombra; salida como
clasificación binaria por píxel, no como medida continua.

Integración con lo ya construido en 006: el plugin ya tiene un perfil transversal por tramo y un
enum `edge_mode` con valores `break` y `surface`. El nuevo criterio debe encajar en ese mismo
mecanismo de selección de modo, panel de parámetros y trazabilidad de origen del borde (medido /
inferido / ninguno) sin romper ninguno de los dos modos existentes ni tocar sus resultados.

A diferencia de 006, esta feature SÍ depende de la ortofoto: es un insumo nuevo para el plugin
`road`. Fuera de alcance: entrenar o reentrenar el modelo; cualquier otro modelo de `geodeep` que no
sea `roads`; combinar la señal de segmentación con el DEM en un único criterio; cambiar el modo de
detección por defecto (`break`) o el resultado de análisis ya guardados; edición manual del borde
detectado; exponer al usuario ningún parámetro propio del modelo de IA más allá de lo estrictamente
necesario para que el criterio sea usable."

## Convención de referencias

Los requisitos de la feature `006-street-width` se citan como `006/FR-0xx` para no confundirlos con
la numeración propia de esta spec, que empieza de nuevo en `FR-001`. Por transitividad, `006` ya
cita a `005-road-metrics` como `005/FR-0xx`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Medir el ancho de una calle cuyo borde no tiene relieve (Priority: P1)

Un usuario tiene una calle donde la calzada termina en un cambio de textura —asfalto contra
grava, o contra tierra compactada— sin bordillo ni talud. Ha probado los modos "quiebre" y
"superficie" y en esos tramos ninguno de los dos encuentra borde, porque físicamente no hay ningún
escalón ni cambio de pendiente que buscar en el modelo de elevación. Cambia el modo de detección a
**segmentación**, relanza el análisis, y en esos tramos el sistema ahora reconoce dónde termina la
calzada a partir de la ortofoto.

**Why this priority**: es el motivo de existir de la feature. Sin esto, hay calles que ningún modo
de detección de `006` puede medir, con independencia de la calidad del modelo de elevación.

**Independent Test**: se puede probar de principio a fin lanzando un análisis en modo segmentación
sobre un tramo cuyo borde es solo un cambio de textura en la ortofoto y comprobando que el sistema
reporta un ancho, cosa que los otros dos modos no consiguen sobre el mismo tramo.

**Acceptance Scenarios**:

1. **Given** un eje trazado sobre una calle cuyo borde no presenta ningún escalón ni cambio de
   pendiente en el modelo de elevación, pero sí un cambio de textura visible en la ortofoto,
   **When** el usuario lanza el análisis en modo segmentación, **Then** el tramo reporta un ancho.
2. **Given** ese mismo tramo, **When** se analiza en modo quiebre o en modo superficie, **Then**
   el tramo se reporta sin borde, evidenciando que el modo segmentación cubre un caso que los otros
   dos no cubren.
3. **Given** un tramo con bordillo real, medible en modo superficie, **When** se analiza también en
   modo segmentación, **Then** el sistema no exige que ambos modos coincidan exactamente en la
   distancia al borde: son criterios distintos y se documenta como tal.

---

### User Story 2 - No recibir un borde donde la ortofoto no permite reconocer la calzada (Priority: P2)

El modelo de segmentación no encuentra una clasificación de calzada clara en algunos tramos: la
sombra de un edificio o de arbolado cubre la vía, o la calle es tan estrecha que el modelo la
confunde con el entorno. El usuario espera que esos tramos se reporten sin borde, no con un número
que aparenta ser correcto y no lo es.

**Why this priority**: es la misma exigencia que ya estableció `006/FR-022` ("nada se rellena, nada
se estima con lo que haya") para los otros dos modos; extenderla es lo que hace aceptable añadir un
tercer modo basado en un modelo experimental.

**Independent Test**: se prueba analizando en modo segmentación un tramo cuya ortofoto no permite
distinguir la calzada del entorno y comprobando que ese tramo no reporta ancho, con un motivo
identificable por lado.

**Acceptance Scenarios**:

1. **Given** un tramo cuya ortofoto no cubre la zona del eje, **When** se analiza en modo
   segmentación, **Then** el tramo no reporta ancho y el motivo indica la falta de ortofoto.
2. **Given** un tramo con ortofoto disponible pero donde el modelo no clasifica ningún píxel como
   calzada dentro del área de búsqueda, **When** se analiza en modo segmentación, **Then** el tramo
   no reporta ancho, con el mismo tratamiento que "sin quiebre dentro del área de búsqueda" en los
   otros modos.
3. **Given** una tarea sin la librería de segmentación instalada o sin poder descargar el modelo,
   **When** el usuario intenta analizar en modo segmentación, **Then** recibe un mensaje de error
   claro que identifica la causa, y los modos quiebre y superficie de esa misma tarea siguen
   funcionando con normalidad.

---

### User Story 3 - Saber que un borde viene del criterio de segmentación (Priority: P3)

El usuario consulta un tramo y ve un ancho. Necesita saber, tanto en pantalla como en la
exportación, que ese número se obtuvo con el criterio de segmentación y no con quiebre o
superficie, porque son criterios con una fiabilidad distinta y quiere poder filtrar o revisar según
el modo usado.

**Why this priority**: sin esto el usuario no puede aplicar el juicio distinto que merece un
criterio basado en un modelo experimental, ni distinguir sus resultados de los de los modos ya
validados sobre el terreno.

**Independent Test**: se prueba consultando y exportando un análisis calculado en modo segmentación
y comprobando que el modo usado se identifica igual de bien que ya lo hace `006/FR-003` para
quiebre y superficie, sin mecanismo adicional.

**Acceptance Scenarios**:

1. **Given** un análisis calculado en modo segmentación, **When** el usuario lo consulta o lo
   exporta, **Then** el modo de detección queda identificado, reutilizando el mismo campo que ya
   distingue quiebre de superficie.
2. **Given** un análisis con tramos de origen mixto por la pasada de coherencia (`006/FR-019` a
   `FR-021`), **When** se consulta un tramo con un borde inferido a partir de vecinos medidos en
   modo segmentación, **Then** el origen (medido/inferido) se distingue igual que ya ocurre para
   los otros dos modos.

---

### User Story 4 - Que los modos existentes sigan exactamente igual (Priority: P4)

El usuario tiene análisis ya calculados en modo quiebre o superficie. Tras la actualización, los
reabre y los recalcula con los mismos parámetros, y obtiene exactamente los mismos números que
antes; el nuevo modo no aparece a menos que lo elija.

**Why this priority**: `006/FR-002` ya estableció esta garantía para el modo superficie frente al
de quiebre; añadir un tercer modo no puede debilitarla.

**Independent Test**: se prueba recalculando un análisis existente en modo quiebre o superficie con
sus parámetros originales y comparando tramo a tramo con el resultado anterior a esta feature.

**Acceptance Scenarios**:

1. **Given** un análisis existente en modo quiebre o superficie, **When** se recalcula sin cambiar
   ningún parámetro, **Then** todos los tramos reportan valores idénticos a los anteriores.
2. **Given** cualquier tarea, **When** el usuario no elige explícitamente el modo segmentación,
   **Then** el comportamiento del análisis es indistinguible del que tenía antes de esta feature.

---

### Edge Cases

- **Ortofoto ausente o sin cobertura sobre el tramo**: el tramo se reporta sin borde con un motivo
  identificable, igual que hoy ocurre por falta de modelo de elevación.
- **Librería o modelo de segmentación no disponibles**: el intento de analizar en modo segmentación
  falla con un mensaje claro; no afecta a los modos quiebre ni superficie de la misma tarea.
- **La calzada real es más estrecha que la resolución del modelo puede distinguir**: el modelo
  puede no reconocer ninguna franja de calzada, o reconocerla más ancha o más estrecha de lo real;
  es un límite conocido del método que debe quedar documentado, no resuelto.
- **Manchas de "calzada" desconectadas de la calle real**: aparcamientos, patios o superficies
  pavimentadas cercanas al eje que el modelo también clasifica como calzada pueden hacer que el
  borde detectado se escape más allá de la calle real. Es un límite conocido, no resuelto por esta
  feature.
- **Sombra densa de edificios o arbolado sobre la calzada**: puede impedir que el modelo reconozca
  la calzada bajo la sombra; el tramo se reporta sin borde en ese lado.
- **Vecindad con el modo quiebre o superficie**: la pasada de coherencia entre tramos (`006/FR-011`
  a `FR-018`) no distingue de qué modo salió cada borde medido; un tramo en modo segmentación puede
  heredar evidencia de vecinos calculados en el mismo modo, nunca de un modo distinto porque cada
  análisis usa un único modo para todo el trazado.
- **El usuario cierra el panel o cambia de tarea mientras la etapa de segmentación está en curso**:
  sin cambios de comportamiento respecto de hoy — el análisis sigue en el candado de ejecución del
  servidor hasta terminar, fallar o cancelarse explícitamente, con independencia de si el panel que
  lo lanzó sigue abierto.

## Requirements *(mandatory)*

### Functional Requirements

#### Modo de detección

- **FR-001**: El sistema DEBE ofrecer un tercer modo de detección de borde, **segmentación**,
  seleccionable junto a los modos **quiebre** y **superficie** ya existentes (`006/FR-001`), sin
  alterar el comportamiento de ninguno de los dos.
- **FR-002**: El modo por defecto DEBE seguir siendo **quiebre** (`006/FR-002`); el modo
  segmentación nunca se activa sin una elección explícita del usuario.
- **FR-003**: El modo elegido DEBE quedar registrado junto al análisis con el mismo mecanismo que ya
  distingue quiebre de superficie (`006/FR-003`), de forma que consultarlo o exportarlo diga con qué
  criterio se obtuvieron sus bordes.
- **FR-004**: Un valor de modo no admitido DEBE rechazarse con un mensaje que enumere los valores
  válidos, igual que `006/FR-004`.

#### Criterio de segmentación

- **FR-005**: En modo segmentación, el sistema DEBE clasificar la zona de la ortofoto alrededor del
  eje del tramo en calzada / no-calzada mediante un modelo de segmentación semántica preentrenado.
- **FR-006**: El borde de cada lado DEBE ser el primer punto, avanzando desde el eje hacia afuera,
  donde la clasificación deja de ser calzada y permanece así durante el número mínimo de muestras
  consecutivas ya existente (`006/FR-006`), para que el resto del sistema no tenga que distinguir de
  qué modo salió un borde salvo por su origen.
- **FR-007**: Cuando la tarea no tenga ortofoto disponible, la ortofoto no cubra la zona del eje del
  tramo, o el modelo de segmentación no esté disponible, el sistema DEBE reportar el tramo sin borde
  con un motivo **nuevo y único** —distinto de los tres ya existentes de `006`
  (`no_break`, `no_data`, `break_at_axis`)— que indique que falta la fuente de datos de
  segmentación, sin distinguir entre ausencia de ortofoto y ausencia de modelo.
- **FR-008**: El sistema DEBE ejecutar la segmentación sobre el corredor de la ortofoto cercano al
  eje trazado completo, recortado con un margen suficiente para cubrir el semiancho de búsqueda de
  todos los tramos del eje, con el mismo patrón de recorte que ya usa `objdetect` cuando hay `crop`,
  en lugar de sobre la ortofoto completa de la tarea, antes de detectar los bordes de cada tramo.
- **FR-009**: El sistema DEBE ejecutar la etapa de segmentación dentro del mismo análisis en segundo
  plano con seguimiento de progreso y cancelación que ya usan hoy los modos quiebre y superficie —el
  plugin `road` ya ejecuta todo análisis de forma asíncrona—, informando el avance de la segmentación
  por el mismo canal de progreso que ya reporta el resto del cálculo, en vez de quedar como un tramo
  ciego sin informar mientras el modelo de IA corre. No se introduce un mecanismo de segundo plano
  nuevo ni distinto del que ya tiene el plugin.
- **FR-010**: La pendiente transversal del tramo en modo segmentación DEBE calcularse sobre las
  muestras de elevación comprendidas entre los dos bordes hallados por segmentación, con el mismo
  criterio que ya usa el modo superficie (`006/FR-009`), de forma que el dato de pendiente no
  dependa de una fuente distinta según el modo.

#### Integración con lo existente

- **FR-011**: La pasada de coherencia entre tramos (`006/FR-011` a `FR-018`) DEBE poder aplicarse
  también al modo segmentación, con la misma ventana configurable y las mismas reglas: solo los
  bordes medidos cuentan como evidencia, y un borde inferido nunca sirve para inferir otro.
- **FR-012**: El modelo de datos de origen del borde por lado —medido, inferido, o ninguno—
  (`006/FR-019` a `FR-022`) DEBE aplicarse sin cambios al modo segmentación: un borde hallado
  directamente por el modelo de segmentación cuenta como medido.
- **FR-013**: Un análisis guardado antes de esta feature DEBE poder leerse sin migración de datos,
  igual que ya garantiza `006/FR-024`; el modo segmentación es una opción nueva, no un cambio de
  significado de los análisis existentes.

#### Parámetros

- **FR-014**: El modo segmentación DEBE quedar disponible por el mismo mecanismo de publicación de
  parámetros y valores por defecto que ya usan el resto de opciones del análisis (`006/FR-026`), sin
  que la interfaz duplique constantes.
- **FR-015**: El modo segmentación NO DEBE exponer al usuario parámetros propios del modelo de IA
  (umbral de confianza, resolución de inferencia u otros) más allá de lo estrictamente necesario
  para que el criterio sea usable. En consecuencia, el modo segmentación no añade ningún parámetro
  nuevo específico de sí mismo: reutiliza únicamente los parámetros ya compartidos entre modos.
- **FR-015a**: Cuando el usuario elige el modo segmentación, el sistema NO DEBE mostrar ni permitir
  editar los parámetros que solo tienen sentido en otro modo —el umbral de quiebre
  (`break_threshold`, propio de quiebre) y la tolerancia de separación (`surface_tolerance`, propia
  de superficie)—, con el mismo mecanismo que ya restringe cada uno de esos dos parámetros a su
  propio modo y que oculta el uno cuando el otro modo está activo.
- **FR-015b**: Los parámetros que no son propios de ningún modo en particular —longitud de tramo,
  semiancho de búsqueda, número mínimo de muestras consecutivas, ventana de coherencia, suavizado
  del perfil de elevación, separación entre transversales y agregación del ancho— DEBEN seguir
  disponibles y editables en modo segmentación exactamente igual que en los otros dos modos. El
  suavizado del perfil de elevación no interviene en cómo el modo segmentación decide el borde
  (`FR-006`), pero sigue interviniendo en el cálculo de la pendiente transversal (`FR-010`), que se
  deriva de elevación en los tres modos.

#### Interfaz y exportación

- **FR-016**: El panel DEBE permitir elegir el modo segmentación junto a los otros dos, con el mismo
  control que ya selecciona entre quiebre y superficie.
- **FR-016a**: Mientras dura la etapa de segmentación (`FR-009`), el indicador de progreso que el
  panel ya muestra para cualquier análisis en curso DEBE reflejar ese avance igual que refleja el
  del resto del cálculo, sin quedar detenido ni en blanco mientras el modelo de IA corre.
- **FR-017**: Al consultar un tramo calculado en modo segmentación, el sistema DEBE mostrar por lado
  la distancia al borde y si es inferida, con el mismo tratamiento que ya aplican quiebre y
  superficie (`006/FR-031`).
- **FR-018**: Las exportaciones tabular y geoespacial DEBEN incluir el modo segmentación como un
  valor más del campo de modo de detección ya existente (`006/FR-033`), sin columnas ni atributos
  adicionales específicos de este modo.

### Key Entities

- **Modo de detección de borde (ampliado)**: pasa a tener tres valores: quiebre (pendiente local
  sostenida), superficie (separación sostenida respecto de la referencia de calzada) y segmentación
  (clasificación semántica de la ortofoto). Sigue siendo un parámetro del análisis que viaja con él.
- **Clasificación de calzada**: resultado interno de aplicar el modelo de segmentación a la zona de
  la ortofoto en torno al eje de un tramo, que distingue calzada de no-calzada. Es interno al
  cálculo del tramo; no se persiste, igual que la referencia de calzada del modo superficie.
- **Origen del borde**: sin cambios respecto de `006` — medido, inferido o ninguno — aplicado ahora
  también a los bordes que produce el modo segmentación.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En un tramo cuyo borde es solo un cambio de textura sin relieve, el usuario obtiene un
  ancho en modo segmentación en un caso donde ni el modo quiebre ni el modo superficie lo consiguen
  sobre el mismo tramo.
- **SC-002**: En un tramo donde la ortofoto no permite reconocer la calzada (sin cobertura, sombra
  total, o ausencia total de clasificación de calzada), el sistema no publica ningún ancho.
- **SC-003**: Un análisis calculado en modo quiebre o en modo superficie produce, tras esta feature,
  valores idénticos tramo a tramo a los que producía antes de que existiera el modo segmentación.
- **SC-004**: Para cualquier tramo con ancho, el usuario puede determinar en menos de cinco segundos,
  desde el mapa o desde la exportación, con qué modo de detección se calculó, igual que ya puede
  hacerlo hoy entre quiebre y superficie.
- **SC-005**: Mientras el sistema calcula un análisis en modo segmentación, el usuario nunca queda
  varios minutos sin ninguna señal de que el sistema sigue trabajando.

## Assumptions

- El modelo `roads` de la librería `geodeep` no cambia de nombre ni de clases (`road` / `not_road`)
  durante el desarrollo de esta feature.
- El modelo se descarga y cachea la primera vez que se usa, con el mismo mecanismo de caché en
  `MEDIA_CACHE` que ya usa `objdetect`.
- Si la librería `geodeep` no está instalada en el entorno, el modo segmentación falla con un
  mensaje claro que identifica la causa, sin afectar a los modos quiebre ni superficie de la misma
  tarea, con el mismo patrón que ya usa `objdetect.api.detect()` ante `ImportError`.
- La resolución a la que se ejecuta el modelo de segmentación es la que gestiona internamente la
  propia librería `geodeep`; no se fuerza a la resolución nativa de la ortofoto como requisito de
  esta feature.
- El caso de referencia para validar esta feature con datos reales queda pendiente de una tarea con
  una calle cuyo borde carezca de relieve pero tenga un cambio de textura reconocible en la
  ortofoto; a diferencia de `006`, no hay todavía una medición real de partida.
- El modo segmentación puede rendir peor que quiebre o superficie fuera del dominio de entrenamiento
  del modelo (imágenes de Google Earth, calles anchas). No se ha medido, y por eso convive como
  opción explícita en vez de sustituir a los modos existentes.

## Dependencies

- Se apoya por completo en `006-street-width`: reutiliza el mecanismo de selección de `edge_mode`,
  el perfil transversal por tramo, el panel de parámetros, la pasada de coherencia entre tramos y el
  modelo de datos de origen del borde (medido/inferido/ninguno), sin cambios estructurales en
  ninguno de ellos.
- Depende transitivamente de `005-road-metrics` a través de `006`.
- Introduce una dependencia de terceros nueva para el plugin `road`: la librería `geodeep`, ya usada
  por el plugin `objdetect` (`coreplugins/objdetect/api.py`). Sigue la escalera de dependencias del
  Principio IV de la constitución del proyecto.
- Requiere que la tarea tenga una ortofoto generada (`orthophoto.tif`), a diferencia de `006`, que
  solo requiere DSM o DTM.

## Fuera de alcance

- Entrenar o reentrenar el modelo de segmentación.
- Cualquier otro modelo de `geodeep` que no sea `roads`.
- Combinar la señal de segmentación con el modelo de elevación en un único criterio de borde.
- Cambiar el modo de detección por defecto (`break`), o alterar el resultado de análisis ya
  guardados.
- Detección automática del eje, o corrección automática de un eje descentrado.
- Edición manual de los bordes detectados.
- Exponer parámetros propios del modelo de IA (umbral de confianza, resolución de inferencia, etc.)
  más allá de lo estrictamente necesario para que el criterio sea usable.
- Mejorar el desempeño del modelo fuera de su dominio de entrenamiento (calles estrechas, sombra
  densa): se documenta como límite conocido, no como algo que esta feature deba resolver.
