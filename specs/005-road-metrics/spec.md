# Feature Specification: Extracción de características geométricas de caminos a partir del eje y el modelo de elevación

**Feature Branch**: `005-road-metrics`

**Created**: 2026-07-27

**Status**: Draft

**Input**: User description: "Plugin `road` para extraer características geométricas de un camino a partir de su eje central y los modelos digitales de elevación de una tarea procesada, en la vista 2D de WebODM.

**Entrada — el eje**: el usuario aporta el eje central del camino como una polilínea 2D en EPSG:4326, por una de dos vías: (a) eligiendo una anotación 2D (`mode: "flat"`) ya trazada en la tarea, obtenida a través del contrato público del plugin `annotations` (`get_plugin_by_name("annotations")`, `CONTRACT_VERSION = 2`, método `get_polylines(task_id)`), o (b) subiendo un archivo GeoJSON con un único `LineString` 2D, que se valida (tipo de geometría, CRS, número de vértices, que caiga dentro de la extensión del modelo de elevación) y se rechaza con un mensaje claro si no cumple. El plugin no detecta ni traza el eje: siempre lo da el usuario. Si el plugin `annotations` está ausente o deshabilitado, el plugin sigue funcionando con la vía del archivo y lo indica en la interfaz en lugar de fallar.

**Fuente de elevación**: el usuario elige el modelo (DSM o DTM) y la variante (los productos originales de la tarea o los corregidos por el plugin `realign`, cuando existan). La variante realineada solo se ofrece si esa tarea tiene una realineación aplicada; en caso contrario se ofrecen únicamente los originales. Por defecto se propone el DTM si la tarea lo tiene, y el DSM en caso contrario.

**Tramificación**: el eje se recorre por progresiva y se divide en tramos de longitud configurable, 2 m por defecto. El último tramo, más corto que el resto si la longitud del eje no es múltiplo exacto, se conserva y se reporta con su longitud real. Cada tramo queda identificado por su progresiva inicial y final y por su geometría en planta.

**Métricas por tramo**, todas derivadas del modelo de elevación elegido:

1. **Cota del eje**: elevación muestreada del DEM en las estaciones del tramo, para reconstruir el perfil longitudinal completo del camino.
2. **Pendiente longitudinal**: variación de cota a lo largo del tramo respecto de su longitud en planta, reportada en porcentaje y en grados, con signo según el sentido de trazado del eje.
3. **Ancho del camino**: en cada tramo se traza una transversal perpendicular al eje, se muestrea el DEM a lo largo de ella hacia ambos lados hasta un semiancho de búsqueda configurable, y el borde de cada lado es el primer punto, avanzando desde el eje hacia afuera, donde la pendiente transversal local supera un umbral configurable de forma sostenida durante un número mínimo de muestras consecutivas (para no confundir ruido del DEM con un talud, una berma o una cuneta). Se reporta el ancho total, la distancia del eje al borde izquierdo y la distancia al borde derecho por separado, de modo que se vea si el eje declarado está descentrado respecto de la calzada real.
4. **Pendiente transversal (bombeo o peralte)**: pendiente de la superficie de la calzada entre el borde izquierdo y el derecho, calculada sobre el mismo perfil transversal, en porcentaje.

**Ausencia de dato**: cuando una transversal no encuentra un borde claro dentro del semiancho de búsqueda, o cuando el DEM no tiene dato en parte del perfil, ese tramo se reporta explícitamente como "borde no detectado" con el ancho y la pendiente transversal vacíos, tanto en el mapa como en la exportación. Nunca se interpola, rellena ni extrapola un valor a partir de tramos vecinos. La pendiente longitudinal y la cota del eje se siguen reportando en esos tramos si el DEM cubre el eje. Si el DEM no cubre parte del eje, esos tramos se identifican como sin cobertura y el resto del análisis se completa igual.

**Salida — capa en el mapa 2D**: los tramos se dibujan sobre el mapa como una capa del camino analizado, coloreados con un semáforo según su pendiente longitudinal: verde, amarillo y rojo. Los dos umbrales que separan los tres rangos son configurables por el usuario, con valores por defecto razonables que puede cambiar antes o después de calcular, viendo el recoloreado sin recalcular el análisis. Los tramos sin dato se distinguen visualmente de los tres rangos. Al hacer clic sobre un tramo se muestran todas sus métricas y su progresiva.

**Salida — exportación**: descarga en CSV, con una fila por tramo y una columna por métrica (progresiva inicial y final, longitud real del tramo, cota, pendiente longitudinal en % y grados, ancho, distancia a borde izquierdo y derecho, pendiente transversal, y el estado del tramo), y en GeoJSON, con la geometría de cada tramo y esas mismas métricas como propiedades, más las transversales y los puntos de borde detectados como geometrías auxiliares, para poder revisarlo en QGIS. Ambas exportaciones incluyen los parámetros con los que se calculó el análisis.

**Ejecución y persistencia**: el análisis es pesado (un camino de varios kilómetros con tramos de 2 m produce miles de transversales, cada una con su propio muestreo del DEM), así que corre de forma asíncrona en el worker, con progreso visible y cancelable, sin bloquear la interfaz. El resultado se persiste asociado a la tarea con los mecanismos del framework de plugins, sobrevive a recargas, y queda claramente identificado por el eje, el modelo de elevación y los parámetros con los que se generó. Se puede recalcular con otros parámetros y se puede eliminar. Los productos de la tarea nunca se modifican.

