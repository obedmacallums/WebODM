# Implementation Plan: borde por segmentación semántica de la ortofoto (`road`)

**Branch**: `006-street-width` (sin rama propia — no hay hook de creación de rama en este repositorio; ver nota) | **Date**: 2026-07-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-road-edge-segmentation/spec.md`

**Nota de rama**: `.specify/extensions.yml` no existe en este repositorio, así que `/speckit-specify`
y este plan no crean ni cambian de rama automáticamente (a diferencia de lo que sugiere el nombre
del directorio). El trabajo de esta feature se hace sobre la rama que esté activa en el momento de
implementar; el directorio `specs/007-road-edge-segmentation/` es independiente de esa decisión.

## Summary

Tercer criterio de detección de borde para el plugin `road`, pensado para calzadas cuyo límite no
tiene ningún relieve —cambio de textura o color entre asfalto y grava, entre calzada y tierra
suelta— donde ni el modo quiebre ni el modo superficie de `006` pueden encontrar nada porque no hay
señal de elevación que buscar.

Enfoque técnico: se clasifica la ortofoto en calzada / no-calzada con el modelo de segmentación
semántica `roads` de la librería `geodeep` (ya presente en la imagen — `research.md` D32), corriendo
sobre el corredor recortado del eje trazado, no sobre la ortofoto completa (`research.md` D26). La
máscara resultante se muestrea con el mismo mecanismo de perfil transversal que ya usan los otros
dos modos sobre el DEM, y el borde de cada lado es la primera muestra, avanzando desde el eje hacia
afuera, que deja de clasificarse como calzada y se mantiene así durante `min_consecutive_samples`
muestras (`research.md` D30) — misma semántica de racha sostenida, sobre una señal distinta.

La pieza que en `006` era nueva del todo —el análisis en segundo plano con progreso— **ya existe**
en el plugin desde antes de `006` (`research.md` D27): no se construye ningún mecanismo asíncrono
nuevo, se inserta la etapa de segmentación como una fase más del `progress_callback` que
`compute.run_analysis` ya reporta.

Detalle de cada decisión y sus alternativas en [research.md](./research.md).

## Convención de numeración de decisiones

Las decisiones de esta feature se numeran **D25 en adelante**, continuando la serie de
`006-street-width` (D17–D24), que a su vez continuó la de `005-road-metrics` (D1–D16): las tres
describen el mismo plugin y el código las cita por número. Los requisitos se numeran de nuevo desde
`FR-001`, y los de `006` se citan como `006/FR-0xx`.

## Technical Context

**Language/Version**: Python 3.9 (imagen `webodm_webapp`) para el backend; JavaScript ES6 + React
para el frontend, compilado por el `build_plugins` existente.

**Primary Dependencies**: `geodeep==0.9.12`, **ya presente en `requirements.txt` del core**
(`requirements.txt:25`, la usa `coreplugins/objdetect` de upstream) — no se añade nada nuevo a la
imagen (`research.md` D32). Trae `onnxruntime` como dependencia transitiva (inferencia del modelo,
sin GPU). `gdalwarp` (CLI), ya disponible y ya usado por `objdetect` para recortar con `-cutline`.
`rasterio` y `numpy`, sin cambios, ya en uso por el resto del plugin. Frontend: sin dependencias
nuevas.

**Storage**: sin cambios de esquema. El índice sigue en `GlobalDataStore('road')`; los tramos, en el
archivo JSON por análisis. El único cambio de dominio de datos es un valor nuevo de texto libre
(`no_orthophoto`) dentro de un campo que ya existía (`left_reason` / `right_reason`); no hay
migración.

**Testing**: `webodm.sh test backend coreplugins.road.tests` en Docker. La detección sobre máscara
(`profile.detect_edges_segmentation`) se prueba igual que las otras dos: pura, contra arrays
sintéticos, sin Django ni ráster. La integración de `segmentation.py` (recorte + llamada a
`geodeep.segment`) se prueba con un doble de `geodeep` inyectado — la suite no depende de tener el
modelo real descargado ni de red saliente (`quickstart.md`, nota del Escenario 1). La validación
contra el modelo real, incluida la descarga, es manual (`quickstart.md` Escenario 6), igual criterio
que ya usó `006/D23` para la verificación de worker.

**Target Platform**: WebODM autoalojado sobre Docker; webapp y worker comparten imagen.

**Project Type**: extensión de un plugin existente — backend Django/DRF más frontend React/Leaflet,
todo dentro de `coreplugins/road/`.

**Performance Goals**: sin objetivo numérico de tiempo total (a diferencia de `006/SC-007`): la
inferencia de un modelo ONNX no tiene el mismo perfil de coste que dos ajustes lineales, y no hay
todavía una medición real sobre la que fijar un porcentaje razonable (`research.md` D33). El
requisito de rendimiento que sí existe es de percepción, no de reloj: el progreso reportado no puede
quedarse congelado mientras la segmentación corre (`007/SC-005`, `research.md` D27).

**Constraints**: la función de worker sigue siendo self-contained — el módulo nuevo se importa de
forma absoluta y dentro del cuerpo, igual que exige `006/D23` (`research.md` D31); el modo por
defecto y el modo superficie no pueden cambiar de resultado (`007/FR-002`, heredado de `006/FR-002`);
la segmentación corre sobre el corredor del eje, no sobre la ortofoto completa (`007/FR-008`); un
único motivo nuevo, no dos ni cero (`research.md` D29); el worker necesita salida de red la primera
vez que usa el modo, para descargar el modelo (`research.md` D31) — si no la tiene, el análisis falla
de forma identificable, no se cuelga.

**Scale/Scope**: mismos órdenes de tramos que `005`/`006` (100 a 2.000). Alcance de código: un módulo
Python nuevo (`segmentation.py`), tres modificados (`profile.py`, `compute.py`, `sources.py`, `api.py`
— cuatro, ver Project Structure), `export.py` **sin cambios** (el motivo nuevo es texto libre dentro
de un campo que ya exporta), y un cambio mínimo de frontend (una entrada de rótulo; el resto del
comportamiento de UI sale gratis del mecanismo ya genérico — ver Project Structure).

## Constitution Check

*GATE: revisado antes de Phase 0 y de nuevo tras Phase 1. Resultado en ambos pasos: **PASA**.*

### I. Desarrollo solo-plugins (no negociable)

Toda la funcionalidad vive dentro de `coreplugins/road/`. Cero cambios en `app/`, `webodm/`,
`worker/`, `nodeodm/`, `nginx/` o los scripts raíz, y tampoco en `coreplugins/objdetect/` —esta
feature **lee** su patrón de uso de `geodeep` como referencia, pero no importa nada de ese plugin,
igual que `axis.py` habla con `annotations` solo por `get_plugin_by_name`, nunca importando su
paquete.

### II. Compatibilidad con upstream

El único archivo nuevo, `coreplugins/road/segmentation.py`, vive en una ruta que upstream no toca.
Los modificados son todos propios del fork. Superficie de conflicto de merge: nula. `requirements.txt`
del core no se toca —`geodeep` ya estaba ahí por `objdetect` (`research.md` D32)—, así que tampoco
hay riesgo de conflicto de merge en ese archivo compartido con upstream.

### III. Convenciones de plugin

No se altera la estructura del plugin: mismo `manifest.json`, misma clase `Plugin(PluginBase)`,
mismos puntos de extensión (`api_mount_points`, sin rutas nuevas — `007/contracts/rest-api-delta.md`
confirma que no hay endpoints nuevos). Los assets de frontend siguen en `public/`. El plugin sigue
pudiendo deshabilitarse sin efecto sobre `annotations`, `realign` ni `objdetect`.

Punto que sí toca vigilar, simétrico al que `006/plan.md` vigiló para el estado `inferred`: esta
feature **sí** amplía el contrato de motivos de "sin borde" con un cuarto valor (`no_orthophoto`),
algo que `006/FR-010` decidió explícitamente no hacer para sus dos modos. La justificación de por
qué aquí sí procede está en `research.md` D29 — no es una contradicción con `006`, es la misma
regla general (ampliar el contrato solo cuando una distinción real no cabe en el existente sin
mentir) aplicada a un caso donde sí hace falta.

### IV. Gestión de dependencias de plugins

- **Paso 1 (Python puro)**: no aplica en la práctica — `geodeep` ya está en el `requirements.txt`
  del core (`research.md` D32). El plugin `road` sigue sin `requirements.txt` propio; no hace falta
  crear uno.
- **Paso 2 (sistema)**: no aplica. `gdalwarp` ya está en la imagen (lo usa `objdetect` desde antes).
  El `Dockerfile` no se toca.
- **Paso 3 (verificación de workers, no negociable)**: **sí aplica, y es el riesgo principal de esta
  feature**, con un componente que `006` no tuvo. `run_function_async` reejecuta `run_analysis` por
  su código fuente en un namespace vacío (`006/D23`); el módulo nuevo `segmentation` solo es visible
  si se importa de forma absoluta y dentro del cuerpo (`research.md` D31). Además, a diferencia de
  `006`, la primera ejecución en modo `segmentation` necesita que el worker **descargue** el modelo
  `roads` desde el repositorio de modelos de GeoDeep — un requisito de red saliente que ningún modo
  anterior del plugin tenía. El procedimiento de verificación está en
  [quickstart.md](./quickstart.md#escenario-6--verificación-del-worker-principio-iv-no-negociable--con-riesgo-de-red-nuevo)
  y la feature no se cierra sin la evidencia del log del worker completando un análisis en modo
  segmentación —incluida la descarga del modelo la primera vez— o, si el entorno no tiene esa salida
  de red, sin la evidencia de que el fallo es identificable y no un análisis colgado.

**Re-evaluación tras Phase 1**: el diseño de datos y de contrato (`data-model.md`,
`contracts/rest-api-delta.md`) no introduce nada que cambie lo anterior. Sin violaciones que
registrar en Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/007-road-edge-segmentation/
├── spec.md                       # Qué y por qué
├── plan.md                       # Este archivo
├── research.md                   # Phase 0: decisiones D25–D33
├── data-model.md                 # Phase 1: delta sobre 006 (un motivo nuevo, sin campos nuevos)
├── contracts/
│   └── rest-api-delta.md         # Phase 1: delta sobre el contrato de 006
├── quickstart.md                 # Phase 1: escenarios de validación ejecutables
├── checklists/
│   └── requirements.md           # Validación de calidad de la spec
└── tasks.md                      # Phase 2 (/speckit-tasks — no lo crea este comando)
```

