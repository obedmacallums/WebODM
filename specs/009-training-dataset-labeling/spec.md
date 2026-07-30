# Feature Specification: Etiquetado de ortofotos y exportación de datasets de entrenamiento

**Feature Branch**: `009-training-dataset-labeling`

**Created**: 2026-07-30

**Status**: Draft

**Input**: User description: un plugin que permita tomar la ortofoto de un procesamiento, crear las
clases, etiquetarlas y exportar toda la data para entrenarla en otra PC con una imagen en un
contenedor. El mismo plugin debe poder importar el fichero del modelo ONNX y tener un store de
modelos, para que luego otros plugins puedan usar esos modelos. Los métodos de etiquetado deben ser
cuatro: desde un modelo, desde un GeoJSON, a mano con polígonos y a mano con un pincel.

## Contexto y motivación

El modo `segmentation` del plugin `road` (`007`) clasifica la ortofoto con un modelo de IA para
encontrar los bordes de la calzada. Usa el modelo `roads` de serie de `geodeep`, y en `008` se hizo
visible su límite: sobre `Polideportivo María Puebla Vásquez` clasificó como calzada **un descampado
de tierra compactada entero**, el 25,3 % del corredor.

Ese modelo no está mal hecho. Está entrenado para otra cosa: calles urbanas asfaltadas, a 21 cm/px.
El terreno del usuario —zonas mineras, pistas de tierra compactada indistinguibles de un descampado
para un modelo que nunca vio una mina— queda fuera de lo que ese modelo aprendió. Y no hay ninguna
manera de arreglarlo desde `road`: el modelo se elige de una lista cerrada de alias en
`segmentation.py:27`.

El único arreglo real es entrenar un modelo con el terreno propio. Hoy eso es imposible dentro de
WebODM: no hay forma de etiquetar, ni de sacar los datos, ni de meter un modelo entrenado fuera.

Esta feature construye la primera mitad de ese camino: **etiquetar y sacar el dataset**. El
entrenamiento ocurre fuera (en una PC con GPU, en un contenedor aparte) y la vuelta del modelo
entrenado es la fase siguiente. El plugin nuevo se llamará `training`.

### Por qué el entrenamiento no puede vivir aquí

PyTorch y CUDA no pueden entrar en la imagen de WebODM. `webapp` y `worker` comparten imagen
(Principio IV y «Restricciones de infraestructura» de la constitución), así que meter el
entrenamiento engordaría también los workers de procesado, y el Mac mini M1 del usuario no expone
GPU a Docker en ningún caso —ni CUDA ni Metal—. El entrenamiento va en una imagen propia, en otra
máquina, y esta feature solo tiene que producir algo que esa imagen sepa leer.

Eso convierte el **formato de exportación en un contrato**, no en un detalle: se consume a ciegas,
desde otro repositorio y otra máquina. Es la parte de esta spec que más caro sale cambiar después.

### Fases del plugin

Un plugin, cuatro entregas. Esta spec cubre **solo la fase 1**.

| | Qué entrega | Estado |
|---|---|---|
| **1** | Dataset (clases, resolución, N tareas), etiquetado a mano con polígonos y pincel, importación de GeoJSON, exportación del dataset | **esta spec** |
| **2** | Store de modelos: importar `.onnx`, validarlo contra el contrato de `geodeep`, listar, borrar. Contrato para otros plugins y `road` consumiéndolo | siguiente |
| **3** | Pre-etiquetado desde un modelo del store, reutilizando `road.segmentation.vectorize_mask` | depende de la 2 |
| **4** | Imagen Docker de entrenamiento (PyTorch + CUDA) para la PC con GPU | fuera de WebODM |

El pre-etiquetado desde un modelo —uno de los cuatro métodos que pidió el usuario— queda en la fase
3 y no aquí, por una razón de dependencia y no de prioridad: necesita el store de la fase 2. Meterlo
ahora obligaría a cablear el modelo `roads` a mano para descablearlo después.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Etiquetar la ortofoto a mano (Priority: P1)

