# Feature Specification: Etiquetado asistido por regiones en el plugin `training`

**Feature Branch**: `010-superpixel-labeling`

**Created**: 2026-07-31

**Status**: Draft

**Input**: User description: "Etiquetado asistido por superpíxeles en el plugin `training`. Añadir al
plugin `coreplugins/training` un modo de selección asistida que acelere el etiquetado manual sobre
la ortofoto, sin sustituir el criterio del usuario: la herramienta solo convierte su intención en un
contorno preciso, el humano sigue decidiendo qué es cada clase. Mecánica: se precalcula una
segmentación en superpíxeles (SLIC) por tesela, sobre el stack de 5 bandas `R, G, B, slope,
roughness` que `coreplugins/training/elevation.py` ya produce alineado a la rejilla de la tesela
(`read_aligned`, `tile_channels`). Un clic selecciona un superpíxel; el pincel existente, al
arrastrarse, pinta regiones enteras en vez de píxeles; un control de tolerancia hace crecer la
selección a superpíxeles vecinos parecidos recorriendo el grafo de adyacencia. El pincel de píxeles
actual sigue disponible para retocar donde el superpíxel se pase de listo."

## Contexto y motivación

La spec `009` entregó el etiquetado a mano: polígonos y un pincel de radio en metros sobre el
terreno. Funciona, pero la parte cara del trabajo no es **encontrar** la pista: es **trazar su borde
con precisión**. Un operador que marca varios kilómetros de caminos mineros pasa la mayor parte del
tiempo persiguiendo el canto de la calzada con el pincel, píxel a píxel, y el resultado depende de
su pulso y de su cansancio.

Esta feature ataca solo ese coste. La ortofoto se divide de antemano en **regiones homogéneas** cuyos
bordes ya coinciden con la estructura real del terreno; el usuario pincha una región y se le añade
entera, con su contorno exacto, en un gesto.

**Lo que esta feature NO es.** No clasifica, no predice y no propone etiquetas. La herramienta no
tiene opinión sobre qué es calzada: solo agrupa píxeles parecidos y espera a que el humano decida.
El pre-etiquetado automático desde un modelo entrenado ya está planificado como **fase 3 de la spec
`009`**, depende del store de modelos de la fase 2, y esta feature no lo adelanta ni lo sustituye.

Esa distinción no es una formalidad: gobierna el criterio de diseño. Una herramienta de asistencia a
la selección se juzga por su **predictibilidad**, no por su acierto. Si el mismo clic devuelve
resultados distintos entre sesiones, el operador deja de confiar en ella y vuelve al pincel, y el
esfuerzo se pierde entero.

### Por qué las regiones se calculan también con el terreno

El plugin ya produce, alineados a la rejilla de salida y medidos, dos canales derivados del DTM:
pendiente y rugosidad (`coreplugins/training/elevation.py`). La rugosidad es el RMS del residuo
respecto al plano local, que vale cero sobre cualquier rampa lisa por inclinada que esté.

Consecuencia para esta feature: **el canto de una superficie nivelada por maquinaria contra el
terreno natural es un borde real en el canal de rugosidad aunque sea invisible en color**. Calcular
las regiones sobre color *más* terreno pone la frontera donde está, no donde el color sugiere.

Importante: esto es una mejora de la calidad del borde, no un requisito de viabilidad. Si en un
terreno concreto los canales de elevación no aportan nada —o la tarea no tiene DTM—, la feature
sigue funcionando solo con color. No hay ningún experimento que tenga que salir bien para que esto
sea útil.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Seleccionar una región de un clic (Priority: P1)

Un usuario está etiquetando la ortofoto de una tarea. Activa el modo de selección asistida en la
barra de herramientas, elige la clase `road` y pincha sobre la calzada. La región homogénea bajo el
cursor se añade entera a esa clase, con su contorno siguiendo el borde real de la calzada, sin que
él haya tenido que trazarlo.

**Why this priority**: es la feature entera reducida a su mínimo. Si solo se entrega esto, el
usuario ya ahorra el trabajo de trazar bordes, que es el objetivo. Todo lo demás son multiplicadores
de este gesto.

