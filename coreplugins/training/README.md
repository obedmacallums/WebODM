# Training

Convierte la ortofoto de una tarea procesada en un dataset de segmentación listo para entrenar
**fuera** de WebODM.

El plugin cubre la primera mitad del camino: etiquetar y sacar los datos. El entrenamiento ocurre
en otra máquina, en una imagen con PyTorch y CUDA, porque `webapp` y `worker` comparten imagen y
meter el entrenamiento aquí engordaría también los workers de procesado.

## Qué hace

- **Datasets** que agrupan una o varias tareas, con sus clases, su resolución de trabajo (10 cm/px
  por defecto) y su tamaño de tesela (512 px por defecto). Un dataset vive por encima de las tareas
  y sobrevive al borrado de cualquiera de ellas.
- **Etiquetado sobre el mapa** con polígonos, un pincel de radio ajustable y un borrador. Las
  etiquetas se guardan como geometrías georreferenciadas, nunca como píxeles: eso permite
  reexportar a otra resolución sin volver a etiquetar y borrar un trazo concreto.
- **Selección asistida**: un clic sobre la calzada y la herramienta se queda con la región que hay
  debajo, siguiendo el borde visible. No clasifica nada —la clase la sigue poniendo el usuario—;
  lo que se ahorra es el trazado del contorno, que es donde se va el tiempo.
- **Exportación asíncrona** a un `.zip` con teselas de imagen, sus máscaras y un manifiesto que se
  basta a sí mismo.

## Dos cosas que hay que entender antes de tocarlo

**El radio del pincel es una medida sobre el terreno, no sobre la pantalla.** Un radio en píxeles
cubriría decenas de metros a zoom alejado. El grosor dibujado se recalcula en cada cambio de zoom
(`labelLayer.strokeWeightPx`) y el buffer al rasterizar se hace en el CRS métrico de la ortofoto.

**255 significa «sin etiquetar», y no es la clase 0.** Si lo no etiquetado se exportara como fondo,
cada camino que el usuario olvidara marcar sería un ejemplo enseñándole al modelo que los caminos
no son caminos. Ese fallo es silencioso y arruina el entrenamiento. Por eso el borrador devuelve a
255 y no a 0, y por eso las máscaras nacen llenas de 255 en vez de con `zeros()`.

## `requirements.txt`: por qué numpy y scipy van pineados

**No son redundantes y quitarlos rompe `rasterio` en silencio.** Es lo primero que le parece
sobrante a quien abre ese fichero, así que conviene tenerlo escrito.

El instalador del framework (`app/plugins/plugin_base.py:44`) ejecuta

```
pip install -U -r requirements.txt --target <plugin>/site-packages
```

**sin `--no-deps`**, y `PluginBase.python_imports()` hace `sys.path.insert(0, ...)` con ese
directorio: lo que caiga ahí **tapa** a lo que trae la imagen. `scikit-image` declara `numpy>=1.23`,
así que sin pin `pip` deja al lado un numpy 2.x y `rasterio` —compilado contra el 1.26.2 de la
imagen— revienta al primer `import` con

```
ValueError: numpy.dtype size changed, may indicate binary incompatibility.
            Expected 96 from C header, got 88 from PyObject
```

El fallo aparece lejos de su causa: en una exportación, dentro del worker, sobre un plugin «que no
se ha tocado». Con los pines, `pip` instala copias con la misma ABI y todo convive (246 MB
duplicados, justificados en el plan de `010`). `--no-deps` lo resolvería sin duplicar, pero el
instalador del core no lo pasa y el core no se modifica (Principio I).

`tests/test_requirements.py` es el aviso: si un merge de upstream sube numpy o scipy en la imagen,
ese test se pone rojo con la versión nueva en el mensaje. Actualizar los pines a lo que diga.

**Ese fichero no admite comentarios.** `app/plugins/pyutils.py:parse_requirements` no filtra las
líneas que empiezan por `#`: toma toda línea no vacía como nombre de paquete, así que una sola línea
de comentario hace que `requirements_installed()` devuelva `False` para siempre. Consecuencia
medida: `WARNING Failed to install requirements.txt` aunque pip termine bien, y 246 MB reinstalados
en **cada arranque** (~8 s). Por eso la explicación vive aquí y no allí, y por eso hay un test que
comprueba que nadie vuelva a meter comentarios.

## Estructura

