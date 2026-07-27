# Implementation Plan: Polilíneas anotadas sobre el mapa 2D, planas o sobre el terreno

**Branch**: `master` (spec dir: `004-polyline-annotations`) | **Date**: 2026-07-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-polyline-annotations/spec.md`

## Summary

Plugin nuevo `annotations` que permite trazar polilíneas sobre el mapa 2D de una tarea, en dos modos
—**plana** o **sobre el terreno** con cotas tomadas del DSM/DTM—, persistirlas por tarea, editarlas,
exportarlas a GeoJSON y ofrecerlas a otros plugins mediante un contrato versionado.

El punto de apoyo central es un hallazgo del análisis del core: **WebODM ya define un sistema de
anotaciones para plugins y ningún plugin lo implementa**. `PluginsAPI.Map` declara
`addAnnotation`/`toggleAnnotation`/`deleteAnnotation`/`downloadAnnotations`
(`classes/plugins/Map.js:24-32`), `Map.jsx:715-717` y `1041-1066` los consumen, y
`LayersControlAnnotations.jsx` ya renderiza visibilidad, encuadre, renombrado, borrado y exportación
—con un `// TODO?` vacío en el botón de descarga esperando a un productor—. Publicar las polilíneas
por ahí entrega FR-028 a FR-032 sin escribir interfaz de capas y **sin tocar el core**.

El dibujo y la edición de vértices se implementan directamente sobre Leaflet, sin librería nueva,
siguiendo el precedente de `realign` (D1). El muestreo del DEM usa `rasterio` y `rasterio.warp`, ya
en la imagen, resuelto **dentro de la propia petición HTTP** —sin Celery— porque el peor caso
admitido ronda el segundo (D3, D6). La persistencia es un documento JSON por tarea en el
`GlobalDataStore`, calcado de `realign/store.py` (D7). **Cero dependencias nuevas** (nivel 0 del
Principio IV) y **cero archivos del core modificados**.

La investigación se validó ejecutando código en el contenedor `webapp` sobre el DSM real de una
tarea procesada (EPSG:32719, 0,0222 m/px), y produjo el hallazgo que más condicionó el diseño: **la
longitud sobre el terreno no es un valor único, depende del paso de densificación**. Sobre un mismo
tramo de 188 m con cobertura completa, la longitud 3D va de +65 % al paso nativo a +15 % al paso de
5 m —un 43 % de variación sin cambiar trazado ni modelo—. Por eso el paso es un parámetro explícito
con defecto acotado, se persiste junto a la cifra que produjo y se muestra siempre con ella. El spec
se actualizó en consecuencia (FR-014, FR-015, FR-017, SC-004 y Assumptions).

## Technical Context

**Language/Version**: Python 3.9 (backend, Django 2.2.27) + JavaScript ES6/React 16 con JSX compilado
por el mecanismo `build_plugins` (webpack) del framework de plugins.

**Primary Dependencies**: framework de plugins de WebODM (`PluginBase`, `MountPoint`,
`TaskView`/`get_and_check_task`, `check_project_perms`, `GlobalDataStore`/`PluginDatum`,
`app.plugins.signals.task_removed`); **`rasterio` 1.3.10** (`requirements.txt:56`) para
`open`/`sample` y `rasterio.warp.transform`; `numpy` 1.26.2; en el frontend, **Leaflet 1.3.1**
(`package.json:53`), `PluginsAPI.Map` y `webodm/classes/Units`. **Sin dependencias nuevas**: no se
usa `pyproj` —presente en la imagen (3.6.1) pero ausente de `requirements.txt`, luego frágil ante
merges de upstream— ni `shapely`, que no está instalado.

**Storage**: un documento JSON por tarea en el `GlobalDataStore`, espacio de nombres `annotations`,
clave `task_<pk>`, `user = NULL`. `PluginDatum.json_value` es `jsonb`
(`app/models/plugin_datum.py:13`). Sin modelos ni migraciones nuevas. La geometría densificada **no
se persiste**: 288 KB de JSON para 188 m al paso nativo frente a 0,014 s de recálculo (D5).

**Testing**: Django tests en `coreplugins/annotations/tests.py`, ejecutados en Docker
(`docker compose exec webapp /webodm/webodm.sh test backend coreplugins.annotations.tests`), con
DEM sintéticos generados al vuelo con `rasterio` —incluido uno con parche de `nodata`—. En el host
solo se corren, como mucho, comprobaciones sin dependencias nativas.

**Target Platform**: contenedores webapp + worker de WebODM (imagen compartida
`webodm/webodm_webapp`, Ubuntu 22.04) + navegador para la parte de mapa.

**Project Type**: plugin nuevo de WebODM en `coreplugins/annotations/`.

**Performance Goals**: medido — muestreo de 8 489 puntos en 0,157 s y de 26 217 en 0,97 s; al paso
por defecto, una línea de 188 m son 755 puntos en 0,014 s. Con el tope de 20 000 puntos el peor caso
queda en torno a 0,3–0,8 s, dentro del objetivo de SC-003 (< 3 s) sin necesidad de asincronía.

**Constraints**: cero modificaciones al core (Principio I); cero dependencias nuevas (Principio IV
nivel 0); nunca se rellenan ni interpolan cotas —cobertura incompleta se rechaza entera (FR-021,
FR-022)—; toda longitud sobre el terreno viaja con su paso de densificación (FR-015); los
manejadores del bus de anotaciones deben devolver `false` sobre layers ajenos para no romper a
futuros productores (`ApiFactory.js:95-102`); trazado y edición de geometría solo con una tarea en
el mapa (FR-031).

