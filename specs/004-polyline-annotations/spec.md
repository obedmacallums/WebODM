# Feature Specification: Polilíneas anotadas sobre el mapa 2D, planas o sobre el terreno

**Feature Branch**: `004-polyline-annotations`

**Created**: 2026-07-26

**Status**: Draft

**Input**: User description: "Crear un plugin nuevo `annotations` que permita al usuario dibujar polilíneas sobre el mapa 2D de una tarea, eligiendo si la línea es plana (2D) o si sigue el relieve del terreno tomando la elevación del modelo de elevación de la tarea (3D), y guardarlas de forma permanente para editarlas, exportarlas y dejarlas disponibles para que otros plugins las consuman como geometría de entrada. Motivación: varias herramientas del fork necesitan que el usuario indique una línea sobre el terreno (un perfil, un eje, un recorrido, un límite). Unas veces basta con el trazado en planta y otras la línea solo es útil si lleva elevación, porque sin Z no se puede calcular una longitud real ni nada que dependa del relieve. Hoy cada plugin tendría que resolver el dibujo y el muestreo del DEM por su cuenta, y las geometrías se perderían al recargar la página. Esta feature centraliza ese trabajo una sola vez y deja la decisión de 'con o sin elevación' en manos del usuario. El usuario elige el modo al crear la línea, con un valor por defecto sensato según lo que la tarea tenga disponible, y puede cambiarlo después sobre una línea ya guardada en ambos sentidos. En el modo sobre el terreno el sistema muestrea el modelo de elevación y obtiene la cota de cada vértice dibujado y una versión densificada de la línea al paso de la resolución del modelo, de la que se derivan la longitud real sobre el terreno y el desnivel acumulado. El usuario elige entre DSM y DTM entre los disponibles, y la elección queda registrada. Las polilíneas se persisten asociadas a la tarea, son compartidas entre los usuarios con acceso, aparecen en el control de capas nativo de WebODM, se exportan a GeoJSON y quedan disponibles para otros plugins mediante un contrato versionado. Fuera de alcance: otras geometrías, la gráfica del perfil, el visor 3D, importación desde archivo, formatos distintos de GeoJSON, estilado, áreas y volúmenes, interacción con realign y edición concurrente en tiempo real."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Trazar y conservar una polilínea sobre el mapa (Priority: P1)

Un usuario abre el mapa 2D de una tarea procesada y necesita dejar marcado un recorrido sobre la
ortofoto: el eje de un camino, el límite de una parcela, la traza de una zanja. Activa la
herramienta de polilíneas, hace click en sucesivos puntos del mapa siguiendo el rasgo que le
interesa, termina el trazado de forma explícita y le pone un nombre. La línea queda dibujada sobre
el mapa y listada junto a las demás capas. Al día siguiente vuelve a abrir la misma tarea desde
otro navegador y la línea sigue ahí, igual que la dejó.

**Why this priority**: es el MVP y la base de todo lo demás. Sin trazado y persistencia no hay nada
que elevar, exportar ni consumir desde otro plugin. Una polilínea plana que sobrevive a la sesión ya
tiene valor por sí sola como anotación del proyecto.

**Independent Test**: sobre una tarea con ortofoto, trazar una polilínea de varios vértices,
nombrarla, recargar la página y comprobar que reaparece con la misma geometría y el mismo nombre;
comprobar también que otro usuario con acceso a la tarea la ve.

**Acceptance Scenarios**:

1. **Given** una tarea procesada con productos visibles en el mapa 2D, **When** el usuario activa la
   herramienta y hace click en tres puntos del mapa y finaliza el trazado, **Then** la polilínea
   queda dibujada sobre el mapa y se le pide un nombre.
2. **Given** una polilínea recién trazada, **When** el usuario la guarda con un nombre, **Then**
   aparece en la lista de polilíneas de la tarea junto con su longitud.
3. **Given** una polilínea guardada, **When** el usuario recarga la página, **Then** la polilínea se
   vuelve a dibujar con la misma geometría, el mismo nombre y el mismo modo.
4. **Given** una polilínea guardada por un usuario, **When** otro usuario con acceso a la misma
   tarea abre el mapa, **Then** ve la misma polilínea.