Un usuario abre una tarea procesada, crea un dataset, define sus clases (`background` y `road`, o
las que necesite), y dibuja sobre la ortofoto qué es cada cosa: polígonos para las formas
geométricas, trazos de pincel para las orgánicas. Puede corregir lo dibujado, borrarlo, y encontrarlo
tal cual al volver otro día.

**Why this priority**: sin etiquetas no hay nada. Es el trabajo que ninguna automatización sustituye
y el que consume las horas del usuario, así que es donde la ergonomía decide si el proyecto avanza o
se abandona a la mitad.

**Independent Test**: crear un dataset sobre una tarea, dibujar polígonos y trazos de dos clases,
recargar la página y comprobar que todo sigue ahí, con sus clases y su orden.

**Acceptance Scenarios**:

1. **Given** una tarea con ortofoto, **When** el usuario crea un dataset y define dos clases,
   **Then** el dataset queda guardado con esas clases y su resolución de trabajo.
2. **Given** un dataset con clases definidas, **When** el usuario selecciona una clase y dibuja un
   polígono sobre la ortofoto, **Then** la geometría queda guardada asociada a esa clase y se
   dibuja con su color.
3. **Given** un dataset con clases definidas, **When** el usuario selecciona una clase, elige un
   radio de pincel y arrastra sobre la ortofoto, **Then** queda guardado un trazo de ese radio y esa
   clase, y se dibuja con el grosor que le corresponde sobre el terreno.
4. **Given** una etiqueta ya dibujada, **When** el usuario la selecciona y mueve un vértice o la
   borra, **Then** el cambio se guarda y se refleja en el mapa.
5. **Given** varias etiquetas superpuestas, **When** el usuario dibuja una nueva encima,
   **Then** la nueva prevalece sobre las anteriores en la zona solapada.
6. **Given** un usuario que ha pintado por error, **When** usa el borrador, **Then** la zona
   afectada vuelve a quedar sin etiquetar, no marcada como fondo.

---

### User Story 2 - Exportar el dataset para entrenar fuera (Priority: P1)

El usuario ha etiquetado lo suficiente y quiere entrenar. Pide la exportación y obtiene un fichero
descargable con las teselas de imagen, sus máscaras de etiquetas y un manifiesto que describe todo
lo que la imagen de entrenamiento necesita saber: clases, resolución, tamaño de tesela y qué valor
significa «sin etiquetar».

**Why this priority**: es lo que convierte el trabajo de etiquetado en algo utilizable. US1 sin US2
es un dibujo bonito que no sale de WebODM.

**Independent Test**: exportar un dataset etiquetado, descomprimir el resultado, y comprobar que el
manifiesto describe exactamente el contenido y que las máscaras coinciden píxel a píxel con lo
dibujado.

**Acceptance Scenarios**:

1. **Given** un dataset con etiquetas, **When** el usuario pide la exportación, **Then** obtiene un
   único fichero descargable con imágenes, máscaras y manifiesto.
2. **Given** el fichero exportado, **When** se lee el manifiesto, **Then** declara las clases y sus
   índices, la resolución en cm/px, el tamaño de tesela, el valor de «sin etiquetar» y la lista de
   teselas con su tarea de origen.
3. **Given** un dataset cuyas teselas incluyen zonas sin etiquetar, **When** se abre la máscara
   correspondiente, **Then** esos píxeles llevan el valor de «ignorar» y no el de ninguna clase.
4. **Given** una ortofoto con más resolución que la del dataset, **When** se exporta, **Then** las
   teselas de imagen salen remuestreadas a la resolución del dataset, no a la nativa.
5. **Given** un dataset donde la mayoría del área no está etiquetada, **When** se exporta,
   **Then** las teselas sin contenido etiquetado se omiten y el manifiesto refleja solo las
   incluidas.
6. **Given** una exportación en curso sobre un dataset grande, **When** el usuario mira el panel,
   **Then** ve el progreso y puede seguir usando WebODM.

