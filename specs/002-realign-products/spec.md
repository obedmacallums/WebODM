# Feature Specification: Realineación manual de productos ráster 2D mediante puntos de control

**Feature Branch**: `002-realign-products`

**Created**: 2026-07-22

**Status**: Draft

**Input**: User description: "Plugin 'realign' para la vista 2D de una tarea procesada. Permite corregir la posición de los productos ráster (ortofoto, DSM y DTM) cuando no cuadran con el mapa base de fondo (OpenStreetMap, Google, etc.), un desajuste frecuente por imprecisiones de georreferenciación. El usuario marca pares de puntos de control (rasgo en la ortofoto → mismo rasgo en el mapa base), el sistema calcula una transformación de similitud, previsualiza el desplazamiento, muestra el error por punto y el RMSE, y con un botón Aplicar genera productos corregidos conservando los originales, con opción de Revertir. La transformación persiste asociada a la tarea. Fase futura: extender a la nube de puntos."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Alinear los rásteres marcando pares de puntos y ver el error en vivo (Priority: P1)

Un usuario con una tarea procesada abre la vista 2D y observa que la ortofoto no cuadra con
el mapa base de fondo (calles, edificios o parcelas aparecen desplazados respecto a
OpenStreetMap o Google). Activa la herramienta de realineación, que muestra la ortofoto
semitransparente sobre el mapa base, y marca pares de puntos de control: primero hace clic
en un rasgo reconocible de la ortofoto (posición actual) y luego en ese mismo rasgo sobre el
mapa base (posición correcta). A medida que marca pares, el sistema calcula una
transformación de similitud (traslación, rotación y escala uniforme), desplaza las capas
ráster sobre el mapa para previsualizar el resultado, y muestra el error de cada punto y un
error global (RMSE) que se actualizan al añadir, mover o eliminar puntos.

**Why this priority**: es la esencia del plugin y su MVP. Sin aplicar ni persistir nada, el
usuario ya obtiene valor inmediato: ve cómo cuadraría la ortofoto con el mapa base y puede
juzgar la calidad del ajuste mediante los errores. Todo lo demás se construye sobre esto.

**Independent Test**: con una tarea procesada abierta en la vista 2D, activar la herramienta,
marcar dos o más pares de puntos y verificar que (a) las capas ráster se desplazan en la
previsualización acercándose al mapa base, (b) aparece un error por cada punto y un RMSE
global, y (c) al mover o eliminar un punto los errores se recalculan.

**Acceptance Scenarios**:

1. **Given** una tarea procesada con al menos un producto ráster 2D abierta en la vista 2D,
   **When** el usuario activa la herramienta de realineación, **Then** la ortofoto se muestra
   semitransparente sobre el mapa base y el sistema queda a la espera de pares de puntos.
2. **Given** la herramienta activa, **When** el usuario marca el punto de origen sobre la
   ortofoto y luego el punto de destino sobre el mapa base, **Then** el par queda registrado y
   representado visualmente como un vector de origen a destino.
3. **Given** un solo par marcado, **When** el sistema calcula la transformación, **Then**
   aplica únicamente una traslación y previsualiza el desplazamiento de las capas ráster.
4. **Given** dos o más pares marcados, **When** el sistema calcula la transformación, **Then**
   ajusta una transformación de similitud por mínimos cuadrados y muestra el residuo de cada
   punto y el RMSE global.
5. **Given** varios pares marcados, **When** el usuario mueve o elimina uno de los puntos,
   **Then** la transformación, la previsualización y los errores se recalculan de inmediato.
6. **Given** una tarea sin ningún producto ráster 2D, **When** el usuario intenta activar la
   herramienta, **Then** el sistema informa con un mensaje claro que la tarea no tiene
   productos 2D para realinear y no activa la herramienta.

---

### User Story 2 - Aplicar la transformación generando productos corregidos (Priority: P2)

Una vez que la previsualización cuadra y el error es aceptable, el usuario pulsa "Aplicar" y el
sistema genera versiones corregidas de todos los productos ráster 2D (ortofoto, DSM y DTM) con
la nueva georreferenciación, conservando siempre los archivos originales intactos. A partir de
ese momento la vista 2D y las descargas reflejan los productos corregidos.

**Why this priority**: convierte la previsualización en un resultado permanente y utilizable
(descarga, uso externo, capas alineadas para otros análisis). Depende de US1 pero añade el
valor de persistir la corrección en los propios productos.

**Independent Test**: tras alinear con US1, pulsar "Aplicar" y verificar que (a) existen
productos corregidos que cuadran con el mapa base, (b) los productos originales se conservan sin
cambios, y (c) la vista 2D pasa a mostrar los productos corregidos.

**Acceptance Scenarios**:

1. **Given** una previsualización con al menos el número mínimo de puntos requerido, **When** el
   usuario pulsa "Aplicar", **Then** el sistema genera productos corregidos de ortofoto, DSM y
   DTM aplicando la misma transformación a todos y conserva los originales.
2. **Given** una transformación ya aplicada, **When** el usuario reedita los puntos y vuelve a
   aplicar, **Then** la nueva corrección se calcula siempre a partir de los productos originales
   (las transformaciones no se acumulan sobre una corrección previa).
