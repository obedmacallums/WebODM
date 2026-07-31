# Contrato — Paquete de dataset exportado

Feature: `009-training-dataset-labeling`. Versión de esquema: **1**.

Este es el contrato más caro de cambiar de toda la feature. Lo consume **a ciegas** la imagen de
entrenamiento de la fase 4, desde otro repositorio y otra máquina, sin acceso a WebODM ni a esta
spec. Todo lo necesario para entrenar tiene que estar dentro del fichero (FR-029).

## Estructura

```text
<nombre-del-dataset>-<fecha>.zip
├── manifest.json
├── images/
│   ├── <task_id>_<fila>_<columna>.png     RGB, 8 bits, tile_size × tile_size
│   └── ...
└── labels/
    ├── <task_id>_<fila>_<columna>.png     un canal, 8 bits, mismas dimensiones
    └── ...
```

Cada tesela de `images/` tiene exactamente una máscara con el **mismo nombre** en `labels/`. El
emparejamiento por nombre es intencionado: un cargador de datos puede construirse sin leer el
manifiesto, aunque el manifiesto sigue siendo la fuente de verdad.

## Teselas de imagen

- **PNG RGB de 8 bits**, sin canal alfa. La ortofoto tiene cuatro bandas y la cuarta es alfa
  ([D7](../research.md#d7)), pero el alfa **no se exporta**: se usa solo para decidir si la tesela
  entra en el paquete. Los modelos de segmentación esperan tres canales.
- Remuestreadas a `resolution_cm_px`, no a la resolución nativa de la ortofoto (FR-023). Todas las
  teselas del paquete comparten escala aunque vengan de vuelos con GSD distinto — en las cinco tareas
  de referencia el GSD nativo va de 2,22 a 6,35 cm/px.
- Sin georreferenciación embebida. Las coordenadas están en el manifiesto; el entrenamiento no las
  necesita y un GeoTIFF encarecería el paquete sin beneficio.

## Máscaras de etiquetas

- **PNG de un canal, 8 bits**. El valor de cada píxel es el índice de la clase.
- **255 significa «sin etiquetar»** y el entrenamiento debe ignorar esos píxeles. Es la convención
  `ignore_index` de PyTorch, y por eso ese valor exacto.
- Sin paleta de colores. Los valores son índices, no colores; añadir una paleta invitaría a que un
  visor los reinterprete.

**Esta es la parte del contrato que más fácil se malinterpreta.** Un cargador que trate el 255 como
una clase más entrenará un modelo que aprende a predecir «sin etiquetar», que no significa nada. Un
cargador que trate el 255 como fondo enseñará que todo lo que el usuario no marcó es fondo — el fallo
silencioso que FR-026 existe para evitar.

## `manifest.json`

```json
{
  "schema_version": 1,
  "dataset": {
    "id": "…uuid…",
    "name": "Pistas mineras",
    "created_at": "2026-07-30T18:00:00Z",
    "exported_at": "2026-07-30T18:42:11Z"
  },
  "resolution_cm_px": 10.0,
  "tile_size_px": 512,
  "ignore_index": 255,
  "classes": [
    {"index": 0, "name": "background"},
    {"index": 1, "name": "road"}
  ],
  "source_tasks": [
    {
      "task_id": "…uuid…",
      "name": "Mina La Coipa - 5/2/2026",
      "native_resolution_cm_px": 6.35,
      "crs": "EPSG:32719"
    }
  ],
  "tiles": [
    {
      "image": "images/<task_id>_012_007.png",
      "label": "labels/<task_id>_012_007.png",
      "task_id": "…uuid…",
      "row": 12,
      "column": 7,
      "bounds": [-70.71, -33.35, -70.70, -33.34],
      "labeled_fraction": 0.62,
      "valid_fraction": 1.0,
      "class_pixels": {"0": 180000, "1": 42000}
    }
  ]
}
```

### Campos y por qué están

| Campo | Por qué está |
|---|---|
| `schema_version` | Permite que la imagen de entrenamiento rechace un paquete que no entiende, en vez de malinterpretarlo |
| `resolution_cm_px` | Debe grabarse en los metadatos del `.onnx`. La librería de inferencia remuestrea la ortofoto a esta escala; si no coincide, el modelo corre a una escala que no es la suya |
| `tile_size_px` | La librería de inferencia lo deduce de la forma de la entrada del modelo, así que el modelo debe entrenarse con este tamaño |
| `ignore_index` | Explícito para que el cargador no tenga que suponerlo |
| `classes` | Los nombres van a los metadatos del `.onnx`; los índices son el contrato con las máscaras |
| `native_resolution_cm_px` | Diagnóstico: permite ver cuánto se remuestreó cada tarea |
| `bounds` | Para poder volver a situar una tesela en el mapa al depurar. En coordenadas geográficas, orden (oeste, sur, este, norte) |
| `labeled_fraction`, `valid_fraction` | Permiten al entrenamiento filtrar más si quiere, sin reexportar |
| `class_pixels` | Permite calcular pesos por clase sin recorrer todas las máscaras |

`class_pixels` no incluye el 255: los píxeles ignorados se deducen restando del total.

## Advertencia sobre la resolución, para quien implemente la fase 4

La librería de inferencia calcula el factor de escala con **división entera**:

```python
if input_res < model_res:
    scale_factor = int(model_res // input_res)
```

Dos consecuencias que el entrenamiento debe conocer:

1. Una resolución de modelo que no divide limpio contra la de la ortofoto produce una escala efectiva
   distinta de la declarada. Con 10 cm/px esto se comporta bien frente a ortofotos de 2,5 y 5 cm/px.
2. Si la ortofoto es **más gruesa** que el modelo, no se interpola: el modelo corre a la escala
   equivocada y nadie avisa.

## Compatibilidad

`schema_version` se incrementa ante cualquier cambio que rompa a un lector existente: renombrar o
quitar campos, cambiar el significado del 255, o cambiar el formato de imágenes o máscaras. Añadir
campos opcionales no lo incrementa.
