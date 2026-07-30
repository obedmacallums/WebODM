# Feature Specification: Capa de máscara del modelo de segmentación

**Feature Branch**: `008-segmentation-mask-layer`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: mostrar en el mapa la máscara de calzada que reconoció el modelo de
segmentación, como capa superpuesta a la ortofoto, para que el usuario pueda juzgar en qué se basó
la medición del modo `segmentation` del plugin `road` (`007-road-edge-segmentation`).

## Contexto y motivación

El modo `segmentation` de `007` mide el ancho de la calzada clasificando la ortofoto con un modelo
de IA en vez de buscar relieve en el DEM. Funciona, pero durante su validación midió anchos
sistemáticamente mayores que el modo `surface` en la misma calle: **+1,80 m de media, hasta +4,36 m
en un tramo**.

Durante un tiempo esa desviación se atribuyó, por escrito y sin comprobarlo, a que el modelo
"probablemente incluía la acera". Era falso. La causa real solo apareció cuando se rescató a mano el
fichero temporal de la máscara y se renderizó: el modelo estaba clasificando como calzada **un
descampado de tierra compactada entero**, contiguo a la vía, más zonas de tierra de un parque
vecino — el 25,3 % del corredor marcado como `road`.

El problema de fondo que esta feature resuelve no es estético: **la cifra que el plugin reporta es
hoy incontrastable desde la interfaz**. El usuario ve un ancho de 9,57 m y no dispone de ningún
medio para saber si el modelo midió la calle o un descampado. La única forma de averiguarlo fue una
inspección manual de desarrollador sobre un fichero temporal que nadie limpia y que se pierde.

Esta feature convierte esa inspección en algo que el usuario hace solo, mirando el mapa.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ver en qué se basó la medición (Priority: P1)

Un usuario ha corrido un análisis en modo `segmentation` sobre una calle y obtiene un ancho medio.
Quiere saber si ese número es creíble antes de usarlo. Activa la capa de máscara en el panel y ve,
superpuesto a la ortofoto, exactamente qué superficie consideró calzada el modelo. Si la mancha
cubre la calle, el número es creíble; si se derrama sobre un descampado, sabe que no debe fiarse.

**Why this priority**: es la feature entera. Sin esto el usuario no tiene forma de auditar un
resultado que ya sabemos que puede estar sesgado varios metros. Cualquier otra historia es
refinamiento sobre esta.

**Independent Test**: correr un análisis en modo `segmentation` sobre una tarea con ortofoto,
activar la capa, y comprobar que los polígonos dibujados coinciden con lo que el modelo clasificó
como calzada y no con otra cosa.

**Acceptance Scenarios**:

1. **Given** un análisis recién terminado en modo `segmentation`, **When** el usuario activa la
   capa de máscara, **Then** el mapa muestra superpuestas las zonas que el modelo clasificó como
   calzada, dentro del corredor analizado.
2. **Given** la capa de máscara activa, **When** el usuario la desactiva, **Then** desaparece del
   mapa sin afectar al eje ni a las reglas transversales de ancho.
3. **Given** un análisis en modo `break` o `surface`, **When** el usuario abre el panel, **Then**
   no se ofrece la capa de máscara, porque esos modos no producen ninguna.
4. **Given** una máscara visible que se derrama sobre una zona que no es calzada, **When** el
   usuario la compara con la ortofoto de fondo, **Then** puede identificar a simple vista que el
   modelo sobreclasificó, sin necesidad de herramientas externas.

---

### User Story 2 - Entender qué precisión tiene lo que ve (Priority: P2)

El usuario ve los polígonos de la máscara con bordes escalonados y quiere saber si eso es un
defecto del dibujo o el límite real del modelo. La interfaz se lo dice: la máscara viene a la
resolución del modelo, más gruesa que la ortofoto, y no debe leerse como un contorno preciso de la
calzada.

**Why this priority**: sin esto, la capa puede generar más confusión de la que resuelve — un usuario
podría medir sobre los polígonos creyendo que tienen la precisión de la ortofoto. Es necesario, pero
la capa aporta valor aunque este aviso llegue después.