3. **Given** un usuario sin permiso de edición sobre la tarea, **When** intenta pulsar
   "Aplicar", **Then** el sistema impide la operación y lo informa.
4. **Given** una previsualización con menos puntos que el mínimo necesario, **When** el usuario
   intenta aplicar, **Then** el sistema impide la operación e indica cuántos puntos faltan.

---

### User Story 3 - Revertir al estado original (Priority: P3)

En cualquier momento, el usuario puede pulsar "Revertir" para descartar la transformación y
restaurar la vista y los productos al estado original, sin pérdida de datos.

**Why this priority**: es la red de seguridad que hace segura toda la operación; permite
experimentar con la alineación sabiendo que siempre se puede deshacer. Aporta valor propio pero
depende de que exista algo que revertir (US1/US2).

**Independent Test**: tras aplicar una transformación con US2, pulsar "Revertir" y verificar que
la vista 2D y los productos vuelven a coincidir con el estado original previo a la realineación.

**Acceptance Scenarios**:

1. **Given** una transformación aplicada, **When** el usuario pulsa "Revertir", **Then** la vista
   2D y los productos vuelven al estado original y los productos corregidos dejan de estar en uso.
2. **Given** una previsualización sin aplicar, **When** el usuario pulsa "Revertir", **Then** se
   descartan los puntos y la previsualización y la vista vuelve al estado original.
3. **Given** un usuario sin permiso de edición sobre la tarea, **When** intenta revertir, **Then**
   el sistema impide la operación y lo informa.

---

### User Story 4 - Conservar y reeditar la realineación entre sesiones (Priority: P3)

La transformación —los pares de puntos, el modelo calculado y su estado (previsualizado,
aplicado o revertido)— se guarda de forma persistente asociada a la tarea. Al reabrir la tarea,
el usuario recupera el estado tal como lo dejó y puede continuar reeditando los puntos.

**Why this priority**: hace que el trabajo de alineación no se pierda y sea reanudable y
compartible entre usuarios de la misma tarea; complementa US1–US3 pero no es imprescindible para
demostrar el valor base.

**Independent Test**: marcar puntos y aplicar en una sesión, cerrar y reabrir la tarea (u otro
usuario con acceso la abre), y verificar que los puntos, los errores y el estado aplicado/revertido
se recuperan igual que quedaron.

**Acceptance Scenarios**:

1. **Given** una realineación con puntos marcados y/o aplicada, **When** el usuario recarga o
   reabre la tarea, **Then** se recuperan los pares de puntos, los errores y el estado.
2. **Given** una realineación guardada, **When** otro usuario con acceso a la tarea la abre,
   **Then** ve la misma realineación y su estado.
3. **Given** una realineación aplicada y recuperada, **When** el usuario modifica los puntos y
   vuelve a aplicar, **Then** la corrección se recalcula desde los productos originales.

---

### Edge Cases

- **Tarea sin productos ráster 2D**: la herramienta no se activa e informa que no hay nada que
  realinear.
- **Cero puntos**: no hay transformación; la vista permanece en el estado original.
- **Un solo punto**: solo se aplica traslación (no hay rotación ni escala estimables).
- **Ajuste degenerado**: pares cuyos puntos de origen coinciden o son insuficientes para estimar
  la similitud; el sistema lo detecta, avisa y no permite aplicar hasta que el ajuste sea válido.
- **Error muy alto (RMSE)**: el sistema muestra el error de forma destacada pero no bloquea al
  usuario; queda a su criterio aceptar o seguir ajustando.
- **Re-aplicar sobre una corrección previa**: la transformación siempre parte de los productos
  originales para no acumular deformaciones.
- **Permisos insuficientes**: un usuario con acceso de solo lectura puede previsualizar pero no
  aplicar ni revertir; el sistema se lo indica.
- **Productos parciales**: si la tarea tiene ortofoto pero no DSM/DTM (o viceversa), se realinean
  los productos ráster 2D que existan.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST ofrecer, en la vista 2D de una tarea procesada, una herramienta de
  realineación que el usuario pueda activar y desactivar.
- **FR-002**: Al activar la herramienta, el sistema MUST mostrar la ortofoto de forma
  semitransparente sobre el mapa base para facilitar la identificación de rasgos comunes.
- **FR-003**: El sistema MUST permitir al usuario marcar pares de puntos de control, cada uno
  compuesto por un punto de origen (sobre la ortofoto) y un punto de destino (sobre el mapa base),
  y representar cada par visualmente.
- **FR-004**: El sistema MUST permitir añadir, mover y eliminar pares de puntos, recalculando la
  transformación y los errores tras cada cambio.
- **FR-005**: El sistema MUST calcular una transformación de similitud (traslación, rotación y
  escala uniforme, sin deformación local) a partir de los pares de puntos: con un solo par, solo
  traslación; con dos o más, ajuste por mínimos cuadrados.
- **FR-006**: El sistema MUST mostrar, en todo momento durante la edición, el error residual de
  cada punto y un error global (RMSE), y actualizarlos de inmediato ante cualquier cambio en los
  puntos.
