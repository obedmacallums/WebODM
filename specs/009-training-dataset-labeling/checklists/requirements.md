# Specification Quality Checklist: Etiquetado de ortofotos y exportación de datasets de entrenamiento

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-30
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

### La primera pasada de validación falló, y esto es lo que se corrigió

La spec se redactó a mano antes de ejecutar esta validación. Al pasarla, **cinco requisitos
incumplían «No implementation details»**: nombraban librerías, clases del framework y hasta líneas
de código concretas dentro del cuerpo normativo. `008` no cometió ese error —allí las librerías
viven en Assumptions y los FR hablan de «el mecanismo del framework»—, así que la corrección fue
alinearse con el precedente del propio repositorio, no con una regla abstracta:

| Requisito | Antes | Ahora |
|---|---|---|
| FR-004 | citaba `class_names = ['not_road', 'road']` | «lo que espera la librería de inferencia» |
| FR-012b | citaba EPSG:4326 | «coordenadas angulares» frente a unidades de terreno |
| FR-016 | citaba `GlobalDataStore` y `get_persistent_path()` | «los mecanismos de almacenamiento del framework» |
| FR-024 | citaba `tiles_size = inputs[0].shape[-1]` | «la librería deduce el tamaño de la forma de la entrada» |
| FR-037 | listaba `rasterio 1.3.10`, `numpy`, `Pillow`, `shapely` | «no introduce dependencias nuevas», con el inventario movido a Assumptions |

Ninguna de esas cifras se ha perdido: todas siguen en la spec, en Assumptions, que es donde este
repositorio guarda la evidencia medida. Lo que cambia es que ya no son normativas. Un requisito que
nombra una versión de librería envejece mal y obliga a tocar la spec cuando cambia la imagen.

También se corrigieron dos criterios de éxito que arrastraban tecnología (`.zip` en SC-002, «memoria
del contenedor» en SC-007) y una referencia cruzada rota: FR-026 apuntaba a FR-032 cuando el
requisito que avisa del fondo ausente es FR-033.

Verificación de que no quedan fugas, sobre el bloque de requisitos:

```
awk '/^### Functional Requirements/,/^### Key Entities/' spec.md | grep -iE "rasterio|geos|…"
→ SIN FUGAS de implementacion en los FR
```

### Requisito añadido por el Constitution Check

Al cargar `.specify/memory/constitution.md` apareció una obligación del **Principio III** que la
spec no recogía: cada plugin debe poder deshabilitarse sin romper el resto del sistema. Se añadió
como **FR-038**.

### Decisiones cerradas con el usuario antes de redactar

No hubo marcadores de clarificación porque las decisiones estructurales se resolvieron en la
conversación previa:

| Decisión | Elegido | Registrada en |
|---|---|---|
| Alcance del dataset | Varias tareas por dataset, no una | FR-002, US3 |
| Resolución de trabajo | 10 cm/px por defecto | FR-005, Assumptions |
| Métodos de etiquetado | Los cuatro: modelo, GeoJSON, polígonos, pincel | Fases; los tres primeros en esta spec |
| Representación del pincel | Polilínea + radio, nunca píxeles | FR-011, Assumptions |
| Lo no etiquetado | «Ignorar», no clase de fondo | FR-026 |

### Cifras: cuáles están medidas y cuál está derivada

Se distinguen a propósito, porque mezclarlas es la forma habitual de colar un presupuesto inventado
en una spec:

- **Medidas**: 3612 teselas de 512 px a resolución nativa sobre las 5 tareas reales; 172 a 21 cm/px;
  25,3 % del corredor sobreclasificado por el modelo `roads` en `008`.
- **Medida en el contenedor `worker`**: la cadena trazo → superficie → máscara (118,14 m² de buffer
  → 11 825 px de clase 1 a 10 cm/px = 118,25 m²), y el inventario de librerías.
- **Derivada, y así etiquetada**: las ~758 teselas a 10 cm/px salen de aplicar la ley del cuadrado
  inverso a las dos cifras medidas (`172 × (21/10)²`). SC-006 exige remedirla durante la
  implementación en vez de darla por buena.

Una corrección de por medio: durante la conversación se dijo «~570 teselas». Era incorrecto; el
cálculo bueno da ~758. No cambió ninguna decisión —hace la opción elegida mejor, no peor— pero la
spec lleva el número correcto.

### Advertencia de alcance para `/speckit-plan`

La spec tiene **39 requisitos funcionales** (FR-001 a FR-038, más FR-012b); `008`, que ya fue una
feature de buen tamaño, tenía 20.
La fase 1 cubre editor de polígonos, pincel, importación de GeoJSON, datasets multi-tarea y
exportación: aproximadamente el doble de lo entregado por iteración hasta ahora en este repositorio.

Está redactada para poder partirse limpiamente si se decide: **US1 + US2** (etiquetar a mano y
exportar) ya es un ciclo completo y utilizable, y **US3 + US4 + US5** son añadidos que no lo
bloquean. La decisión es del usuario y está pendiente; el plan debe recogerla explícitamente antes
de generar tareas.

### Riesgo abierto que el plan debe resolver

**El pincel no tiene precedente en el repositorio.** El editor de polígonos se apoya en
`PolylineEditor` de `annotations`, que está probado en producción; el pincel comparte la primitiva
pero necesita interacción de arrastre, previsualización del radio sobre el terreno y convivencia con
el zoom y el desplazamiento del mapa. Es la parte con más incertidumbre de esfuerzo, y SC-004 —que
pintar sea más rápido que dibujar polígonos— es su única justificación. Si al planificar resulta
desproporcionado, la spec permite entregarlo separado sin tocar el resto.
