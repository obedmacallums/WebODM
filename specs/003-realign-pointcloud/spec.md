# Feature Specification: Corrección de la nube de puntos con la transformación de realineación

**Feature Branch**: `003-realign-pointcloud`

**Created**: 2026-07-23

**Status**: Draft

**Input**: User description: "Extender el plugin `realign` para aplicar la corrección de georreferenciación también a la nube de puntos (`georeferenced_model.laz`), con alcance acotado a la generación de un LAZ corregido descargable. Reutiliza los puntos de control, el ajuste y el estado que ya existen en la feature 002 — no se marca ningún punto nuevo ni se crea un flujo aparte. El original nunca se modifica: la nube corregida se escribe en el almacenamiento persistente del plugin, igual que los rásteres corregidos. Solo se ofrece en modo rígido (sin escala): como los puntos de control son 2D y no hay control vertical, aplicar un factor de escala a la nube distorsionaría la geometría 3D (si se escala solo XY las pendientes dejan de ser consistentes; si se escala también Z las elevaciones absolutas se corren sin ningún dato que lo justifique). Cuando el interruptor 'Usar escala' está tildado, la corrección de nube debe quedar bloqueada con una explicación clara al usuario. Las alturas Z nunca se alteran. Fuera de alcance en esta feature: el visor 3D (Potree/EPT sigue mostrando la nube original), la reindexación con Entwine, el modelo texturizado y las posiciones de cámara. La transformación aplicada a la nube debe ser exactamente la misma que la aplicada a los productos 2D, de modo que la nube corregida y el DSM/DTM/ortofoto corregidos queden coherentes entre sí en XY. La operación es pesada (nubes de cientos de MB) y debe correr de forma asíncrona con progreso visible y sin bloquear la interfaz."

**Relación con la feature 002**: esta feature realiza la "etapa posterior" anticipada por la
FR-017 de `002-realign-products` ("aplicar la misma transformación a la nube de puntos"). Toda la
mecánica de marcado de puntos, ajuste, métricas de error, persistencia y permisos ya existe y se
reutiliza sin cambios; aquí solo se añade un producto más al que aplicar la transformación ya
calculada.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Obtener la nube de puntos corregida (Priority: P1)

Un usuario ya realineó los productos ráster de una tarea con la herramienta de realineación y
aplicó la corrección en modo rígido: la ortofoto, el DSM y el DTM corregidos ahora cuadran con el
mapa base. Sin embargo, la nube de puntos que descarga sigue estando en la posición original, lo
que la deja desalineada respecto de los rásteres corregidos y del resto de sus datos. Desde el
mismo panel de realineación pide generar la nube corregida; el sistema la procesa en segundo plano
y, cuando termina, el usuario la descarga y comprueba que cuadra con los productos 2D corregidos.

**Why this priority**: es el valor completo de la feature y su MVP. Sin esto, una tarea realineada
queda internamente inconsistente: los rásteres en un sitio y la nube en otro. Todo lo demás de
esta feature son salvaguardas alrededor de este flujo.

**Independent Test**: sobre una tarea con nube de puntos y una realineación aplicada en modo
rígido, pedir la nube corregida, esperar a que termine y descargarla; verificar en una herramienta
externa que un rasgo identificable de la nube coincide en XY con ese mismo rasgo en la ortofoto
corregida, y que las elevaciones son idénticas a las del original.

**Acceptance Scenarios**:

1. **Given** una tarea con nube de puntos y una realineación aplicada en modo rígido, **When** el
   usuario abre el panel de realineación, **Then** aparece disponible la acción para generar la
   nube de puntos corregida.
2. **Given** esa acción disponible, **When** el usuario la ejecuta, **Then** el sistema inicia la
   generación en segundo plano e informa que está en proceso, sin bloquear la interfaz.
3. **Given** una generación en curso, **When** termina correctamente, **Then** el sistema informa
   que la nube corregida está lista y ofrece descargarla.
4. **Given** una nube corregida lista, **When** el usuario la descarga y la abre en una herramienta
   externa, **Then** su posición horizontal coincide con la de los rásteres corregidos de la misma
   tarea dentro del error de ajuste de la realineación.
5. **Given** una nube corregida lista, **When** se comparan sus elevaciones con las del original,
   **Then** son idénticas: la corrección no alteró ninguna altura.
