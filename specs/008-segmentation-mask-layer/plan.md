# Implementation Plan: Capa de máscara del modelo de segmentación

**Branch**: `006-street-width` (rama de trabajo actual del plugin) | **Date**: 2026-07-29 |
**Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/008-segmentation-mask-layer/spec.md`

## Summary

Hacer visible en el mapa la máscara de calzada que el modelo de segmentación produce, para que el
usuario pueda auditar de un vistazo un número que hoy es incontrastable desde la interfaz.

El enfoque técnico se apoya en un hallazgo de la fase de investigación: **la máscara ráster ya se
calcula y ya se guarda en un temporal**. No hace falta volver a correr el modelo — basta con
vectorizar ese ráster (`rasterio.features.shapes`, 0,048 s, resultado idéntico al de pedirle el
GeoJSON a la librería, que costaría una segunda inferencia de hasta 13,5 s), simplificarlo a la
resolución de la propia máscara y persistirlo junto al documento de tramos. El frontend lo pide solo
cuando el usuario enciende la capa.

## Technical Context

**Language/Version**: Python 3.9 (contenedor WebODM) · JavaScript ES2018+ / React (panel del plugin)

**Primary Dependencies**: `rasterio` (vectorización y lectura, ya presente desde `005`),
`django.contrib.gis.geos` (simplificación, ya presente), `geodeep` (inferencia, ya presente desde
`007`), Leaflet (dibujo, ya presente). **Ninguna dependencia nueva.**

**Storage**: ficheros JSON en `get_plugins_persistent_path('road', 'task_<pk>')`, el mecanismo del
framework que el plugin ya usa para los tramos. Índice de análisis en `GlobalDataStore`.

**Testing**: `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.road.tests`
(310 tests hoy). Los tests de JS del plugin corren con jsdom sin navegador.

**Target Platform**: contenedor Linux de WebODM (webapp + worker comparten imagen), navegador para
el panel.

**Project Type**: plugin de WebODM (backend Django/DRF + frontend React dentro de `coreplugins/`).

**Performance Goals**: la vectorización y simplificación no deben ser perceptibles frente al coste
de la inferencia. Medido: 0,036–0,048 s de vectorización frente a 0,66–13,49 s de inferencia, es
decir <0,4 % del total. Encender la capa debe ser inmediato para el usuario (`SC-002`).

**Constraints**: la máscara persistida debe quedar en decenas de KB (medido: 19,5 KB a 66 m,
76,9 KB a 293 m). Ningún análisis existente puede cambiar de resultado. La capa no puede capturar
eventos de ratón ni usar la paleta del semáforo de pendiente.

**Scale/Scope**: corredores medidos entre 66 m y 293 m. Un único plugin, ~6 ficheros de código
tocados y 2 nuevos.

## Constitution Check

*GATE: revisado antes de Phase 0 y de nuevo tras Phase 1. Sin violaciones.*

### I. Desarrollo solo-plugins (NO NEGOCIABLE) — ✅ PASS

Todo el cambio vive en `coreplugins/road/`. No se toca `app/`, `webodm/`, `worker/`, `nodeodm/`,
`nginx/` ni ningún script raíz. La integración con el mapa usa `PluginsAPI`, que es un punto de
extensión público del framework y ya lo usa el plugin desde `005`.

### II. Compatibilidad con upstream — ✅ PASS

No se modifica ningún fichero que upstream toque. Los artefactos de esta feature viven en
`specs/008-…/` y en `coreplugins/road/`, rutas propias del fork.

### III. Convenciones de plugin — ✅ PASS

Se conserva la estructura estándar: la ruta nueva se registra por `api_mount_points`, el frontend
sigue en `public/` y se construye con el `build_plugins`/webpack existente. El plugin sigue pudiendo
deshabilitarse sin romper nada — la máscara es un fichero inerte si el plugin no está activo.

Detalle atendido: `plugin.py` documenta que un `MountPoint` sin `$` final resuelve por prefijo. La
ruta nueva se ancla con `$` y se registra antes del patrón genérico de `<analysis_id>`, siguiendo la
convención ya establecida para `estimate`, `cancel` y `export`.

### IV. Gestión de dependencias de plugins — ✅ PASS, con el paso 3 como riesgo principal

- **Paso 1 (dependencias Python puras)**: no aplica. `rasterio`, `django.contrib.gis.geos` y
  `geodeep` ya están en la imagen; las dos primeras desde `005`/el core, `geodeep` desde antes de
  `007` porque la usa `objdetect` de upstream. **No se añade nada a ningún `requirements.txt`.**
- **Paso 2 (dependencias de sistema)**: no aplica. No hay binarios nuevos; `gdalwarp` ya se usaba en
  `007`. **El `Dockerfile` no se toca y no hay que reconstruir la imagen.**
- **Paso 3 (verificación de workers, NO NEGOCIABLE)**: **aplica y es el riesgo principal de esta
  feature.** La vectorización corre en el worker, dentro de la cadena que arranca en `run_analysis`,
  que es *self-contained*: `run_function_async` la recompila desde su código fuente en un espacio de
  nombres vacío. Un import mal colocado produce un `NameError` que **ningún test de la suite
  detecta**, porque la suite no usa el worker real. La mitigación es D41 (los imports nuevos van en
  `segmentation.py`, no en `run_analysis`, reutilizando el patrón ya probado de `006`/D23 y
  `007`/D31) y la verificación obligatoria del Escenario 10 del quickstart, con log del worker como
  evidencia.

### Restricciones de infraestructura — ✅ PASS

«Datos persistentes de plugins van en `get_persistent_path()` / la base de datos vía los mecanismos
del framework, nunca en rutas ad-hoc del contenedor.» Esta feature **mejora** el cumplimiento
actual: hoy la máscara solo existe en un temporal de `MEDIA_TMP` que nadie limpia ni sirve, y pasa a
persistirse por `get_plugins_persistent_path`, el mismo mecanismo que los tramos (D35). No se tocan
`docker-compose*.yml`.

### Flujo de desarrollo — ✅ PASS

Se sigue `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`. Ninguna
tarea se marcará completa sin ejecutar su comando de verificación y mostrar la salida.

## Project Structure

### Documentation (this feature)

```text
specs/008-segmentation-mask-layer/
├── plan.md              # Este fichero
├── spec.md              # Qué y por qué
├── research.md          # D34–D41, con las mediciones que las sostienen
├── data-model.md        # Documento de máscara + campo has_mask
├── quickstart.md        # 10 escenarios de validación
├── contracts/
│   └── rest-api-delta.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Lo genera /speckit-tasks, no este comando
```

### Source Code (repository root)

```text
coreplugins/road/
├── segmentation.py          # MODIFICADO: vectorizar + simplificar la máscara ráster
├── store.py                 # MODIFICADO: write/read/delete del documento de máscara
├── compute.py               # MODIFICADO: persistir la máscara y marcar has_mask
├── api.py                   # MODIFICADO: endpoint de máscara; borrado en cascada
├── plugin.py                # MODIFICADO: registrar la ruta (antes del patrón genérico)
├── README.md                # MODIFICADO: documentar la capa y sus límites
├── public/
│   ├── RoadPanel.jsx        # MODIFICADO: control de la capa y avisos de FR-016/FR-018
│   ├── roadBridge.js        # MODIFICADO: publicar/retirar la capa de máscara
│   ├── maskLayer.js         # NUEVO: estilo y construcción de la capa
│   └── tests/
│       └── maskLayer.test.js    # NUEVO
└── tests/
    ├── test_mask_store.py       # NUEVO: persistencia y borrado en cascada
    ├── test_mask_vectorize.py   # NUEVO: vectorización, simplificación, filtro de área
    ├── test_api_mask.py         # NUEVO: endpoint y los tres estados de FR-017
    └── __init__.py              # MODIFICADO: reexportar los módulos nuevos