### Source Code (repository root)

```text
coreplugins/road/
├── profile.py                    # MODIF: + detect_edges_segmentation(), + NO_ORTHOPHOTO
├── segmentation.py               # NUEVO: corredor + recorte + geodeep.segment(), sin dependencias
│                                  #   del resto del plugin salvo geometry (import diferido de geodeep)
├── compute.py                    # MODIF: despacho al tercer modo, fase de segmentación antes del
│                                  #   bucle de bloques, su propio tramo de progress_callback
├── sources.py                    # MODIF: EDGE_MODE_SEGMENTATION en EDGE_MODES; sin parámetros
│                                  #   nuevos ni rangos nuevos (007/FR-015)
├── api.py                        # MODIF: comprobación de ortofoto antes de aceptar el análisis
│                                  #   cuando edge_mode == "segmentation" (ERR_NO_ORTHOPHOTO);
│                                  #   resuelve y pasa la ruta de la ortofoto a run_analysis
├── export.py                     # SIN CAMBIOS: left_reason/right_reason ya exportan texto libre
├── public/
│   ├── RoadPanel.jsx             # MODIF mínimo: una entrada en EDGE_MODE_LABELS. El selector de
│   │                              #   modo ya es genérico sobre capabilities.edge_modes, y
│   │                              #   PARAM_FIELDS ya oculta break_threshold/surface_tolerance en
│   │                              #   cualquier modo que no sea el suyo (007/FR-015a sale gratis
│   │                              #   del mecanismo `onlyMode` ya existente — sin lógica nueva)
│   └── tests/
│       └── panelLogic.test.js    # MODIF si aplica: cobertura del tercer valor en las funciones
│                                  #   puras de panelLogic.js que iteran sobre edge_mode
├── tests/
│   ├── test_profile.py           # MODIF: perfiles sintéticos de máscara binaria, los 4 motivos
│   ├── test_segmentation.py      # NUEVO: corredor, recorte, invocación a geodeep con doble
│   ├── test_compute.py           # MODIF: no regresión de break/surface; segmentación con
│   │                              #   segmentation.run_segmentation mockeado
│   ├── test_params.py            # MODIF: edge_mode admite "segmentation"; sin parámetros nuevos
│   │                              #   que validar
│   ├── test_api_analyses.py      # MODIF: comprobación de ortofoto antes de lanzar (400
│   │                              #   no_orthophoto); fallo global de segmentación -> status failed
│   └── __init__.py                # MODIF: re-export de la clase de test nueva
└── README.md                      # MODIF: los tres modos y cuándo usar cada uno
```