---

### User Story 3 - Reunir varias tareas en un mismo dataset (Priority: P2)

El usuario comprueba que un solo vuelo no da suficiente material, o quiere que el modelo vea más de
una zona. Añade otras tareas al dataset, las etiqueta igual, y al exportar salen todas juntas en un
único paquete coherente.

**Why this priority**: es lo que separa un modelo que funciona en una mina de uno que funciona en
las minas del usuario. No es P1 porque el modelo de datos ya lo soporta desde US1 y la interfaz de
añadir tareas es incremental.

**Independent Test**: crear un dataset, añadirle dos tareas, etiquetar en ambas, exportar y
comprobar que el paquete trae teselas de las dos con su tarea de origen identificada.

**Acceptance Scenarios**:

1. **Given** un dataset con una tarea, **When** el usuario añade otra tarea con ortofoto, **Then**
   el dataset pasa a incluirla y puede etiquetarse en ella con las mismas clases.
2. **Given** un dataset con dos tareas etiquetadas, **When** se exporta, **Then** el paquete incluye
   teselas de ambas y cada una declara de qué tarea proviene.
3. **Given** un dataset con dos tareas, **When** el usuario abre una de ellas, **Then** ve solo las
   etiquetas de esa tarea, no las de la otra.
4. **Given** una tarea que forma parte de un dataset, **When** esa tarea se borra de WebODM,
   **Then** el dataset sigue abriéndose, indica que esa tarea ya no está disponible y la excluye de
   la exportación en vez de fallar.

---

### User Story 4 - Traer etiquetas hechas fuera (Priority: P2)

El usuario ya tiene polígonos digitalizados en QGIS, o prefiere hacer el trabajo pesado allí. Sube
un GeoJSON, dice qué propiedad del fichero corresponde a la clase, y las geometrías entran en el
dataset como si las hubiera dibujado en el plugin.

**Why this priority**: es la válvula de escape del proyecto. Si el editor del navegador se queda
corto para un volumen grande, esto evita que el usuario quede atrapado. Y cuesta poco comparado con
lo que aporta.

**Independent Test**: subir un GeoJSON con polígonos y una propiedad de clase, mapearla a las clases
del dataset, y comprobar que las geometrías aparecen en el mapa y salen en la exportación.

**Acceptance Scenarios**:

1. **Given** un dataset con clases definidas, **When** el usuario sube un GeoJSON de polígonos y
   asocia una de sus propiedades a las clases, **Then** las geometrías quedan guardadas como
   etiquetas de esas clases.
2. **Given** un GeoJSON con geometrías fuera de la extensión de las ortofotos del dataset,
   **When** se importa, **Then** el sistema avisa de cuántas quedaron fuera en vez de aceptarlas en
   silencio.
3. **Given** un GeoJSON con valores de clase que no corresponden a ninguna clase del dataset,
   **When** se importa, **Then** el sistema lo rechaza indicando qué valores no supo mapear.
4. **Given** un GeoJSON en un sistema de coordenadas distinto, **When** se importa, **Then** las
   geometrías se reproyectan al del dataset o se rechaza el fichero con el motivo exacto.

---

### User Story 5 - Saber si el dataset sirve antes de gastar horas de GPU (Priority: P3)

Antes de exportar, el usuario ve un resumen del dataset: cuántas teselas saldrán, cuánta superficie
tiene cada clase, y qué problemas conocidos lo harían fracasar. Decide entonces si sigue etiquetando
o si ya puede entrenar.

**Why this priority**: el ciclo de realimentación de esta feature es lentísimo —etiquetar, exportar,
mover el fichero a otra máquina, entrenar, volver— y un dataset inservible no se descubre hasta el
final. Es P3 porque no bloquea el flujo, pero es lo que evita repetir el ciclo entero.

**Independent Test**: preparar un dataset sin ninguna etiqueta de la clase de fondo, abrir el
resumen, y comprobar que avisa de ello antes de dejar exportar.

