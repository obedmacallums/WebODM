# Specification Quality Checklist: Capa de máscara del modelo de segmentación

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-29
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

### Decisiones resueltas antes de redactar (no quedaron como NEEDS CLARIFICATION)

Las cuatro decisiones de producto se cerraron con el usuario antes de escribir la spec, así que no
hubo marcadores de clarificación:

| Decisión | Elegido | Registrada en |
|---|---|---|
| Cuándo se genera | Junto al análisis, sin botón aparte | Assumptions, FR-001 |
| Extensión | Solo el corredor del eje | FR-002 |
| Clases dibujadas | Solo `road` | FR-003 |
| Formato | Vectorial (polígonos), no ráster | Assumptions |

### Cifras medidas, no estimadas

Los números de la spec se midieron sobre el corredor real antes de redactar, para que FR-007/FR-009
y SC-003 no fueran presupuestos inventados:

- Salida cruda del modelo: 525 KB · solo clase `road`: 115 KB · simplificada a 20 cm: **19,5 KB**
- JSON de tramos que el plugin ya guarda hoy por análisis: **8,7–42 KB** (5 análisis reales)
- Máscara devuelta a 20 cm/px frente a ortofoto a 5 cm/px (recorte 1688×1919 → máscara 422×479)

La tolerancia de simplificación de FR-007 no es un número arbitrario: coincide con la resolución de
la propia máscara, por debajo de la cual no hay información que perder. Eso hace que el requisito
sea justificable y no una preferencia.

### Sobre el tono de la sección de contexto

La motivación describe un error real de documentación cometido durante `007` (atribuir el sesgo a la
acera sin comprobarlo). Se deja escrito a propósito: es la evidencia de por qué la feature hace
falta, no una anécdota. Un resultado que solo puede auditarse rescatando ficheros temporales a mano
es un resultado que en la práctica nadie audita.

### Riesgo abierto que el plan debe recoger — RESUELTO en `/speckit-plan` (2026-07-29)

FR-009 fijaba el tamaño en órdenes de magnitud porque **solo se había medido un corredor** (66 m).

**Se midió un corredor largo real** (`Noria`, 293 m): la máscara simplificada da **76,9 KB**, casi el
doble del techo de 8,7–42 KB que FR-009 exigía. Es decir, el requisito que yo mismo había escrito
antes de medir **lo incumplía el propio diseño**.

Resolución: se corrigieron **FR-009 y SC-003** para reflejar lo medido, en vez de subir la tolerancia
de simplificación hasta hacer cuadrar un número inventado (que habría descartado información real
solo para salvar un requisito mal puesto). Detalle en [`research.md`](../research.md) D40.

Dos invariantes quedaron comprobados de paso: el tamaño escala con la **longitud del corredor** y no
con el GSD de la ortofoto (2,2 cm/px y 5 cm/px producen ambas máscaras a 20 cm/px), y no salta de
orden de magnitud (1,8× el documento de tramos del mismo análisis, no 10×).

Riesgo residual, aceptado y anotado en el plan: no se han medido ejes de más de 293 m.

### Otra suposición de la spec corregida al planificar

La spec asumía que se usaría la salida GeoJSON de la librería de segmentación. Al leer el código de
`007` resultó **inviable sin correr el modelo dos veces**: el cálculo del borde necesita la máscara
ráster para muestrear los perfiles, y la librería devuelve una cosa o la otra, no ambas. Se
vectoriza el ráster ya guardado (D34) — resultado idéntico byte a byte, y catorce veces más barato.