5. **Given** un trazado en curso con un solo vértice, **When** el usuario intenta finalizarlo,
   **Then** el sistema no lo guarda y explica que hacen falta al menos dos vértices.
6. **Given** una polilínea guardada, **When** se elimina la tarea a la que pertenece, **Then** la
   polilínea se elimina también y no queda ningún dato huérfano.
7. **Given** un mapa que muestra varias tareas a la vez, **When** el usuario busca la herramienta de
   trazado, **Then** no está disponible y el sistema explica que debe abrir el mapa de una sola tarea
   para poder trazar, mientras las polilíneas ya guardadas siguen viéndose.

---

### User Story 2 - Obtener la línea con la elevación del terreno (Priority: P2)

El mismo usuario necesita que la línea que acaba de trazar sirva para algo más que marcar una
posición: quiere saber cuánto mide realmente sobre el terreno, no en el plano, y quiere que la
geometría lleve cotas para poder usarla después. Al crear la línea elige el modo "sobre el terreno" y
selecciona si quiere la superficie (DSM) o el suelo desnudo (DTM). El sistema toma las cotas del
modelo de elevación de la tarea y le muestra la longitud sobre el terreno junto a la longitud en
planta y el desnivel acumulado del recorrido.

**Why this priority**: es lo que convierte la anotación en un dato de trabajo. La mayoría de los usos
previstos (perfiles, ejes, recorridos) carecen de sentido sin elevación. Se separa de la P1 porque
una tarea sin modelo de elevación debe seguir pudiendo usar la herramienta.

**Independent Test**: sobre una tarea con DSM, trazar una línea que cruce un desnivel conocido en
modo sobre el terreno y comprobar que la longitud sobre el terreno es mayor que la longitud en planta
en una proporción coherente con el desnivel, y que las cotas de los vértices coinciden con las que da
una herramienta GIS externa sobre el mismo modelo.

**Acceptance Scenarios**:

1. **Given** una tarea con DSM y DTM disponibles, **When** el usuario crea una polilínea en modo
   sobre el terreno, **Then** puede elegir cuál de los dos modelos usar y la elección queda
   registrada junto a la línea.
2. **Given** una tarea con un solo modelo de elevación disponible, **When** el usuario crea una
   polilínea en modo sobre el terreno, **Then** el sistema usa ese modelo sin preguntar y lo deja
   registrado.
3. **Given** una polilínea en modo sobre el terreno sobre un relieve accidentado, **When** el sistema
   termina de calcularla, **Then** muestra la longitud sobre el terreno, la longitud en planta y el
   desnivel acumulado, en las unidades configuradas por el usuario en WebODM.
4. **Given** una polilínea en modo sobre el terreno cuyos vértices están muy separados, **When** el
   sistema calcula la longitud sobre el terreno, **Then** el cálculo tiene en cuenta el relieve
   intermedio entre vértices y no una interpolación en línea recta entre sus cotas.
5. **Given** una tarea sin DSM ni DTM, **When** el usuario crea una polilínea, **Then** el modo sobre
   el terreno no está disponible y el sistema explica por qué, permitiendo continuar en modo plano.
6. **Given** una polilínea en modo sobre el terreno, **When** el sistema la guarda, **Then** quedan
   registrados qué modelo se usó, cuándo se muestreó y en qué unidad vertical están las cotas.
7. **Given** un trazado que sale del área cubierta por el modelo de elevación o cruza un hueco sin
   dato, **When** el usuario intenta guardarlo en modo sobre el terreno, **Then** el sistema no lo
   guarda en ese modo, le señala qué tramo del recorrido carece de dato y le ofrece guardarlo en modo
   plano o corregir el trazado, sin rellenar ninguna cota.

---

### User Story 3 - Exportar las polilíneas para usarlas fuera de WebODM (Priority: P3)

El usuario ha marcado varias líneas sobre la tarea y necesita llevárselas a su software habitual: las
abre en QGIS para cruzarlas con otra cartografía, o se las pasa a un colega. Descarga las polilíneas
de la tarea en un archivo y comprueba que conserva los nombres, las longitudes y, en las que la
tienen, la elevación.

**Why this priority**: cierra el ciclo de valor para el usuario final. Hasta aquí la información vive
dentro de WebODM; la exportación es lo que la hace utilizable en el resto del flujo de trabajo. Va
después de la elevación porque exportar líneas sin cotas tiene una utilidad mucho menor.