**Independent Test**: activar la capa y comprobar que la interfaz comunica la limitación de
resolución sin que el usuario tenga que consultar documentación.

**Acceptance Scenarios**:

1. **Given** la capa de máscara activa, **When** el usuario busca entender su precisión, **Then**
   la interfaz indica que es una aproximación a la resolución del modelo y no un contorno exacto.
2. **Given** un usuario que hace zoom hasta el máximo, **When** los bordes escalonados se hacen
   evidentes, **Then** ese escalonado es coherente con la resolución anunciada y no una sorpresa.

---

### User Story 3 - Análisis antiguos sin máscara guardada (Priority: P3)

Un usuario abre un análisis de segmentación hecho antes de esta feature. Como entonces la máscara no
se guardaba, no hay nada que mostrar. La interfaz se lo explica y le ofrece la salida: recalcular.

**Why this priority**: afecta solo a los análisis ya existentes y tiene una salida trivial
(recalcular). Pero no puede quedar sin resolver: la alternativa sería una capa que aparece vacía sin
explicación, que es peor que no ofrecerla.

**Independent Test**: abrir un análisis de segmentación anterior a esta feature y comprobar que la
interfaz no miente — ni muestra una capa vacía como si fuera un resultado, ni falla.

**Acceptance Scenarios**:

1. **Given** un análisis en modo `segmentation` guardado antes de esta feature, **When** el usuario
   abre el panel, **Then** se le indica que ese análisis no tiene máscara guardada y que puede
   obtenerla recalculando.
2. **Given** ese mismo análisis, **When** el usuario lo recalcula, **Then** la máscara queda
   guardada y la capa pasa a estar disponible.

---

### Edge Cases

- **El modelo no encuentra ninguna calzada en el corredor.** La máscara existe pero está vacía. Ese
  caso debe distinguirse de "no hay máscara guardada": son cosas distintas y la segunda no es un
  resultado. Un corredor sin calzada detectada es información valiosa, porque explica por qué los
  tramos salieron sin borde.
- **El modelo clasifica casi todo el corredor como calzada.** Es el caso patológico que motiva la
  feature. La capa debe seguir siendo legible: si tapa por completo la ortofoto, el usuario no puede
  juzgar nada, que es precisamente lo que se quiere evitar.
- **La máscara se solapa con el eje y las reglas transversales.** El panel ya dibuja el eje
  coloreado por pendiente (verde/amarillo/rojo) y las reglas de ancho. La máscara no puede taparlos
  ni usar colores que se confundan con esa escala.
- **Corredor muy largo.** Un eje de cientos de metros produce más polígonos y más vértices que el
  caso de referencia de 66 m. El tamaño de lo guardado debe seguir siendo razonable.
- **La ortofoto de la tarea se borra o se regenera después del análisis.** La máscara guardada sigue
  siendo válida como registro de lo que el modelo vio entonces; no debe romperse ni desaparecer.
- **Se borra un análisis.** Su máscara debe irse con él, sin dejar ficheros huérfanos.

## Requirements *(mandatory)*

### Functional Requirements

**Generación y persistencia**

- **FR-001**: Al ejecutar un análisis en modo `segmentation`, el sistema DEBE guardar, junto al
  resultado del análisis, la máscara de calzada que produjo el modelo, en forma de geometrías
  vectoriales georreferenciadas.
- **FR-002**: La máscara persistida DEBE cubrir exactamente el corredor analizado (el eje ensanchado
  por el semiancho de búsqueda más su margen), ni más ni menos. No se segmenta la ortofoto completa.
- **FR-003**: El sistema DEBE guardar únicamente las geometrías de clase «calzada». Las de clase
  «no calzada» se descartan y no se persisten.
- **FR-004**: La máscara DEBE persistirse mediante el mismo mecanismo del framework que el plugin ya
  usa para los tramos de cada análisis, **nunca** en rutas ad-hoc del contenedor ni en directorios
  temporales. (Constitución, «Restricciones de infraestructura».)
- **FR-005**: La máscara DEBE quedar asociada al análisis concreto que la produjo, de modo que
  borrar el análisis borre también su máscara, sin dejar ficheros huérfanos.