**Independent Test**: activar el modo, pinchar sobre una calzada en la ortofoto, comprobar que
aparece una etiqueta nueva de la clase activa cuyo contorno sigue el borde visible; recargar la
página y comprobar que sigue ahí.

**Acceptance Scenarios**:

1. **Given** una tarea con ortofoto y un dataset con clases definidas, **When** el usuario activa el
   modo de selección asistida y pincha sobre la ortofoto, **Then** se crea una etiqueta de la clase
   activa que cubre la región homogénea bajo el cursor.
2. **Given** una región ya seleccionada, **When** el usuario vuelve a pinchar exactamente en el
   mismo punto del terreno, **Then** el resultado es idéntico al anterior (misma geometría), sin
   duplicar la etiqueta.
3. **Given** el usuario ha pinchado una región, **When** recarga la página, **Then** la etiqueta
   sigue presente con la misma geometría y la misma clase.
4. **Given** el usuario ha seleccionado una región que se pasa del borde real en un tramo, **When**
   usa el borrador o el pincel de píxeles sobre ese tramo, **Then** puede corregirlo sin deshacer el
   resto de la selección.
5. **Given** el usuario pincha fuera de la huella del vuelo (zona sin datos de la ortofoto),
   **When** se procesa el clic, **Then** no se crea ninguna etiqueta y el sistema lo comunica sin
   error.

---

### User Story 2 - Pintar varias regiones arrastrando (Priority: P2)

El usuario mantiene pulsado y arrastra sobre la ortofoto como haría con el pincel. En vez de pintar
píxeles, va añadiendo enteras todas las regiones que toca. Recorre una pista de punta a punta en un
gesto continuo y la calzada queda marcada con sus bordes exactos.

**Why this priority**: convierte el ahorro de un clic en el ahorro de una sesión. Es el gesto que ya
tiene aprendido de la fase 1, aplicado a un objeto más grande, así que no cuesta aprendizaje nuevo.

**Independent Test**: activar el modo, arrastrar el cursor a lo largo de una pista, comprobar que
todas las regiones tocadas quedan etiquetadas con la clase activa y que el contorno resultante sigue
el borde de la calzada.

**Acceptance Scenarios**:

1. **Given** el modo de selección asistida activo, **When** el usuario arrastra el cursor sobre
   varias regiones contiguas, **Then** todas quedan asignadas a la clase activa.
2. **Given** un arrastre en curso, **When** el usuario suelta, **Then** el resultado equivale a
   haber pinchado una a una las mismas regiones.
3. **Given** un arrastre que pasa parcialmente por una región, **When** el cursor la toca aunque sea
   brevemente, **Then** la región se añade entera y no parcialmente.

---

### User Story 3 - Extender la selección a lo parecido (Priority: P3)

El usuario pincha una vez sobre un descampado grande y, con un control de tolerancia, hace que la
selección se extienda a las regiones vecinas que se le parecen. Una superficie amplia y uniforme
queda marcada sin recorrerla entera.

**Why this priority**: resuelve el caso contrario al de la pista estrecha —áreas grandes y
uniformes, donde ir región por región sería tedioso—. Es una mejora clara, pero el trabajo funciona
sin ella.

**Independent Test**: pinchar en el centro de un área uniforme con la tolerancia al mínimo (solo una
región) y luego subirla progresivamente, comprobando que la selección crece de forma continua y
monótona, y que se detiene al llegar a un borde marcado.

**Acceptance Scenarios**:

1. **Given** la tolerancia en su valor mínimo, **When** el usuario pincha, **Then** se selecciona
   exactamente una región.
2. **Given** una tolerancia mayor, **When** el usuario pincha en un área uniforme, **Then** la
   selección incluye las regiones vecinas parecidas y se detiene en el borde con las que no lo son.
3. **Given** dos valores de tolerancia A < B, **When** se pincha el mismo punto con cada uno,
   **Then** la selección obtenida con A está contenida en la obtenida con B.
4. **Given** una tolerancia alta sobre un terreno muy uniforme, **When** la extensión alcanzaría un
   área desproporcionada, **Then** el crecimiento se detiene en un límite conocido y el sistema
   avisa de que se alcanzó.

---

