# Implementation Plan: Etiquetado asistido por regiones en el plugin `training`

**Branch**: `010-superpixel-labeling` | **Date**: 2026-07-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/010-superpixel-labeling/spec.md`

## Summary

Se añade al plugin `training` un modo de selección asistida: la ortofoto se particiona en regiones
homogéneas y el usuario las añade a una clase con un clic o arrastrando el pincel.

El problema central de la feature era la tensión entre FR-009 (sin bordes rectos artificiales) y
FR-015 (por porciones acotadas, sin la ortofoto entera en memoria). **Está resuelto y medido**: si
las ventanas de cálculo se alinean a múltiplos del paso de superpíxel `S` en coordenadas globales de
la ortofoto y se calculan con un halo de `8S`, la partición del núcleo es **idéntica** (0,000 % de
desacuerdo) a la que produciría un cálculo con margen mucho mayor. La rejilla de celdas se ancla al
origen de la ortofoto, igual que hace `tiling.py` con las teselas de exportación, así que el
resultado es determinista y no depende del encuadre (FR-007, FR-008).

Coste medido en la configuración de producción (celda 512 px a 10 cm/px, halo 128 px, 5 bandas,
ortofoto y DTM reales de la instancia): **0,951 s por celda**, pico de **71 MB**. Los clics
siguientes sobre la misma celda son una consulta a un array ya en caché.

Detalles y alternativas descartadas: [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.9 (backend, imagen `webodm/webodm_webapp`); JavaScript ES2015+ y JSX
para `public/` (build por el mecanismo `build_plugins`/webpack del framework)

**Primary Dependencies**: ya en la imagen — numpy 1.26.2, scipy 1.11.3, rasterio 1.3.10, GDAL 3.4.x.
Nueva — `scikit-image==0.24.0` por el `requirements.txt` del plugin, **con numpy y scipy pineados a
las versiones exactas de la imagen** (ver Constitution Check y research.md D1)

**Storage**: ajustes de asistencia en el documento del dataset (`GlobalDataStore('training')`, vía
`store.update_dataset`); mapas de regiones en caché de fichero bajo `get_persistent_path()`, con
presupuesto acotado y expulsión por antigüedad

**Testing**: `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests`
(backend) y los tests de `public/tests/` con node + jsdom, que la misma orden arrastra vía
`tests/test_frontend.py`. **Nunca `./run_tests_in_docker.sh`**: hace `docker compose down -v` y
borraría las tareas reales de la instancia

**Target Platform**: contenedor Linux aarch64 (Ubuntu 22.04); webapp y worker comparten imagen

**Project Type**: plugin de WebODM (backend Django REST + frontend sobre Leaflet)

**Performance Goals**: preparación de una celda < 5 s (SC-004; medido 0,951 s); clic sobre celda ya
preparada sin espera perceptible (SC-003)

**Constraints**: ~1 GB de memoria disponible en el contenedor (SC-007; medido 71 MB de pico por
celda); ortofotos de hasta 14145×29380 px; sin GPU

**Scale/Scope**: una celda cubre 51×51 m de terreno a la resolución por defecto; un superpíxel medio
mide 1,6 m; 1089 regiones por celda

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Veredicto | Justificación |
|---|---|---|
| **I. Desarrollo solo-plugins** | ✅ PASA | Todo el cambio vive en `coreplugins/training/`. No se toca `app/`, `webodm/`, `worker/`, `nodeodm/`, `nginx/` ni los scripts raíz. |
| **II. Compatibilidad con upstream** | ✅ PASA | Ningún archivo del core modificado, así que no hay superficie de conflicto de merge. |
| **III. Convenciones de plugin** | ✅ PASA | Rutas nuevas por `api_mount_points()` con `$` final, siguiendo la convención documentada en `plugin.py`. Frontend en `public/`. El modo nuevo se puede desactivar sin romper el etiquetado existente (FR-026). |
| **IV. Gestión de dependencias** | ⚠️ **PASA CON CONDICIONES** | Ver abajo. |

### Principio IV en detalle

`scikit-image` es Python puro instalable con pip, así que le corresponde el **paso 1** de la escalera
(`requirements.txt` del plugin, sin tocar el `Dockerfile`). Pero el mecanismo tiene un fallo real y
**medido** que la feature debe neutralizar:

`PluginBase.check_requirements()` (`app/plugins/plugin_base.py:44`) ejecuta
`pip install -U -r requirements.txt --target <site-packages>` **sin `--no-deps`**, y
`python_imports()` hace `sys.path.insert(0, ...)`. Instalar `scikit-image` a secas arrastra numpy
2.0.2 y scipy 1.13.1 al directorio del plugin, que quedan **por delante** del numpy 1.26.2 de la
imagen. Medido en el contenedor:

```
numpy visto por el plugin: 2.0.2 /tmp/skresearch/numpy/__init__.py
rasterio ROTO: ValueError numpy.dtype size changed, may indicate binary incompatibility.
               Expected 96 from C header, got 88 from PyObject