**Independent Test**: con una tarea que tenga al menos una polilínea plana y una sobre el terreno,
descargar el archivo, abrirlo en QGIS y verificar que aparecen ambas, con sus nombres y con cotas en
la que corresponde.

**Acceptance Scenarios**:

1. **Given** una tarea con polilíneas guardadas de ambos modos, **When** el usuario pide la
   descarga, **Then** obtiene un archivo GeoJSON que contiene todas ellas.
2. **Given** el archivo exportado, **When** se abre en QGIS, **Then** se carga sin errores, las
   geometrías caen en su posición correcta y las líneas sobre el terreno conservan sus cotas.
3. **Given** una polilínea exportada, **When** se inspeccionan sus atributos, **Then** incluyen el
   nombre, el modo, la longitud en planta y, cuando aplique, la longitud sobre el terreno, el
   desnivel acumulado y el modelo de elevación utilizado.
4. **Given** una polilínea en modo sobre el terreno, **When** el usuario la exporta, **Then** puede
   elegir entre exportar solo los vértices que dibujó o la versión densificada que sigue el relieve.
5. **Given** una tarea con polilíneas, **When** el usuario usa el botón de exportar del panel de
   anotaciones de WebODM, **Then** obtiene el mismo resultado que desde la herramienta del plugin.

---

### User Story 4 - Corregir y reorganizar lo ya trazado (Priority: P4)

Al revisar el trabajo el usuario ve que una línea se desvía del camino en un tramo, que otra necesita
un vértice más para seguir una curva, y que una que trazó plana debería llevar elevación. Ajusta los
vértices arrastrándolos, añade uno intermedio, borra el que sobra, renombra la línea y convierte la
plana en una sobre el terreno sin volver a dibujarla. Todas las magnitudes se actualizan solas.

**Why this priority**: es refinamiento sobre capacidades ya entregadas. Sin esto la herramienta sirve,
pero obliga a borrar y redibujar ante cualquier error; con volúmenes reales de trabajo eso se vuelve
inasumible.

**Independent Test**: sobre una polilínea guardada en modo sobre el terreno, mover un vértice a una
zona de cota claramente distinta y comprobar que la longitud sobre el terreno y el desnivel acumulado
cambian en consecuencia; convertir una línea plana a sobre el terreno y comprobar que adquiere cotas
conservando exactamente el mismo trazado en planta.

**Acceptance Scenarios**:

1. **Given** una polilínea guardada, **When** el usuario mueve uno de sus vértices, **Then** la
   geometría se actualiza y las longitudes se recalculan.
2. **Given** una polilínea guardada, **When** el usuario inserta un vértice intermedio o elimina uno
   existente, **Then** la geometría y las longitudes se actualizan, y la operación se rechaza si
   dejaría la línea con menos de dos vértices.
3. **Given** una polilínea en modo sobre el terreno, **When** el usuario modifica su geometría,
   **Then** las cotas se vuelven a muestrear para el trazado nuevo.
4. **Given** una polilínea plana, **When** el usuario la convierte a modo sobre el terreno, **Then**
   adquiere cotas sin que cambie su trazado en planta.
5. **Given** una polilínea en modo sobre el terreno, **When** el usuario la convierte a plana,
   **Then** conserva su trazado y deja de reportar magnitudes derivadas de la elevación.
6. **Given** una polilínea guardada, **When** el usuario la renombra o la elimina desde el panel de
   capas de WebODM, **Then** el cambio se refleja en el mapa y persiste tras recargar.
7. **Given** una tarea reprocesada cuyo modelo de elevación ha cambiado, **When** el usuario consulta
   una polilínea sobre el terreno muestreada antes del reproceso, **Then** el sistema indica que las
   cotas corresponden a un muestreo anterior y le permite volver a muestrear.
8. **Given** una polilínea plana cuyo trazado sale de la cobertura del modelo de elevación, **When**
   el usuario intenta convertirla a modo sobre el terreno, **Then** la conversión no se realiza y el
   sistema le señala qué tramo carece de dato.

---

### User Story 5 - Reutilizar las polilíneas desde otro plugin (Priority: P5)

