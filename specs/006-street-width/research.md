# Research — ancho de calle por criterio de superficie (`006-street-width`)

Decisiones numeradas **D17 en adelante**, continuando la serie de `005-road-metrics` (D1–D16),
porque ambas features describen el mismo plugin y el código cita las decisiones por número.

Toda la evidencia numérica de este documento procede de mediciones sobre datos reales de la
instancia de desarrollo, no de estimaciones: la tarea `Polideportivo María Puebla Vásquez` (proyecto
`marcoleta`, DSM y DTM a 5 cm, eje de 135 m = 27 tramos) para el caso urbano, y las tareas `Noria` y
`ruta de zona 1` para el caso rural.

---

## D17 — El borde por separación de la superficie, no por pendiente local

**Decisión**: en modo `surface`, el borde de cada lado es el primer punto —avanzando desde el eje
hacia afuera— cuyo residuo respecto de una recta ajustada a la calzada supera `surface_tolerance`
y **sigue superándola** durante `min_consecutive_samples` muestras consecutivas.

**Justificación**: el criterio de quiebre de D3 mide **cuán afilada** es la transición, y sobre un
DEM fotogramétrico urbano esa magnitud está dominada por el ruido, no por el bordillo. Medido:

| Magnitud | Valor medido | Consecuencia |
|---|---|---|
| Escalón real de un bordillo | ~15 cm | — |
| Cómo aparece en el DEM a 5 cm de GSD | rampa de ~25 cm repartida en ~1 m (20–30 %) | la fotogrametría redondea la vertical |
| Pendiente local máxima cerca del eje | mediana 86 % (DTM), 134 % (DSM), en picos de **una sola muestra** | el ruido es más afilado que la señal |

De ahí que afinar el detector actual hacia lo vertical lo aleje del objetivo, cosa que se comprobó
antes de diseñar nada: `break_threshold=100 %` con racha 2 detecta **0 de 27** tramos; con 40 % y
racha 2, **0–1 de 27**.

Un criterio de nivel invierte la relación señal-ruido: un bordillo de 15 cm produce 15 cm de
separación **esté difuminado en 5 cm o en 1 m**, mientras que los picos de ruido (~4 cm entre
muestras vecinas) no llegan a una tolerancia de 6 cm. Exigir además una racha los elimina del todo.

**Alternativas descartadas**:

- *Subir `sample_step` para suavizar el ruido*: medido, **0 de 27** tramos con paso 0,25 m. Promedia
  la rampa del bordillo por debajo del umbral y destruye la señal antes que el ruido. (Es, además,
  el consejo contrario al que sirve para un camino rural, donde el quiebre es ancho y suave.)
- *Máximo de la derivada segunda (curvatura)*: ya descartado en D3 por sensibilidad al ruido; aquí
  sería peor todavía, porque el ruido domina precisamente las derivadas altas.
- *Plantilla paramétrica de calzada ajustada por mínimos cuadrados* (calzada plana con peralte más
  un resalte a cada lado a distancias desconocidas): más principiada y daría incertidumbre por borde
  gratis, pero mucho más pesada, difícil de explicar en la consulta de un tramo, y falla de forma
  opaca cuando el perfil no se parece a la plantilla — que es la mitad del caso de referencia.
- *Umbral sobre la diferencia de cota respecto del eje*: es la alternativa que D3 ya descartó, y con
  razón: falla con peralte marcado, donde la calzada acumula desnivel antes del borde. **D18 explica
  por qué el diseño actual no es esa alternativa.**

---

## D18 — La referencia se ajusta y se reajusta, en vez de configurarse

**Decisión**: la recta de referencia se ajusta por mínimos cuadrados (reutilizando `fit_line`) sobre
las muestras a ±0,5 m del eje, se detectan bordes provisionales, se **rehace el ajuste usando solo
las muestras entre esos bordes**, y se repite la detección. Dos iteraciones y para. No hay parámetro
de ventana de ajuste.

**Justificación**: dos problemas se resuelven con la misma pieza.

El primero es el **peralte**. Al comparar contra una recta ajustada —no contra la cota del eje— la
pendiente transversal de la calzada queda absorbida por el propio ajuste, y solo cuenta como
separación lo que se aparta de esa pendiente. Un peralte del 8 % deja de ser un falso borde. Esto es
exactamente lo que le faltaba a la alternativa descartada en D3, y es la diferencia entre las dos.

