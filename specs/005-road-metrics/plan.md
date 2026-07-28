# Implementation Plan: características geométricas de caminos (`road`)

**Branch**: `005-road-metrics` | **Date**: 2026-07-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-road-metrics/spec.md`

## Summary

Plugin nuevo `road` que, dado el eje central de un camino y un modelo de elevación de la tarea,
divide el eje en tramos configurables (5 m por defecto) y reporta por tramo la cota, la pendiente
longitudinal, el ancho medido entre bordes y la pendiente transversal, pintándolos sobre el mapa 2D
con un semáforo verde/amarillo/rojo y exportándolos a CSV y GeoJSON.

Enfoque técnico: el eje llega por el contrato público de `annotations` o por un GeoJSON subido, se
proyecta al CRS del propio DEM y se recorre por progresiva. El cálculo corre en el worker con
`run_function_async`, procesando el eje **por bloques de tramos**: por cada bloque se lee una única
ventana del ráster a un array `numpy` y todas las muestras del bloque —eje y transversales— se
resuelven por indexación vectorizada, lo que hace viable el orden de 10⁵–10⁶ muestras y da el punto
natural de progreso y cancelación. Los bordes salen de la primera racha sostenida de pendiente
transversal por encima de un umbral, recorriendo cada lado desde el eje hacia afuera; las pendientes
salen de ajustes por mínimos cuadrados, no de diferencias entre extremos. El índice de análisis vive
en el `GlobalDataStore` y los tramos en un archivo JSON por análisis, para no meter megabytes en una
fila de texto que se reescribe en cada actualización de progreso.

Detalle de cada decisión y sus alternativas en [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.9 (imagen `webodm/webodm_webapp`, Ubuntu 22.04) para el backend;
JavaScript ES6 + React para el frontend, compilado por el `build_plugins` existente (webpack).

**Primary Dependencies**: ninguna nueva. `rasterio` 1.3.10 (lectura y muestreo del DEM), `numpy`
1.26.2 (perfiles, ajustes por mínimos cuadrados) y Django/DRF, todas ya en `requirements.txt` del
core y presentes en webapp y worker. Frontend: Leaflet y el bus `PluginsAPI.Map`, ya disponibles.
No se usa `pyproj` —aunque esté instalado de hecho— porque no está declarado en `requirements.txt`;
`rasterio.warp.transform` cubre la reproyección, igual que en `annotations`.

**Storage**: `GlobalDataStore('road')` (modelo `PluginDatum`, `user=None`) para el índice de
análisis por tarea, y archivos JSON en `get_plugins_persistent_path('road', 'task_<pk>')` para los
tramos. Ninguna tabla ni migración propia.

**Testing**: suite de Django del repo — `webodm.sh test backend coreplugins.road.tests` dentro de
Docker, con `CELERY_TASK_ALWAYS_EAGER` para el pipeline asíncrono, DEM sintéticos generados con
`rasterio` en directorios temporales, y los tests de frontend en jsdom lanzados desde la misma suite
(patrón que `annotations` dejó montado).

**Target Platform**: WebODM autoalojado sobre Docker; webapp y worker comparten imagen. Navegador de
escritorio para la vista 2D.

**Project Type**: plugin de WebODM — backend Django/DRF más frontend React/Leaflet, en un único
directorio `coreplugins/road/`.

**Performance Goals**: 1 km con los parámetros por defecto (~200 tramos, ~40.000 muestras) por
debajo de 2 minutos con progreso visible (SC-002); recoloreado por umbrales en menos de 2 segundos y
sin recálculo (SC-005); cancelación efectiva en menos de 5 segundos (SC-008).

**Constraints**: sin tope duro de tamaño — se estima el coste y se avisa (FR-043); nunca interpolar
ni rellenar métricas (FR-022); no modificar ningún producto de la tarea (FR-039); un único análisis
en curso por tarea (FR-036); la función del worker debe ser self-contained porque se reejecuta por
código fuente en un namespace vacío.

**Scale/Scope**: caminos de 0,5 a 10 km en el caso habitual, de 100 a 2.000 tramos y de 10⁴ a 10⁶
muestras de DEM por análisis; varios análisis por tarea. Alcance de código estimado: ~10 módulos
Python y ~6 archivos de frontend, más una adición de contrato en `realign`.

## Constitution Check

*GATE: revisado antes de Phase 0 y de nuevo tras Phase 1. Resultado en ambos pasos: **PASA**.*

### I. Desarrollo solo-plugins (no negociable)

Toda la funcionalidad vive en `coreplugins/road/`, con una clase `Plugin(PluginBase)` que se integra
solo por `api_mount_points`, `include_js_files` y `build_jsx_components`. **Cero cambios** en `app/`,
`webodm/`, `worker/`, `nodeodm/`, `nginx/` o los scripts raíz.

El único archivo fuera del plugin nuevo es `coreplugins/realign/`, al que se le añade un `contract.py`
y dos métodos públicos en su `Plugin` ([consumed-contracts.md §2](./contracts/consumed-contracts.md)).
`realign` es un plugin propio del fork, no código de upstream, así que esto **no es una excepción al
Principio I** y no genera deuda de merge. La alternativa —que `road` reconstruyera las rutas internas
de `realign`— sería peor: acoplamiento sin contrato entre dos plugins.

### II. Compatibilidad con upstream

Todos los archivos nuevos están en rutas que upstream no toca (`coreplugins/road/`,
`specs/005-road-metrics/`). La adición a `coreplugins/realign/` afecta a archivos que ya son propios
del fork. Ningún archivo compartido con upstream se modifica, reordena ni renombra: la superficie de
conflicto de merge es nula.

### III. Convenciones de plugin

- Directorio propio `coreplugins/road/`; el nombre no colisiona con ningún plugin de upstream
  (`ls coreplugins/` verificado).
- `manifest.json` completo, con `webodmMinVersion` alineado con el de los plugins hermanos.
- `plugin.py` con `Plugin(PluginBase)`; integración solo por puntos de extensión del framework y la
  señal `task_removed` para el borrado en cascada.
- Assets de frontend en `public/`, compatibles con el `build_plugins` existente: `main.js` para el
  registro y `Road.jsx` como componente construido, igual que `annotations` y `realign`.
- Deshabilitable sin efectos: al desactivarlo desaparecen sus rutas y su capa; `annotations` y
  `realign` no dependen de él en ningún sentido (el flujo de dependencia es unidireccional).

### IV. Gestión de dependencias de plugins

- **Paso 1 (Python puro)**: no aplica. No hay dependencia nueva; `rasterio` y `numpy` ya están en
  `requirements.txt` del core (líneas 56 y 63) y en la imagen. El plugin **no** lleva
  `requirements.txt`, para no duplicar lo que ya provee la imagen.
- **Paso 2 (sistema)**: no aplica. El `Dockerfile` no se toca.
- **Paso 3 (verificación de workers, no negociable)**: obligatoria aunque no haya dependencias
  nuevas, porque `run_function_async` reejecuta el código fuente en un namespace vacío y un import
  relativo solo falla allí. El procedimiento está en
  [quickstart.md](./quickstart.md#verificación-del-worker-principio-iv-no-negociable) y la feature no
  se cierra sin la evidencia del log del worker completando un análisis real.

**Re-evaluación tras Phase 1**: el diseño no introdujo ningún elemento que cambie lo anterior. Sin
violaciones que registrar.

## Project Structure

### Documentation (this feature)

```text
specs/005-road-metrics/
├── plan.md                          # Este archivo
├── spec.md                          # Especificación y clarificaciones
├── research.md                      # Phase 0: D1–D16
├── data-model.md                    # Phase 1: entidades, estados, invariantes
├── quickstart.md                    # Phase 1: despliegue, tests y validación manual
├── contracts/
│   ├── rest-api.md                  # Phase 1: rutas, esquemas y errores
│   └── consumed-contracts.md        # Phase 1: annotations, realign, bus del core
├── checklists/
│   └── requirements.md              # Calidad de la spec
└── tasks.md                         # Phase 2 (/speckit-tasks — no lo crea /speckit-plan)
```

### Source Code (repository root)

```text
coreplugins/road/
├── __init__.py                      # Imprescindible: sin él el paquete no se importa
├── manifest.json
├── plugin.py                        # Plugin(PluginBase): rutas, JS, señal task_removed
├── api.py                           # Vistas DRF de contracts/rest-api.md
├── axis.py                          # Eje: desde annotations o desde GeoJSON, con validación
├── sources.py                       # DEM: modelos, variantes, capabilities, obsolescencia
├── geometry.py                      # Proyección, progresivas, tramificación, transversales
├── profile.py                       # Detección de bordes y pendientes (puro, sin E/S)
├── compute.py                       # Función de worker self-contained: pipeline por bloques
├── export.py                        # CSV y GeoJSON
├── store.py                         # Índice en DataStore + archivo de tramos + candado
├── signals.py                       # task_removed: borrado en cascada
├── tests.py                         # Suite del plugin
├── README.md
└── public/
    ├── main.js                      # Registro del control en el mapa
    ├── icon.svg
    ├── Road.jsx                     # Control Leaflet + botón
    ├── Road.scss
    ├── RoadPanel.jsx                # Panel: ejes, parámetros, progreso, umbrales, exportación
    ├── RoadPanel.scss
    ├── roadBridge.js                # Bus PluginsAPI.Map: publicar, alternar, borrar
    ├── segmentStyle.js              # Semáforo: pendiente + umbrales -> color (puro)
    ├── panelStacking.js             # Apilado entre paneles de plugins (mismo helper del fork)
    └── tests/                       # jsdom: bridge y semáforo

coreplugins/realign/
├── contract.py                      # NUEVO: corrected_rasters(task_id)
└── plugin.py                        # MODIFICADO: contract_version() y corrected_rasters()
```

**Structure Decision**: estructura estándar de plugin de WebODM, calcada de `coreplugins/annotations/`
por ser el plugin del fork más cercano en forma (backend con muestreo de DEM más panel en la vista
2D). La separación que importa es **`profile.py` sin entrada/salida**: toda la matemática de
detección de bordes y de ajuste de pendientes opera sobre arrays en memoria, sin tocar rásteres ni
la base de datos. Es la parte que más puede equivocarse en silencio y así se prueba de forma exacta
con perfiles sintéticos, mientras `compute.py` se queda con la orquestación por bloques, el progreso
y la cancelación. `segmentStyle.js` cumple el mismo papel en el frontend: la regla del semáforo es
una función pura y testeable, separada del dibujo en Leaflet.

## Complexity Tracking

Sin violaciones de la constitución. No hay nada que justificar.