Un desarrollador del fork construye un plugin nuevo que necesita una línea de entrada trazada por el
usuario —por ejemplo, para calcular un perfil longitudinal—. En lugar de implementar su propio
dibujo y su propio muestreo del modelo de elevación, pide las polilíneas de la tarea y recibe
geometría lista para usar, sabiendo de cada una si lleva elevación y de qué modelo salió. Si el
usuario la trazó plana, puede pedir que se eleve sin obligarle a redibujarla.

**Why this priority**: es la razón estratégica de la feature, pero no aporta valor observable hasta
que exista el primer plugin consumidor. Se apoya íntegramente en lo construido en las historias
anteriores; lo que se añade aquí es un contrato estable, documentado y versionado.

**Independent Test**: escribir un consumidor mínimo de prueba que pida las polilíneas de una tarea y
verifique que recibe los vértices, la versión densificada y los metadatos de elevación, y que puede
solicitar la elevación de una línea plana sin duplicarla.

**Acceptance Scenarios**:

1. **Given** una tarea con polilíneas de ambos modos, **When** otro plugin pide sus polilíneas,
   **Then** las recibe todas, cada una declarando si lleva elevación y, si la lleva, contra qué
   modelo y en qué momento se muestreó.
2. **Given** una polilínea en modo sobre el terreno, **When** un plugin consumidor la solicita,
   **Then** recibe tanto los vértices dibujados como la versión densificada que sigue el relieve, sin
   tener que muestrear el modelo de elevación por su cuenta.
3. **Given** una polilínea plana, **When** un plugin consumidor necesita elevación sobre ella,
   **Then** puede solicitar que se eleve y obtiene el resultado sin que se cree una polilínea
   duplicada ni se pida al usuario redibujarla.
4. **Given** un consumidor escrito contra la versión actual del contrato, **When** el contrato se
   amplía en el futuro, **Then** el consumidor sigue funcionando porque el contrato está versionado.

---

### Edge Cases

- **Trazado degenerado**: un solo vértice, o dos vértices en la misma posición. El sistema rechaza el
  guardado explicando el motivo, sin dejar geometría inválida almacenada.
- **Nombre vacío o repetido**: si el usuario no escribe nombre, el sistema asigna uno por defecto
  distinguible; los nombres repetidos se permiten pero cada polilínea sigue siendo identificable de
  forma independiente.
- **Vértices fuera de la cobertura del modelo de elevación** en modo sobre el terreno: parte del
  recorrido cae fuera del área cubierta por el DSM/DTM.
- **Huecos (nodata) en el modelo** bajo parte del recorrido: el modelo existe y cubre la zona, pero
  no tiene dato en algunos puntos. En este caso y en el anterior el modo sobre el terreno se rechaza
  señalando el tramo afectado, y el usuario decide entre guardar en plano o corregir el trazado;
  nunca se rellenan las cotas que faltan.
- **Tarea sin modelo de elevación**: el modo sobre el terreno no se ofrece; la herramienta sigue
  siendo utilizable en modo plano.
- **Línea desproporcionada**: un recorrido tan largo o con tantos vértices que el muestreo dejaría de
  ser inmediato. El sistema aplica un límite definido y comunicado, y la interfaz nunca queda
  bloqueada sin respuesta ni fallando en silencio.
- **Modelo de elevación cambiado por un reproceso**: las cotas guardadas ya no corresponden al modelo
  actual de la tarea.
- **Mapa con varias tareas simultáneas**: las polilíneas existentes se muestran agrupadas por la tarea
  a la que pertenecen, pero crear o modificar geometría no está disponible en esa vista; el sistema lo
  explica en lugar de ofrecer una herramienta que no podría atribuir la línea a una tarea concreta.
- **Usuario sin permiso de edición sobre la tarea**: puede ver las polilíneas y exportarlas, pero las
  acciones que las modifican no están disponibles.
- **Edición simultánea**: dos usuarios editan la misma polilínea a la vez. El resultado debe ser
  predecible y explicable, sin corromper la geometría almacenada.
- **Cota igual a cero legítima**: un terreno a nivel del mar produce cotas de valor cero, que no deben
  confundirse con la ausencia de dato.

## Requirements *(mandatory)*

### Functional Requirements

**Trazado y ciclo de vida**