El segundo es el **eje descentrado**, que en el caso de referencia es la norma y no la excepción: las
distancias del eje al bordillo van de 0,45 a 2,05 m. Con la semilla de ±0,5 m, un tramo cuyo bordillo
esté a 0,45 m contamina el ajuste inicial con muestras de acera. El reajuste sobre la calzada ya
acotada lo corrige sin que el usuario tenga que saber nada.

La semilla es pequeña a propósito: cuanto más estrecha, menos probable que cruce el bordillo, y el
error de ajuste que introduce (una recta sobre 1 m de calzada) es despreciable frente a una
tolerancia de 6 cm.

**Alternativas descartadas**:

- *Ventana de ajuste configurable*: un mando más que el usuario no sabría fijar, y cuyo valor
  correcto depende de algo que él no conoce (a qué distancia quedó el eje del bordillo en cada
  tramo). El reajuste lo resuelve solo.
- *Crecimiento de región desde el eje* (extender el ajuste mientras los residuos sean pequeños,
  refitando en cada paso): elegante y sin parámetros, pero con más modos de fallo —puede trepar a la
  acera si esta es casi coplanar— y más difícil de acotar en número de iteraciones. Dos pasadas
  fijas son predecibles y bastan.
- *Ajuste robusto tipo RANSAC o mínimos cuadrados recortados sobre toda la transversal*: resistente
  a la contaminación, pero la calzada no es mayoría en un perfil de ±10 m, así que el estimador
  robusto podría "converger" al terreno de fuera. La semilla centrada en el eje aporta la
  información que RANSAC no tiene: dónde está seguro que hay calzada.

---

## D19 — La pendiente transversal sale de la referencia ajustada

**Decisión**: en modo `surface`, el bombeo del tramo es la pendiente de la recta de referencia tras
el reajuste. En modo `break` se conserva el cálculo actual de D5 (ajuste a posteriori entre los dos
bordes).

**Justificación**: sale gratis y es mejor. La referencia ya está ajustada exactamente sobre las
muestras que el criterio considera calzada, así que la cifra es consistente por construcción con los
bordes que se reportan; el cálculo actual hace un segundo ajuste sobre un rango que puede diferir del
que se usó para decidir. Además evita recorrer el perfil dos veces.

**Alternativas descartadas**:

- *Unificar los dos modos usando siempre la referencia ajustada*: cambiaría el valor de la pendiente
  transversal en modo `break`, y con él el resultado de análisis ya entregados. Choca con FR-002.

---

## D20 — Reparación local por mediana, con umbral derivado de la propia vecindad

**Decisión**: pasada posterior a la detección, para cada lado por separado. Para el tramo `i`, con
ventana `w`:

```
vecinos = bordes MEDIDOS en [i-w, i+w], sin contar el propio i
si hay menos de 2      -> se deja como está
med = mediana(vecinos)
tol = max(3 * 1,4826 * MAD(vecinos), 0,30 m)

sin borde propio       -> se rellena con med, origen = inferido
|propio - med| > tol   -> se sustituye por med, origen = inferido
resto                  -> origen = medido
```

**Justificación**: el borde de una calle es una **línea continua**, y hasta ahora cada tramo decidía
sin usar esa información. Medido en el caso de referencia, lado acera: media 1,24 m con desviación
1,29 m y rango 0,10–7,25 m, con saltos entre tramos contiguos de 1,25 → 0,10 → 1,50 m sobre un
bordillo que es recto. Ningún ajuste del umbral de detección arregla eso.

Tres propiedades del estimador, cada una elegida por una razón:

- **Mediana y MAD, no media y desviación típica.** Un solo atípico de 7,25 m desplaza la media lo
  suficiente para arrastrar consigo a los tramos sanos. La mediana no se entera.
- **Solo votan los bordes medidos.** Es lo que impide que la inferencia avance en cadena por un
  descampado: si el tramo `i` se rellena y luego sirviera de evidencia para `i+1`, cien metros sin
  bordillo se poblarían de bordes inventados a partir del último real. Con esta regla, el frente de
  inferencia no avanza más de `w` tramos desde la última evidencia genuina.
