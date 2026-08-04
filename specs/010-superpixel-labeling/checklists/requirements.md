# Specification Quality Checklist: Etiquetado asistido por regiones en el plugin `training`

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-31
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

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`

### Registro de validación

Dos pasadas. La primera encontró tres fallos, todos corregidos en la spec antes de marcar
el checklist:

1. **Detalles de implementación en los requisitos.** El primer borrador nombraba SLIC, el grafo de
   adyacencia y `scikit-image` dentro de los FR. Se reescribieron en términos de resultado
   observable («regiones homogéneas», «extender a las vecinas parecidas») y las restricciones
   técnicas se movieron a Assumptions, donde son dependencias declaradas y no requisitos.
   La mención de SLIC en **Input** se conserva a propósito: es la cita literal de la petición.

2. **Criterio de éxito con unidad técnica.** SC-003 decía «por debajo de 100 ms». Se reformuló como
   «sin espera perceptible», que es lo que el usuario puede juzgar y no depende de dónde se mida.

3. **Frontera de alcance implícita.** «No es pre-etiquetado» estaba solo en la motivación. Se elevó
   a exclusión explícita en Assumptions, con la referencia a la fase 3 de `009`.

### Decisiones tomadas sin preguntar

Cuatro puntos admitían más de una lectura. Se resolvieron con un valor por defecto razonable,
documentado en Assumptions, en vez de gastar marcadores de clarificación:

- **Escritura inmediata por clic** frente a selección acumulada con confirmación. Se eligió
  inmediata, por coherencia con el pincel que el usuario ya tiene aprendido.
- **Cálculo bajo demanda** frente a precálculo de la ortofoto entera. Lo decide la restricción de
  memoria (~1 GB) y que el usuario rara vez etiqueta la ortofoto completa.
- **Granularidad expuesta al usuario** frente a fija. Se expone, por analogía con el radio del
  pincel, que ya es ajustable.
- **Partición propia sin solape** frente a reutilizar la rejilla de teselas de exportación. Las
  teselas de `009` se solapan por diseño (D20), lo que rompería el determinismo de FR-007.

### Riesgo señalado para la fase de planificación

FR-009 (sin bordes rectos artificiales) y FR-015 (por porciones acotadas, sin la ortofoto entera en
memoria) tiran en direcciones opuestas: trocear introduce juntas, y las juntas producen justo el
artefacto que FR-009 prohíbe. `elevation.py` ya resolvió esta misma tensión con halo, pero allí los
operadores eran locales (`np.gradient`, ventana 3×3) y aquí la partición en regiones no lo es.
Es el problema técnico central de esta feature y le corresponde a `/speckit-plan` resolverlo.