- **FR-001**: El sistema MUST permitir al usuario activar una herramienta de trazado desde el mapa 2D
  de una tarea y crear una polilínea marcando vértices sucesivos, con una acción explícita para
  finalizar el trazado.
- **FR-002**: El sistema MUST rechazar el guardado de polilíneas con menos de dos vértices distintos,
  explicando el motivo al usuario.
- **FR-003**: El sistema MUST permitir asignar un nombre a la polilínea al guardarla, y MUST asignar
  un nombre por defecto distinguible cuando el usuario no proporcione ninguno.
- **FR-004**: Los usuarios MUST poder modificar la geometría de una polilínea guardada moviendo
  vértices, insertando vértices intermedios y eliminando vértices, sin redibujarla por completo.
- **FR-005**: Los usuarios MUST poder renombrar y eliminar una polilínea guardada.
- **FR-006**: El sistema MUST mostrar la longitud del trazado mientras el usuario dibuja, expresada
  en el sistema de unidades configurado por el usuario en WebODM.

**Modos plano y sobre el terreno**

- **FR-007**: Cada polilínea MUST tener exactamente uno de dos modos: plana (sin elevación) o sobre el
  terreno (con elevación tomada del modelo de elevación de la tarea).
- **FR-008**: El modo plano MUST estar disponible siempre, incluso en tareas sin modelo de elevación.
- **FR-009**: El modo sobre el terreno MUST ofrecerse únicamente cuando la tarea tenga al menos un
  modelo de elevación disponible; cuando no lo tenga, el sistema MUST explicar por qué no está
  disponible en lugar de presentar una opción inoperante.
- **FR-010** *(revisado, contrato v2)*: El usuario MUST elegir el modo **antes** de trazar, mediante
  controles de creación separados y rotulados como 2D (plana) y 3D (sobre el terreno). El control de
  3D MUST quedar inoperante y explicado cuando la tarea no tenga modelo de elevación.
- **FR-011** *(revisado, contrato v2)*: El modo de una polilínea MUST quedar fijado al crearla y
  MUST NOT poder cambiarse después. Para obtener el otro tipo, el usuario traza una nueva. *(Antes:
  conversión en ambos sentidos mediante elevar/aplanar.)*
- **FR-012**: El sistema MUST mostrar el modo de cada polilínea en su listado, de forma que el usuario
  distinga sin abrirlas cuáles llevan elevación.

**Elevación**

- **FR-013**: En modo sobre el terreno, el sistema MUST obtener la cota de cada vértice dibujado a
  partir del modelo de elevación seleccionado.
- **FR-014**: En modo sobre el terreno, el sistema MUST generar una versión densificada de la línea,
  con puntos intermedios a un paso de densificación determinado, de modo que la geometría siga el
  relieve entre vértices en lugar de interpolar en línea recta entre sus cotas. El paso MUST tener un
  valor por defecto derivado de la resolución del modelo de elevación pero acotado inferiormente, y
  MUST poder ajustarlo el usuario.
- **FR-015**: El sistema MUST calcular y mostrar, para cada polilínea sobre el terreno, la longitud
  sobre el terreno (derivada de la versión densificada), la longitud en planta y el desnivel
  acumulado, en las unidades configuradas por el usuario. La longitud sobre el terreno y el desnivel
  acumulado MUST presentarse siempre acompañados del paso de densificación con el que se
  calcularon, porque su valor depende de él.
- **FR-016**: Cuando la tarea tenga más de un modelo de elevación disponible, el usuario MUST poder
  elegir entre el modelo de superficie (DSM) y el del terreno (DTM); cuando solo haya uno, el sistema
  MUST usarlo sin preguntar.
- **FR-017**: El sistema MUST registrar, junto a cada polilínea sobre el terreno, qué modelo de
  elevación se usó, con qué paso de densificación se calcularon sus magnitudes, en qué momento se
  realizó el muestreo y en qué unidad vertical están las cotas.
- **FR-018**: El sistema MUST reportar las cotas tal como figuran en el modelo de elevación, sin
  aplicar conversiones de datum vertical.
- **FR-019**: El sistema MUST volver a muestrear la elevación y recalcular las magnitudes derivadas
  cuando cambie la geometría de una polilínea sobre el terreno.
