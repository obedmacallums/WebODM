# Contrato — Paquete de dataset exportado

Feature: `009-training-dataset-labeling`. Versión de esquema: **2**.

Este es el contrato más caro de cambiar de toda la feature. Lo consume **a ciegas** la imagen de
entrenamiento de la fase 4, desde otro repositorio y otra máquina, sin acceso a WebODM ni a esta
spec. Todo lo necesario para entrenar tiene que estar dentro del fichero (FR-029).

> **Cambios frente al esquema 1**: teselas en GeoTIFF de 5 bandas en vez de PNG RGB, `labels/` pasa
> a llamarse `masks/`, `manifest.json` pasa a llamarse `dataset.json`, y aparecen el bloque de
> normalización, el reparto train/val y los contadores de curación. Un lector del esquema 1 **no**
> lee un paquete del 2; por eso sube la versión.

## Estructura

```text
<export_id>.zip
├── dataset.json
├── images/
│   ├── <task_id>_<fila>_<columna>.tif    GeoTIFF, 5 bandas, tile_size × tile_size
│   └── ...
└── masks/
    ├── <task_id>_<fila>_<columna>.tif    GeoTIFF, 1 banda uint8, mismas dimensiones
    └── ...
```

Cada tesela de `images/` tiene exactamente una máscara con el **mismo nombre** en `masks/`. El
emparejamiento por nombre es intencionado: un cargador puede construirse sin leer `dataset.json`,
aunque `dataset.json` sigue siendo la fuente de verdad.

El zip va **sin comprimir** (`ZIP_STORED`): los GeoTIFF ya llevan DEFLATE dentro, y comprimir dos
veces solo cuesta tiempo.

## Teselas de imagen

**GeoTIFF de 5 bandas**, `float32` por defecto, con CRS y `transform` propios: cada tesela sabe
dónde está sin necesidad del manifiesto. Las bandas llevan su nombre en `descriptions`.

| # | Banda       | Origen   | Rango | Contenido |
|---|-------------|----------|-------|-----------|
| 1 | `red`       | ortofoto | [0,1] | `valor / 255` |
| 2 | `green`     | ortofoto | [0,1] | `valor / 255` |
| 3 | `blue`      | ortofoto | [0,1] | `valor / 255` |
| 4 | `slope`     | DTM      | [0,1] | `clip(grados / 45, 0, 1)` |
| 5 | `roughness` | DTM      | [0,1] | `clip(metros / ceiling_m, 0, 1)` |

**Siempre 5 bandas**, incluso con `elevation_source: "none"` (las dos últimas salen a cero). Un
paquete con teselas de distinto número de bandas no lo carga el mismo código, y descubrirlo a mitad
de un entrenamiento cuesta más que dos bandas de ceros. Una tarea sin ráster de elevación se salta
entera y aparece en `skipped_tasks` con el motivo (FR-044).