**Structure Decision**: se conserva la estructura de `005`/`006` sin reorganizar nada. La pieza
nueva es `segmentation.py`, separada de `profile.py` y de `compute.py` por el mismo criterio que ya
separó `coherence.py` en `006` (`research.md` D25): es E/S y depende de una librería externa
opcional, mientras que `profile.py` es matemática pura sobre arrays y debe seguir siéndolo para
poder probarse sin Django ni rásteres.

`export.py` es la única pieza de `006` que aquí queda intacta: a diferencia de las columnas nuevas
que `006` sí tuvo que añadir (origen del borde), esta feature no añade ninguna columna ni propiedad
—el motivo nuevo cabe en un campo que ya se exportaba como texto—, así que no hay nada que tocar.

Recordatorio de `005`/`006` que sigue vigente: los tests del plugin viven en un paquete de espacio de
nombres, así que toda clase de test nueva debe re-exportarse desde `tests/__init__.py` o el
descubridor de Django no la encuentra.

## Complexity Tracking

> Sin violaciones de la constitución que justificar.

Se registra aquí, como en `006`, la deuda aceptada conscientemente y no como violación:

| Elemento | Por qué se acepta | Alternativa descartada |
|---|---|---|
| Tercer modo de detección, sin haber medido si el modelo `roads` sirve sobre ortofotos de dron (`research.md` D33) | La única forma de medirlo es implementarlo y probarlo sobre una tarea real; no hay atajo que no sea escribir el código | Medir antes con un prototipo desechable: se descartó por el mismo motivo que `006/D24` — el propio usuario decidió seguir sin medición previa, y el coste de estar equivocados es bajo porque el modo es opcional y no toca el defecto |
| Un cuarto motivo de "sin borde" (`no_orthophoto`), ampliando un contrato que `006/FR-010` cerró explícitamente en tres | La fuente de fallo (ortofoto/modelo) es estructuralmente distinta de la del DEM, y reutilizar un motivo existente mentiría sobre la causa (`research.md` D29) | Reutilizar `no_data`: se le ofreció al usuario en la clarificación de `spec.md` y no se eligió |