6. **Given** una nube corregida lista, **When** se comparan sus atributos con los del original,
   **Then** conserva la misma cantidad de puntos y sus atributos por punto (clasificación,
   intensidad, color, retornos, tiempo GPS) sin pérdida.
7. **Given** una tarea sin nube de puntos disponible, **When** el usuario abre el panel de
   realineación, **Then** el sistema no ofrece la acción e informa con un mensaje claro que la
   tarea no tiene nube de puntos.

---

### User Story 2 - Entender por qué la nube no se corrige en modo escala (Priority: P2)

Un usuario realineó su tarea con el interruptor "Usar escala" tildado y busca la opción para
corregir la nube de puntos. En lugar de encontrarla habilitada, ve la acción bloqueada junto con
una explicación de por qué: los puntos de control son 2D y no aportan control vertical, así que
aplicar un factor de escala deformaría la geometría 3D de la nube. La explicación le indica qué
hacer: destildar "Usar escala", revisar que el ajuste rígido siga siendo aceptable y volver a
aplicar. Tras hacerlo, la acción queda disponible.

**Why this priority**: sin esta explicación, el usuario solo ve una opción ausente o deshabilitada
sin motivo aparente y la interpreta como un fallo. Convierte una limitación técnica legítima en una
decisión informada, pero no aporta capacidad nueva por sí sola, por eso va después de US1.

**Independent Test**: con una realineación aplicada con escala habilitada, verificar que la acción
de nube está bloqueada y muestra la explicación y el camino a seguir; luego destildar la escala,
volver a aplicar y verificar que la acción queda disponible.

**Acceptance Scenarios**:

1. **Given** una realineación con el modo de escala habilitado, **When** el usuario abre el panel,
   **Then** la acción de generar la nube corregida aparece bloqueada con una explicación del motivo
   y de cómo habilitarla.
2. **Given** esa situación, **When** el usuario deshabilita la escala y vuelve a aplicar la
   corrección, **Then** la acción de nube queda disponible.
3. **Given** una nube corregida ya generada en modo rígido, **When** el usuario habilita la escala
   y vuelve a aplicar, **Then** el sistema deja de ofrecer la nube corregida anterior y explica que
   el modo actual no la admite.

---

### User Story 3 - Mantener el estado coherente a lo largo del tiempo (Priority: P3)

Un usuario lanza la generación de la nube corregida y, como es una operación larga, cierra el panel
y navega a otra parte de la aplicación. Al volver más tarde encuentra el estado actualizado: en
proceso, lista para descargar, o con un error explicado. Si más adelante modifica los puntos de
control o revierte la realineación, el sistema no le sigue ofreciendo una nube corregida que ya no
corresponde al ajuste vigente.

**Why this priority**: protege contra el peor fallo silencioso de esta feature — que el usuario
descargue una nube generada con un ajuste anterior creyendo que refleja el actual. Es una
salvaguarda importante, pero solo tiene sentido una vez que US1 funciona.

**Independent Test**: lanzar una generación, recargar la página y verificar que el estado mostrado
es el real; luego, con la nube ya lista, modificar un punto de control y verificar que el sistema
deja de ofrecer la nube previa como descargable.

**Acceptance Scenarios**:

1. **Given** una generación en curso, **When** el usuario recarga la página o reabre el panel,
   **Then** el estado mostrado refleja el progreso real de la operación.
2. **Given** una nube corregida lista, **When** el usuario añade, mueve o elimina un par de puntos
   de control, **Then** el sistema deja de ofrecerla como descargable e indica que debe volver a
   generarse con el ajuste vigente.
3. **Given** una nube corregida lista, **When** el usuario revierte la realineación, **Then** el
   sistema elimina la nube corregida y libera su espacio.
4. **Given** una generación que falla, **When** el usuario consulta el estado, **Then** ve el
   motivo del fallo y no se le ofrece ninguna descarga.

---

### Edge Cases

- **Tarea sin nube de puntos**: la acción no se ofrece y el usuario recibe un mensaje claro en vez
  de un botón que falla al pulsarlo.
- **Realineación previsualizada pero no aplicada**: la acción de nube no está disponible hasta que
  la corrección se haya aplicado, para que la nube nunca pueda quedar corregida con un ajuste
  distinto del de los rásteres.
- **Ajuste degenerado o con un solo par de puntos**: rigen las mismas restricciones que para los
  rásteres (FR-015 de 002); si no se puede aplicar la corrección 2D, tampoco la de nube.