**Parámetros configurables** por el usuario al lanzar el análisis, todos con valores por defecto: longitud de tramo (2 m), semiancho de búsqueda de la transversal, paso de muestreo a lo largo de la transversal, umbral de quiebre de pendiente que define el borde, número mínimo de muestras consecutivas para confirmar un borde, y los dos umbrales del semáforo de pendiente. Los valores fuera de rango razonable se rechazan con un mensaje que explique el rango admitido, y hay un tope al número total de muestras por análisis para no degradar el sistema con ejes desmedidos o parámetros absurdos.

**Fuera de alcance en esta feature**: clasificación o tipificación del camino (asfaltado, minero, forestal) y cualquier evaluación de cumplimiento normativo — el plugin mide y colorea por rangos, no juzga; detección automática del eje; uso de la ortofoto o de cualquier clasificación radiométrica para hallar los bordes; nube de puntos y vista 3D; curvatura, radios de giro, distancias de visibilidad, cubicaciones de corte y terraplén, análisis de drenaje; edición manual de los bordes detectados; tabla de tramos y gráfico de perfil longitudinal dentro del panel (los tramos se consultan en el mapa y se analizan en la exportación).

**Restricciones del fork**: se implementa como un plugin nuevo en `coreplugins/road/` siguiendo la constitución del repositorio, sin modificar el core de upstream, consumiendo `annotations` y `realign` solo a través de sus interfaces públicas, y sin dependencias nuevas: `rasterio`, GDAL y `pyproj` ya están presentes en la imagen. El plugin debe poder deshabilitarse sin afectar a `annotations`, a `realign` ni al resto del sistema."

## Clarifications

La descripción original de arriba se conserva literal. Donde una respuesta de esta sección la
contradiga —la longitud de tramo por defecto y el tope de muestras—, prevalece la respuesta, que es
la que recogen los requisitos.

### Session 2026-07-27

- Q: ¿Hasta qué tamaño de camino debe poder analizar el sistema en una sola corrida? → A: Sin tope fijo; el sistema estima muestras y duración antes de lanzar, avisa y deja decidir al usuario.
- Q: ¿Cómo se calcula la pendiente longitudinal de cada tramo? → A: Por ajuste de mínimos cuadrados sobre todas las muestras del eje dentro del tramo, no con la diferencia entre extremos.
- Q: ¿Qué identifica a un análisis y qué pasa al recalcular? → A: Recalcular pisa el análisis anterior de ese eje (identificado por la anotación de origen o por el nombre del archivo subido), avisando antes.
- Q: ¿Cómo se aplican los rangos de color del semáforo? → A: En la interfaz, de forma inmediata sobre las pendientes ya calculadas en el backend; los umbrales se persisten para sobrevivir a un refresco de la página, y no forman parte del cálculo.
- Q: Longitud de tramo por defecto → A: 5 m (en lugar de los 2 m de la descripción original).
- Q: Si la transversal se sale del DEM o entra en zona sin dato antes de encontrar el borde, ¿cómo se reporta? → A: Como tramo sin borde, registrando por lado el motivo (sin quiebre dentro del área de búsqueda / sin datos de elevación); en el mapa se ven igual, en la exportación el motivo viaja como dato.
- Q: ¿Qué pasa si se lanza un análisis mientras otro corre en la misma tarea? → A: Uno a la vez por tarea; el sistema avisa de que ya hay uno en curso y ofrece cancelarlo antes de lanzar el nuevo.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Obtener pendientes y anchos por tramo de un camino ya trazado (Priority: P1)

Un usuario con una tarea procesada ya trazó el eje central de un camino como polilínea 2D sobre el
mapa. Abre la herramienta de caminos, elige ese eje de la lista, acepta el modelo de elevación
propuesto y lanza el análisis. Mientras corre ve el progreso y puede cancelarlo. Al terminar, el
camino aparece sobre el mapa dividido en tramos de 5 m coloreados en verde, amarillo o rojo según
su pendiente longitudinal, y al hacer clic en cualquier tramo ve su progresiva, su cota, su
pendiente longitudinal, el ancho medido, las distancias a cada borde y la pendiente transversal.

**Why this priority**: es la esencia de la feature y su MVP. Con solo esto el usuario ya obtiene lo
que hoy no tiene: saber dónde el camino es más empinado y cuánto mide de ancho en cada punto, sin
salir de WebODM ni exportar nada a otra herramienta. Todo lo demás son formas de aprovechar o
afinar este resultado.

**Independent Test**: sobre una tarea con DSM o DTM y una polilínea 2D trazada a lo largo de un
camino, lanzar el análisis con los parámetros por defecto y verificar que (a) aparecen tramos de
5 m cubriendo todo el eje, (b) están coloreados en tres rangos según su pendiente, (c) al hacer
clic en un tramo se muestran sus cuatro métricas, y (d) los tramos donde no se detectó borde se
distinguen y no muestran ancho.

**Acceptance Scenarios**:

1. **Given** una tarea con al menos un modelo de elevación y una polilínea 2D trazada, **When** el
   usuario abre la herramienta de caminos, **Then** puede elegir esa polilínea como eje y ve
   preseleccionado el modelo de elevación por defecto.
2. **Given** un eje y un modelo elegidos, **When** el usuario lanza el análisis, **Then** el cálculo
   corre sin bloquear la interfaz, muestra el progreso y permite cancelarlo.
3. **Given** un análisis en curso, **When** el usuario lo cancela, **Then** el cálculo se detiene, se
   informa de la cancelación y no queda ningún resultado parcial guardado.
4. **Given** un análisis en curso en la tarea, **When** el usuario intenta lanzar otro, **Then** el
   sistema no lo inicia, informa de que ya hay uno corriendo y ofrece cancelarlo primero.
5. **Given** un análisis terminado, **When** el usuario mira el mapa, **Then** el eje aparece
   dividido en tramos de la longitud configurada, cada uno coloreado según el rango de pendiente
   longitudinal en que cae.
6. **Given** un análisis terminado, **When** el usuario hace clic sobre un tramo, **Then** ve su
   progresiva inicial y final, su longitud real, la cota del eje, la pendiente longitudinal en
   porcentaje y grados, el ancho, la distancia a cada borde y la pendiente transversal.
7. **Given** un tramo donde la transversal no encontró borde en alguno de los lados, **When** el
   usuario lo consulta, **Then** ve el tramo marcado como sin borde detectado, con el ancho y la
   pendiente transversal vacíos, el motivo por el que ese lado no tiene borde, y sin ningún valor
   estimado o interpolado.
8. **Given** una tarea sin ningún modelo de elevación, **When** el usuario abre la herramienta,
   **Then** el sistema explica que la tarea no tiene DSM ni DTM y no permite lanzar el análisis.
9. **Given** un análisis terminado, **When** el usuario recarga la página y vuelve a la vista 2D,
   **Then** el análisis sigue disponible con los mismos tramos y métricas.

---

### User Story 2 - Llevarse el análisis a una herramienta externa (Priority: P2)

El usuario necesita entregar el resultado a un cliente o cruzarlo con datos de diseño en otra
herramienta. Desde el análisis ya calculado descarga un CSV con una fila por tramo para abrirlo en
una hoja de cálculo, y un GeoJSON con la geometría de los tramos, las transversales y los puntos de
borde detectados, que abre en QGIS junto a la ortofoto para revisar visualmente dónde la detección
de bordes funcionó y dónde no.

**Why this priority**: es lo que convierte una consulta en pantalla en un entregable. Alto valor y
esfuerzo bajo una vez que el análisis existe, pero sin la Historia 1 no hay nada que exportar.

**Independent Test**: sobre un análisis ya calculado, descargar ambos archivos y verificar que el
CSV abre en una hoja de cálculo con una fila por tramo y todas las columnas de métricas, y que el
GeoJSON abre en QGIS mostrando los tramos, las transversales y los puntos de borde, con los
parámetros del análisis incluidos en ambos.

**Acceptance Scenarios**:

1. **Given** un análisis terminado, **When** el usuario descarga el CSV, **Then** el archivo tiene
   una fila por tramo con progresiva inicial y final, longitud real, cota, pendiente longitudinal
   en porcentaje y grados, ancho, distancia a borde izquierdo y derecho, pendiente transversal y
   estado del tramo.
2. **Given** un análisis terminado, **When** el usuario descarga el GeoJSON, **Then** contiene la
   geometría de cada tramo con sus métricas como propiedades, más las transversales y los puntos de
   borde detectados como geometrías auxiliares identificables.
3. **Given** un análisis con tramos sin dato, **When** el usuario revisa cualquiera de las dos
   exportaciones, **Then** esos tramos aparecen con los campos correspondientes vacíos y su estado
   explícito, nunca con un valor rellenado.
4. **Given** cualquiera de las dos exportaciones, **When** el usuario la inspecciona, **Then**
   encuentra registrados el eje, el modelo de elevación, la variante y todos los parámetros con los
   que se calculó el análisis.

---

### User Story 3 - Ajustar los parámetros al camino concreto (Priority: P3)

El primer análisis con los valores por defecto deja muchos tramos sin borde detectado porque el
camino es una pista de tierra con bordes suaves, o produce un semáforo poco informativo porque
todos los tramos salen verdes. El usuario baja el umbral de quiebre de pendiente, amplía el
semiancho de búsqueda y vuelve a calcular; después mueve los dos umbrales del semáforo y ve el
camino recolorearse al instante, sin repetir el cálculo.

**Why this priority**: sin esto la feature funciona, pero solo para los caminos que encajen con los
valores por defecto. Es lo que la hace utilizable en caminos asfaltados, mineros o forestales sin
que el plugin tenga que saber de qué tipo es cada uno.

**Independent Test**: sobre un análisis ya calculado, cambiar los umbrales del semáforo y verificar
que el coloreado cambia sin recalcular; después cambiar el umbral de quiebre o el semiancho,
recalcular y verificar que el número de tramos con borde detectado cambia en consecuencia.

**Acceptance Scenarios**:

1. **Given** la herramienta abierta, **When** el usuario despliega los parámetros, **Then** ve la
   longitud de tramo, el semiancho de búsqueda, el paso de muestreo transversal, el umbral de
   quiebre, el mínimo de muestras consecutivas y los dos umbrales del semáforo, todos con su valor
   por defecto y editables.
2. **Given** un análisis terminado, **When** el usuario cambia cualquiera de los dos umbrales del
   semáforo, **Then** los tramos se recolorean de inmediato sin repetir el cálculo, y al recargar la
   página el camino conserva esos mismos colores.
3. **Given** un parámetro con un valor fuera del rango admitido, **When** el usuario intenta lanzar
   el análisis, **Then** el sistema lo rechaza indicando el rango válido y no inicia el cálculo.
4. **Given** una combinación de eje y parámetros de coste elevado, **When** el usuario intenta
   lanzarla, **Then** el sistema muestra la estimación de muestras y duración, indica qué parámetro
   la reduciría y pide confirmación explícita antes de empezar.
5. **Given** un análisis existente sobre un eje, **When** el usuario lo recalcula con otros
   parámetros, **Then** el sistema advierte de que sustituirá el resultado anterior y, al confirmar,
   ese resultado se pisa y los parámetros nuevos quedan registrados con él.
6. **Given** un análisis que ya no interesa, **When** el usuario lo elimina, **Then** desaparece del
   mapa y del listado, sin afectar a ningún otro análisis ni a los productos de la tarea.

---

### User Story 4 - Analizar un eje que viene de fuera de WebODM (Priority: P4)

El eje del camino ya existe en el software de topografía o de diseño del usuario. En vez de
retrazarlo a mano sobre el mapa, sube un archivo GeoJSON con esa línea y analiza directamente sobre
ella.

**Why this priority**: evita retrabajo y permite analizar contra un eje de proyecto en lugar de uno
dibujado a ojo, pero es una vía de entrada alternativa: con la Historia 1 el flujo ya está completo.

**Independent Test**: subir un GeoJSON con un LineString 2D que recorra un camino de la tarea,
lanzar el análisis y verificar que produce el mismo tipo de resultado que un eje trazado en el mapa;
después subir archivos inválidos y verificar que cada uno se rechaza con un mensaje que explique la
causa.

**Acceptance Scenarios**:

1. **Given** un archivo GeoJSON con un único LineString 2D dentro de la extensión del modelo de
   elevación, **When** el usuario lo sube, **Then** queda disponible como eje y el análisis procede
   igual que con una anotación.
2. **Given** un archivo cuya geometría no es un LineString, o que contiene más de una línea, o que
   tiene menos de dos vértices distintos, **When** el usuario lo sube, **Then** el sistema lo
   rechaza indicando exactamente qué falla.
3. **Given** un archivo cuyo sistema de coordenadas no es el esperado, **When** el usuario lo sube,
   **Then** el sistema lo rechaza explicando el sistema de coordenadas requerido.
4. **Given** un archivo cuya línea cae fuera de la extensión del modelo de elevación, **When** el
   usuario lo sube, **Then** el sistema lo rechaza indicando que el eje no está sobre los datos de
   la tarea.
5. **Given** que el sistema de anotaciones no está disponible, **When** el usuario abre la
   herramienta, **Then** la vía del archivo sigue funcionando y el sistema explica por qué no hay
   anotaciones que elegir.

---

### User Story 5 - Analizar sobre los productos realineados (Priority: P5)

El usuario ya corrigió la georreferenciación de la tarea con la herramienta de realineación. Al
analizar el camino elige la variante realineada del modelo de elevación, de modo que las métricas
queden en la misma posición que el resto de sus datos corregidos.

**Why this priority**: solo aplica a tareas realineadas y no cambia ninguna métrica en sí, solo la
posición sobre la que se miden. Es una casilla de selección más sobre un flujo que ya funciona.

**Independent Test**: sobre una tarea con realineación aplicada, comprobar que se ofrece la variante
realineada además de la original, analizar con cada una y verificar que los tramos resultantes
quedan desplazados entre sí de forma coherente con la corrección aplicada.

**Acceptance Scenarios**:

1. **Given** una tarea con una realineación aplicada, **When** el usuario elige la fuente de
   elevación, **Then** puede escoger entre el producto original y el realineado.
2. **Given** una tarea sin realineación aplicada, **When** el usuario elige la fuente de elevación,
   **Then** solo se le ofrecen los productos originales, sin opciones muertas.
3. **Given** un análisis calculado sobre la variante realineada, **When** el usuario lo consulta o
   lo exporta, **Then** la variante empleada queda registrada junto al resultado.
4. **Given** que la herramienta de realineación no está disponible, **When** el usuario abre la
   herramienta de caminos, **Then** el análisis sobre los productos originales funciona con
   normalidad.

---

### Edge Cases

- **Eje más corto que la longitud de tramo**: se produce un único tramo con la longitud real del eje.
- **Eje con vértices duplicados o segmentos de longitud nula**: no deben generar tramos vacíos ni
  transversales sin dirección definida.
- **Curvas cerradas**: en curvas de radio pequeño las transversales de tramos contiguos se cruzan;
  cada tramo mide lo suyo y el sistema no debe descartar ni fusionar tramos por ese solapamiento.
