# Implementation Plan: Realineación manual de productos ráster 2D mediante puntos de control

**Branch**: `master` (spec dir: `002-realign-products`) | **Date**: 2026-07-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-realign-products/spec.md`

## Summary

Plugin `realign` para el fork de WebODM: en la vista 2D de una tarea procesada, el usuario
activa una herramienta, marca pares de puntos de control (rasgo en la ortofoto → mismo rasgo
en el mapa base) y el sistema ajusta una **transformación de similitud** (traslación +
rotación + escala uniforme) por mínimos cuadrados (Umeyama), mostrando el residuo por punto y
el RMSE en vivo. La **previsualización** desplaza/rota/escala las capas ráster en el mapa
mediante una matriz CSS afín sobre el contenedor de la capa Leaflet (instantáneo, sin tocar
archivos). Al pulsar **Aplicar**, un cálculo asíncrono en el worker genera copias corregidas
de los productos ráster 2D (`orthophoto.tif`, `dsm.tif`, `dtm.tif`) como COG north-up con la
nueva georreferenciación, guardadas en el **directorio persistente del plugin** (compartido
webapp↔workers), conservando intactos los originales de la tarea. El plugin **sirve sus
propios tiles y descargas** de los productos corregidos (rio-tiler, ya en la imagen) y el
frontend intercambia la capa mostrada; **Revertir** vuelve al estado original. El estado
—pares de puntos, transformación, residuos, estado y rutas corregidas— se **persiste por
tarea** en el `GlobalDataStore` del plugin (modelo `PluginDatum`), accesible para todos los
usuarios con acceso a la tarea. **Cero dependencias nuevas** (nivel 0 de la escalera del
Principio IV): GDAL CLI, numpy y rio-tiler ya están en la imagen. Sigue el patrón del
coreplugin `viewshed` (control Leaflet + panel React + cálculo async en worker vía
`run_function_async`), extendido con persistencia (`DataStore`) y un tiler propio.

## Technical Context

**Language/Version**: Python 3.9 (backend, Django 2.2.27) + JavaScript ES6/React 16 con JSX
compilado por el mecanismo `build_plugins` (webpack) del framework de plugins.

**Primary Dependencies**: framework de plugins de WebODM (`PluginBase`, `MountPoint`,
`TaskView`/`get_and_check_task`, `run_function_async`, `CheckTask`/`GetTaskResult`,
`GlobalDataStore`/`PluginDatum`, `get_persistent_path`); GDAL 3.4.x de la imagen
(`gdalwarp`, `gdal_edit`/`gdal_translate`, driver `COG`, bindings `osgeo`); `numpy` 1.26
(ajuste de similitud); `rio-tiler` 2.1 (`COGReader`) para el tiler propio del plugin;
Leaflet + `PluginsAPI.Map` (frontend). **Sin dependencias nuevas** — ver `docs/entorno-plugins.md`.

**Storage**: (1) estado de realineación por tarea en BD vía `GlobalDataStore` del plugin
(`PluginDatum.json_value`, key `task_<pk>`); (2) productos ráster corregidos en el directorio
persistente del plugin `get_persistent_path("task_<pk>/<producto>.tif")`
(`MEDIA_ROOT/plugins/realign/...`, volumen compartido webapp↔workers). Los assets originales
de la tarea (`task.get_asset_download_path(...)`) NUNCA se modifican.

**Testing**: Django tests en `coreplugins/realign/tests.py`, ejecutados en Docker
(`./run_tests_in_docker.sh` o `docker compose exec webapp /webodm/webodm.sh test backend
coreplugins.realign.tests`). Tests de la matemática de similitud (numpy) y del pipeline GDAL
con un GeoTIFF pequeño de fixture. En el Mac local solo tests ligeros sin stack nativo.

**Target Platform**: contenedores webapp + worker de WebODM (imagen compartida
`webodm/webodm_webapp`, Ubuntu 22.04).

**Project Type**: plugin de WebODM (directorio autocontenido `coreplugins/realign/`).

**Performance Goals**: residuos/RMSE y previsualización actualizados de forma percibida como
inmediata (< 1 s, SC-002) — se calculan en el cliente sin ida y vuelta al servidor;
generación de productos corregidos asíncrona en worker con indicador de progreso (UI no
bloqueante).

**Constraints**: cero modificaciones al core (Principio I) — el core tiler solo lee el asset
original, por lo que el plugin sirve sus propios tiles/descargas de los corregidos; operación
no destructiva (originales intactos, FR-009); cada aplicación parte siempre del original
(FR-010, sin acumulación); Aplicar/Revertir restringidos a `change_project` (FR-014); diseño
de la transformación independiente del tipo de dato para habilitar la nube de puntos en una
etapa futura (FR-017).

**Scale/Scope**: ortofotos/DEM típicos de dron (decenas a cientos de MB); pocos pares de
puntos por tarea (típicamente 2–8); un estado de realineación por tarea.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Principio | Evaluación |
|---|---|---|
| G1 | I. Desarrollo solo-plugins | ✅ PASS — todo el código vive en `coreplugins/realign/`; cero ediciones a `app/`, `webodm/`, `worker/`, `nodeodm/`. El intercambio de capa en el mapa se hace desde el control del plugin vía `PluginsAPI.Map.willAddControls` (`args.map`, `args.tiles`), sin tocar el frontend del core |
| G2 | II. Compatibilidad con upstream | ✅ PASS — solo se agrega un directorio nuevo (`realign`, sin colisión con `align-service` de upstream); ningún archivo upstream tocado |
| G3 | III. Convenciones de plugin | ✅ PASS — `manifest.json`, `plugin.py` con `Plugin(PluginBase)`; integración solo vía `api_mount_points`, `include_js_files`, `build_jsx_components`; assets en `public/`; persistencia vía `GlobalDataStore`/`get_persistent_path` (mecanismos del framework); deshabilitable sin romper el resto |
| G4 | IV. Gestión de dependencias | ✅ PASS — nivel 0: cero dependencias nuevas (GDAL CLI+bindings, numpy y rio-tiler ya en la imagen); la verificación de arranque del worker ejecutando el pipeline queda como paso obligatorio en `quickstart.md` |
| G5 | Tests en Docker (`docs/entorno-plugins.md`) | ✅ PASS — la validación corre con `run_tests_in_docker.sh`; nada se instala en el host |

**Post-design re-check (tras Phase 1)**: ✅ PASS — el diseño no introdujo dependencias nuevas
ni toques al core. Los datos persistentes usan `PluginDatum` (BD del framework) y el
directorio persistente del plugin; los contratos exponen solo endpoints bajo
`/api/plugins/realign/` y assets en `public/`.

## Project Structure

### Documentation (this feature)

```text
specs/002-realign-products/
├── plan.md              # Este archivo
├── research.md          # Phase 0: decisiones técnicas y alternativas
├── data-model.md        # Phase 1: entidades y validaciones
├── quickstart.md        # Phase 1: guía de validación end-to-end (incluye verificación de worker)
├── contracts/
│   └── api.md           # Phase 1: contrato de la API del plugin
├── checklists/
│   └── requirements.md  # Checklist de calidad de la spec (de /speckit-specify)
└── tasks.md             # Phase 2 (/speckit-tasks — no lo crea este comando)
```

### Source Code (repository root)

```text
coreplugins/realign/
├── __init__.py
├── manifest.json                 # metadatos del plugin (base: manifest de viewshed)
├── plugin.py                     # Plugin(PluginBase): api_mount_points + include_js + build_jsx
├── api.py                        # endpoints REST (estado, aplicar, revertir, tiles, tilejson, descarga)
├── transform.py                  # ajuste de similitud (Umeyama, numpy) + residuos/RMSE (reutilizable backend)
├── corrections.py                # pipeline GDAL: similitud → geotransform rotado → gdalwarp COG north-up
├── store.py                      # helpers de persistencia sobre GlobalDataStore (estado por tarea)
├── tests.py                      # tests Django del plugin (corren en Docker)
└── public/
    ├── main.js                   # PluginsAPI.Map.willAddControls → monta el control
    ├── Realign.jsx               # control Leaflet (botón en el mapa; se compila a build/)
    ├── Realign.scss
    ├── RealignPanel.jsx          # panel: captura de pares de puntos, tabla de residuos/RMSE,
    │                             #   previsualización (matriz CSS), botones Aplicar/Revertir, polling
    ├── RealignPanel.scss
    ├── similarity.js             # ajuste de similitud en el cliente (previsualización/residuos en vivo)
    └── icon.svg
