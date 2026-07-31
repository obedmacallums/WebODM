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
| `public/` | Página global, panel del mapa, editor y capa de dibujo |

## Contratos

- **Paquete exportado**: [`specs/009-training-dataset-labeling/contracts/dataset-package.md`](../../specs/009-training-dataset-labeling/contracts/dataset-package.md).
  Es el contrato más caro de cambiar: lo consume a ciegas la imagen de entrenamiento, desde otro
  repositorio y otra máquina.
- **API HTTP**: [`specs/009-training-dataset-labeling/contracts/rest-api.md`](../../specs/009-training-dataset-labeling/contracts/rest-api.md).

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