- **Eje que se sale del modelo de elevación a mitad de recorrido**: los tramos sin cobertura se
  marcan como tales y el resto del análisis se completa igual.
- **Borde detectado solo en un lado**: se reporta la distancia del lado detectado, el ancho y la
  pendiente transversal quedan vacíos, y el lado sin borde registra su motivo.
- **Transversal que se sale del modelo de elevación**: el lado afectado se reporta sin borde con el
  motivo "sin datos de elevación", distinto de "sin quiebre dentro del área de búsqueda"; el otro
  lado y las métricas longitudinales del tramo se conservan.
- **Camino sin quiebre de pendiente (calzada a nivel del terreno circundante)**: ningún tramo obtiene
  ancho; el análisis se entrega igual con las métricas longitudinales y el usuario ve claramente que
  la detección no encontró bordes.
- **El eje se borra del sistema de anotaciones después de calcular**: el análisis persistido debe
  seguir consultándose y exportándose, ya que conserva su propia copia de la geometría.
- **El modelo de elevación cambia (reproceso de la tarea) después de calcular**: el análisis se marca
  como desactualizado, indicando que fue calculado sobre datos que ya no son los actuales, y no se
  recalcula por su cuenta.
- **Dos análisis sobre la misma tarea**: conviven como capas independientes, cada una identificable
  por su eje, pero se calculan de uno en uno: con un análisis en curso, la tarea no admite lanzar
  otro hasta que termine o se cancele.
- **Análisis lanzado sobre un eje desmedido**: la estimación previa advierte del coste y pide
  confirmación explícita; si el usuario confirma, el análisis se lanza igualmente y sigue siendo
  cancelable en cualquier momento.
- **Usuario sin permiso sobre la tarea**: no puede lanzar, consultar, exportar ni eliminar análisis
  de esa tarea.

## Requirements *(mandatory)*

### Functional Requirements

**Entrada del eje**

- **FR-001**: El sistema DEBE permitir elegir como eje del camino una polilínea 2D ya existente en la
  tarea, listándolas por su nombre.
- **FR-002**: El sistema DEBE permitir aportar el eje subiendo un archivo GeoJSON que contenga una
  única línea 2D.
- **FR-003**: El sistema DEBE validar el eje aportado por archivo (tipo de geometría, número de
  líneas, dimensión, sistema de coordenadas, al menos dos vértices distintos, y que caiga dentro de
  la extensión del modelo de elevación elegido) y rechazar el que no cumpla con un mensaje que
  identifique la causa concreta.
- **FR-004**: El sistema NO DEBE detectar, trazar ni ajustar el eje automáticamente: el eje siempre
  lo aporta el usuario.
- **FR-005**: Cuando el sistema de anotaciones no esté disponible, el sistema DEBE seguir ofreciendo
  la vía del archivo e indicar por qué no hay anotaciones que elegir, sin fallar ni quedar
  inutilizable.
- **FR-006**: El análisis DEBE conservar su propia copia de la geometría del eje, de modo que
  permanezca consultable y exportable aunque la polilínea de origen se modifique o se elimine.

**Fuente de elevación**

- **FR-007**: El sistema DEBE permitir elegir el modelo de elevación entre los que la tarea tenga
  disponibles, proponiendo el DTM por defecto y el DSM cuando no haya DTM.
- **FR-008**: El sistema DEBE ofrecer la variante realineada del modelo únicamente cuando la tarea
  tenga una realineación aplicada, y ofrecer siempre la variante original.
- **FR-009**: Cuando la tarea no tenga ningún modelo de elevación, el sistema DEBE informarlo con
  claridad y no permitir lanzar el análisis.
- **FR-010**: El sistema DEBE registrar junto al resultado qué modelo y qué variante se emplearon.

**Tramificación**

- **FR-011**: El sistema DEBE dividir el eje en tramos consecutivos de la longitud configurada,
  medidos sobre la progresiva en planta, cubriendo el eje completo y sin solapamientos ni huecos.
- **FR-012**: El sistema DEBE conservar el último tramo con su longitud real cuando la longitud del
  eje no sea múltiplo exacto de la longitud de tramo, y DEBE producir un único tramo cuando el eje
  sea más corto que un tramo.
- **FR-013**: Cada tramo DEBE quedar identificado por su progresiva inicial, su progresiva final, su
  longitud real y su geometría en planta.

**Métricas por tramo**

- **FR-014**: El sistema DEBE muestrear la cota del eje a lo largo de cada tramo con el paso de
  muestreo configurado, y reportar por tramo la cota del ajuste en su punto medio, de forma que el
  conjunto de tramos reconstruya el perfil longitudinal del camino.
- **FR-015**: El sistema DEBE calcular la pendiente longitudinal de cada tramo por ajuste de mínimos
  cuadrados de la cota contra la progresiva, sobre todas las muestras del eje contenidas en el
  tramo, y reportarla en porcentaje y en grados, referida a la longitud en planta y con signo según
  el sentido de trazado del eje. El sistema NO DEBE derivarla únicamente de las cotas de los
  extremos del tramo, que en tramos cortos quedan dominadas por el ruido del modelo de elevación.