- **FR-006**: Los modos `break` y `surface` NO DEBEN generar ni persistir máscara alguna, y su
  resultado no debe cambiar en nada respecto a `006`/`007`.

**Tamaño de lo guardado**

- **FR-007**: Antes de persistirla, el sistema DEBE simplificar las geometrías de la máscara con una
  tolerancia no más fina que la resolución de la propia máscara (~20 cm). Justificación: por debajo
  de esa resolución la máscara no contiene información real, así que simplificar hasta ahí no
  descarta nada — solo elimina vértices que no representan nada medido.
- **FR-008**: El sistema DEBE descartar los polígonos cuya superficie esté por debajo de un umbral
  mínimo, por corresponder a ruido de clasificación y no a calzada útil.
- **FR-009**: El tamaño de la máscara persistida DEBE crecer con la **longitud del corredor** y no
  con la resolución de la ortofoto, y mantenerse en decenas de KB — el mismo orden de magnitud que
  los datos de tramos que el plugin ya guarda por análisis (hoy 8,7–42 KB), sin dispararse a otro
  orden.

  > **Revisado el 2026-07-29 tras medir.** La primera redacción exigía quedar *dentro* de la banda
  > 8,7–42 KB. Al medir un corredor largo real (293 m) la máscara resultó de **76,9 KB**, casi el
  > doble del techo de esa banda, mientras que un corredor de 66 m da 19,5 KB. El requisito se
  > reescribe para reflejar lo medido en vez de mantener un límite que el diseño incumple: lo que
  > importa es que crezca de forma proporcional y acotada, no que quepa en una banda fijada antes de
  > tener datos. La independencia respecto al GSD de la ortofoto está comprobada: dos ortofotos de
  > 2,2 cm/px y 5 cm/px producen máscaras a 20 cm/px en ambos casos.

**Visualización**

- **FR-010**: Los usuarios DEBEN poder activar y desactivar la capa de máscara desde el panel del
  plugin, sin recargar la página y sin recalcular el análisis.
- **FR-011**: La capa DEBE dibujarse translúcida sobre la ortofoto, de manera que el usuario pueda
  ver a la vez lo que el modelo clasificó y la imagen real que hay debajo. Una capa opaca no cumple
  el propósito de la feature.
- **FR-012**: La capa NO DEBE usar los colores de la escala de pendiente del eje
  (verde/amarillo/rojo), para que no se confunda con ella.
- **FR-013**: La capa NO DEBE ocultar ni dificultar la lectura del eje ni de las reglas
  transversales de ancho que el panel ya dibuja.
- **FR-014**: La capa DEBE estar desactivada por defecto al abrir un análisis.
- **FR-015**: El control de la capa solo DEBE ofrecerse cuando el análisis mostrado tenga
  efectivamente una máscara guardada.

**Honestidad sobre lo que se muestra**

- **FR-016**: La interfaz DEBE comunicar que la máscara es una aproximación a la resolución del
  modelo (más gruesa que la ortofoto) y no un contorno preciso de la calzada.
- **FR-017**: El sistema DEBE distinguir en la interfaz tres situaciones que no son lo mismo: (a) el
  análisis tiene máscara con calzada detectada, (b) el análisis tiene máscara pero el modelo no
  detectó calzada, (c) el análisis no tiene máscara guardada por ser anterior a esta feature.
- **FR-018**: Para los análisis sin máscara guardada, la interfaz DEBE explicar por qué no la hay e
  indicar que recalcular el análisis la genera.

**Compatibilidad**

- **FR-019**: Los análisis ya guardados NO DEBEN alterarse ni invalidarse por esta feature; deben
  seguir abriéndose y mostrándose con normalidad.
- **FR-020**: Las exportaciones existentes (CSV y GeoJSON de descarga) NO DEBEN cambiar de formato
  ni incluir la máscara.

### Key Entities

- **Máscara de segmentación**: el conjunto de zonas que el modelo clasificó como calzada dentro del
  corredor de un análisis concreto. Es un registro de *lo que el modelo vio*, no una medición.
  Pertenece a un único análisis y desaparece con él. Tiene una resolución propia, más gruesa que la
  de la ortofoto, que forma parte de lo que hay que comunicar al usuario.