### User Story 4 - Ajustar la asistencia al terreno (Priority: P4)

El usuario trabaja sobre una tarea donde el relieve no aporta nada —o directamente no tiene modelo
de terreno—. Baja el peso de los canales de elevación hasta anularlos y sigue etiquetando con las
regiones calculadas solo por color, sin cambiar de herramienta.

**Why this priority**: es la garantía de que la feature no depende de que el terreno coopere.
Protege la inversión, pero el flujo principal ya funciona con los valores por defecto.

**Independent Test**: etiquetar una zona con el peso de elevación por defecto, anularlo, repetir en
la misma zona y comprobar que la herramienta sigue produciendo regiones utilizables.

**Acceptance Scenarios**:

1. **Given** una tarea sin modelo de terreno disponible, **When** el usuario activa el modo de
   selección asistida, **Then** la herramienta funciona con color únicamente y comunica que los
   canales de terreno no están disponibles.
2. **Given** una tarea con modelo de terreno, **When** el usuario anula el peso de los canales de
   elevación, **Then** las regiones se recalculan solo con color y el cambio es visible.
3. **Given** un ajuste de pesos elegido por el usuario, **When** vuelve al dataset en otra sesión,
   **Then** encuentra el mismo ajuste que dejó.

---

### Edge Cases

- **Tarea sin DTM ni DSM**: la herramienta funciona con color y lo comunica; no es un error (US4).
- **Continuidad entre unidades internas de proceso**: el usuario percibe la ortofoto como una
  superficie continua. Ninguna región puede terminar en un borde recto artificial que corresponda a
  una división interna de procesamiento en vez de a un rasgo del terreno.
- **Invariancia al viewport**: la región que produce un clic no puede depender del zoom, del encuadre
  ni del momento en que se pinchó. Pinchar el mismo punto del terreno desde dos encuadres distintos
  debe dar la misma geometría.
- **Zona sin datos de la ortofoto**: pinchar fuera de la huella del vuelo no crea etiqueta y se
  comunica al usuario.
- **Región que solapa una etiqueta existente**: se comporta igual que el pincel actual al dibujar
  sobre una etiqueta ya presente; esta feature no introduce una regla nueva.
- **Lo no etiquetado sigue siendo «sin etiquetar»**: la herramienta nunca convierte terreno no
  marcado en clase de fondo. La invariante de `009` (255 = sin etiquetar, distinto de la clase 0) se
  mantiene intacta.
- **Región demasiado grande para lo que el usuario quería**: siempre puede retocar con el borrador y
  el pincel de píxeles sin perder el resto (US1, escenario 4).
- **Primera vez sobre una zona nueva**: el cálculo de las regiones de una zona no vista antes tarda
  más que un clic posterior sobre la misma zona; el usuario debe saber que está ocurriendo.
- **Ortofotos de resolución nativa muy distinta**: el trabajo ocurre a la resolución del dataset, así
  que el tamaño de las regiones sobre el terreno es comparable entre tareas de 2,2 cm/px y 6,35 cm/px.
- **Cambio de los ajustes con etiquetas ya creadas**: cambiar granularidad, tolerancia o pesos no
  altera ninguna etiqueta ya guardada; solo afecta a las selecciones siguientes.
- **Memoria del contenedor**: el proceso no puede superar el presupuesto de memoria disponible
  (~1 GB) por muy grande que sea la ortofoto.

## Requirements *(mandatory)*

### Functional Requirements

#### Modo y gesto

- **FR-001**: El sistema DEBE ofrecer la selección asistida como un modo más de la barra de
  herramientas de etiquetado, junto a polígono, pincel y borrador.
- **FR-002**: El sistema NO DEBE usar `Shift` como modificador para esta feature; esa tecla ya está
  asignada en el plugin a la selección múltiple de etiquetas y al marcado de vértices.
- **FR-003**: Los usuarios DEBEN poder añadir la región bajo el cursor a la clase activa con un solo
  clic (US1).
- **FR-004**: Los usuarios DEBEN poder añadir varias regiones en un gesto continuo de arrastre (US2).
- **FR-005**: El sistema DEBE añadir siempre la región completa, nunca una fracción de ella, aunque
  el cursor solo la haya tocado parcialmente.