- **Segunda generación mientras hay una en curso**: el sistema no lanza un segundo procesamiento en
  paralelo para la misma tarea.
- **Fallo a mitad de la generación**: no queda un archivo incompleto ofrecido como descarga; el
  usuario ve el error y puede reintentar.
- **Espacio en disco insuficiente**: la generación falla de forma controlada con un mensaje que
  identifica la causa, sin dejar residuos ocupando espacio.
- **Revertir mientras se genera**: la generación en curso deja de ser válida y su resultado no se
  ofrece como descargable.
- **Nube muy grande**: la operación puede tardar varios minutos; el usuario nunca queda con la
  interfaz bloqueada ni sin información de estado.
- **Cambio del modo de escala con una nube ya generada**: cubierto por US2, escenario 3.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST ofrecer una acción para generar una versión corregida de la nube de
  puntos de la tarea, a partir de la transformación de realineación ya calculada y aplicada.
- **FR-002**: El sistema MUST aplicar a la nube exactamente la misma transformación horizontal
  (traslación y rotación) que aplicó a los productos ráster 2D de la misma tarea, de modo que ambos
  queden coherentes entre sí en XY.
- **FR-003**: El sistema MUST dejar las elevaciones (Z) de la nube sin alterar en ningún caso.
- **FR-004**: El sistema MUST ofrecer la corrección de nube únicamente cuando la realineación esté
  en modo rígido (escala deshabilitada, ver FR-018 de 002); con la escala habilitada MUST bloquear
  la acción y explicar al usuario el motivo y cómo habilitarla.
- **FR-005**: El sistema MUST requerir que la realineación esté aplicada (no solo previsualizada)
  para poder generar la nube corregida.
- **FR-006**: El sistema MUST conservar la nube de puntos original sin alterarla, de modo que la
  operación no sea destructiva.
- **FR-007**: El sistema MUST calcular cada generación a partir de la nube original, evitando
  acumular transformaciones sobre una corrección previa.
- **FR-008**: El sistema MUST preservar en la nube corregida la cantidad de puntos, los atributos
  por punto disponibles en el original (clasificación, intensidad, color, retornos, tiempo GPS) y el
  sistema de referencia declarado, entregándola en el mismo formato que el original.
- **FR-009**: El sistema MUST ejecutar la generación de forma asíncrona, sin bloquear la interfaz, e
  informar su estado (pendiente, en proceso, lista o con error) mientras dura.
- **FR-010**: El sistema MUST permitir descargar la nube corregida una vez que esté lista.
- **FR-011**: El sistema MUST persistir el estado de la nube corregida asociado a la tarea, de modo
  que se recupere al recargar la página o reabrir el panel y sea consistente para todos los usuarios
  con acceso a la tarea.
- **FR-012**: El sistema MUST dejar de ofrecer como descargable una nube corregida que ya no
  corresponda al ajuste vigente, sea porque cambiaron los pares de puntos, porque cambió el modo de
  escala o porque se revirtió la realineación.
- **FR-013**: El sistema MUST eliminar la nube corregida y liberar su espacio al revertir la
  realineación.
- **FR-014**: El sistema MUST informar la causa cuando la generación falle y MUST NOT ofrecer como
  descarga un archivo incompleto o corrupto.
- **FR-015**: El sistema MUST impedir que se lance más de una generación simultánea para la misma
  tarea.
- **FR-016**: El sistema MUST restringir la acción de generar la nube corregida a usuarios con
  permiso de edición sobre la tarea, con el mismo criterio que "Aplicar" y "Revertir" (FR-014 de
  002); los usuarios con solo lectura pueden descargar el resultado existente pero no generarlo.
- **FR-017**: El sistema MUST informar con un mensaje claro cuando la tarea no tenga nube de puntos
  y no ofrecer la acción en ese caso.
- **FR-018**: El sistema MUST indicar al usuario que la corrección de nube afecta únicamente al
  archivo descargable y no a lo que muestra el visor 3D, que sigue presentando la nube original.

### Key Entities *(include if feature involves data)*

- **Nube de puntos corregida**: producto derivado de la nube original de una tarea tras aplicarle la
  transformación de realineación vigente en modo rígido. Conserva formato, atributos, cantidad de
  puntos, elevaciones y sistema de referencia del original; solo cambian las coordenadas
  horizontales.
