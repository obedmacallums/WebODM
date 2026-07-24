# Implementation Plan: Corrección de la nube de puntos con la transformación de realineación

**Branch**: `master` (spec dir: `003-realign-pointcloud`) | **Date**: 2026-07-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-realign-pointcloud/spec.md`

## Summary

Extensión del plugin `realign` que aplica a la nube de puntos de la tarea
(`georeferenced_model.laz`) **la misma transformación rígida** que 002 ya aplicó a los rásteres,
generando un LAZ corregido descargable. El usuario no marca puntos nuevos ni entra a un flujo
aparte: desde el mismo panel pide la generación, que corre en el worker vía
`run_function_async` con progreso y cancelación, y descarga el resultado cuando está listo.

Técnicamente es un pipeline **PDAL** de tres etapas (`readers.las → filters.transformation →
writers.las`) invocado por `subprocess` con el CLI ya presente en la imagen. La matriz 4×4 se
construye con los mismos `cos`, `sin`, `tx`, `ty` que `corrections.py` pasa al pipeline ráster, con
la fila Z en identidad, de modo que **las elevaciones quedan bit a bit intactas**. El resultado se
escribe en el directorio persistente del plugin con nombre temporal y `os.replace()` atómico, y se
sirve desde un endpoint propio (no desde el `celery_task_id`, que es efímero). Un campo nuevo
`pointcloud` dentro del documento `TaskRealignment` ya existente guarda el estado y una huella de
la transformación que permite detectar cuándo el resultado dejó de corresponder al ajuste vigente.

**Cero dependencias nuevas** (nivel 0 de la escalera del Principio IV) y **cero archivos nuevos en
el plugin salvo uno**: toda la lógica del pipeline vive en un `pointcloud.py` nuevo, y el resto son
extensiones de `api.py`, `plugin.py`, `store.py` y `RealignPanel.jsx`.

Todas las decisiones técnicas de `research.md` se validaron ejecutando PDAL sobre la nube real de
una tarea procesada (61.780.499 puntos, 268 MB): **48 segundos** de proceso, `max|ΔZ| = 0` exacto,
error XY de medio paso de cuantización y atributos preservados punto a punto.

## Technical Context

**Language/Version**: Python 3.9 (backend, Django 2.2.27) + JavaScript ES6/React 16 con JSX
compilado por el mecanismo `build_plugins` (webpack) del framework de plugins.

**Primary Dependencies**: framework de plugins de WebODM (`PluginBase`, `MountPoint`,
`TaskView`/`get_and_check_task`, `check_project_perms`, `run_function_async` con `with_progress` y
`with_cancel`, `GlobalDataStore`/`PluginDatum`, `get_persistent_path`, `download_file_response`);
**CLI `pdal` 2.3.0** de la imagen (`filters.transformation`, `writers.las` con LASZIP), invocado
por `subprocess`; `Workers.waitForCompletion`/`Workers.cancel` en el frontend. **Sin dependencias
nuevas** — los bindings `python-pdal` no están instalados y no hacen falta
(`docs/entorno-plugins.md`).

**Storage**: (1) estado de la nube en el documento `TaskRealignment` ya existente
(`GlobalDataStore`, key `task_<pk>`), bajo la clave nueva `pointcloud`; (2) LAZ corregido en
`get_persistent_path("task_<pk>/pointcloud.laz")`, el mismo volumen compartido webapp↔worker donde
002 deja los GeoTIFF. El asset original de la tarea NUNCA se modifica.

**Testing**: Django tests en `coreplugins/realign/tests.py`, ejecutados en Docker
(`docker compose exec webapp python manage.py test coreplugins/realign` — forma con `/`, ver
`quickstart.md`). Los fixtures LAZ se generan al vuelo con `readers.faux` de PDAL, sin binarios
versionados en el repo.

**Target Platform**: contenedores webapp + worker de WebODM (imagen compartida
`webodm/webodm_webapp`, Ubuntu 22.04).

**Project Type**: extensión de un plugin de WebODM existente (`coreplugins/realign/`).

**Performance Goals**: medido — **48 s** para 61,7 M de puntos / 268 MB, más de un orden de
magnitud por debajo del objetivo de la SC-006 (< 10 min para ~250 MB). Progreso reportado al
usuario con granularidad de ~2 s (cadencia de sondeo de `Workers.waitForCompletion`).

**Constraints**: cero modificaciones al core (Principio I); Z inalterada de forma estructural, no
aproximada (FR-003); misma transformación que los rásteres, tomada del estado persistido y no del
cliente (FR-002); solo modo rígido y solo con la realineación aplicada (FR-004, FR-005); operación
no destructiva (FR-006) y siempre desde el original (FR-007); nunca un archivo parcial descargable
(FR-014); precisión de la cabecera LAZ preservada — el default de PDAL degradaría de 1 mm a 1 cm
(D3).

**Scale/Scope**: nubes de dron de decenas a cientos de MB (la de referencia: 268 MB / 61,7 M de
puntos); un resultado de nube por tarea; una generación simultánea por tarea.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Principio | Evaluación |
|---|---|---|
| G1 | I. Desarrollo solo-plugins | ✅ PASS — todo el código vive en `coreplugins/realign/`; cero ediciones a `app/`, `webodm/`, `worker/`, `nodeodm/`. Se consumen solo puntos de extensión existentes (`api_mount_points`, `run_function_async`, `GetTaskResult`/`CheckTask`, `Workers.*`) |
| G2 | II. Compatibilidad con upstream | ✅ PASS — solo se modifican archivos propios del fork dentro de `coreplugins/realign/` y `specs/`; ningún archivo upstream tocado |
| G3 | III. Convenciones de plugin | ✅ PASS — se extiende el `Plugin(PluginBase)` existente con rutas nuevas en `api_mount_points`; persistencia por los mecanismos del framework (`GlobalDataStore`, `get_persistent_path`); el plugin sigue siendo deshabilitable sin romper nada (la nube original se sigue sirviendo por el core) |
| G4 | IV. Gestión de dependencias | ✅ PASS — **nivel 0**: el CLI `pdal` 2.3.0 ya está en la imagen compartida (verificado: `pdal --version`, `filters.transformation` en `pdal --drivers`). No se toca `requirements.txt` global ni el `Dockerfile`. La verificación obligatoria del worker (IV.3) está documentada en `quickstart.md` §4 |
| G5 | Tests en Docker (`docs/entorno-plugins.md`) | ✅ PASS — toda la validación corre dentro de Docker; nada se instala en el host. Los fixtures se generan con `readers.faux` dentro del contenedor |

**Post-design re-check (tras Phase 1)**: ✅ PASS — el diseño no introdujo dependencias nuevas ni
toques al core. El estado vive en el `PluginDatum` ya usado por 002 (una clave más en el mismo
documento, retrocompatible: su ausencia equivale a "nunca generada"), el artefacto en el
directorio persistente del plugin, y los contratos exponen solo rutas nuevas bajo
`/api/plugins/realign/` más el endpoint genérico `/api/workers/check/` que el framework ya ofrece
a los plugins.

## Project Structure

### Documentation (this feature)

```text
specs/003-realign-pointcloud/
├── plan.md              # Este archivo
├── research.md          # Phase 0: decisiones técnicas, todas verificadas con PDAL real
├── data-model.md        # Phase 1: extensión de TaskRealignment + PointCloudCorrection
├── quickstart.md        # Phase 1: guía de validación end-to-end (incluye verificación de worker)
├── contracts/
│   └── api.md           # Phase 1: rutas nuevas del plugin
├── checklists/
│   └── requirements.md  # Checklist de calidad de la spec (de /speckit-specify)
└── tasks.md             # Phase 2 (/speckit-tasks — no lo crea este comando)
```

### Source Code (repository root)

```text
coreplugins/realign/
├── plugin.py                     # MODIFICADO: 3 MountPoint nuevos (pointcloud, download)
├── api.py                        # MODIFICADO: RealignPointCloud (POST/DELETE), RealignPointCloudDownload,
│                                 #   clave `pointcloud` en GET state, elegibilidad + stale derivados
├── pointcloud.py                 # NUEVO: matriz 4x4, offsets desde la cabecera, pipeline PDAL,
│                                 #   bucle de sondeo (progreso + cancelación), escritura atómica
├── store.py                      # MODIFICADO: helpers get/set/del del subdocumento `pointcloud`
├── tests.py                      # MODIFICADO: tests de la feature (fixtures con readers.faux)
├── transform.py                  # SIN CAMBIOS — la transformación se reutiliza tal cual
├── corrections.py                # SIN CAMBIOS — pipeline ráster intacto
└── public/
    ├── RealignPanel.jsx          # MODIFICADO: sección de nube (estado, generar, progreso,
    │                             #   descarga, motivo de inelegibilidad, aviso del visor 3D)
    └── RealignPanel.scss         # MODIFICADO: estilos de la sección nueva
```

**Structure Decision**: se extiende el plugin existente en vez de crear uno nuevo, porque la
feature **reutiliza íntegramente** los puntos de control, el ajuste, el estado y los permisos de
002 — un plugin aparte tendría que duplicar toda esa mecánica o depender del otro, violando la
autocontención del Principio III. Un único archivo nuevo (`pointcloud.py`) aísla el pipeline PDAL
igual que `corrections.py` aísla el pipeline GDAL, manteniendo `transform.py` como la
representación de la transformación independiente del tipo de dato — que es exactamente lo que la
**D8 de 002** dejó preparado para esta etapa.

> **Nota de implementación heredada del plugin**: `run_function_async` re-ejecuta la función por
> *source* en un namespace vacío, así que la función que corre en el worker debe hacer sus imports
> **dentro del cuerpo y en forma absoluta** (`from coreplugins.realign import pointcloud, store`),
> como ya hace `corrections.py:77-79`.

## Complexity Tracking

> Sin violaciones constitucionales que justificar — tabla vacía.