- **FR-006**: Los modos de polígono, pincel de píxeles y borrador DEBEN seguir disponibles y sin
  cambios de comportamiento, para poder retocar lo que la asistencia deje mal.

#### Predictibilidad

- **FR-007**: El sistema DEBE ser determinista: pinchar el mismo punto del terreno con los mismos
  ajustes DEBE producir siempre la misma geometría, entre clics, entre sesiones y entre usuarios.
- **FR-008**: El resultado de un clic NO DEBE depender del zoom, del encuadre del mapa ni del orden
  en que se hayan hecho los clics anteriores.
- **FR-009**: Las regiones NO DEBEN presentar bordes rectos artificiales originados en divisiones
  internas de procesamiento; los bordes deben corresponder a rasgos del terreno.

#### Cálculo de las regiones

- **FR-010**: El sistema DEBE calcular las regiones a partir del color de la ortofoto y, cuando estén
  disponibles, de los canales derivados del modelo de terreno que el plugin ya produce.
- **FR-011**: El sistema DEBE funcionar con color únicamente cuando la tarea no tenga modelo de
  terreno, comunicándolo al usuario sin tratarlo como error (US4).
- **FR-012**: Los usuarios DEBEN poder ajustar el peso de los canales de terreno, incluido anularlo
  por completo (US4).
- **FR-013**: Los usuarios DEBEN poder ajustar la granularidad de las regiones (más regiones
  pequeñas frente a menos regiones grandes).
- **FR-014**: El sistema DEBE trabajar a la resolución de trabajo del dataset, no a la resolución
  nativa de cada ortofoto, para que el tamaño de las regiones sobre el terreno sea comparable entre
  tareas.
- **FR-015**: El sistema DEBE calcular las regiones por porciones acotadas y bajo demanda, sin
  requerir en ningún momento tener la ortofoto entera en memoria.

#### Extensión por tolerancia

- **FR-016**: Los usuarios DEBEN poder extender la selección desde la región pinchada a las regiones
  vecinas parecidas, con un control de tolerancia (US3).
- **FR-017**: La extensión DEBE ser monótona respecto a la tolerancia: a mayor tolerancia, una
  selección que contenga a la de menor tolerancia.
- **FR-018**: La extensión DEBE detenerse en un límite de superficie conocido, y el sistema DEBE
  avisar cuando lo alcance.

#### Persistencia y salida

- **FR-019**: El sistema DEBE guardar el resultado como etiquetas georreferenciadas, por el mismo
  camino y en el mismo formato que las que produce el pincel y el polígono actuales.
- **FR-020**: El sistema NO DEBE introducir un formato de etiqueta nuevo ni modificar el contrato del
  paquete exportado (`specs/009-training-dataset-labeling/contracts/dataset-package.md`).
- **FR-021**: El sistema DEBE preservar la invariante de `009`: lo no etiquetado permanece «sin
  etiquetar» y nunca se convierte en clase de fondo.
- **FR-022**: El sistema DEBE conservar los ajustes del usuario (granularidad, tolerancia, pesos)
  entre sesiones, asociados al dataset.
- **FR-023**: Cambiar cualquiera de esos ajustes NO DEBE alterar las etiquetas ya guardadas.

#### Comunicación con el usuario

- **FR-024**: El sistema DEBE indicar al usuario cuándo está preparando una zona nueva y cuándo está
  listo para responder a los clics.
- **FR-025**: El sistema DEBE comunicar de forma clara y accionable los casos en que un clic no
  produce selección (fuera de la huella del vuelo, zona sin datos).
- **FR-026**: El sistema DEBE poder deshabilitarse sin afectar al resto del etiquetado del plugin
  (Principio III de la constitución).

### Key Entities

- **Región asistida**: agrupación de píxeles contiguos y homogéneos de la ortofoto, calculada a
  partir del color y de los canales de terreno. Es la unidad mínima que un clic añade. No tiene
  clase propia: la clase se la da el usuario al seleccionarla.
- **Mapa de regiones**: partición completa de una porción acotada de la ortofoto en regiones
  asistidas. Es reproducible: los mismos datos y ajustes producen el mismo mapa.