```

**Structure Decision**: plugin autocontenido en `coreplugins/realign/`, calcado de la
estructura real de `coreplugins/viewshed/` (verificada en este repo), con tres piezas backend
extra respecto a viewshed: `store.py` (persistencia por tarea con `GlobalDataStore`),
`transform.py` (matemática de similitud) y `corrections.py` (pipeline GDAL + tiler). La
integración con WebODM ocurre exclusivamente por `api_mount_points` (endpoints bajo
`/api/plugins/realign/`) y por los puntos de extensión de frontend (`include_js_files`,
`build_jsx_components`). La lógica de similitud se implementa dos veces —en JS para la
previsualización instantánea en el cliente y en Python (numpy) para el cálculo autoritativo al
aplicar— y ambas se cubren con tests de paridad sobre los mismos casos.

## Complexity Tracking

> Sin violaciones constitucionales que justificar — tabla vacía.

## Actualización — Interruptor de escala (User Story 5, 2026-07-23)

Ampliación planeada en `research.md` (D9), `data-model.md` (campo `use_scale` en
`SimilarityTransform`) y `contracts/api.md` (campo `use_scale` en `PUT state` / `POST apply`).
**No agrega archivos nuevos ni dependencias**: es un branch dentro de las mismas funciones de
ajuste (`public/similarity.js`, `transform.py`), un campo nuevo en el documento persistido
(`store.py`/`api.py`) y un control en `RealignPanel.jsx`. Constitution Check no cambia (sigue
PASS en los 5 gates: nada nuevo toca el core, no hay dependencias nuevas, mismo mecanismo de
persistencia `PluginDatum`).