**Acceptance Scenarios**:

1. **Given** un dataset etiquetado, **When** el usuario abre su resumen, **Then** ve cuántas teselas
   producirá la exportación y qué superficie tiene etiquetada cada clase.
2. **Given** un dataset donde solo se han etiquetado zonas de una clase y ninguna de fondo,
   **When** el usuario mira el resumen, **Then** se le advierte de que el modelo no tendrá ejemplos
   negativos que aprender.
3. **Given** un dataset con muy pocas teselas etiquetadas, **When** el usuario mira el resumen,
   **Then** se le advierte de que el volumen es insuficiente, con la cifra concreta.

---

### Edge Cases

- **La tarea no tiene ortofoto.** Sin ortofoto no hay nada que etiquetar. Debe decirse antes de
  dejar crear el dataset, no al exportar.
- **La ortofoto se regenera o cambia después de etiquetar.** Las etiquetas son geometrías
  georreferenciadas, así que siguen siendo válidas mientras la nueva ortofoto cubra la misma zona.
  Si la extensión cambia, hay etiquetas que caen fuera: no deben desaparecer en silencio.
- **Se borra una tarea que pertenece a un dataset.** Cubierto en US3-4: el dataset sobrevive y la
  excluye. Es el caso que distingue este plugin de `road` y `annotations`, donde el borrado en
  cascada por tarea es la respuesta correcta y aquí no lo es.
- **Zonas de la ortofoto sin datos** (el `nodata` del perímetro del vuelo). Una tesela mayormente
  vacía no aporta nada al entrenamiento y encima enseña bordes artificiales.
- **El usuario pinta con el pincel a un zoom muy alejado.** Un radio de pincel definido en píxeles
  de pantalla cubriría decenas de metros de terreno. El radio tiene que ser una medida sobre el
  terreno, no sobre la pantalla.
- **Trazos de pincel muy largos.** Pintar durante minutos genera polilíneas de miles de vértices. El
  volumen guardado tiene que mantenerse acotado sin que el usuario note pérdida de precisión.
- **Dos usuarios etiquetando la misma tarea a la vez.** Sin protección, el último en guardar borra el
  trabajo del otro. `annotations` ya resolvió esto con un advisory lock por documento
  (`annotations/store.py:31-40`).
- **Solape entre etiquetas de clases distintas.** Tiene que haber una regla determinista y visible,
  o dos exportaciones del mismo dataset podrían no coincidir.
- **Exportación de un dataset grande.** Cientos de teselas de imagen más sus máscaras: no puede
  bloquear la petición web ni construirse entero en memoria.
- **Clases modificadas después de etiquetar.** Renombrar una clase es inocuo; borrarla deja
  etiquetas huérfanas apuntando a un índice que ya no existe.

## Requirements *(mandatory)*

### Functional Requirements

**Dataset y clases**

- **FR-001**: Los usuarios DEBEN poder crear datasets, listarlos y borrarlos. Un dataset es una
  entidad propia del plugin, **no** una propiedad de una tarea.
- **FR-002**: Un dataset DEBE poder referenciar varias tareas, y DEBE guardar sus etiquetas por
  separado para cada una.
- **FR-003**: Un dataset DEBE tener una lista ordenada de clases, cada una con un índice entero
  consecutivo desde 0 y un nombre elegido por el usuario. El índice es lo que acaba grabado en las
  máscaras y en los metadatos del modelo entrenado; el nombre es lo que se muestra.
- **FR-004**: El índice 0 DEBE corresponder por convención a la clase negativa o de fondo. Motivo:
  es lo que espera `geodeep`, cuyo modelo de serie declara `class_names = ['not_road', 'road']`.
- **FR-005**: Un dataset DEBE tener una resolución de trabajo en cm/px, fijada al crearlo, con
  **10 cm/px por defecto**.
- **FR-006**: El sistema DEBE impedir borrar una clase que tenga etiquetas asociadas, o exigir
  confirmación explícita indicando cuántas etiquetas se perderán.