- **El umbral lateral sale del MAD, no de un parámetro.** Cuánto puede variar legítimamente un borde
  entre tramos vecinos depende de la calle, no de una constante: un ensanche gradual varía y un
  bordillo recto no. El factor 1,4826 convierte el MAD en desviación típica equivalente para una
  normal, y el suelo de 0,30 m evita que una vecindad casualmente idéntica rechace una variación
  legítima pequeña (FR-017).

**Alternativas descartadas**:

- *Ajuste global del borde como recta o curva sobre todo el trazado*: daría ancho continuo, pero en
  el caso de referencia extrapolaría un bordillo este que **no existe** — ahí hay palmeras y terreno
  suelto hasta la vía del tren, verificado sobre la ortofoto. Es exactamente lo que `005/FR-022`
  prohíbe.
- *Apilar los perfiles de varios tramos y detectar sobre el perfil mediano*: sube la relación
  señal-ruido, pero con un eje trazado a mano que serpentea ~0,5 m respecto del bordillo, el apilado
  difumina el escalón justo en la magnitud que se quiere resolver (15 cm). Reparar decisiones es más
  seguro que promediar evidencia.
- *Filtro de mediana simple sobre la serie de offsets*: sustituiría **todos** los valores, no solo
  los atípicos, aplanando variaciones reales y borrando la distinción medido/inferido.
- *Cota de cordura sobre el ancho máximo admisible*: sería un parámetro más y un prior que el usuario
  tendría que acertar. La reparación por vecindad cubre el mismo caso sin preguntarle nada.

---

## D21 — Origen por lado y estado `inferred`, en vez de reutilizar el motivo

**Decisión**: se añaden dos campos por tramo, `left_edge_source` y `right_edge_source`, con valores
`measured`, `inferred` o `null`. El motivo por lado conserva intacto su significado actual —por qué
no hay borde **medido** ahí—, de modo que un tramo puede llevar a la vez `right_reason: no_break`,
`right_edge_source: inferred` y `offset_right: 5.80`. Se añade el estado `inferred` para el tramo que
tiene los dos bordes y al menos uno inferido.

**Justificación**: sin esta distinción la feature violaría `005/FR-022`, que es el principio que
hace fiable al plugin. Con ella, la combinación de motivo y origen se lee como la frase completa de
lo que ocurrió: *"aquí no encontré borde, y ese 5,80 viene de los vecinos"*.

El estado nuevo es necesario porque el invariante de `data-model.md` §6 de `005` ata el ancho a
`measured`, y ahora hay anchos que no proceden de dos bordes medidos. Dejar esos tramos como
`measured` mentiría; dejarlos como `no_edge` con ancho rompería el invariante.

**Alternativas descartadas**:

- *Añadir un cuarto motivo (`inferred`) a los tres existentes*: rompería el contrato que el frontend
  ya consume con tres etiquetas (FR-010) y, peor, borraría el motivo original: se perdería la
  información de **por qué** no se pudo medir ese lado.
- *Un único campo booleano por tramo* (`has_inferred_edges`): no dice qué lado, que es justo lo que
  el usuario necesita para decidir si se fía de la cifra.
- *No distinguir nada y documentar que la coherencia suaviza*: es la opción que se planteó en el
  brainstorming y se descartó explícitamente. El CSV dejaría de distinguir medido de inferido, y ese
  archivo es el que acaba en un informe.

---

## D22 — Dónde encaja en el pipeline, y el coste de retener los perfiles

**Decisión**: la coherencia corre **después** del bucle de bloques de `compute.analyze` y **antes**
de la reproyección final. Cuando `coherence_window > 0`, el bucle retiene el vector de cotas de cada
transversal para poder recalcular la pendiente transversal de los tramos reparados; cuando vale 0,
no retiene nada y el consumo de memoria es idéntico al actual.

**Justificación**: la reparación necesita ver todos los tramos a la vez, así que no puede vivir
dentro del bucle por bloques. Y un tramo reparado necesita recalcular su ancho, su estado y su
pendiente transversal, que depende de las cotas entre los bordes nuevos — cotas que hoy se descartan
al terminar cada bloque.