- **FR-020** *(revisado, contrato v2)*: El sistema MUST advertir al usuario cuando las cotas de una
  polilínea provengan de un muestreo anterior al modelo de elevación actual de la tarea. *(Antes
  incluía además una acción de volver a muestrear a demanda; se retiró junto con la conversión de
  tipos. El re-muestreo sigue ocurriendo solo, al editar la geometría — FR-019.)*
- **FR-021**: El sistema MUST NOT almacenar ni presentar valores de relleno (como cero) como si fueran
  cotas medidas; la ausencia de dato MUST ser distinguible de una cota legítima de valor cero.
- **FR-022**: El modo sobre el terreno MUST exigir cobertura completa de elevación a lo largo de todo
  el recorrido. Cuando alguna parte caiga fuera del área cubierta por el modelo o sobre huecos sin
  dato, el sistema MUST rechazar el guardado en ese modo, MUST indicar al usuario qué parte del
  recorrido está afectada y MUST ofrecerle como alternativas guardar la polilínea en modo plano o
  ajustar el trazado. El sistema MUST NOT estimar, interpolar ni rellenar de ninguna forma las cotas
  que falten.
- **FR-023**: El sistema MUST aplicar un límite definido al tamaño de las polilíneas que puede
  muestrear (en número de vértices y en número de puntos densificados), MUST comunicarlo al usuario
  cuando lo alcance, y MUST mantener la interfaz utilizable durante el cálculo, sin bloqueos ni
  esperas sin realimentación.

**Persistencia**

- **FR-024**: El sistema MUST conservar las polilíneas asociadas a su tarea, de forma que sobrevivan a
  recargas de página, cierres de sesión y reinicios del servidor.
- **FR-025**: Las polilíneas de una tarea MUST ser visibles para todos los usuarios con acceso a esa
  tarea, y editables por quienes tengan permiso de edición sobre ella, con el mismo criterio de
  permisos que aplica el plugin de realineación.
- **FR-026**: El sistema MUST almacenar las coordenadas en WGS84 (EPSG:4326), incorporando la altura
  como tercera coordenada en las polilíneas que la tengan.
- **FR-027**: El sistema MUST eliminar las polilíneas de una tarea cuando la tarea se elimine, sin
  dejar datos huérfanos.

**Integración con el control de capas**

- **FR-028**: Cada polilínea guardada MUST aparecer en el panel de capas del mapa, dentro del grupo de
  anotaciones que WebODM ya provee, identificada por su nombre.
- **FR-029**: El sistema MUST responder correctamente a todas las acciones que ese panel ofrece sobre
  una anotación: mostrar y ocultar, encuadrar el mapa sobre ella, renombrar y eliminar; ninguna de
  esas acciones puede quedarse sin efecto.
- **FR-030**: Cuando el mapa muestre varias tareas a la vez, el sistema MUST presentar las polilíneas
  agrupadas bajo la tarea a la que pertenecen.
- **FR-031**: El sistema MUST asociar cada polilínea nueva a una única tarea de forma no ambigua: las
  herramientas de creación y de modificación de la geometría MUST ofrecerse únicamente cuando el mapa
  muestre una sola tarea, y cuando muestre varias el sistema MUST explicar por qué no están
  disponibles. Con varias tareas en el mapa, las polilíneas ya guardadas MUST seguir mostrándose y
  MUST permanecer disponibles las acciones que no dependen de resolver a qué tarea pertenece la
  línea: mostrar y ocultar, encuadrar, renombrar, eliminar y exportar.

**Exportación**

- **FR-032** *(revisado, contrato v2)*: Los usuarios MUST poder descargar en GeoJSON **la polilínea
  que seleccionen** desde la herramienta del plugin, y el nombre del archivo MUST indicar su tipo
  (`2d`/`3d`). El botón de exportación del panel de anotaciones de WebODM sigue descargando el grupo
  completo en un solo archivo, sin sufijo por mezclar ambos tipos. *(Antes: ambas vías descargaban
  todas las polilíneas y debían dar el mismo resultado.)*
- **FR-033**: El archivo exportado MUST incluir, por cada polilínea, su nombre, su modo, su longitud
  en planta y —cuando sea sobre el terreno— su longitud sobre el terreno, su desnivel acumulado y el
  modelo de elevación utilizado.
