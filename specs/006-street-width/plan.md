# Implementation Plan: ancho de calle por criterio de superficie (`road`)

**Branch**: `006-street-width` | **Date**: 2026-07-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-street-width/spec.md`

## Summary

Segundo criterio de detección de borde para el plugin `road`, pensado para calles con bordillo, más
una pasada de coherencia entre tramos vecinos que corrige atípicos y huecos cortos declarando
siempre el origen de cada borde.

Enfoque técnico: donde el criterio actual busca **lo afilado** (racha de pendiente local por encima
de un umbral), el nuevo busca **lo alto** — se ajusta una recta a las muestras de calzada del propio
perfil transversal y el borde es el primer punto que se aparta de esa recta más de una tolerancia y
se mantiene apartado. El ajuste se rehace sobre las muestras entre los bordes provisionales y la
detección se repite, lo que absorbe el peralte y tolera un eje descentrado sin añadir parámetros. La
coherencia es una pasada posterior, sobre los bordes ya detectados de todos los tramos, que
reemplaza por la mediana de la vecindad los bordes que se apartan más de lo que la propia dispersión
de esa vecindad admite; solo los bordes medidos votan, de modo que la inferencia nunca se propaga en
cadena.

Ambas piezas son funciones puras sin E/S, igual que `profile.py` hoy, y el único cambio en el
pipeline es un despacho por modo y una llamada a la coherencia antes de la reproyección final.

Detalle de cada decisión y sus alternativas en [research.md](./research.md).

## Convención de numeración de decisiones

Las decisiones de esta feature se numeran **D17 en adelante**, continuando la serie de
`005-road-metrics` (D1–D16), porque ambas describen el mismo plugin y el código las cita por número.
Los requisitos, en cambio, se numeran de nuevo desde `FR-001` y los de la feature anterior se citan
como `005/FR-0xx`.

## Technical Context

**Language/Version**: Python 3.9 (imagen `webodm/webodm_webapp`, Ubuntu 22.04) para el backend;
JavaScript ES6 + React para el frontend, compilado por el `build_plugins` existente (webpack).

**Primary Dependencies**: ninguna nueva. `numpy` 1.26.2 para el ajuste por mínimos cuadrados, la
mediana y el MAD; `rasterio` 1.3.10 sigue siendo quien lee el DEM, sin cambios. Frontend: Leaflet y
el bus `PluginsAPI.Map`, ya en uso.

**Storage**: sin cambios. El índice sigue en `GlobalDataStore('road')` y los tramos en el archivo
JSON por análisis. Los campos nuevos son claves nuevas dentro del mismo documento de tramos; no hay
tabla, migración ni conversión de datos existentes.

**Testing**: `webodm.sh test backend coreplugins.road.tests` dentro de Docker. Los dos módulos
nuevos son puros, así que la mayor parte del peso cae en tests unitarios contra perfiles sintéticos
—sin ráster y sin Django—, más los de integración sobre DEM sintéticos generados con `rasterio` y
los de frontend en jsdom que ya lanza la misma suite.

**Target Platform**: WebODM autoalojado sobre Docker; webapp y worker comparten imagen.

**Project Type**: extensión de un plugin existente — backend Django/DRF más frontend React/Leaflet,
todo dentro de `coreplugins/road/`.

**Performance Goals**: el modo superficie no debe superar en más del 25 % el tiempo del modo quiebre
con los mismos parámetros (SC-007). El coste añadido por transversal son dos ajustes lineales sobre
un vector que ya está en memoria, frente a la lectura del ráster que domina el total.

**Constraints**: el modo por defecto debe producir resultados **idénticos** a los actuales, bit a
bit en los valores reportados (FR-002, SC-004); la inferencia nunca puede propagarse en cadena
(FR-013); la función que corre en el worker se reejecuta por código fuente en un namespace vacío, así
que todo import nuevo debe ser absoluto y estar dentro del cuerpo (D23); retener perfiles
transversales para la coherencia tiene un coste de memoria acotado que hay que declarar (D22).

**Scale/Scope**: mismos órdenes que `005` — de 100 a 2.000 tramos por análisis. Alcance de código:
un módulo Python nuevo (`coherence.py`), cuatro modificados (`profile.py`, `compute.py`,
`sources.py`, `export.py`) y tres archivos de frontend.

## Constitution Check

*GATE: revisado antes de Phase 0 y de nuevo tras Phase 1. Resultado en ambos pasos: **PASA**.*

### I. Desarrollo solo-plugins (no negociable)

Toda la funcionalidad vive dentro de `coreplugins/road/`. **Cero cambios** en `app/`, `webodm/`,
`worker/`, `nodeodm/`, `nginx/` o los scripts raíz, y esta vez tampoco en ningún otro plugin: a
diferencia de `005`, no hace falta tocar `coreplugins/realign/` porque no se consume ningún contrato
nuevo.

### II. Compatibilidad con upstream

Los archivos nuevos están en rutas que upstream no toca (`coreplugins/road/coherence.py`,
`specs/006-street-width/`). Los modificados son todos propios del fork. Superficie de conflicto de
merge: nula.

### III. Convenciones de plugin

No se altera la estructura del plugin: mismo `manifest.json`, misma clase `Plugin(PluginBase)`,
mismos puntos de extensión. Los assets de frontend siguen en `public/` y los construye el
`build_plugins` existente. El plugin sigue pudiendo deshabilitarse sin efectos sobre `annotations`
ni `realign`.

Un punto que sí toca vigilar: los tres motivos de "sin borde" se **reutilizan** en lugar de ampliarse
(FR-010), para no romper el contrato que ya consume el frontend con sus tres etiquetas.

### IV. Gestión de dependencias de plugins

- **Paso 1 (Python puro)**: no aplica. `numpy` ya está en `requirements.txt` del core y en la imagen.
  El plugin sigue sin `requirements.txt` propio.
- **Paso 2 (sistema)**: no aplica. El `Dockerfile` no se toca.
- **Paso 3 (verificación de workers, no negociable)**: **sí aplica, y es el riesgo principal de esta
  feature.** `run_function_async` reejecuta la función del worker por código fuente en un namespace
  vacío, así que el módulo nuevo `coherence` solo es visible si se importa de forma absoluta y dentro
  del cuerpo de la función. Un import a nivel de módulo, o relativo, pasa todos los tests locales y
  falla únicamente en el worker. El procedimiento de verificación está en
  [quickstart.md](./quickstart.md#verificación-del-worker-principio-iv-no-negociable) y la feature no
  se cierra sin la evidencia del log del worker completando un análisis en modo superficie.

**Re-evaluación tras Phase 1**: el diseño no introdujo ningún elemento que cambie lo anterior. Sin
violaciones que registrar en Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/006-street-width/
├── spec.md                       # Qué y por qué
├── plan.md                       # Este archivo
├── research.md                   # Phase 0: decisiones D17–D23
├── data-model.md                 # Phase 1: campos, estados e invariantes (delta sobre 005)
├── contracts/
│   └── rest-api-delta.md         # Phase 1: solo las adiciones al contrato de 005
├── quickstart.md                 # Phase 1: escenarios de validación ejecutables
├── checklists/
│   └── requirements.md           # Validación de calidad de la spec
└── tasks.md                      # Phase 2 (/speckit-tasks — no lo crea este comando)
```