- **Ajustes de asistencia**: granularidad de las regiones, tolerancia de extensión y peso de los
  canales de terreno. Pertenecen al dataset y sobreviven a la sesión.
- **Etiqueta**: entidad ya existente de `009`. Esta feature es una forma nueva de producirlas, no una
  entidad nueva.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Etiquetar una pista de tierra de ~100 m lleva **menos de la mitad de tiempo** con la
  selección asistida que con el pincel de píxeles, medido sobre la misma pista y con el mismo
  operador.
- **SC-002**: El **100 %** de los clics repetidos sobre el mismo punto del terreno, con los mismos
  ajustes, producen geometrías idénticas — incluidos los hechos desde encuadres y niveles de zoom
  distintos, en sesiones distintas.
- **SC-003**: Tras el primer clic en una zona, los clics siguientes en esa misma zona devuelven la
  región **sin espera perceptible** para el usuario (por debajo del umbral en el que una interacción
  deja de sentirse inmediata).
- **SC-004**: La preparación de una zona nueva termina en **menos de 5 segundos**, con el usuario
  informado de que está ocurriendo.
- **SC-005**: En una pista de ~100 m, **menos del 20 %** de las regiones seleccionadas necesitan
  retoque posterior con el pincel de píxeles o el borrador.
- **SC-006**: La feature es utilizable sobre una tarea **sin modelo de terreno**, completando el
  mismo recorrido de etiquetado que una tarea que sí lo tiene.
- **SC-007**: El proceso completa el etiquetado de la ortofoto más grande del usuario **sin superar
  el presupuesto de memoria disponible del contenedor** (~1 GB) ni provocar reinicios.
- **SC-008**: Las etiquetas producidas por la selección asistida se exportan en el paquete del
  dataset **sin ninguna diferencia de formato** respecto a las producidas con pincel o polígono.

## Assumptions

- **El etiquetado ocurre a la resolución de trabajo del dataset** (10 cm/px por defecto), igual que
  el resto del plugin. Las regiones se calculan a esa escala.
- **Cada clic escribe inmediatamente**, como el pincel actual: no hay una selección pendiente que el
  usuario deba confirmar con un paso extra. Corregir se hace con el borrador, que ya existe.
- **Las regiones se calculan bajo demanda** para la zona en la que el usuario está trabajando, no
  para la ortofoto entera por adelantado. Es lo único compatible con el presupuesto de memoria y con
  el hecho de que el usuario rara vez etiqueta la ortofoto completa.
- **La unidad interna de proceso no es la tesela de exportación.** Las teselas de exportación se
  solapan por diseño (`009`, D20), lo que haría que un mismo píxel cayera en varias con resultados
  potencialmente distintos y rompería FR-007. Esta feature necesita una partición sin solape y
  anclada de forma determinista.
- **Se reutiliza `coreplugins/training/elevation.py` tal cual** para los canales de terreno: ya
  entrega el DTM remuestreado a la rejilla de destino —corrigiendo el desalineo de 0,6 px medido
  entre ortofoto y DTM— más pendiente y rugosidad, con la técnica de halo que evita materializar el
  stack completo en memoria.
- **La comparación de tiempos de SC-001 usa como base el pincel de píxeles**, no el polígono. La
  medición de pincel frente a polígono es la tarea T055 de `009`, todavía pendiente, y es
  independiente de esta.
- **Dependencia nueva**: la partición en regiones requiere una librería de procesamiento de imagen
  que hoy no está en la imagen (`scikit-image`). Entra por el paso 1 de la escalera del Principio IV
  —`requirements.txt` del plugin, wheel disponible para la arquitectura del contenedor, sin rebuild
  de imagen—. Queda pendiente de evaluar **después del prototipo** si conviene implementar la
  partición directamente sobre las librerías ya presentes para soltar la dependencia; la decisión se
  toma con el prototipo medido delante, no antes.
- **Sin cambios en el core de upstream** (Principio I) ni en el contrato de exportación del dataset.
- **Alcance excluido**: cualquier forma de clasificación, predicción o propuesta automática de
  etiquetas. Eso es la fase 3 de `009` y depende del store de modelos de la fase 2.