- **FR-007**: Cada clase DEBE tener un color distinguible para dibujarla en el mapa, y esos colores
  NO DEBEN coincidir con la escala verde/amarillo/rojo que `road` usa para la pendiente.

**Etiquetado**

- **FR-008**: Los usuarios DEBEN poder dibujar polígonos sobre la ortofoto y asignarlos a una clase
  del dataset.
- **FR-009**: Los usuarios DEBEN poder pintar trazos con un pincel de radio ajustable y asignarlos a
  una clase.
- **FR-010**: El radio del pincel DEBE expresarse en metros sobre el terreno y mantenerse constante
  al hacer zoom.
- **FR-011**: Toda etiqueta —venga de polígono, pincel o importación— DEBE guardarse como una
  geometría georreferenciada con su clase y su posición en un orden explícito. NO se guardan píxeles.
- **FR-012**: Al componer las etiquetas, las posteriores en el orden DEBEN prevalecer sobre las
  anteriores en las zonas solapadas. El orden por defecto es el de creación: lo último dibujado gana.
- **FR-012b**: La conversión de un trazo de pincel a superficie DEBE realizarse en un sistema de
  coordenadas métrico. Justificación: el radio está en metros (FR-010) y en EPSG:4326 se
  interpretaría como grados, dando un trazo unas cinco órdenes de magnitud mayor.
- **FR-013**: Los usuarios DEBEN poder seleccionar, modificar y borrar etiquetas ya creadas.
- **FR-014**: DEBE existir un borrador que devuelva una zona al estado «sin etiquetar», distinto de
  marcarla como clase 0.
- **FR-015**: El sistema DEBE simplificar las geometrías antes de guardarlas, con una tolerancia no
  más fina que la resolución del dataset. Justificación: por debajo de esa resolución la etiqueta no
  contiene información que la exportación pueda representar, así que esos vértices no se pierden —
  nunca llegaron a significar nada.
- **FR-016**: Las etiquetas DEBEN persistirse mediante los mecanismos del framework
  (`GlobalDataStore` y `get_persistent_path()`), **nunca** en rutas ad-hoc del contenedor ni en
  directorios temporales.
- **FR-017**: El sistema DEBE proteger la escritura concurrente de etiquetas de una misma tarea, de
  forma que dos usuarios simultáneos no se pisen el trabajo.

**Importación de GeoJSON**

- **FR-018**: Los usuarios DEBEN poder subir un fichero GeoJSON de polígonos e incorporarlo como
  etiquetas del dataset.
- **FR-019**: El sistema DEBE permitir indicar qué propiedad del GeoJSON contiene la clase, y
  mapear sus valores a las clases del dataset.
- **FR-020**: El sistema DEBE rechazar la importación indicando el motivo exacto cuando haya valores
  de clase sin mapear o el sistema de coordenadas no se pueda resolver. Un rechazo sin motivo obliga
  al usuario a adivinar.
- **FR-021**: El sistema DEBE informar de cuántas geometrías quedaron fuera de la extensión de las
  ortofotos, sin descartarlas en silencio.

**Exportación**

- **FR-022**: Los usuarios DEBEN poder exportar un dataset como un único fichero descargable que
  contenga teselas de imagen, sus máscaras de etiquetas y un manifiesto.
- **FR-023**: Las teselas de imagen DEBEN salir remuestreadas a la resolución del dataset, no a la
  nativa de cada ortofoto, para que todas las tareas del dataset compartan escala.
- **FR-024**: Las teselas DEBEN ser cuadradas, de un tamaño en píxeles configurable por dataset, con
  **512 por defecto**. Justificación: `geodeep` deduce el tamaño de tesela de la forma del tensor de
  entrada del modelo (`tiles_size = inputs[0].shape[-1]`), y el modelo de serie usa 512.
- **FR-025**: Cada tesela de imagen DEBE tener una máscara del mismo tamaño en píxeles, donde el
  valor de cada píxel es el índice de la clase que le corresponde.
