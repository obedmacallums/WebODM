# Implementation Plan: Análisis de visibilidad (viewshed) desde un punto en la vista 2D

**Branch**: `master` (spec dir: `001-viewshed-analysis`) | **Date**: 2026-07-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-viewshed-analysis/spec.md`

## Summary

Plugin `viewshed` para el fork de WebODM: en la vista 2D de una tarea procesada, el
usuario activa un control, hace clic en un punto y el sistema calcula las zonas visibles
desde ese punto usando el modelo de elevación de la tarea (DSM preferido, DTM como
respaldo), con altura de observador configurable (default 1,60 m). El cálculo corre
asíncrono en el worker con `gdal_viewshed` (ya presente en la imagen), el resultado se
poligoniza a GeoJSON y se muestra como capa Leaflet sobre la ortofoto. Sigue el patrón
del coreplugin `contours` (el análogo más cercano: DEM → GDAL en worker → capa en mapa).

## Technical Context

**Language/Version**: Python 3.9 (backend, Django 2.2.27) + JavaScript ES6/React 16 con
JSX compilado por el mecanismo `build_plugins` (webpack) del framework de plugins

**Primary Dependencies**: framework de plugins de WebODM (`PluginBase`, `MountPoint`,
`TaskView`, `run_function_async`, `CheckTask`/`GetTaskResult`), GDAL 3.4.x de la imagen
(`gdal_viewshed`, `gdal_polygonize`/`ogr2ogr` vía subprocess), Leaflet (vista 2D),
`PluginsAPI.Map` (frontend). **Sin dependencias nuevas** — ver
`docs/entorno-plugins.md`.

**Storage**: sin persistencia propia. Entrada: assets de la tarea
(`task.get_asset_download_path("dsm.tif"|"dtm.tif")`). Salida: archivo temporal GeoJSON
en `settings.MEDIA_TMP` (patrón `contours`), consumido por el frontend y efímero.

**Testing**: Django tests en `coreplugins/viewshed/tests.py`, ejecutados en Docker
(`./run_tests_in_docker.sh` o `docker compose exec webapp /webodm/webodm.sh test backend
coreplugins.viewshed.tests`). En el Mac local solo tests ligeros sin stack.

**Target Platform**: contenedores webapp + worker de WebODM (imagen compartida
`webodm/webodm_webapp`, Ubuntu 22.04)

**Project Type**: plugin de WebODM (directorio autocontenido `coreplugins/viewshed/`)

**Performance Goals**: resultado visible en < 15 s para datasets típicos de dron
(SC-002); UI no bloqueante durante el cálculo (FR-009)

**Constraints**: cero modificaciones al core (Principio I); cero dependencias nuevas
(Principio IV, nivel 0 de la escalera); resultado efímero (sin migraciones de BD);
un análisis a la vez por sesión de visualización (FR-008)

**Scale/Scope**: DSMs típicos de levantamiento con dron (decenas a cientos de MB);
un usuario ejecutando análisis interactivos sobre una tarea

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Principio | Evaluación |
|---|---|---|
| G1 | I. Desarrollo solo-plugins | ✅ PASS — todo el código vive en `coreplugins/viewshed/`; cero ediciones a `app/`, `webodm/`, `worker/`, `nodeodm/` |
| G2 | II. Compatibilidad con upstream | ✅ PASS — solo se agrega un directorio nuevo que upstream no tiene; ningún archivo upstream tocado |
| G3 | III. Convenciones de plugin | ✅ PASS — `manifest.json`, `plugin.py` con `Plugin(PluginBase)`, integración solo vía `api_mount_points`, `include_js_files`, `build_jsx_components`; assets en `public/`; deshabilitable sin efectos |
| G4 | IV. Gestión de dependencias | ✅ PASS — nivel 0 de la escalera: no se requiere ninguna dependencia nueva (GDAL CLI + bindings y rasterio ya están en la imagen); la verificación de workers queda como paso obligatorio en `quickstart.md` |
| G5 | Tests en Docker (`docs/entorno-plugins.md`) | ✅ PASS — la validación corre con `run_tests_in_docker.sh`; nada se instala en el host |

**Post-design re-check (tras Phase 1)**: ✅ PASS — el diseño no introdujo dependencias
nuevas ni toques al core; los contratos usan exclusivamente los puntos de extensión del
framework.

## Project Structure

### Documentation (this feature)

```text
specs/001-viewshed-analysis/
├── plan.md              # Este archivo
├── research.md          # Phase 0: decisiones técnicas y alternativas
├── data-model.md        # Phase 1: entidades y validaciones
├── quickstart.md        # Phase 1: guía de validación end-to-end
├── contracts/
│   └── api.md           # Phase 1: contrato de la API del plugin
└── tasks.md             # Phase 2 (/speckit-tasks — no lo crea este comando)
```

### Source Code (repository root)

```text
coreplugins/viewshed/
├── __init__.py
├── manifest.json            # metadatos del plugin (base: manifest de contours)
├── plugin.py                # Plugin(PluginBase): api_mount_points + JS/JSX
├── api.py                   # TaskViewshedGenerate (POST) + TaskViewshedDownload (GET)
│                            #   + función calc_viewshed ejecutada en worker
├── tests.py                 # tests Django del plugin (corren en Docker)
└── public/
    ├── main.js              # PluginsAPI.Map.willAddControls → monta el control
    ├── Viewshed.jsx         # control Leaflet (botón en el mapa, se compila a build/)
    ├── Viewshed.scss
    ├── ViewshedPanel.jsx    # panel: captura de clic, campo de altura, progreso,
    │                        #   polling (Workers.js) y render de la capa GeoJSON
    ├── ViewshedPanel.scss
    └── icon.svg
```

**Structure Decision**: plugin autocontenido en `coreplugins/viewshed/`, calcado de la
estructura real de `coreplugins/contours/` (verificada en este repo). Backend de dos
endpoints montados bajo `/api/plugins/viewshed/`, cálculo asíncrono en worker, frontend
como control Leaflet + panel React compilados por `build_plugins`.

## Complexity Tracking

> Sin violaciones constitucionales que justificar — tabla vacía.