- **FR-034**: Para las polilíneas sobre el terreno, el usuario MUST poder elegir entre exportar
  únicamente los vértices dibujados o la versión densificada que sigue el relieve.
- **FR-035**: El archivo exportado MUST abrirse sin errores en herramientas GIS de escritorio de uso
  común, conservando la posición de las geometrías y las cotas de las polilíneas que las tengan.

**Contrato para otros plugins**

- **FR-036**: El sistema MUST ofrecer una vía documentada para que otro plugin obtenga las polilíneas
  de una tarea, utilizable tanto desde el backend como desde el frontend.
- **FR-037**: Ese contrato MUST indicar, por cada polilínea, si lleva elevación y, en tal caso, contra
  qué modelo y en qué momento se muestreó.
- **FR-038**: Ese contrato MUST entregar, para las polilíneas sobre el terreno, tanto los vértices
  dibujados como la versión densificada, de forma que un consumidor no necesite muestrear el modelo
  de elevación por su cuenta.
- **FR-039** *(retirado, contrato v2)*: ~~Un plugin consumidor MUST poder solicitar la elevación de
  una polilínea plana existente sin que se genere una polilínea duplicada ni se requiera que el
  usuario la redibuje.~~ El tipo es inmutable desde v2, así que el contrato ya no eleva nada: un
  consumidor que necesite cotas trabaja con las polilíneas 3D existentes (FR-038).
- **FR-040**: El contrato MUST estar versionado, de modo que pueda ampliarse posteriormente sin
  romper a los consumidores ya escritos.

### Key Entities

- **Polilínea**: recorrido trazado por un usuario sobre el mapa 2D de una tarea. Atributos: nombre,
  modo (plana o sobre el terreno), secuencia ordenada de vértices en coordenadas geográficas,
  longitud en planta, autoría y momento de creación y de última modificación. Pertenece a exactamente
  una tarea.
- **Muestreo de elevación**: información asociada a una polilínea en modo sobre el terreno. Atributos:
  modelo de elevación utilizado (superficie o terreno), momento del muestreo, unidad vertical de
  origen, cota de cada vértice, secuencia densificada de puntos con cota, longitud sobre el terreno y
  desnivel acumulado. Deja de existir si la polilínea se convierte a plana.
- **Colección de polilíneas de la tarea**: conjunto de polilíneas de una tarea, unidad de
  exportación, de consulta por otros plugins y de eliminación en cascada cuando la tarea desaparece.
  Lleva la versión del contrato con la que fue escrita.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un usuario que ya conoce WebODM traza y guarda su primera polilínea en menos de un
  minuto, sin consultar documentación.
- **SC-002**: El 100 % de las polilíneas guardadas reaparecen tras recargar la página, y también en la
  sesión de otro usuario con acceso a la tarea, con idéntica geometría, nombre y modo.
- **SC-003**: Para una polilínea de hasta el límite establecido de vértices sobre un modelo de
  elevación de tamaño habitual, el resultado con elevación se presenta en menos de 3 segundos, y en
  ningún caso la interfaz queda sin respuesta ni sin indicación de progreso.
- **SC-004**: La longitud sobre el terreno calculada para una línea de prueba difiere en menos de un
  2 % de la obtenida con una herramienta GIS externa sobre el mismo modelo de elevación, el mismo
  trazado y **el mismo paso de densificación**; a igualdad de trazado y modelo pero con pasos
  distintos, las cifras no son comparables y el sistema no pretende que lo sean.
- **SC-005**: El archivo exportado se abre sin errores en QGIS, con las geometrías en su posición
  correcta y con las cotas conservadas en las polilíneas sobre el terreno.
- **SC-006**: Las cuatro acciones que el panel de anotaciones ofrece sobre una polilínea —mostrar y
  ocultar, encuadrar, renombrar y eliminar— producen el efecto esperado en el 100 % de los intentos.
- **SC-007**: Un plugin consumidor de prueba obtiene la geometría con elevación de una tarea sin
  muestrear el modelo de elevación por su cuenta y sin conocer cómo se almacenan las polilíneas.
- **SC-008**: En una tarea sin modelo de elevación, el usuario puede trazar y guardar polilíneas
  planas, y recibe una explicación del motivo por el que el modo sobre el terreno no está disponible.