- **FR-026**: Los píxeles sin etiquetar DEBEN llevar en la máscara un valor reservado de «ignorar»,
  distinto de cualquier índice de clase, y el manifiesto DEBE declarar cuál es. El valor es **255**,
  por convención de PyTorch (`ignore_index`). Justificación: si lo
  no etiquetado se exportara como clase 0, cada camino que el usuario olvidara marcar se convertiría
  en un ejemplo que le enseña al modelo que los caminos no son caminos. Ese fallo es silencioso y
  arruina el entrenamiento; el fallo contrario —que el modelo no aprenda el fondo— es ruidoso y lo
  avisa FR-032.
- **FR-027**: La exportación DEBE omitir las teselas sin contenido etiquetado y las que no tengan
  suficientes píxeles válidos de ortofoto. Ambos umbrales son configurables por dataset, con estos
  valores por defecto: se descarta la tesela si menos del **1 %** de su superficie está etiquetada, o
  si menos del **50 %** de sus píxeles tienen datos de ortofoto.
- **FR-028**: El manifiesto DEBE declarar, como mínimo: versión del esquema, identidad y nombre del
  dataset, resolución en cm/px, tamaño de tesela, lista de clases con índice y nombre, valor de
  «ignorar», y la lista de teselas con su fichero de imagen, su fichero de máscara, la tarea de
  origen y su extensión geográfica.
- **FR-029**: El manifiesto DEBE ser suficiente por sí solo para entrenar: la imagen de
  entrenamiento de la fase 4 NO DEBE necesitar acceso a WebODM, a su base de datos ni a esta spec
  para interpretar el paquete.
- **FR-030**: La exportación DEBE ejecutarse de forma asíncrona, con progreso visible, sin bloquear
  la interfaz ni construir el paquete completo en memoria.
- **FR-031**: Dos exportaciones del mismo dataset sin cambios intermedios DEBEN producir el mismo
  conjunto de teselas, las mismas máscaras y el mismo manifiesto salvo marcas de tiempo. No se exige
  que el fichero comprimido sea idéntico byte a byte.

**Calidad del dataset**

- **FR-032**: El sistema DEBE mostrar un resumen del dataset con el número de teselas que producirá
  y la superficie etiquetada por clase.
- **FR-033**: El sistema DEBE advertir cuando el dataset no tenga ninguna etiqueta de la clase 0, o
  cuando el número de teselas resultante sea insuficiente para entrenar.
- **FR-034**: Las advertencias NO DEBEN impedir exportar. Informan; la decisión es del usuario.

**Compatibilidad y encaje en el fork**

- **FR-035**: Todo el código nuevo DEBE vivir en `coreplugins/training/`. NO se modifica el core de
  upstream (`app/`, `webodm/`, `worker/`, `nodeodm/`, `nginx/` ni los scripts de raíz).
- **FR-036**: Esta feature NO DEBE cambiar el comportamiento de `road`, `annotations` ni ningún otro
  plugin existente. `road` sigue usando el modelo `roads` de serie hasta la fase 2.
- **FR-037**: El plugin NO DEBE introducir dependencias de sistema nuevas en la imagen, ni
  dependencias de npm en el frontend. Comprobado **en el contenedor `worker`**, que es donde correría
  la exportación: `rasterio 1.3.10`, `numpy 1.26.2`, `Pillow 11.3.0` y GEOS de GeoDjango están
  presentes. `shapely` **no está**, así que el motor geométrico es el GEOS de GeoDjango y
  `rasterio.features.rasterize` se alimenta con diccionarios tipo GeoJSON, que es lo que ya hace
  `road`.

### Key Entities

- **Dataset**: la unidad de trabajo. Agrupa un conjunto de clases, una resolución, un tamaño de
  tesela y una o varias tareas de las que se toman ortofotos y etiquetas. Vive por encima de las
  tareas y sobrevive al borrado de cualquiera de ellas. Es la entidad que se exporta.