| Fichero | Qué hace |
|---|---|
| `plugin.py` | Menú global, página de datasets y rutas de la API |
| `models.py` | Entidades puras y sus validaciones. Sin ORM: el plugin no añade migraciones |
| `store.py` | Índice en `GlobalDataStore`, etiquetas y paquetes en fichero, advisory lock |
| `api.py` | Vistas REST y la función que se despacha al worker |
| `tiling.py` | Rejilla de teselas de una ortofoto a la resolución del dataset |
| `rasterize.py` | Etiquetas → máscara de una tesela |
| `export.py` | Construcción del `.zip` y del manifiesto |
| `elevation.py` | Canales de pendiente y rugosidad del DTM, alineados a la rejilla de salida |
| `superpixels.py` | Rejilla de trabajo, partición en regiones, costura de juntas y vectorización |
| `regions.py` | Caché en disco de las particiones por celda y el proveedor que las sirve |
| `public/` | Página global, panel del mapa, editor y capa de dibujo |

### La rejilla de trabajo de la selección asistida

La ortofoto se parte en **celdas disjuntas de 512 px** a la resolución del dataset —51,2 m a
10 cm/px— ancladas a su esquina superior izquierda. **No es la rejilla de teselas de exportación**
(`tiling.py`), que se solapa por diseño; aquí las celdas tienen que ser disjuntas para que cada
punto del terreno pertenezca a una y solo una, que es de donde salen el determinismo y la
independencia del encuadre.

Cada celda se calcula sobre una ventana con **halo de `8·S`** píxeles y se conserva solo el núcleo.
Dos detalles que no se pueden tocar sin romper la feature, los dos medidos y con test:

1. **El origen de cada ventana es múltiplo de `S`.** SLIC siembra cada `S` px empezando en `S/2`
   *relativo a la ventana*, así que dos ventanas desalineadas parten el mismo terreno de formas
   distintas: 11,3 % de desacuerdo desalineadas frente a 0,96 % alineadas.
2. **Una región que cruza una junta se cose**, no se recalcula. Sin coser, la región se queda en un
   IoU de 0,79 contra la partición sin junta —le falta el trozo del otro lado, y eso se ve como un
   corte recto—; cosiendo sube a 0,981 y ahí se estanca, que es lo que fija el halo en `8·S`.

Lo sostiene `tests/test_superpixels.py::SeamTest`. Es invisible en revisión de código: romperlo no
lanza ningún error, solo hace que de vez en cuando una región termine en una línea recta perfecta.

## Contratos

- **Paquete exportado**: [`specs/009-training-dataset-labeling/contracts/dataset-package.md`](../../specs/009-training-dataset-labeling/contracts/dataset-package.md).
  Es el contrato más caro de cambiar: lo consume a ciegas la imagen de entrenamiento, desde otro
  repositorio y otra máquina.
- **API HTTP**: [`specs/009-training-dataset-labeling/contracts/rest-api.md`](../../specs/009-training-dataset-labeling/contracts/rest-api.md),
  ampliado con las dos rutas de selección asistida en
  [`specs/010-superpixel-labeling/contracts/rest-api.md`](../../specs/010-superpixel-labeling/contracts/rest-api.md).

La selección asistida **no toca el contrato del paquete exportado**, y no por casualidad: produce
etiquetas `kind: polygon`, que ya existían, así que `rasterize.py` y `export.py` ni se enteran. Solo
aparece un valor más en `source` (`assisted`), que el paquete no exporta.

## Tests

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests
```

**Nunca** `./run_tests_in_docker.sh`: hace `docker compose down -v` y borraría las tareas reales de
la instancia.

Los tests de JavaScript (`public/tests/`) corren con `node` + `jsdom` desde `tests/test_frontend.py`,
así que entran en la misma orden. Se saltan si no hay `node`.

**Al añadir un módulo de test hay que reexportarlo en `tests/__init__.py`.** Si no, no se ejecuta y
la suite sigue en verde.

## Lo que no hace (todavía)

Esta entrega es la fase 1: US1 (etiquetar) y US2 (exportar). Quedan para después:

- Interfaz para añadir varias tareas a un dataset — el modelo de datos ya lo soporta.
- Importar etiquetas desde GeoJSON.
- Resumen de calidad del dataset antes de exportar.
- Store de modelos `.onnx` y pre-etiquetado con un modelo (fases 2 y 3).
