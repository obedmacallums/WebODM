# Specification Quality Checklist: Polilíneas anotadas sobre el mapa 2D, planas o sobre el terreno

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-26
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

- **Iteración 2 (2026-07-26)**: los 2 marcadores `[NEEDS CLARIFICATION]` quedaron resueltos por
  decisión del usuario; checklist completo, sin ítems pendientes.
  - **FR-022**: el modo sobre el terreno exige cobertura completa; con tramos sin dato se rechaza el
    guardado en ese modo, señalando el tramo, y se ofrece guardar en plano o corregir el trazado.
    Nunca se interpolan ni rellenan cotas. Propagado a los casos límite, al escenario 7 de la US2, al
    escenario 8 de la US4, a SC-009 y a Assumptions.
  - **FR-031**: crear y modificar geometría solo está disponible cuando el mapa muestra una sola
    tarea; con varias se explica el motivo y siguen disponibles ver, encuadrar, renombrar, eliminar y
    exportar. Propagado al caso límite correspondiente, al escenario 7 de la US1 y a Assumptions.
- **Iteración 1 (2026-07-26)**: 2 marcadores `[NEEDS CLARIFICATION]` planteados al usuario como
  preguntas con opciones, por afectar al alcance y carecer de un valor por defecto defendible.
- Correcciones aplicadas en esta iteración antes de dar por buenos los demás ítems:
  - Se eliminaron menciones a mecanismos concretos del framework en el cuerpo normativo (endpoints,
    almacén de datos, librerías) y se trasladaron a **Assumptions** como restricciones del fork
    derivadas de la Constitución, para no filtrar implementación en los requisitos.
  - Los criterios de éxito se reformularon en términos observables por el usuario (tiempos
    percibidos, porcentajes de reaparición, desviación frente a una medida de referencia externa) en
    vez de métricas internas del sistema.
  - Se añadió SC-010 para cubrir el Principio III de la Constitución: el plugin debe poder
    deshabilitarse sin romper el resto del sistema.
- Los ítems marcados incompletos requieren actualizar la especificación antes de `/speckit-plan`.
  La vía prevista es responder las dos preguntas planteadas y luego `/speckit-clarify` si aparecen
  más huecos.