- **Clase**: un índice entero y un nombre, dentro de un dataset. El índice es el contrato con el
  modelo entrenado; el nombre es para el usuario. La clase 0 es el fondo.
- **Etiqueta**: una geometría georreferenciada con una clase y una posición en el orden de
  composición. Un polígono dibujado, un trazo de pincel (una polilínea con un radio en metros) y un
  polígono importado son la misma cosa con distinta procedencia. No hay píxeles guardados en ningún
  sitio: los píxeles solo existen en el momento de exportar.
- **Exportación**: el paquete producido a partir de un dataset en un instante dado. Contiene teselas
  de imagen, máscaras y manifiesto. Es un artefacto derivado y desechable: se puede volver a generar
  desde el dataset.
- **Tarea** (existente, del core): aporta la ortofoto y su georreferenciación. El plugin la lee y
  nunca la modifica.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un usuario puede etiquetar una ortofoto y obtener un paquete de entrenamiento sin
  salir de WebODM, sin herramientas externas y sin asistencia técnica. Hoy no existe ningún camino
  para hacerlo.
- **SC-002**: El paquete exportado es interpretable por un programa que solo tiene el fichero:
  alguien que reciba el `.zip` y nada más puede escribir el cargador de datos leyendo únicamente el
  manifiesto.
- **SC-003**: Las máscaras exportadas coinciden con lo dibujado. Sobre un dataset de prueba con
  geometrías conocidas, la máscara resultante es idéntica píxel a píxel a la esperada, incluida la
  regla de precedencia por orden.
- **SC-004**: Etiquetar con pincel una pista de tierra de 100 m de longitud lleva menos tiempo que
  dibujarla con polígonos. Es la razón de ser del pincel; si no se cumple, no compensa su coste.
- **SC-005**: Las etiquetas sobreviven a recargas de página, a reinicios del contenedor y al borrado
  de una de las tareas del dataset.
- **SC-006**: Un dataset sobre las 5 tareas actuales del usuario produce del orden de **cientos** de
  teselas de 512 px a 10 cm/px, y no decenas. Derivado de dos cifras medidas —3612 teselas a
  resolución nativa y 172 a 21 cm/px— por la ley del cuadrado inverso: unas **758** a 10 cm/px. La
  cifra exacta debe remedirse durante la implementación.
- **SC-007**: Exportar un dataset de varios cientos de teselas no bloquea la interfaz ni agota la
  memoria del contenedor.
- **SC-008**: Un usuario que ha etiquetado solo una clase es advertido antes de exportar, no después
  de perder horas de GPU.

## Assumptions

- **El plugin se llama `training`.** Cubre el ciclo completo —etiquetar, exportar, y en fases
  posteriores almacenar y servir modelos—, así que el nombre describe el propósito y no una de sus
  partes. Cambiarlo ahora es trivial; después de la fase 2 implicaría romper el contrato con `road`.
- **Un trazo de pincel se guarda como una polilínea con un radio, no como píxeles.** Es la decisión
  estructural de la feature. Hace que los cuatro métodos de etiquetado converjan en una sola entidad,
  mantiene todo independiente de la resolución —se puede reexportar a 20 cm/px sin volver a
  etiquetar—, permite borrar un trazo concreto (imposible si fueran píxeles) y hace que el borrador
  sea simplemente un trazo que devuelve al estado sin etiquetar.
- **La cadena «trazo → superficie → máscara» está comprobada, no supuesta.** Ejecutada en el
  contenedor `worker` con el código que usaría la implementación: una polilínea de 20 m en UTM con
  radio 2,5 m da un polígono de 118,14 m², y al rasterizarla a 10 cm/px con relleno 255 salen 11 825
  píxeles de clase 1 — 118,25 m², coincidente con el área del polígono— y el resto a «ignorar». El
  mecanismo central de la feature funciona con lo que ya hay instalado.