- **FR-016**: El sistema DEBE trazar, para cada tramo, una transversal perpendicular al eje y
  muestrear el modelo de elevación a lo largo de ella hacia ambos lados hasta el semiancho de
  búsqueda configurado.
- **FR-017**: El sistema DEBE situar el borde de cada lado en el primer punto, avanzando desde el eje
  hacia afuera, donde la pendiente transversal local supere el umbral de quiebre configurado durante
  al menos el número configurado de muestras consecutivas.
- **FR-018**: El sistema DEBE reportar por tramo el ancho total entre bordes y, por separado, la
  distancia del eje al borde izquierdo y al borde derecho.
- **FR-019**: El sistema DEBE reportar la pendiente transversal de la calzada entre el borde
  izquierdo y el derecho, en porcentaje.

**Ausencia de dato**

- **FR-020**: Cuando no se detecte borde en un lado dentro del semiancho de búsqueda, el sistema DEBE
  marcar ese tramo como sin borde detectado, dejar vacíos el ancho y la pendiente transversal, y
  reportar la distancia del lado que sí se detectó si lo hubiera.
- **FR-021**: El sistema DEBE registrar, para cada lado sin borde, por qué no lo hay: porque no
  aparece ningún quiebre dentro del semiancho de búsqueda, o porque el modelo de elevación deja de
  tener dato en ese lado antes de alcanzarlo. Ambos casos se dibujan igual en el mapa —tramo sin
  dato—, pero el motivo DEBE quedar disponible al consultar el tramo y en las exportaciones, para
  que el usuario distinga lo que el terreno no tiene de lo que el vuelo no cubrió.
- **FR-022**: El sistema NO DEBE interpolar, rellenar ni extrapolar ninguna métrica a partir de
  tramos vecinos ni de los parámetros de búsqueda: lo que no se mide se reporta vacío.
- **FR-023**: Cuando el modelo de elevación no tenga dato sobre parte del eje, el sistema DEBE marcar
  esos tramos como sin cobertura y completar el análisis del resto del eje.
- **FR-024**: El sistema DEBE seguir reportando la cota y la pendiente longitudinal en los tramos sin
  borde detectado, siempre que el modelo cubra el eje en ellos.

**Salida en el mapa**

- **FR-025**: El sistema DEBE dibujar los tramos del análisis sobre el mapa 2D como una capa
  identificable por el eje analizado, que se pueda mostrar y ocultar.
- **FR-026**: El sistema DEBE colorear cada tramo en verde, amarillo o rojo según en cuál de los tres
  rangos de pendiente longitudinal caiga, delimitados por los dos umbrales configurables.
- **FR-027**: El sistema DEBE distinguir visualmente los tramos sin dato de los tres rangos de color.
- **FR-028**: El sistema DEBE mostrar, al seleccionar un tramo, su progresiva y todas sus métricas.
- **FR-029**: El sistema DEBE recolorear los tramos de inmediato al cambiar cualquiera de los dos
  umbrales del semáforo, resolviendo el color sobre las métricas ya calculadas, sin repetir el
  cálculo ni volver a pedir el análisis.
- **FR-030**: El sistema DEBE conservar los umbrales del semáforo elegidos por el usuario, de modo
  que al recargar la página o volver a la tarea el camino se muestre con los mismos colores. Los
  umbrales NO forman parte del cálculo: cambiarlos nunca invalida un análisis ni obliga a
  recalcularlo.

**Exportación**

- **FR-031**: El sistema DEBE permitir descargar el análisis en CSV con una fila por tramo y una
  columna por métrica, incluyendo progresivas, longitud real, cota, pendiente longitudinal en
  porcentaje y grados, ancho, distancias a cada borde, pendiente transversal, estado del tramo y el
  motivo por lado cuando no haya borde.
- **FR-032**: El sistema DEBE permitir descargar el análisis en GeoJSON con la geometría de cada
  tramo y sus métricas como propiedades, más las transversales y los puntos de borde detectados como
  geometrías auxiliares identificables.
- **FR-033**: Ambas exportaciones DEBEN incluir el eje, el modelo, la variante y los parámetros de
  cálculo con los que se generó el análisis.

**Ejecución, persistencia y permisos**

- **FR-034**: El análisis DEBE ejecutarse sin bloquear la interfaz, mostrando progreso mientras
  corre.
- **FR-035**: El usuario DEBE poder cancelar un análisis en curso; tras cancelar, el sistema no DEBE
  conservar resultados parciales.
- **FR-036**: El sistema NO DEBE permitir lanzar un análisis en una tarea mientras otro siga en curso
  en esa misma tarea: DEBE indicar que ya hay uno corriendo y ofrecer cancelarlo antes de lanzar el
  nuevo.
- **FR-037**: El sistema DEBE persistir el resultado asociado a la tarea, de modo que sobreviva a
  recargas y a cierres de sesión, identificado por el eje, el modelo, la variante y los parámetros
  de cálculo, junto con los umbrales del semáforo elegidos para verlo.
- **FR-038**: El usuario DEBE poder recalcular un análisis con otros parámetros y eliminar un
  análisis existente. Recalcular DEBE sustituir el resultado anterior de ese eje —conservando su
  posición en el listado y en el mapa— en lugar de acumular un análisis nuevo, y el sistema DEBE
  advertir de la sustitución antes de ejecutarla.