### Source Code (repository root)

```text
coreplugins/road/
├── profile.py                    # MODIF: + detect_edges_surface(), + constantes de origen
├── coherence.py                  # NUEVO: repair_edges(), función pura sin E/S
├── compute.py                    # MODIF: despacho por modo, pasada de coherencia, estado inferred
├── sources.py                    # MODIF: 3 parámetros nuevos (defectos, rangos, validación)
├── export.py                     # MODIF: columnas y propiedades de origen y modo
├── api.py                        # sin cambios (los parámetros viajan por el mismo canal)
├── public/
│   ├── segmentStyle.js           # MODIF: estilo propio para el estado inferred
│   ├── roadBridge.js             # MODIF: el popup marca el origen por lado
│   ├── RoadPanel.jsx             # MODIF: selector de modo y dos controles nuevos
│   └── tests/
│       ├── segmentStyle.test.js  # MODIF: estilo del estado inferred
│       └── roadBridge.test.js    # MODIF: popup con origen por lado
├── tests/
│   ├── test_profile.py           # MODIF: perfiles sintéticos del criterio de superficie
│   ├── test_coherence.py         # NUEVO: reparación local, sin cascada, ventana 0 = identidad
│   ├── test_compute.py           # MODIF: no regresión del modo quiebre, calle sintética
│   ├── test_params.py            # MODIF: rangos y validación de los tres parámetros
│   ├── test_export.py            # MODIF: origen y modo en CSV y GeoJSON
│   └── __init__.py               # MODIF: re-export de la clase de test nueva
└── README.md                     # MODIF: los dos modos y cuándo usar cada uno
```

**Structure Decision**: se conserva la estructura de `005` sin reorganizar nada. La única pieza nueva
es `coherence.py`, separada de `profile.py` a propósito: `profile` opera sobre **un** perfil
transversal y no sabe que existen otros tramos, mientras que `coherence` opera sobre la **secuencia**
de bordes ya detectados y no sabe qué es un DEM. Son dos responsabilidades con entradas distintas y
mezclarlas obligaría a `profile` a recibir contexto que no necesita para su trabajo.

Recordatorio de `005` que sigue vigente: los tests del plugin viven en un paquete de espacio de
nombres, así que toda clase de test nueva debe re-exportarse desde `tests/__init__.py` o el
descubridor de Django no la encuentra.

## Complexity Tracking

> Sin violaciones de la constitución que justificar.

Se registra aquí, no como violación sino como deuda aceptada conscientemente, la decisión de
mantener **dos criterios de detección** en vez de uno:

| Elemento | Por qué se acepta | Alternativa descartada |
|---|---|---|
| Dos modos de detección coexistiendo | Los análisis rurales ya entregados no pueden cambiar de resultado, y no se ha medido si el criterio de superficie los serviría igual de bien | Sustituir el detector: se descartó por apostar a ciegas sobre trabajo ya validado. La medición que lo resolvería está descrita en D24 y puede convertir esto en un solo modo más adelante |