- **Pintar el fondo es barato gracias a la regla de precedencia por orden.** Un polígono enorme de
  clase 0 sobre toda la zona, y encima los caminos: cuatro clics. Sin esa regla, exigir fondo
  explícito (FR-026) sería una carga inaceptable; con ella, es asumible. Las dos decisiones se
  sostienen mutuamente.
- **10 cm/px por defecto.** Elegido con el usuario entre las tres opciones medidas. Da del orden de
  760 teselas (frente a 172 a 21 cm/px, insuficientes) y conserva contexto de terreno: 51 m por
  tesela, suficiente para que el modelo distinga una pista de un descampado, cosa que a 2,5 cm/px —
  13 m por tesela— no puede hacer. Además 10 divide limpiamente contra ortofotos de 2,5 y 5 cm/px,
  lo que importa porque `geodeep` calcula el factor de escala con **división entera**
  (`scale_factor = int(model_res // input_res)`): una resolución que no divide limpio produce una
  escala efectiva distinta de la declarada. Y si la ortofoto es más gruesa que el modelo, `geodeep`
  **no interpola** y corre a la escala equivocada sin avisar.
- **El editor se construye extendiendo `PolylineEditor`**, no con una librería nueva. Las 291 líneas
  de `annotations/public/PolylineEditor.js` ya resuelven trazado, arrastre de vértices, inserción,
  borrado y —lo que más caro habría salido descubrir— la interacción con el popup de la ortofoto del
  core durante el trazado. Un polígono es una polilínea cerrada; un trazo de pincel es una polilínea
  con un radio. No se añaden dependencias de npm.
- **El lienzo de etiquetado es el mapa que ya existe.** El core sirve teselas de la ortofoto
  (`app/api/urls.py:46`), así que el plugin dibuja encima como ya hacen `road` y `annotations`.
- **El entrenamiento y la vuelta del modelo quedan fuera de esta spec.** El traspaso entre máquinas
  es manual: se descarga el paquete, se entrena en la PC con GPU, y en la fase 2 se sube el `.onnx`.
  Las dos máquinas nunca se comunican.
- **El modelo de datos soporta varias tareas desde el principio**, aunque la interfaz para añadirlas
  sea US3. Hacerlo al revés obligaría a rehacer el formato de exportación, porque «de qué tarea viene
  esta etiqueta» pasaría de implícito a explícito.

## Dependencies

- Requiere tareas con ortofoto procesada. Sin ortofoto no hay nada que etiquetar ni que exportar.
- Reutiliza `rasterio` y GEOS de GeoDjango, ya presentes en la imagen y ya usados por `road`.
- Reutiliza el patrón de persistencia de `annotations` (`GlobalDataStore` con bloqueo por documento)
  y el editor de geometría de su frontend.
- La fase 4 (imagen de entrenamiento) depende del formato que fija esta spec, no al revés.
- La fase 2 (store de modelos) depende de que esta produzca datasets con los que entrenar.

## Fuera de alcance

- Entrenar modelos. Ni aquí ni en ninguna otra parte de WebODM.
- Importar, validar, almacenar o servir modelos `.onnx`. Es la fase 2.
- Pre-etiquetar con un modelo existente. Es la fase 3, y depende de la 2.
- Cambiar el modelo que usa `road`. Sigue con el `roads` de serie hasta la fase 2.
- Aumentación de datos, partición en entrenamiento y validación, y balanceo de clases: son
  decisiones del entrenamiento, y van en la imagen de la fase 4 sobre el paquete que esta produce.
- Etiquetado de detección de objetos (cajas). Esta feature es de segmentación semántica.
- Etiquetar sobre el DEM, la nube de puntos o las fotos originales. Solo ortofoto.
- Colaboración en tiempo real entre varios usuarios sobre el mismo dataset. Se protege la escritura
  concurrente (FR-017), que no es lo mismo.
- Versionado de datasets o historial de cambios de las etiquetas.
- Cualquier comunicación automática entre WebODM y la máquina de entrenamiento.