El alfa de la ortofoto **no se exporta**: se usa para decidir qué píxeles son válidos
([D7](../research.md#d7)). Los píxeles sin datos van a **cero en las cinco bandas** y a 255 en la
máscara ([D23](../research.md#d23)).

`pixel_dtype: "uint16"` es una alternativa por dataset: los valores se guardan como
`round(v * uint16_scale)` y hay que dividir por `uint16_scale` al cargar. Cuesta la mitad de disco
(1,67 MB/tesela frente a 3,28 medidos, [D17](../research.md#d17)).

### Normalización

`dataset.json` declara la fórmula **escrita** y sus constantes, banda a banda, en
`normalization.bands` (FR-045). La inferencia tiene que aplicar exactamente la misma transformación.

`roughness` **no es el TRI de Riley**: es el RMS del residuo respecto al plano de mínimos cuadrados
de la ventana 3×3, en metros. Vale cero sobre cualquier plano, esté inclinado o no. La razón, con
las medidas, en [D21](../research.md#d21); el campo `definition` lo dice dentro del propio paquete.

`ceiling_m` se mide por exportación (p98 sobre una muestra de teselas) y **cambia entre datasets**:
hay que leerlo del paquete, nunca cablearlo.

## Máscaras

GeoTIFF de **1 banda `uint8`** con `nodata = 255`, mismo CRS y mismo `transform` que su imagen —
alineación píxel a píxel garantizada, y comprobada tesela a tesela por la suite.

| Valor  | Significado |
|--------|-------------|
| `0`    | **Fondo revisado**: alguien miró ese terreno y no es camino. Es una etiqueta real y el modelo aprende de ella. |
| `1..n` | Índice de clase, según `classes`. |
| `255`  | **No revisado o sin datos.** Se excluye de la pérdida (`ignore_index=255`). |

La distinción entre `0` y `255` es de donde depende la calidad del dataset (FR-040). El `0` solo
aparece dentro de las áreas que el anotador declaró revisadas ([D18](../research.md#d18)).

## `dataset.json`

```jsonc
{
  "schema_version": 2,
  "dataset": {"id": "...", "name": "...", "created_at": "...", "exported_at": "..."},

  "resolution_cm_px": 10.0,
  "tile_size_px": 512,
  "tile_overlap_px": 64,        // las teselas SE SOLAPAN
  "stride_px": 448,             // tile_size - overlap: el paso real de la rejilla
  "bands": ["red", "green", "blue", "slope", "roughness"],
  "pixel_dtype": "float32",
  "uint16_scale": null,         // el divisor, cuando pixel_dtype es uint16
  "ignore_index": 255,
  "background_index": 0,
  "elevation_source": "dtm",

  "normalization": {
    "bands": [ /* una entrada por banda: name, formula y sus constantes */ ],
    "output_range": [0.0, 1.0]
  },

  "classes": [{"index": 0, "name": "background"}, {"index": 1, "name": "road"}],

  "split": {
    "strategy": "geographic_blocks",
    "block_tiles": 4,
    "requested_val_fraction": 0.2,
    "seed": "<id del dataset>",
    "train_tiles": 39, "val_tiles": 16,
    "dropped_by_gutter": 9,
    "warning": null             // no null si no salió conjunto de validación
  },

  "curation": {
    "min_reviewed_fraction": 0.9,
    "min_valid_fraction": 0.8,
    "negative_tiles": 42,        // revisadas sin ninguna clase encima
    "hard_negative_tiles": 0,
    "hard_negative_fraction": 0.0
  },

  "source_tasks": [{"task_id": "...", "crs": "EPSG:32719",
                    "native_resolution_cm_px": 6.35,
                    "elevation_source": "dtm", "roughness_ceiling_m": 0.0729}],
  "skipped_tasks": [{"task_id": "...", "reason": "..."}],

  "tiles": [{
    "tile_id": "<task>_0014_0014",
    "image": "images/<task>_0014_0014.tif",
    "mask":  "masks/<task>_0014_0014.tif",
    "task_id": "...", "row": 14, "column": 14,
    "split": "train",            // "train" | "val" — NUNCA repartir al azar por tesela
    "block": [3, 3],
    "origin": [475306.26, 7036379.6],   // esquina superior izquierda, CRS métrico
    "bounds": [...],             // en el CRS de la ortofoto
    "bounds_wgs84": [...],
    "reviewed_fraction": 1.0,
    "valid_fraction": 1.0,
    "positive_fraction": 0.105,  // superficie con clase distinta del fondo
    "hard_negative": false,
    "class_pixels": {"0": 234649, "1": 27495}   // sin el 255: se deduce restando
  }]
}
```

## Reglas que el cargador DEBE respetar

1. **Usar el `split` que viene dado.** Las teselas se solapan 64 px: repartirlas al azar mete
   píxeles de validación en el entrenamiento y la métrica deja de significar nada
   ([D19](../research.md#d19)). El campo ya viene calculado con esa garantía.
2. **Excluir el 255 de la pérdida** (`ignore_index=255`, o una máscara de validez multiplicando).
3. **Leer `ceiling_m` del paquete**, no cablearlo: se mide por exportación.
4. **No suponer que hay conjunto de validación.** Si `split.warning` no es `null`, no lo hay.
5. **Vigilar `curation.hard_negative_fraction`**: la especificación pide mantenerla en 20-30 %.

`class_pixels` no incluye el 255: los píxeles ignorados se deducen restando del total. Sirve para
calcular pesos por clase sin recorrer todas las máscaras.

## Advertencia sobre la resolución, para quien implemente la fase 4

La librería de inferencia calcula el factor de escala con **división entera**:

```python
if input_res < model_res:
    scale_factor = int(model_res // input_res)
```

Dos consecuencias que el entrenamiento debe conocer:

1. Una resolución de modelo que no divide limpio contra la de la ortofoto produce una escala
   efectiva distinta de la declarada. Con 10 cm/px esto se comporta bien frente a ortofotos de 2,5
   y 5 cm/px.
2. Si la ortofoto es **más gruesa** que el modelo, no se interpola: el modelo corre a la escala
   equivocada y nadie avisa.

## Determinismo

Dos exportaciones del mismo dataset sin cambios producen las mismas teselas, las mismas máscaras,
el mismo reparto train/val y el mismo `dataset.json` salvo `exported_at` (FR-031). El reparto usa
el identificador del dataset como semilla, así que las métricas de dos entrenamientos son
comparables. No se exige que el zip sea idéntico byte a byte.

## Compatibilidad

`schema_version` se incrementa ante cualquier cambio que rompa a un lector existente: renombrar o
quitar campos, cambiar el significado del 255, o cambiar el formato de imágenes o máscaras. Añadir
campos opcionales no lo incrementa.