- **FR-007**: El sistema MUST previsualizar la transformación desplazando las capas ráster sobre el
  mapa, sin modificar los archivos, y MUST mover todos los rásteres 2D como un conjunto porque
  comparten la misma georreferenciación.
- **FR-008**: El sistema MUST ofrecer una acción "Aplicar" que genere versiones corregidas de todos
  los productos ráster 2D disponibles (ortofoto, DSM, DTM) con la nueva georreferenciación,
  aplicando la misma transformación a todos.
- **FR-009**: El sistema MUST conservar siempre los productos originales sin alterarlos, de modo que
  la operación no sea destructiva.
- **FR-010**: El sistema MUST calcular cada aplicación a partir de los productos originales, evitando
  acumular transformaciones sobre una corrección previa.
- **FR-011**: El sistema MUST ofrecer una acción "Revertir" que restaure la vista y los productos al
  estado original en cualquier momento, tanto sobre una previsualización como sobre una corrección
  ya aplicada.
- **FR-012**: El sistema MUST persistir la realineación asociada a la tarea —pares de puntos, modelo
  calculado y estado (previsualizado, aplicado o revertido)— de modo que se conserve entre sesiones y
  sea accesible para todos los usuarios con acceso a la tarea.
- **FR-013**: El sistema MUST recuperar el estado guardado al reabrir la tarea, permitiendo continuar
  la edición de los puntos.
- **FR-014**: El sistema MUST restringir las acciones "Aplicar" y "Revertir" a usuarios con permiso de
  edición sobre la tarea; los usuarios con solo lectura pueden previsualizar pero no modificar el
  estado persistido.
- **FR-015**: El sistema MUST impedir "Aplicar" cuando los puntos sean insuficientes o produzcan un
  ajuste degenerado, informando la causa al usuario.
- **FR-016**: El sistema MUST informar con un mensaje claro cuando la tarea no tenga productos ráster
  2D para realinear y no activar la herramienta en ese caso.
- **FR-017**: El diseño de la transformación y su persistencia MUST ser independiente del tipo de dato
  (no cerrarse a los rásteres) para permitir, en una etapa posterior, aplicar la misma transformación
  a la nube de puntos.

### Key Entities *(include if feature involves data)*

- **Par de puntos de control**: correspondencia entre un punto de origen (posición actual sobre el
  producto) y un punto de destino (posición correcta sobre el mapa base). Tras el ajuste tiene un
  residuo de error asociado.
- **Transformación de realineación**: modelo de similitud calculado a partir de los pares de puntos;
  incluye sus parámetros (traslación, rotación, escala), sus métricas de error (residuos por punto y
  RMSE) y su estado (previsualizado, aplicado o revertido). Su representación es independiente del tipo
  de producto al que se aplica.
- **Estado de realineación de la tarea**: asociación persistente entre una tarea y su transformación;
  registra qué productos abarca y mantiene la referencia a los productos originales y, cuando existe, a
  los productos corregidos.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un usuario puede corregir una ortofoto claramente desplazada hasta que cuadre
  visualmente con el mapa base marcando entre 2 y 4 pares de puntos, en menos de 3 minutos.
- **SC-002**: El error por punto y el RMSE se muestran y se actualizan de forma percibida como
  inmediata (en menos de 1 segundo) tras marcar, mover o eliminar un punto.
- **SC-003**: Tras aplicar, los productos corregidos coinciden con el mapa base dentro de una
  tolerancia coherente con el RMSE alcanzado durante la previsualización.
- **SC-004**: La acción "Revertir" restaura el estado original el 100% de las veces sin pérdida ni
  alteración de los productos originales.
- **SC-005**: La realineación (puntos, errores y estado) se recupera de forma idéntica al 100% de las
  veces al reabrir la tarea o al abrirla otro usuario con acceso.
- **SC-006**: Todos los productos ráster 2D disponibles quedan alineados de forma consistente entre sí
  tras aplicar (no aparecen desalineaciones relativas entre ortofoto, DSM y DTM).

## Assumptions

- Los productos ráster 2D de una tarea (ortofoto, DSM, DTM) comparten sistema de referencia y
  extensión, por lo que una única transformación aplica de forma coherente a todos.
- El mapa base de fondo (OpenStreetMap, Google, etc.) se toma como referencia de posición correcta; se
  asume que el desajuste proviene de la georreferenciación de la tarea, no del mapa base.
- La operación es no destructiva: los productos originales se conservan siempre.
- El modelo de transformación es de similitud (sin deformación local ni rectificación por remuestreo
  polinomial); casos que requieran deformación local quedan fuera de alcance.
- La nube de puntos y las capas vectoriales quedan fuera de alcance de esta primera versión; solo se
  actúa sobre los productos ráster 2D. El diseño se mantiene abierto para extender a la nube de puntos
  en una etapa posterior.
- El permiso para "Aplicar" y "Revertir" se deriva del permiso de edición existente sobre la tarea o su
  proyecto; no se introduce un modelo de permisos nuevo.
- La feature aplica a tareas ya procesadas que disponen de al menos un producto ráster 2D.
