# Feature Specification: Análisis de visibilidad (viewshed) desde un punto en la vista 2D

**Feature Branch**: `001-viewshed-analysis`

**Created**: 2026-07-21

**Status**: Draft

**Input**: User description: "el primer plugin es que en la vista 2d me permita seleccionar un punto y se genere las zonas que son visibles desde ese punto debido a la topografia, tambien podria agregar una altura, pero como default podemos dejar la altura a los ojos de un hombre de estatura promedio"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generar zonas visibles desde un punto (Priority: P1)

Un usuario con una tarea procesada abre la vista 2D del mapa, activa la herramienta de
visibilidad, hace clic en un punto del terreno y el sistema le muestra sobre el mapa las
zonas que son visibles desde ese punto según la topografía, usando la altura de
observador por defecto (nivel de los ojos de una persona de estatura promedio, 1,60 m
sobre el suelo).

**Why this priority**: es la esencia del plugin — sin esto no hay producto. Por sí sola
ya entrega el valor completo del análisis para el caso más común.

**Independent Test**: con una tarea procesada que tenga modelo de elevación, activar la
herramienta, hacer clic en un punto y verificar que aparece una capa de zonas visibles
coherente con el terreno (por ejemplo, una colina entre el punto y una zona baja debe
ocultar esa zona).

**Acceptance Scenarios**:

1. **Given** una tarea procesada con modelo de elevación abierta en la vista 2D,
   **When** el usuario activa la herramienta de visibilidad y hace clic en un punto
   dentro del área del proyecto, **Then** el sistema calcula y muestra sobre el mapa las
   zonas visibles desde ese punto con la altura por defecto de 1,60 m.
2. **Given** un análisis en curso, **When** el cálculo aún no termina, **Then** el
   usuario ve un indicador de progreso y puede seguir navegando el mapa.
3. **Given** un resultado de visibilidad mostrado en el mapa, **When** el usuario observa
   la capa, **Then** distingue sin ayuda adicional qué zonas son visibles y cuáles no
   (simbología con leyenda o distinción visual evidente).
4. **Given** una tarea sin modelo de elevación, **When** el usuario intenta usar la
   herramienta, **Then** el sistema le informa con un mensaje claro que la tarea no tiene
   datos de elevación y no ejecuta ningún cálculo.

---

### User Story 2 - Ajustar la altura del observador (Priority: P2)

Antes de lanzar el análisis, el usuario puede cambiar la altura del observador sobre el
suelo (por ejemplo, para simular una torre de vigilancia de 15 m o un dron a 50 m) y el
resultado refleja esa altura.

**Why this priority**: amplía los casos de uso (torres, antenas, drones) pero el valor
base ya existe con la altura por defecto.

**Independent Test**: ejecutar dos análisis desde el mismo punto con alturas distintas
(1,60 m y 30 m) y verificar que el de mayor altura produce un área visible mayor o igual.

**Acceptance Scenarios**:

1. **Given** la herramienta de visibilidad activa, **When** el usuario edita el campo de
   altura y ejecuta el análisis, **Then** el resultado se calcula con la altura indicada.
2. **Given** el campo de altura visible, **When** el usuario no lo modifica, **Then** el
   análisis usa 1,60 m y el valor por defecto es visible en el control.
3. **Given** el campo de altura, **When** el usuario ingresa un valor inválido (negativo,
   no numérico o fuera del rango permitido), **Then** el sistema se lo indica y no
   ejecuta el análisis.

---

### User Story 3 - Gestionar el resultado en el mapa (Priority: P3)

El usuario puede quitar la capa de resultado del mapa, y al lanzar un nuevo análisis
(otro punto u otra altura) el resultado anterior se reemplaza para evitar confusión.

**Why this priority**: calidad de uso — evita mapas saturados y resultados ambiguos, pero
no bloquea el valor principal.

**Independent Test**: generar un análisis, quitarlo y verificar que el mapa queda limpio;
generar dos análisis consecutivos y verificar que solo se muestra el último.

**Acceptance Scenarios**:

1. **Given** un resultado mostrado en el mapa, **When** el usuario lo quita, **Then** la
   capa desaparece y el mapa vuelve a su estado normal.
2. **Given** un resultado mostrado, **When** el usuario ejecuta un nuevo análisis,
   **Then** el resultado anterior se reemplaza por el nuevo.

---

### Edge Cases

- Clic en un punto fuera de la cobertura del modelo de elevación (o sobre una celda sin
  datos): el sistema informa que el punto está fuera del área con datos y no calcula.
- Tarea cuyo procesamiento no ha terminado o falló: la herramienta no está disponible y
  se explica por qué.
- Altura ingresada fuera de rango (negativa o mayor al máximo permitido): se rechaza con
  mensaje de validación.
- Modelo de elevación muy grande: el cálculo sigue mostrando progreso y termina o informa
  el error; nunca deja la interfaz bloqueada ni el análisis en estado indefinido.
- El usuario lanza un análisis mientras otro está en curso: el sistema cancela el
  anterior o impide el segundo, comunicándolo — nunca muestra resultados mezclados.
