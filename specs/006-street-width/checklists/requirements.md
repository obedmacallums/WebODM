# Specification Quality Checklist: Detección del ancho de calle por criterio de superficie y coherencia entre tramos

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-28
**Feature**: [spec.md](../spec.md)

## Content Quality

- [X] No implementation details (languages, frameworks, APIs)
- [X] Focused on user value and business needs
- [X] Written for non-technical stakeholders
- [X] All mandatory sections completed

## Requirement Completeness

- [X] No [NEEDS CLARIFICATION] markers remain
- [X] Requirements are testable and unambiguous
- [X] Success criteria are measurable
- [X] Success criteria are technology-agnostic (no implementation details)
- [X] All acceptance scenarios are defined
- [X] Edge cases are identified
- [X] Scope is clearly bounded
- [X] Dependencies and assumptions identified

## Feature Readiness

- [X] All functional requirements have clear acceptance criteria
- [X] User scenarios cover primary flows
- [X] Feature meets measurable outcomes defined in Success Criteria
- [X] No implementation details leak into specification

## Notes

Correcciones aplicadas durante la validación (iteración 1, sin más iteraciones necesarias):

- **FR-017 no era comprobable**: decía "un suelo mínimo que impida rechazar variaciones legítimas
  pequeñas" sin decir cuánto es pequeña. Reescrito con la propiedad verificable: una desviación de
  hasta 0,30 m nunca se considera atípica.
- **FR-009 dejaba el modo quiebre sin definir**: fijaba de dónde sale la pendiente transversal en
  modo superficie y callaba sobre el otro modo, lo que admitía dos lecturas. Añadido explícitamente
  que en modo quiebre no cambia nada.
- **SC-001 no era verificable tal cual**: "una calle con bordillo a ambos lados" no identificaba
  qué tramos entran en la medida. Anclado a las progresivas concretas del caso de referencia,
  verificadas sobre la ortofoto.

Observaciones que no requieren cambio:

- La sección **Input** conserva literal la descripción del usuario, que sí contiene cifras y
  detalle técnico. Es el registro de entrada, no un requisito, y sigue la convención de
  `005-road-metrics`.
- El vocabulario de dominio (bordillo, peralte, transversal, progresiva) se mantiene: es el
  lenguaje del usuario de la herramienta, no jerga de implementación.
- Los nombres de módulos y funciones acordados en el diseño previo se han dejado **fuera** de la
  spec deliberadamente; corresponden a `plan.md`.