Retenerlas está acotado y es barato: el peor caso realista son 2.000 tramos con 1.001 muestras por
transversal (semiancho 50 m, paso 0,1 m), es decir ~16 MB en `float64`. El caso habitual del
proyecto —200 tramos, 400 muestras— son 640 kB. Se paga solo cuando la coherencia está activada.

La reproyección tiene que ir después porque los puntos de borde de un tramo reparado cambian de
posición, y `_unproject_in_place` hace una única pasada para todos los puntos de todos los tramos
(D2): reproyectar antes obligaría a una segunda llamada, que es justo el coste que aquella decisión
evitaba.

**Alternativas descartadas**:

- *No recalcular la pendiente transversal de los tramos reparados*: dejaría tramos con ancho y sin
  bombeo, contra FR-023, y por una razón puramente interna que al usuario no le dice nada.
- *Volver a leer del ráster las transversales de los tramos reparados*: evita la memoria pero añade
  E/S aleatoria sobre el DEM justo al final, y en el caso malo —muchos tramos reparados— es más lenta
  que haber retenido todo.
- *Retener solo las muestras entre los bordes detectados*: no sirve, porque un borde inferido puede
  caer **fuera** del rango que se retuvo.

---

## D23 — El import del módulo nuevo en la función del worker

**Decisión**: `run_analysis` importa `coreplugins.road.coherence` de forma **absoluta y dentro del
cuerpo de la función**, igual que ya hace con el resto de módulos del plugin.

**Justificación**: no es una preferencia de estilo, es un requisito de ejecución. `run_function_async`
reejecuta la función **por su código fuente** en un namespace vacío (`eval(compile(source), ns, ns)`
con `ns = {}`), así que nada del ámbito del módulo está disponible allí. Un import a nivel de módulo,
o un import relativo, funciona en todos los tests locales —donde la función se llama directamente— y
falla **solo** dentro del worker, con un `NameError` o un `ImportError` que aparece en runtime y en
producción.

Es el mismo mecanismo que obligó al Principio IV paso 3 en `005`, y la razón de que la verificación
en worker siga siendo obligatoria aunque esta feature no añada ninguna dependencia.

**Alternativas descartadas**:

- *Meter la lógica de coherencia dentro de `compute.py`* para no crear un módulo nuevo: evitaría el
  problema del import, pero mezcla dos responsabilidades con entradas distintas (un perfil frente a
  una secuencia de bordes) y hace `compute.py` más difícil de probar sin ráster.

---

## D24 — Lo que **no** se ha medido: si de verdad hacen falta dos modos

**Decisión**: se implementan los dos modos y `break` sigue siendo el defecto, **sin haber medido**
si el criterio de superficie serviría igual de bien en caminos rurales. Queda registrado como
supuesto, no como hecho.

**Justificación**: la hipótesis que sostiene los dos modos es que una calzada rural que se hunde
suavemente hacia la cuneta nunca se aparta lo suficiente de su propia referencia, y daría `no_break`
donde el criterio de quiebre acierta. Es plausible pero **dudosa**: un talud de 1 m de desnivel
supera una tolerancia de 6 cm de inmediato, así que puede que el criterio de superficie funcione
igual de bien en tierra.

Si resultara que funciona, el diseño se simplificaría de forma sustancial: un solo criterio, un
parámetro menos, la mitad de tests y una explicación en vez de dos. El coste de mantener dos modos
está registrado en la tabla de Complexity Tracking del plan como deuda aceptada, no como necesidad
demostrada.

**Cómo se resuelve, si se quiere resolver**: correr el criterio de superficie sobre `Noria` y
`ruta de zona 1` y comparar tramo a tramo contra el resultado del criterio de quiebre. Es una
comparación de dos columnas sobre datos que ya están en la instancia, y el andamiaje para hacerla es
el mismo que produjo las mediciones de D17. Está recogido como escenario opcional en
[quickstart.md](./quickstart.md).

**Alternativas descartadas**:

- *Medirlo antes de implementar*: se propuso y el usuario optó por seguir con el diseño de dos modos.
  Se deja constancia de la decisión y de su coste para que revisarla más adelante sea barato.
- *Sustituir el detector sin medir*: apostaría a ciegas sobre análisis rurales ya validados y
  entregados.