- **Estado de generación de la nube**: registro persistente, asociado a la tarea, de la situación de
  la nube corregida (no generada, en proceso, lista, obsoleta o con error) y de la transformación con
  la que fue generada, que permite detectar cuándo deja de corresponder al ajuste vigente.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un rasgo identificable presente tanto en la nube corregida como en la ortofoto
  corregida de la misma tarea coincide horizontalmente dentro del error de ajuste (RMSE) informado
  por la realineación.
- **SC-002**: Las elevaciones de la nube corregida son idénticas a las del original: la diferencia
  máxima en Z entre ambos archivos es cero.
- **SC-003**: La nube corregida contiene exactamente la misma cantidad de puntos que el original y
  conserva todos sus atributos por punto.
- **SC-004**: La nube original permanece intacta tras cualquier cantidad de generaciones,
  reversiones o cambios de puntos: su contenido es byte a byte el mismo que antes de usar el plugin.
- **SC-005**: Durante toda la generación de una nube de al menos 250 MB, el usuario puede seguir
  navegando y usando la aplicación sin bloqueos, y el estado de la operación es consultable en todo
  momento sin recargar manualmente.
- **SC-006**: Una nube de aproximadamente 250 MB queda lista para descargar en menos de 10 minutos
  en el entorno de referencia del proyecto.
- **SC-007**: Ante un fallo o una interrupción de la generación, en el 100% de los casos no queda
  ninguna descarga ofrecida al usuario.
- **SC-008**: Tras modificar los puntos de control o revertir la realineación, el sistema deja de
  ofrecer la nube corregida anterior en el 100% de los casos, de modo que nunca se descarga una nube
  que no corresponde al ajuste vigente.
- **SC-009**: Con el modo de escala habilitado, el usuario recibe siempre una explicación del motivo
  del bloqueo y del camino para habilitar la corrección de nube, en lugar de una opción ausente sin
  justificación.

## Assumptions

- **La generación es a demanda, no automática**: por el costo de la operación (nubes de cientos de
  MB), "Aplicar" sigue corrigiendo solo los rásteres 2D como hasta ahora; la nube se genera cuando el
  usuario la pide explícitamente. Aplicar no se vuelve más lento por esta feature.
- **Se exige realineación aplicada**: generar la nube desde una previsualización no aplicada
  permitiría que la nube quedara corregida con un ajuste distinto al de los rásteres; se descarta por
  coherencia (FR-005).
- **Modo rígido obligatorio**: los pares de puntos de control son 2D y no aportan control vertical.
  Escalar solo XY rompe la consistencia entre distancias horizontales y verticales (deforma las
  pendientes); escalar también Z desplaza las elevaciones absolutas sin ningún dato que lo respalde.
  Ambas alternativas se descartan y la feature se limita al modo rígido ya disponible desde la US5
  de 002.
- **Mismo sistema de referencia**: se asume que la nube de puntos de la tarea está expresada en el
  mismo sistema de coordenadas proyectadas que los rásteres, que es el que usa la transformación.
- **Mismo formato de salida**: la nube corregida se entrega en el mismo formato comprimido del
  original, sin conversiones ni remuestreos.
- **Costo de almacenamiento**: mantener la nube corregida junto al original aproximadamente duplica
  el espacio ocupado por la nube de una tarea realineada. Se acepta como contrapartida de la
  operación no destructiva, coherente con el criterio ya adoptado para los rásteres en 002.
- **Reutilización total del flujo de 002**: no se marcan puntos nuevos, no se calcula una
  transformación aparte y no se crea un panel separado; la feature se apoya en los puntos, el ajuste,
  el estado y los permisos ya existentes.

## Fuera de alcance

Estos puntos se dejan explícitamente fuera de esta feature y podrán abordarse más adelante:

- **Visor 3D**: la vista 3D sigue mostrando la nube original, sin realinear. Corregir lo que muestra
  el visor exigiría reindexar la nube corregida, con un costo de espacio y de proceso muy superior al
  de esta feature.
- **Modelo texturizado y posiciones de cámara**: no se transforman, por lo que dentro del visor 3D
  seguirán siendo coherentes con la nube original.
- **Corrección vertical**: no se ajustan alturas ni se incorpora control vertical de ningún tipo.
- **Escalado de la nube**: descartado por lo argumentado en Assumptions.
