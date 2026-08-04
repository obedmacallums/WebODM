# Modelo de datos

Esta feature **no añade ninguna entidad persistente nueva al dominio**. Extiende el documento del
dataset con un bloque de ajustes, reutiliza la entidad Etiqueta tal cual, e introduce dos estructuras
puramente derivadas —reconstruibles en cualquier momento a partir de la ortofoto— que viven en caché.

Referencia de las entidades existentes: [`specs/009-training-dataset-labeling/data-model.md`](../009-training-dataset-labeling/data-model.md).

---

## Ajustes de asistencia *(campo nuevo en Dataset)*

Bloque `assist` dentro del documento del dataset (`GlobalDataStore('training')`, clave
`dataset_<id>`). Se lee y escribe con `store.update_dataset`, bajo el advisory lock que el plugin ya
usa.

| Campo | Tipo | Por defecto | Validación |
|---|---|---|---|
| `granularity` | cadena | `'medium'` | uno de `fine` / `medium` / `coarse`, que corresponden a un paso `S` de 8 / 16 / 32 px |
| `tolerance` | número | `0.0` | `0.0 ≤ t ≤ 1.0`. `0.0` selecciona exactamente una región |
| `elevation_weight` | número | `1.0` | `0.0 ≤ w ≤ 1.0`. `0.0` desactiva los canales de terreno |

Reglas:

- Cambiar cualquiera de los tres **no modifica ninguna etiqueta ya guardada** (FR-023). Solo afecta a
  las selecciones siguientes.
- Los tres forman parte de la clave de la caché de mapas de regiones, así que cambiarlos la invalida
  sin necesidad de código de invalidación (research.md D5).
- Un dataset creado antes de esta feature no tiene el bloque: `with_defaults()` lo rellena al leer,
  como ya hace con los demás campos añadidos después.

---

## Rejilla de trabajo *(derivada, no se persiste)*

Partición de la ortofoto de una tarea en celdas cuadradas sin solape. **No es la rejilla de teselas de
exportación**, que sí se solapa por diseño y por eso no serviría (research.md D2).

| Propiedad | Valor |
|---|---|
| Lado del núcleo | `CELL = 512` px a la resolución de trabajo del dataset |
| Halo de cálculo | `8 · S` px por cada lado |
| Anclaje | esquina superior izquierda de la ortofoto, igual criterio que `tiling.py` |
| Invariantes | `S` divide a `CELL`; el origen de cada ventana es múltiplo de `S` en coordenadas globales de la ortofoto |

La identidad de una celda es `(fila, columna)` sobre esa rejilla. Es **función únicamente del punto
del terreno**: no depende del encuadre, del zoom ni del orden de los clics, que es lo que hace
cumplir FR-007 y FR-008.

---

## Mapa de regiones *(derivado, en caché)*

Partición del núcleo de una celda en regiones. Se guarda comprimido bajo `get_persistent_path()`.

| Campo | Tipo | Notas |
|---|---|---|
| `labels` | matriz `int32` de `CELL × CELL` | índice de región de cada píxel |
| `means` | matriz `float32` de `n_regiones × n_bandas` | vector medio por región, alimenta el crecimiento por tolerancia |
| `adjacency` | pares de índices | vecindad entre regiones, derivada del mapa |
| `elevation_source` | cadena | `dtm`, `dsm` o `none`; lo que respondió `elevation.resolve_source` |
| `band_count` | entero | 3 sin canales de terreno, 5 con ellos |

Clave de caché: `(task_id, resolución de trabajo, S, elevation_weight, versión del algoritmo)`.

Incluir la **versión del algoritmo** es deliberado: sin ella, un cambio futuro en la partición
convivirá con mapas viejos y romperá el determinismo de FR-007 en silencio.

Ciclo de vida: se crea al primer clic sobre la celda, se reutiliza en los siguientes, y se expulsa
por antigüedad de acceso cuando el dataset supera su presupuesto de caché. **Perderlo no pierde
nada**: se reconstruye en 0,951 s medidos.

Medido: 1089 regiones en el núcleo de una celda; 1,05 MB en `int32` antes de comprimir.

---

## Región asistida *(derivada, efímera)*

Un elemento del mapa de regiones. Es la unidad mínima que un clic añade.

- **No tiene clase.** La clase se la da el usuario al seleccionarla; la herramienta no opina sobre
  qué hay en el terreno (es la frontera de alcance de la spec).
- Su geometría se deriva del mapa por vectorización, no se almacena.
- Una región puede cruzar el borde de una celda. Sale idéntica desde las dos celdas vecinas
  (0,000 % de desacuerdo medido con halo `8S`), así que la unión no tiene junta.

---

## Etiqueta *(entidad existente, un valor nuevo)*

Sin cambios estructurales. Una selección asistida produce una etiqueta corriente:

| Campo | Valor que produce esta feature |
|---|---|
| `kind` | `KIND_POLYGON` — el que ya existe |
| `source` | **`SOURCE_ASSISTED = 'assisted'`** — constante nueva en `models.py` |
| `geometry` | anillo en EPSG:4326, obtenido por vectorización de la máscara |
| `class_index` | la clase activa que eligió el usuario |
| el resto | igual que cualquier etiqueta manual |

Que el `kind` sea uno ya soportado es lo que hace que **FR-020 se cumpla sin trabajo**: `rasterize.py`
y `export.py` no se enteran de esta feature y el contrato del paquete exportado no cambia.

`source` distingue lo asistido de lo manual, lo que permitirá medir la calidad de la asistencia más
adelante sin volver a etiquetar. `SOURCE_MODEL` sigue libre para la fase 3 de `009`.

**Invariante heredada que no se toca**: lo no etiquetado sigue valiendo 255, distinto de la clase 0
(FR-021). Esta feature solo añade etiquetas; nunca convierte terreno no marcado en fondo.