- **FR-039**: El sistema DEBE señalar un análisis como desactualizado cuando el modelo de elevación
  sobre el que se calculó haya cambiado, sin recalcularlo por su cuenta.
- **FR-040**: El sistema NO DEBE modificar ningún producto de la tarea.
- **FR-041**: Solo los usuarios con acceso a la tarea DEBEN poder lanzar, consultar, exportar o
  eliminar sus análisis.
- **FR-042**: El sistema DEBE poder deshabilitarse sin afectar al sistema de anotaciones, a la
  herramienta de realineación ni al resto de la aplicación.

**Parámetros**

- **FR-043**: El sistema DEBE permitir configurar, con valores por defecto, los parámetros de
  cálculo: la longitud de tramo, el semiancho de búsqueda de la transversal, el paso de muestreo a
  lo largo de la transversal, el umbral de quiebre de pendiente que define el borde y el número
  mínimo de muestras consecutivas para confirmar un borde. Cambiar cualquiera de ellos requiere
  recalcular el análisis.
- **FR-044**: El sistema DEBE permitir configurar, con valores por defecto, los dos umbrales del
  semáforo de pendiente, que son parámetros de visualización y se aplican sobre un análisis ya
  calculado sin recalcularlo (FR-029, FR-030).
- **FR-045**: El sistema DEBE rechazar los valores fuera del rango admitido con un mensaje que
  indique el rango válido, sin iniciar el cálculo.
- **FR-046**: El sistema DEBE estimar, antes de iniciar el cálculo, cuántas muestras del modelo de
  elevación requerirá la combinación de eje y parámetros elegida y cuánto tardará
  aproximadamente, y mostrárselo al usuario.
- **FR-047**: Cuando la estimación supere el umbral de aviso, el sistema DEBE pedir una confirmación
  explícita antes de lanzar el análisis e indicar qué parámetros reducirían el coste. El sistema NO
  DEBE imponer un tope que impida lanzarlo: la decisión final es del usuario, que siempre puede
  cancelar el análisis en curso.

### Key Entities

- **Análisis de camino**: resultado completo de aplicar unos parámetros a un eje sobre un modelo de
  elevación de una tarea. Contiene el nombre y la geometría del eje analizado, el modelo y la
  variante empleados, los parámetros, la fecha de cálculo, su estado (en curso, terminado, cancelado,
  desactualizado) y la colección de tramos. Pertenece a una tarea; una tarea puede tener varios.
- **Tramo**: unidad de reporte del análisis. Progresiva inicial y final, longitud real, geometría en
  planta, cota del eje, pendiente longitudinal, ancho, distancia a borde izquierdo y derecho,
  pendiente transversal, estado (medido, sin borde detectado, sin cobertura) y, por cada lado sin
  borde, el motivo: sin quiebre dentro del área de búsqueda, o sin datos de elevación.
- **Perfil transversal**: muestreo del modelo de elevación perpendicular al eje en un tramo, del que
  se derivan el ancho y la pendiente transversal. Conserva la geometría de la transversal y los
  puntos de borde detectados, que se exportan como geometrías auxiliares.
- **Parámetros de cálculo**: valores que gobiernan la tramificación y la búsqueda de bordes. Definen
  el resultado: cambiarlos exige recalcular. Se guardan con cada análisis y viajan en las
  exportaciones.
- **Umbrales del semáforo**: los dos valores de pendiente que separan verde, amarillo y rojo. No
  intervienen en el cálculo: se aplican sobre un análisis ya calculado y se conservan para que el
  camino se vea igual al volver a abrirlo.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Con un eje ya trazado, un usuario obtiene el análisis completo de su camino eligiendo
  el eje, aceptando el modelo propuesto y pulsando calcular, sin abandonar la vista 2D.
- **SC-002**: Un camino de 1 km analizado con tramos de 5 m (unos 200 tramos) entrega su resultado en
  menos de 2 minutos, con el progreso actualizándose de forma visible durante todo el cálculo.
- **SC-003**: En un camino con bordes topográficamente definidos (corte, terraplén, berma o cuneta),
  al menos el 90 % de los tramos obtienen ancho medido, y el ancho medido no se aparta más de 0,5 m
  del que un usuario mide manualmente sobre el mismo modelo de elevación.
- **SC-004**: El 100 % de los tramos en los que no se detecta borde aparecen marcados como tales en
  el mapa y en las exportaciones, sin ningún valor de ancho o pendiente transversal rellenado, y con
  el motivo por lado que permite distinguir la falta de quiebre de la falta de datos.
- **SC-005**: Cambiar cualquiera de los dos umbrales del semáforo recolorea el camino completo en
  menos de 2 segundos y sin volver a calcular el análisis.
- **SC-006**: Las exportaciones se abren sin edición manual en una hoja de cálculo y en un SIG de
  escritorio, con una fila o entidad por tramo y los parámetros del análisis localizables en el
  propio archivo.
- **SC-007**: Un análisis terminado sigue disponible con idénticos tramos y métricas tras recargar el
  navegador y volver a entrar a la tarea.
- **SC-008**: Cancelar un análisis en curso devuelve el control al usuario en menos de 5 segundos y
  no deja ningún resultado parcial guardado.