- Usuario sin permiso sobre la tarea: no puede ejecutar el análisis (se aplican los
  permisos existentes de la tarea).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: La herramienta de visibilidad MUST estar disponible en la vista 2D del mapa
  de una tarea únicamente cuando la tarea está procesada y tiene modelo de elevación.
- **FR-002**: El usuario MUST poder seleccionar el punto de observación con un clic
  directo sobre el mapa.
- **FR-003**: El sistema MUST calcular las zonas visibles desde el punto seleccionado
  considerando la topografía del terreno (incluyendo obstáculos presentes en la
  superficie, como construcciones y vegetación, cuando el modelo de la tarea los capture).
- **FR-004**: El análisis MUST usar una altura de observador sobre el suelo con valor por
  defecto de 1,60 m (nivel de los ojos de una persona de estatura promedio), visible y
  editable por el usuario.
- **FR-005**: El sistema MUST validar la altura ingresada: numérica, entre 0 y 500 m; si
  es inválida, informa el motivo y no ejecuta el cálculo.
- **FR-006**: El resultado MUST mostrarse como una capa superpuesta en el mapa que
  distinga con claridad zonas visibles de no visibles, legible sobre la ortofoto.
- **FR-007**: El usuario MUST poder quitar la capa de resultado del mapa.
- **FR-008**: Un nuevo análisis MUST reemplazar el resultado anterior en el mapa.
- **FR-009**: Durante el cálculo, el sistema MUST mostrar un indicador de progreso y la
  interfaz MUST seguir siendo utilizable.
- **FR-010**: Si la tarea no tiene modelo de elevación, o el punto seleccionado cae fuera
  de la cobertura de datos, el sistema MUST informarlo con un mensaje claro y accionable,
  sin fallos silenciosos.
- **FR-011**: El análisis MUST cubrir toda la extensión del modelo de elevación de la
  tarea (sin límite de radio configurable en esta versión).
- **FR-012**: El acceso a la herramienta y sus resultados MUST respetar los permisos
  existentes de la tarea (solo usuarios con acceso a la tarea pueden analizarla).

### Key Entities

- **Punto de observación**: ubicación geográfica elegida por el usuario dentro del área
  del proyecto; atributos: coordenadas y altura del observador sobre el suelo.
- **Parámetros de análisis**: altura del observador (default 1,60 m); en esta versión no
  incluye radio máximo ni altura del objetivo observado.
- **Resultado de visibilidad**: representación de las zonas visibles/no visibles desde el
  punto de observación; existe como capa temporal asociada a la sesión de visualización.
- **Modelo de elevación de la tarea**: dato de terreno generado por el procesamiento de
  la tarea; es la fuente topográfica del cálculo y define la cobertura analizable.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Desde la vista 2D, un usuario genera su primer análisis de visibilidad con
  máximo 3 interacciones (activar herramienta, clic en el punto, sin pasos adicionales
  obligatorios).
- **SC-002**: Para conjuntos de datos típicos de levantamientos con dron, el resultado
  aparece en el mapa en menos de 15 segundos desde el clic.
- **SC-003**: El 100% de los casos sin datos de elevación o con punto fuera de cobertura
  terminan en un mensaje claro para el usuario — cero fallos silenciosos.
- **SC-004**: En una prueba con usuarios, al menos el 90% interpreta correctamente qué
  zonas son visibles desde el punto sin explicación adicional.
- **SC-005**: Dos análisis consecutivos nunca dejan capas superpuestas de resultados
  distintos en el mapa (el 100% de los análisis nuevos reemplaza al anterior).

## Assumptions

- **Superficie de análisis**: se usa el modelo de superficie de la tarea (que incluye
  edificios y vegetación) por representar la visibilidad realista; si la tarea solo
  cuenta con modelo de terreno desnudo, se usa este y el resultado representa visibilidad
  sobre terreno sin obstáculos.
- **Altura por defecto**: 1,60 m corresponde al nivel de los ojos de una persona adulta
  de estatura promedio (~1,71 m); se eligió como aproximación razonable a "los ojos de un
  hombre de estatura promedio".
- **Altura del objetivo observado**: 0 m — se evalúa visibilidad del terreno a nivel del
  suelo; alturas de objetivo configurables quedan fuera de alcance de esta versión.
- **Un análisis a la vez**: por usuario y tarea solo se muestra un resultado; el nuevo
  reemplaza al anterior. Comparación de múltiples puntos queda fuera de alcance.
- **Resultado efímero**: el resultado vive en la sesión de visualización; exportarlo o
  persistirlo entre sesiones queda fuera de alcance de esta versión.
- **Fuera de alcance v1**: vista 3D, radio máximo configurable, múltiples observadores,
  exportación del resultado, perfiles de línea de vista punto a punto.
- **Restricción de proyecto**: conforme a la constitución del fork, la funcionalidad se
  entrega como plugin autocontenido sin modificar el core de WebODM (restricción de
  alcance para la fase de plan, no de diseño de experiencia).