**Scale/Scope**: decenas de polilíneas por tarea; hasta 500 vértices y 20 000 puntos densificados por
polilínea; un documento `jsonb` por tarea del orden de decenas de KB.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Principio | Evaluación |
|---|---|---|
| G1 | I. Desarrollo solo-plugins | ✅ PASS — todo el código vive en `coreplugins/annotations/`. Se consumen solo puntos de extensión existentes: `api_mount_points`, `include_js_files`, `build_jsx_components`, `GlobalDataStore`, `app.plugins.signals.task_removed` y el bus `PluginsAPI.Map`. El defecto detectado en `Map.jsx:1148-1150` (da de baja el manejador equivocado) **no se corrige aquí**: sería tocar el core. |
| G2 | II. Compatibilidad con upstream | ✅ PASS — archivos nuevos en `coreplugins/annotations/` y `specs/004-…`; ningún archivo de upstream modificado, luego superficie de conflicto nula. Se descarta `pyproj` justamente por no estar declarado en `requirements.txt` y poder desaparecer en un merge. |
| G3 | III. Convenciones de plugin | ✅ PASS — estructura estándar: `manifest.json` completo, `plugin.py` con `Plugin(PluginBase)`, `__init__.py` con `from .plugin import *` (requisito del cargador), assets en `public/` compilados por `build_plugins`. Nombre `annotations` sin colisión en `coreplugins/`. Deshabilitable sin romper nada, verificado en `quickstart.md` §4 (SC-010). |
| G4 | IV. Gestión de dependencias | ✅ PASS — **nivel 0**: `rasterio`, `numpy` y `osgeo` ya están en la imagen; Leaflet ya está en el bundle del core. Sin `requirements.txt` de plugin, sin `package.json`, sin tocar el `Dockerfile`. La verificación obligatoria del worker (IV.3) está en `quickstart.md` §4, e importa aquí porque el receptor de `task_removed` corre donde se borre la tarea. |
| G5 | Tests en Docker (`docs/entorno-plugins.md`) | ✅ PASS — toda la validación corre dentro de Docker; los DEM de prueba se generan en el contenedor y no se versiona ningún GeoTIFF. |

**Post-design re-check (tras Phase 1)**: ✅ PASS — el diseño no introdujo dependencias ni toques al
core. Los contratos exponen únicamente rutas nuevas bajo `/api/plugins/annotations/` y métodos
públicos de la propia clase `Plugin`, obtenida por el `get_plugin_by_name` del framework, que además
permite al consumidor degradar con elegancia si el plugin está ausente o deshabilitado. La única
observación de riesgo —acaparar el bus de anotaciones devolviendo `true` de más— queda recogida como
regla explícita en `contracts/plugin-contract.md` §2.3 y debe cubrirse con un test.

## Project Structure

### Documentation (this feature)

```text
specs/004-polyline-annotations/
├── plan.md                       # Este archivo
├── spec.md                       # Especificación (actualizada tras D4)
├── research.md                   # Phase 0: D1–D12 + riesgos
├── data-model.md                 # Phase 1: documento por tarea, entidades, transiciones
├── quickstart.md                 # Phase 1: despliegue, tests y validación manual
├── contracts/
│   ├── rest-api.md               # Endpoints REST del plugin
│   └── plugin-contract.md        # Contrato para otros plugins + contrato con el core
├── checklists/
│   └── requirements.md           # Checklist de calidad del spec
└── tasks.md                      # Phase 2 (/speckit-tasks — no lo crea este comando)
```

### Source Code (repository root)

```text
coreplugins/annotations/
├── __init__.py                   # from .plugin import *  (requisito del cargador)
├── manifest.json
├── plugin.py                     # Plugin(PluginBase): mount points, assets, métodos del contrato
├── api.py                        # Vistas TaskView: CRUD, elevate/flatten, densified, export
├── store.py                      # GlobalDataStore: leer/escribir el documento de la tarea
├── elevation.py                  # Selección de DEM, densificación, sample(), cobertura, métricas
├── geometry.py                   # Validación de vértices, proyección, longitudes
├── contract.py                   # Superficie pública versionada para otros plugins
├── signals.py                    # Receptor de task_removed (borrado en cascada)
├── tests.py                      # Django tests (patrón de coreplugins/realign/tests.py)
└── public/
    ├── main.js                   # Engancha a PluginsAPI.Map.willAddControls
    ├── Annotations.jsx           # Control Leaflet + botón
    ├── Annotations.scss
    ├── AnnotationsPanel.jsx      # Panel: lista, modos, paso, acciones
    ├── AnnotationsPanel.scss
    ├── PolylineEditor.js         # Trazado y edición de vértices sobre Leaflet (D1)
    ├── annotationsBridge.js      # Manejadores del bus de anotaciones del core (D2)
    └── icon.svg
```

**Structure Decision**: plugin autónomo bajo `coreplugins/annotations/`, con la estructura estándar
del framework que ya siguen `viewshed` y `realign` en este fork. El backend se separa por
responsabilidad —`store` (persistencia), `elevation` (DEM), `geometry` (validación y longitudes),
`contract` (superficie pública)— para que `api.py` quede como capa delgada de vistas y para que el
contrato de otros plugins no dependa de detalles de almacenamiento. En el frontend se aísla
`PolylineEditor.js` (interacción pura con Leaflet, sin React) de los componentes de panel, y
`annotationsBridge.js` concentra el diálogo con el bus del core, que es donde está la regla delicada
de no devolver `true` sobre layers ajenos.

## Complexity Tracking

> Sin violaciones de la Constitución que justificar: los cinco gates pasan en verde, sin
> dependencias nuevas y sin modificaciones al core.