- **SC-009**: Un análisis calculado sigue siendo consultable y exportable después de que el eje del
  que partió se haya modificado o eliminado.
- **SC-010**: Ningún parámetro fuera de rango llega a iniciar un cálculo, y el usuario conoce el
  coste estimado —muestras y duración aproximada— de cualquier análisis antes de lanzarlo, con
  confirmación explícita cuando ese coste supera el umbral de aviso.

## Assumptions

- **Ubicación y nombre**: el plugin se llama `road` y vive en `coreplugins/road/`, conforme a la
  constitución del fork.
- **Modelo por defecto**: se propone el DTM porque describe la superficie del terreno sin vegetación
  ni objetos encima, que es lo que interesa de un camino; el DSM se usa cuando no hay DTM, y sobre
  una calzada despejada ambos coinciden en la práctica.
- **Posición de la transversal**: cada tramo se mide con una única transversal trazada en su punto
  medio, perpendicular a la dirección del tramo. Con tramos de 5 m eso equivale a una medición cada
  5 m del camino.
- **Valores por defecto de los parámetros**, todos ajustables por el usuario: longitud de tramo 5 m;
  semiancho de búsqueda 10 m por lado; paso de muestreo transversal igual a la resolución del modelo
  de elevación; umbral de quiebre 15 % de pendiente transversal; mínimo 3 muestras consecutivas para
  confirmar un borde; umbrales del semáforo en 8 % (verde/amarillo) y 12 % (amarillo/rojo).
- **Referencia de las pendientes**: la pendiente longitudinal se calcula sobre la longitud en planta
  del tramo, que es la convención habitual en obra vial.
- **Solo ejes 2D**: no se ofrecen las polilíneas con cotas propias, porque el análisis toma toda la
  elevación del modelo elegido y una línea con cotas propias induciría a pensar que se usan las
  suyas. Un eje trazado en 3D se vuelve a trazar en 2D si se quiere analizar.
- **Varios análisis por tarea**: una tarea puede tener varios caminos analizados a la vez, cada uno
  como capa propia; recalcular sobre el mismo eje sustituye su resultado anterior en lugar de
  acumularlo, avisando antes.
- **Identidad del eje**: un eje elegido de las anotaciones se identifica por la anotación de la que
  sale; un eje subido por archivo, por el nombre del archivo. Volver a analizar el mismo origen pisa
  el análisis anterior; subir un archivo con otro nombre crea un análisis nuevo, de modo que el
  usuario controla explícitamente cuándo pisa y cuándo acumula.
- **Umbrales del semáforo**: se aplican en la interfaz sobre las pendientes ya calculadas, así que el
  recoloreado es inmediato y no vuelve a pedir nada al servidor; los valores elegidos se conservan
  para que un refresco de la página no devuelva el camino a los colores por defecto.
- **Obsolescencia**: un análisis calculado sobre un modelo que después cambió se marca como
  desactualizado, pero se conserva y sigue siendo consultable; recalcularlo es decisión del usuario.
- **Permisos**: son los de la tarea, con la misma comprobación de acceso que ya aplican los plugins
  hermanos del fork en todas sus operaciones; el plugin no introduce permisos propios ni distingue
  niveles por acción.
- **Unidades**: distancias y cotas en metros, pendientes en porcentaje (y también en grados para la
  longitudinal). Las cotas se reportan tal como las entrega el modelo de elevación, sin conversión de
  datum vertical.
- **Sin dependencias nuevas**: las librerías necesarias para leer y muestrear los modelos de
  elevación ya están presentes en la imagen del fork.

## Dependencies

- **Tarea procesada con al menos un modelo de elevación** (DSM o DTM): sin ellos no hay análisis
  posible.
- **Sistema de anotaciones (`annotations`)**: opcional. Aporta la vía cómoda de elegir un eje ya
  trazado; su ausencia degrada la feature a la vía del archivo, sin romperla.
- **Herramienta de realineación (`realign`)**: opcional. Aporta la variante realineada del modelo de
  elevación; su ausencia deja solo los productos originales.

## Fuera de alcance

Nada de lo siguiente forma parte de esta feature, y el diseño no debe anticiparlo más allá de no
cerrarse la puerta:

- **Clasificación o tipificación del camino** (asfaltado, minero, forestal) y **evaluación de
  cumplimiento normativo**: el sistema mide y colorea por rangos que el usuario elige; no juzga si un
  camino cumple una norma ni deduce de qué tipo es.
- **Detección automática del eje**: el eje siempre lo aporta el usuario.
- **Uso de la ortofoto** o de cualquier clasificación por color o textura para hallar los bordes: los
  bordes salen exclusivamente de la forma del terreno en el modelo de elevación.
- **Nube de puntos y vista 3D**: el análisis vive en la vista 2D y se alimenta de los modelos ráster.
- **Otras métricas viales**: curvatura, radios de giro, distancias de visibilidad, cubicaciones de
  corte y terraplén, análisis de drenaje.
- **Edición manual de los bordes detectados**: el usuario ajusta parámetros y recalcula, pero no
  corrige bordes uno a uno.
- **Tabla de tramos y gráfico de perfil longitudinal dentro del panel**: los tramos se consultan en el
  mapa y se analizan en las exportaciones.