- **SC-009**: Ninguna polilínea almacenada en modo sobre el terreno contiene cotas estimadas o de
  relleno: el 100 % de los intentos de guardar en ese modo con cobertura incompleta se rechazan
  indicando qué tramo del recorrido carece de dato.
- **SC-010**: Deshabilitar el plugin deja WebODM plenamente funcional: el mapa 2D, el panel de capas y
  el resto de plugins siguen operando sin errores.

## Assumptions

- **Alcance geométrico**: solo polilíneas. El almacenamiento y el contrato de lectura se diseñan para
  admitir otras geometrías más adelante, pero polígonos, puntos, importación desde archivo, formatos
  distintos de GeoJSON, estilado por línea y cálculos de área o volumen quedan fuera de esta feature.
- **Solo mapa 2D**: las polilíneas no se representan en el visor 3D.
- **Sin gráfica de perfil**: esta feature entrega los datos con elevación; su visualización como
  gráfico corresponde a un plugin consumidor posterior.
- **Independencia de la realineación**: las polilíneas se muestrean contra los productos originales de
  la tarea; la interacción con el plugin de realineación queda fuera de alcance.
- **Concurrencia**: no se implementa fusión de ediciones simultáneas; basta con un comportamiento
  predecible y explicado, coherente con el que ya aplica el plugin de realineación.
- **Permisos**: se reutiliza el criterio de acceso a la tarea ya vigente en el fork —ver para quien
  accede a la tarea, editar para quien puede editarla— sin introducir un modelo de permisos propio.
- **Modelo por defecto**: cuando ambos estén disponibles se preselecciona el modelo de superficie
  (DSM), por ser el que refleja lo que el usuario ve en la ortofoto.
- **Paso de densificación (revisado el 2026-07-26 tras medirlo)**: la longitud sobre el terreno
  depende de la escala a la que se muestrea. Sobre el DSM real de una tarea de referencia
  (resolución 0,0222 m), un mismo tramo de 188 m en planta arroja +65 % de longitud al paso nativo y
  +15 % al paso de 5 m: una variación del 43 % sin cambiar ni el trazado ni el modelo. Al paso nativo
  se está midiendo la rugosidad y el ruido del DSM, no el recorrido. Por eso el paso es un parámetro
  explícito con valor por defecto acotado —no la resolución nativa sin más— y toda longitud sobre el
  terreno se presenta junto al paso que la produjo. Detalle y mediciones en `research.md` (D4).
- **Unidad vertical**: se asume que el modelo de elevación de la tarea está en metros salvo que él
  mismo declare otra unidad, que se registra sin convertir.
- **Restricciones del fork** (Constitución, Principios I–IV): la feature se implementa íntegramente
  como un plugin nuevo bajo `coreplugins/`, sin modificar archivos del core de WebODM, sin migraciones
  de base de datos ni modelos nuevos —usando el almacén de datos de plugins del framework, como hace
  el plugin de realineación—, y apoyándose en las librerías geoespaciales ya presentes en la imagen
  Docker. El cálculo de elevación ocurre en el servidor; el navegador nunca descarga el modelo de
  elevación.
- **Dependencia del framework**: la integración con el control de capas se apoya en los puntos de
  extensión de anotaciones que el core de WebODM ya expone para plugins, que hoy ningún plugin
  implementa.
- **Cobertura de elevación completa (decisión del 2026-07-26)**: el modo sobre el terreno exige dato
  en todo el recorrido. Se descartaron interpolar los tramos sin dato y admitir huecos en la
  geometría: una longitud sobre el terreno solo es defendible si toda ella procede de mediciones, y
  admitir huecos trasladaría esa complejidad a cada plugin consumidor. El usuario con cobertura
  parcial recorta el trazado o guarda la línea en modo plano.
- **Trazado solo en la vista de una tarea (decisión del 2026-07-26)**: crear o modificar geometría
  requiere que el mapa muestre una sola tarea, siguiendo el precedente de otros plugins del fork que
  se activan únicamente en esa vista. Se descartaron elegir la tarea en un paso previo y deducirla del
  primer vértice: el primero añade fricción al caso mayoritario y el segundo produce atribuciones
  sorprendentes cuando las tareas se solapan.