```

**Structure Decision**: se mantiene la estructura del plugin tal cual. La lógica de vectorización va
en `segmentation.py` (ya es el módulo de todo lo relativo al modelo) en lugar de crear uno nuevo,
porque comparte contexto con `run_segmentation` y porque así `compute` la alcanza con el import de
módulo que ya tiene — condición para que el worker self-contained funcione (D41). En el frontend sí
se crea `maskLayer.js` aparte, siguiendo el precedente de `segmentStyle.js` y `widthTick.js`: el
estilo separado del dibujo se puede probar con jsdom sin navegador.

**Nota sobre `tests/__init__.py`**: `coreplugins/` no tiene `__init__.py` (es un *namespace
package*), así que el runner de Django solo encuentra los tests explícitamente reexportados. Un
módulo de test nuevo que no se importe ahí **sencillamente no se ejecuta** — y pasaría inadvertido
como un falso «todo en verde».

## Complexity Tracking

> Sin violaciones de la constitución que justificar. La tabla se conserva vacía a propósito.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| *(ninguna)* | — | — |

## Riesgos y cómo se abordan

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| `NameError`/`ImportError` en el worker por la disciplina self-contained | **Alta** — ya ocurrió en `007` | D41 + Escenario 10 del quickstart con log real como evidencia |
| Olvidar un camino de borrado y dejar máscaras huérfanas | Media — hay **cinco** | Escenario 5 del quickstart cubre explícitamente cancelación y fallo, que son los que se olvidan |
| La capa captura clics y rompe los popups de tramo | Media | `interactive: false` (D39) + comprobación explícita en el Escenario 6 |
| La máscara tapa la ortofoto y la feature no sirve | Media | `FR-011` + verificación visual obligatoria (Escenario 6) |
| Tamaño desbocado en corredores muy largos | **Baja — medido** | 76,9 KB a 293 m (D40). Riesgo residual: no se han medido ejes de >1 km |

## Riesgo residual aceptado

No se han medido corredores de más de 293 m. El crecimiento observado es aproximadamente lineal con
la longitud (464 → 1836 vértices para 66 → 293 m), así que un eje de 1 km rondaría los 250 KB. No se
implementa mecanismo adaptativo (D40): sería complejidad especulativa para un caso no observado, y
tendría el efecto perverso de dar precisiones distintas a análisis del mismo modo sin avisar. Si
aparece, se mide y se decide entonces.
