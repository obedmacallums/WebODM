# Data Model — `008-segmentation-mask-layer`

Delta sobre el modelo de `007-road-edge-segmentation`. Solo se describe lo que cambia; todo lo demás
sigue igual y no se repite aquí.

## 1. Entidad nueva: documento de máscara

Un fichero por análisis, hermano del documento de tramos, escrito solo por los análisis en modo
`segmentation`.

**Ubicación**: `get_plugins_persistent_path('road', 'task_<pk>')/<analysis_id>.mask.json`

Misma carpeta y mismo mecanismo del framework que el documento de tramos (D35, exigido por la
constitución). Escritura atómica: temporal en el mismo directorio y `os.replace`, igual que
`write_segments`, para que una cancelación a media escritura no deje un JSON truncado que el `GET`
no sepa distinguir de un resultado válido.

**Forma**:

| Campo | Tipo | Descripción |
|---|---|---|
| `version` | entero | Versión de esquema, para poder evolucionar sin romper lo escrito |
| `analysis_id` | texto | El análisis al que pertenece; redundante con el nombre del fichero, pero permite detectar un fichero mal ubicado |
| `generated_at` | texto ISO | Cuándo se generó |
| `resolution_m` | número | Resolución de la máscara en metros (medido: 0,20). Es el dato que sostiene el aviso de precisión de FR-016: la interfaz no debe inventarlo |
| `simplify_tolerance_m` | número | Tolerancia aplicada (D38). Deja trazado qué se descartó |
| `features` | lista | Polígonos de clase calzada, en EPSG:4326 |

**Sobre `features`**: colección de geometrías tipo polígono con la propiedad de clase, en
coordenadas geográficas. Puede estar **vacía** — es un estado legítimo y distinto de «no hay
documento» (D37): significa que el modelo corrió y no reconoció calzada en el corredor, lo cual
explica por qué los tramos salieron sin borde.

**Tamaño medido**: 19,5 KB para un corredor de 66 m, 76,9 KB para uno de 293 m.

**Ciclo de vida**: nace con el análisis y muere con él. Todo camino que hoy borra el documento de
tramos debe borrar también el de máscara — son cinco puntos en el código actual (tres en la capa
de API y dos en el worker, en los caminos de cancelación y de fallo). Dejar uno sin cubrir produce
ficheros huérfanos, que es exactamente lo que FR-005 prohíbe.

## 2. Cambio en el índice de análisis

El registro de cada análisis (dentro del documento global del `GlobalDataStore`) gana **un campo**:

| Campo | Tipo | Descripción |
|---|---|---|
| `has_mask` | booleano | Si este análisis tiene documento de máscara guardado |

Lo escribe el worker al terminar, junto al resto del resumen. Permite al panel decidir si ofrece el
control **sin leer el fichero de máscara** (D37, FR-015).

**Compatibilidad hacia atrás**: los análisis escritos antes de esta feature no tienen el campo. Su
ausencia se interpreta como falso, en memoria, **sin migración ni reescritura en disco** — el mismo
criterio que `006`/FR-024 aplicó con `_upgrade_segments` para los documentos de `005`. Un análisis
viejo sigue siendo válido tal cual.

## 3. Lo que NO cambia

Se hace explícito porque el valor de esta feature depende de no perturbar nada de lo anterior
(FR-006, FR-019, FR-020):

- **El documento de tramos**: ni un campo nuevo, ni un cambio de versión de esquema. La máscara vive
  aparte precisamente para no tocarlo.
- **El cálculo del borde y del ancho**: la máscara ráster se sigue muestreando igual en
  `_read_block`. Vectorizarla es un producto adicional, no una entrada del cálculo. Ningún análisis
  existente cambia de resultado.
- **Los modos `break` y `surface`**: no generan máscara, no ganan el campo, no cambian en nada.
- **Las exportaciones CSV y GeoJSON**: mismo esquema, mismas columnas. La máscara no aparece.
- **Los umbrales de color, el eje, las reglas transversales**: intactos.

## 4. Relación entre entidades

```text
Tarea
 └── Documento global (índice de análisis)
      └── Análisis  ──┬── has_mask: booleano        (nuevo)
                      │
                      ├── Documento de tramos       <analysis_id>.json        (existente)
                      └── Documento de máscara      <analysis_id>.mask.json   (nuevo, opcional)
                             └── features: polígonos de calzada en EPSG:4326
```

El documento de máscara es **opcional y dependiente**: no existe sin su análisis, no existe para los
modos que no lo producen, y no existe para los análisis anteriores a esta feature.
