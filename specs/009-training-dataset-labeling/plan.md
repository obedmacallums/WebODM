# Implementation Plan: Etiquetado de ortofotos y exportación de datasets de entrenamiento

**Branch**: `006-street-width` (rama de trabajo actual del fork) | **Date**: 2026-07-30 |
**Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/009-training-dataset-labeling/spec.md`

## Summary

Un plugin nuevo, `training`, que convierte una ortofoto ya procesada en un dataset de segmentación
listo para entrenar fuera de WebODM.

El enfoque se apoya en tres hallazgos de la fase de investigación, los tres medidos contra la
instancia real y no supuestos:

1. **Las ortofotos ya están en un CRS métrico** (las cinco en EPSG:32719). El radio del pincel en
   metros no necesita elegir zona UTM ni reproyectar a un CRS auxiliar: el buffer se hace en el CRS
   nativo de la ortofoto.
2. **La cuarta banda es alfa y `nodata` es `None`**, así que el filtro de píxeles válidos de FR-027
   sale de leer una banda que ya está ahí, sin heurísticas sobre valores centinela.
3. **El remuestreo a la resolución del dataset lo hace la propia lectura**: una ventana de 806 px
   nativos se lee directamente como 512 px de salida en una sola llamada, sobre un ráster ya
   *tiled*. No hace falta ningún paso de warp intermedio.

Con eso, la pieza central —trazo de pincel → superficie → máscara— queda comprobada de punta a punta
antes de escribir una línea de producción: una polilínea de 20 m con radio 2,5 m produce 118,14 m² de
polígono y 11 825 píxeles de clase a 10 cm/px, es decir 118,25 m². Coinciden.

## Alcance de esta entrega

**Decidido con el usuario**: esta entrega implementa **US1 + US2** — etiquetar a mano (polígonos y
pincel) y exportar el paquete. US3, US4 y US5 quedan planificadas aquí pero se abordan después.

El corte no es arbitrario. Al medir la rejilla real de teselas apareció el argumento:

| Tarea | Extensión | Teselas a 10 cm/px |
|---|---|---|
| Mina La Coipa | 1087 × 1402 m | **616** |
| Colegio Trabunco | 468 × 491 m | 100 |
| Noria | 314 × 652 m | 91 |
| Task 2026-07-24 | 314 × 478 m | 70 |
| Polideportivo | 328 × 220 m | 35 |
| **Total** | | **912** |

Una sola tarea —la mina, que es justo el terreno que motiva el proyecto— aporta 616 de las 912. Un
dataset de una única tarea ya da material de sobra para entrenar, así que **US3 (multi-tarea) deja de
estar en el camino crítico**. El modelo de datos sí lo soporta desde el primer día (FR-002), porque
añadirlo después obligaría a rehacer el formato de exportación; lo que se aplaza es la interfaz.

Requisitos cubiertos por esta entrega: FR-001 a FR-017, FR-022 a FR-031, FR-035 a FR-038.
Aplazados: FR-018 a FR-021 (GeoJSON, US4) y FR-032 a FR-034 (resumen de calidad, US5).

## Technical Context

**Language/Version**: Python 3.9 (contenedor WebODM) · JavaScript ES2018+ / React (panel y página
del plugin)

**Primary Dependencies**: `rasterio` 1.3.10 (lectura remuestreada por ventana y rasterizado),
`django.contrib.gis.geos` (buffer y simplificación), `Pillow` 11.3.0 (escritura de teselas y
máscaras), `numpy` 1.26.2, Leaflet (dibujo sobre el mapa). **Ninguna dependencia nueva** — inventario
verificado en el contenedor `worker`, que es donde corre la exportación. `shapely` no está en la
imagen y no se necesita.

**Storage**: metadatos de dataset en `GlobalDataStore` (namespace `training`); etiquetas y paquetes
exportados en ficheros bajo `get_persistent_path()`. Es el reparto que `road` ya usa: índice en el
store, datos voluminosos en fichero.

**Testing**: `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests`.
Los tests de JS corren con jsdom sin navegador, como en `road` y `annotations`. **Nunca**
`run_tests_in_docker.sh`: hace `docker compose down -v` y destruiría las tareas reales del usuario.

**Target Platform**: contenedor Linux de WebODM (webapp y worker comparten imagen), navegador para la
interfaz.

**Project Type**: plugin de WebODM (backend Django/DRF + frontend React en `coreplugins/`), con dos
superficies de interfaz: página global y panel sobre el mapa de una tarea.

**Performance Goals**: la exportación de un dataset de varios cientos de teselas no debe bloquear la
interfaz ni construirse en memoria. Referencia dura: la ortofoto de la mina a 10 cm/px son
10 876 × 14 023 px, o sea 152 Mpx — una máscara global en `uint8` ocuparía 152 MB y la imagen RGB
457 MB. El diseño rasteriza **tesela a tesela** precisamente por esto.

**Constraints**: el radio del pincel es una medida sobre el terreno y debe mantenerse constante al
hacer zoom. Las etiquetas nunca se guardan como píxeles. Lo no etiquetado se exporta como «ignorar»
(255), jamás como clase 0.

**Scale/Scope**: 912 teselas sobre las cinco tareas actuales; ortofotos de hasta 17 128 × 22 084 px.
Un plugin nuevo, ~10 ficheros de código.

## Constitution Check

*GATE: revisado antes de Phase 0 y de nuevo tras Phase 1. Sin violaciones.*

### I. Desarrollo solo-plugins (NO NEGOCIABLE) — ✅ PASS

Todo el código vive en `coreplugins/training/`, un directorio nuevo. No se toca `app/`, `webodm/`,
`worker/`, `nodeodm/`, `nginx/` ni ningún script raíz (FR-035). La integración usa exclusivamente
puntos de extensión públicos: `main_menu()`, `app_mount_points()`, `api_mount_points()`,
`include_js_files()`, `build_jsx_components()` y `PluginsAPI` en el frontend.

El plugin **lee** ortofotos de tareas del core mediante `Task.assets_path()` y nunca las modifica.

### II. Compatibilidad con upstream — ✅ PASS

`coreplugins/training/` es un nombre que no colisiona con ningún plugin de upstream (comprobado
contra los 25 directorios de `coreplugins/`). Los artefactos de la feature viven en
`specs/009-training-dataset-labeling/`. Ningún fichero que upstream toque cambia, así que la
superficie de merge es cero.

### III. Convenciones de plugin — ✅ PASS

Estructura estándar de `coreplugins/<nombre>/`: `manifest.json` completo, `plugin.py` con
`Plugin(PluginBase)`, assets en `public/` construidos con el `build_plugins`/webpack existente.

**Deshabilitable sin romper nada (FR-038)**: los datasets y las etiquetas son datos inertes cuando el
plugin está desactivado — nadie más los lee. A diferencia de `road`, este plugin no depende de ningún
otro, y en esta entrega ningún otro depende de él (el contrato para consumidores llega en la fase 2).

Detalle heredado de `annotations` y `road`: un `MountPoint` sin `$` final resuelve por prefijo, así
que toda ruta ancla el final con `$` y las literales más específicas se registran antes que los
patrones genéricos con identificador.

### IV. Gestión de dependencias de plugins — ✅ PASS

- **Paso 1 (Python puras)**: no aplica. No se añade nada a ningún `requirements.txt`.
- **Paso 2 (dependencias de sistema)**: no aplica. El `Dockerfile` no se toca.
- **Paso 3 (verificación de workers, NO NEGOCIABLE)**: aplica igualmente, y es el riesgo principal
  del plan. La exportación corre en el worker vía `run_function_async`, que **recompila la función
  por código fuente en un espacio de nombres vacío**: un import mal colocado produce un fallo que
  ningún test de la suite detecta. Mitigación heredada de `008` (D41): todos los imports viven en los
  módulos del plugin, nunca dentro de la función asíncrona. La verificación con Celery real y
  evidencia de log es obligatoria antes de dar la feature por completa.

El inventario ya se verificó en el contenedor `worker` —no en `webapp`— precisamente porque es ahí
donde el paso 3 falla en silencio.

### Restricciones de infraestructura — ✅ PASS

Datos persistentes solo por `get_persistent_path()` y `GlobalDataStore` (FR-016). No se toca
`docker-compose*.yml` ni se publica imagen nueva.

### Re-evaluación tras el diseño de Phase 1 — ✅ SIN CAMBIOS

El diseño no introdujo ninguna violación nueva, y cerró dos incógnitas que podrían haberlas
provocado:

- **El CRS métrico salió de la propia ortofoto** ([D4](./research.md#d4)), así que no hizo falta
  ninguna librería de proyecciones adicional. Si las ortofotos hubieran estado en coordenadas
  geográficas, habría que haber calculado la zona UTM y el Principio IV habría vuelto a la mesa.
- **El buffer geométrico se resuelve con el GEOS de GeoDjango** y el rasterizado acepta geometrías en
  formato GeoJSON, así que `shapely` —ausente de la imagen— no se necesita. Comprobado ejecutando la
  cadena completa, no leyendo documentación.

Sigue en pie el único punto que exige evidencia y no diseño: la verificación del worker del
Principio IV paso 3, con Celery real. Está en `quickstart.md` como Escenario 4.

## Project Structure

### Documentation (this feature)

```text
specs/009-training-dataset-labeling/
├── plan.md              # Este fichero
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── checklists/
│   └── requirements.md  # checklist de calidad de /speckit-specify
├── contracts/
│   ├── rest-api.md      # Phase 1 — interfaz HTTP del plugin
│   └── dataset-package.md # Phase 1 — formato del paquete exportado
└── tasks.md             # Phase 2 (/speckit-tasks — NO lo crea este comando)
```

### Source Code (repository root)

```text
coreplugins/training/
├── manifest.json
├── plugin.py                 # Plugin(PluginBase): menú global, app/api mount points
├── api.py                    # vistas DRF: datasets, etiquetas, exportación
├── store.py                  # persistencia: índice en GlobalDataStore + ficheros; lock por documento
├── models.py                 # entidades puras: Dataset, Clase, Etiqueta (sin Django ORM)
├── rasterize.py              # etiquetas -> máscara de una tesela (buffer + rasterize)
├── tiling.py                 # rejilla de teselas de una ortofoto a una resolución dada
├── export.py                 # construcción del paquete y del manifiesto
├── templates/
│   └── index.html            # página global de gestión de datasets
├── public/
│   ├── main.js               # engancha el panel al mapa vía PluginsAPI
│   ├── Training.jsx          # panel sobre el mapa de la tarea
│   ├── TrainingPanel.jsx
│   ├── LabelEditor.js        # polígonos y pincel sobre Leaflet puro
│   ├── labelLayer.js         # dibujo de las etiquetas existentes
│   ├── datasets.js           # página global (lista de datasets)
│   └── tests/                # tests de JS con jsdom
└── tests/
    ├── __init__.py           # reexporta todos los módulos (ver nota)
    ├── test_store.py
    ├── test_rasterize.py
    ├── test_tiling.py
    ├── test_export.py
    ├── test_api_datasets.py
    ├── test_api_labels.py
    └── test_frontend.py
```

**Structure Decision**: plugin único con dos superficies de interfaz. La página global
(`main_menu()` + `app_mount_points()`, precedente exacto en `coreplugins/task-manager/plugin.py`)
gestiona datasets, que viven por encima de las tareas. El panel sobre el mapa
(`include_js_files()` + `build_jsx_components()` + `PluginsAPI`, precedente en `annotations` y
`road`) es donde se etiqueta. Los módulos de backend se separan por responsabilidad —rejilla,
rasterizado, empaquetado— para que cada uno sea comprobable con datos sintéticos, sin ortofoto.

**Nota que ahorra un fallo silencioso**: `coreplugins/` es un *namespace package* sin `__init__.py`.
Un módulo de test que no se reexporte en `tests/__init__.py` **no se ejecuta y nadie se entera** —
pasó en `008`. La verificación es que el total de la suite suba exactamente en el número de tests
nuevos.

## Complexity Tracking

Sin violaciones de la constitución que justificar. Esta sección queda vacía a propósito.