- **Análisis** (existente, de `006`/`007`): gana la posibilidad de tener una máscara asociada. Los
  análisis en modo `break` y `surface` nunca la tienen; los de modo `segmentation` la tienen si se
  calcularon después de esta feature.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Ante un resultado de segmentación sesgado, un usuario puede determinar si el modelo
  midió la calzada o sobreclasificó terreno adyacente **mirando solo el mapa**, sin abrir ficheros,
  sin herramientas externas y sin asistencia técnica. Hoy esto requiere una inspección manual de
  desarrollador sobre un fichero temporal.
- **SC-002**: Activar o desactivar la capa se refleja en el mapa de forma inmediata, sin recargar la
  página y sin volver a ejecutar el modelo.
- **SC-003**: La máscara guardada por análisis se mantiene en decenas de KB y no supera el doble del
  documento de tramos del mismo análisis. Medido: 19,5 KB para un corredor de 66 m (tramos: 13 KB) y
  76,9 KB para uno de 293 m (tramos: 42 KB).
- **SC-004**: Con la capa activa, el usuario sigue pudiendo leer la ortofoto de fondo y distinguir
  el eje y las reglas de ancho.
- **SC-005**: Ningún análisis existente cambia de resultado ni deja de abrirse tras esta feature.
- **SC-006**: Un usuario que abre un análisis de segmentación sin máscara guardada entiende por qué
  no la hay y qué hacer, sin que la interfaz muestre una capa vacía como si fuera un resultado.

## Assumptions

- **La máscara se genera solo con el análisis**, no bajo demanda ni con un botón aparte. Decidido
  con el usuario: la capa siempre corresponde exactamente a la medición que la acompaña, y no hay un
  camino que dispare el modelo sin medir.
- **Formato vectorial, no ráster.** Medido sobre el corredor de referencia: la librería de
  segmentación puede devolver directamente polígonos ya en coordenadas geográficas, y el visor de
  WebODM y el propio plugin ya dibujan geometrías vectoriales. Servir un ráster o generar teselas
  sería mucho más trabajo sin beneficio para este propósito.
- **La resolución de la máscara (~20 cm) se acepta tal cual.** Es el comportamiento por defecto del
  modelo, que se entrenó a esa escala. Forzarla más fina es técnicamente posible pero le presentaría
  al modelo formas a una escala distinta de la que aprendió, con degradación esperable. Queda fuera
  de alcance; lo que sí entra es *comunicar* esa resolución al usuario (FR-016).
- **El caso de referencia para dimensionar** es el corredor ya medido: eje de 66 m, 4 polígonos de
  calzada, 115 KB sin simplificar y 19,5 KB simplificados a 20 cm. Los corredores mucho más largos
  no se han medido; FR-009 fija el criterio en órdenes de magnitud precisamente por eso.
- **El sesgo del modelo no se corrige en esta feature.** Se hace visible. Corregirlo (o cambiar de
  modelo) sería otra feature con otras decisiones.

## Dependencies

- Depende de `007-road-edge-segmentation`: sin el modo `segmentation` no hay máscara que mostrar.
- Depende de que la tarea tenga ortofoto, igual que `007`.
- Reutiliza el corredor y la ejecución del modelo que `007` ya realiza; no introduce una segunda
  pasada del modelo ni una dependencia nueva.

## Fuera de alcance

- Servir la máscara como ráster o como teselas.
- Segmentar la ortofoto completa de la tarea.
- Mostrar máscara para los modos `break` y `surface` (no producen ninguna).
- Editar, corregir o recortar la máscara a mano.
- Incluir la máscara en las exportaciones CSV/GeoJSON existentes.
- Cambiar el criterio de detección de borde, los anchos medidos o el sesgo del modelo.
- Usar la máscara para algo que no sea mostrarla (por ejemplo, alimentar la detección de borde de
  otra forma, o calcular métricas nuevas a partir de su superficie).
- Generar automáticamente la máscara para análisis ya existentes; el usuario recalcula si la quiere.