```

Eso rompería `rasterio` —y con él la mitad del plugin— dentro de `python_imports()`.

**Condiciones que la implementación DEBE cumplir**, y sin las cuales esta feature no pasa el gate:

1. El `requirements.txt` del plugin pinea `numpy==1.26.2` y `scipy==1.11.3` junto a
   `scikit-image==0.24.0`, de forma que pip instale en el directorio del plugin copias
   ABI-idénticas a las de la imagen en vez de versiones nuevas. Verificado en el contenedor: con
   los pines, `rasterio` importa correctamente y `slic` corre.
2. Un test de regresión afirma que la versión de numpy y de scipy del directorio del plugin
   **coincide** con la del sistema, y que `rasterio` importa bajo `python_imports()`. Convierte en
   fallo ruidoso lo que hoy sería una rotura silenciosa la próxima vez que upstream suba numpy.
3. **Verificación de workers (paso 3, no negociable)**: demostrar con salida de comandos que el
   contenedor `worker` importa el módulo nuevo y ejecuta una selección sin errores de import.

No se toca el `Dockerfile`: el paso 2 de la escalera no aplica.

## Project Structure

### Documentation (this feature)

```text
specs/010-superpixel-labeling/
├── plan.md              # Este fichero
├── spec.md              # Qué y por qué
├── research.md          # Fase 0: decisiones medidas
├── data-model.md        # Fase 1: entidades
├── quickstart.md        # Fase 1: guía de validación
├── contracts/
│   └── rest-api.md      # Fase 1: contrato HTTP
├── checklists/
│   └── requirements.md
└── tasks.md             # Lo genera /speckit-tasks, no este comando
```

### Source Code (repository root)

```text
coreplugins/training/
├── requirements.txt     # NUEVO: scikit-image + pines de numpy/scipy (Principio IV)
├── superpixels.py       # NUEVO: rejilla de celdas anclada, partición, grafo de
│                        #        adyacencia, crecimiento por tolerancia, vectorización
├── regions.py           # NUEVO: caché de mapas de regiones en get_persistent_path()
├── api.py               # + RegionSelect, RegionStatus
├── models.py            # + SOURCE_ASSISTED, validación de los ajustes de asistencia
├── plugin.py            # + dos MountPoint
├── elevation.py         # SIN CAMBIOS — se consume tal cual (read_aligned, tile_channels)
├── rasterize.py         # SIN CAMBIOS — la salida es KIND_POLYGON, ya soportado
├── export.py            # SIN CAMBIOS — el contrato del paquete no se toca (FR-020)
├── public/
│   ├── LabelEditor.js   # + MODE_ASSIST
│   ├── assistLayer.js   # NUEVO: previsualización de la región bajo el cursor
│   ├── TrainingPanel.jsx# + botón de modo y controles de granularidad/tolerancia/peso
│   └── tests/
│       └── assistMode.test.js   # NUEVO
└── tests/
    ├── __init__.py      # reexportar los módulos nuevos o no se ejecutan
    ├── test_superpixels.py      # NUEVO
    ├── test_regions_cache.py    # NUEVO
    ├── test_api_regions.py      # NUEVO
    └── test_requirements.py     # NUEVO: el gate de ABI del Principio IV
```

**Structure Decision**: se extiende el plugin `training` existente, sin plugin nuevo. La feature
produce etiquetas del tipo que el plugin ya guarda, rasteriza y exporta; separarla en otro plugin
obligaría a duplicar el modelo de dataset, el store y el editor. La lógica nueva se concentra en
`superpixels.py` (puro, sin Django, testeable en aislamiento) y `regions.py` (caché e I/O),
siguiendo la separación que el plugin ya practica entre `tiling.py`/`rasterize.py` y `store.py`.

## Complexity Tracking

> Solo se rellena si el Constitution Check tiene violaciones que justificar.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Pinear `numpy` y `scipy` en el `requirements.txt` del plugin, duplicando 246 MB en `MEDIA_ROOT` | El instalador del framework no ofrece `--no-deps` y `python_imports()` antepone el directorio del plugin a `sys.path`. Sin los pines, `scikit-image` arrastra numpy 2.0.2 y **rompe `rasterio`** (medido). | `--no-deps` funciona (verificado) pero no es alcanzable desde `requirements.txt`; usarlo exigiría modificar `app/plugins/plugin_base.py`, que es core y violaría el Principio I por una comodidad. Implementar la partición sin `scikit-image` se evaluó y se descartó en research.md D1 por coste de cómputo. |
