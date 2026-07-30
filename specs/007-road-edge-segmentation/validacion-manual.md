# Validación manual — `007-road-edge-segmentation`

Registro honesto de qué se validó a mano, contra la instancia real, y qué solo quedó cubierto por
la suite automática con dobles de `geodeep`. Sigue el mismo criterio que
[`006/validacion-manual.md`](../006-street-width/validacion-manual.md) — que no existe como archivo
separado en `006` (su equivalente vive repartido entre `quickstart.md` y las notas de `tasks.md`);
aquí se centraliza en un solo documento porque esta feature tuvo más pasos manuales que automáticos
por la naturaleza de la dependencia externa.

Fecha de la validación: 2026-07-29. Instancia: local vía `docker compose` (`webapp`, `worker`, `db`,
`broker`), imagen `webodm_webapp`, `geodeep==0.9.12` ya presente.

---

## Escenario 1 — Suite completa

**Validado automáticamente**, no a mano. Última corrida:

```text
docker compose exec -T webapp /webodm/webodm.sh test backend coreplugins.road.tests
Ran 310 tests in 23.9s
OK
```

310 tests frente a los ~285 de antes de empezar esta feature (Foundational ya subió a 285 sobre el
recuento de `006`; el resto de fases lo llevó a 310). Ninguno depende de `geodeep` real ni de red:
`segmentation.run_segmentation` se sustituye por un doble en todos los tests automáticos.

## Escenario 2 — No regresión de `break`/`surface`

**Validado contra datos reales**, no solo sintéticos (T027). Los 5 análisis existentes en la
instancia (`Mina La Coipa`, `Polideportivo María Puebla Vásquez`, `Noria`, `Colegio Trabunco`,
`Task of 2026-07-24…`) se recalcularon con el código de esta feature y se compararon campo a campo
contra el estado ya persistido. Cero diferencias en todo lo que `006`/`007` pueden tocar: `width`,
`offset_left`, `offset_right`, `cross_slope`, `status`, motivos, orígenes. Sí aparecieron
diferencias en `width_min`/`width_max`/`width_sections`/`width_measured_sections` para 3 de los 5,
pero **confirmadas ajenas a esta feature** — ver el detalle en `tasks.md` T027: son análisis
persistidos antes del commit `0ae6050f` de `006`, que ya añadía esas columnas antes de que
empezara `007`.

## Escenario 3 — Disponibilidad de ortofoto

**Validado por tests** (`SegmentationModeAvailabilityTest`), no repetido a mano por ser
determinista y no depender de infraestructura externa.

## Escenario 4 — El progreso no se congela

**No validado a mano de forma cronometrada.** El análisis real del Escenario 6 (abajo) terminó en
~10 s desde el lanzamiment hasta el primer sondeo, demasiado rápido para observar la fase de
segmentación como un tramo de progreso claramente distinto del resto — el modelo ya estaba
disponible (cacheado) y el corredor de esta calle es pequeño. Queda pendiente de observar con un eje
más largo o la primera vez que el modelo se descargue de verdad desde cero, donde el tramo de
`SEGMENTATION_PROGRESS_SHARE` sí debería notarse. El mecanismo en sí —que la fase de segmentación
reporta por el mismo `progress_callback`— está verificado por `research.md` D27 y no depende de
cuánto tarde.

## Escenario 5 — Parámetros propios de otro modo, ocultos

**Validado en el navegador real** (2026-07-29, Chrome sobre `http://localhost:8000`, proyecto
`marcoleta`, panel «Camino» → «Ajustar parámetros»). El desplegable «Criterio de borde» ofrece las
tres opciones, con la nueva rotulada *«Segmentación de la ortofoto — sin relieve en el borde (IA,
experimental)»*. Recorriendo los tres modos y comparando las etiquetas renderizadas en el DOM, los
campos exclusivos de cada uno son:

| Modo | Campos exclusivos visibles |
|---|---|
| `break` | Umbral de quiebre (%) |
| `surface` | Tolerancia de separación (m) |
| `segmentation` | *(ninguno)* |

Es decir, con `segmentation` seleccionado no se renderiza ningún parámetro ajeno al modo, y el
propio modo no añade ninguno — que es exactamente lo que pide FR-015a/FR-015b.

Matiz honesto sobre el método: el cambio de opción se disparó con el setter nativo de
`HTMLSelectElement` + `change`, no con un clic físico sobre el desplegable, porque el popup nativo
de `<select>` en macOS no responde a eventos sintéticos de CDP. Se ejercita el mismo `onChange` de
React que dispararía un usuario, pero no es un clic real del ratón sobre la lista desplegada.

**Descubierto al hacer esta validación** (y por lo que el escenario no era una formalidad): el modo
no aparecía en absoluto en la interfaz, pese a estar el código correcto en disco y los 310 tests en
verde. Dos pasos de despliegue faltaban, ninguno cubierto por los tests:

1. El bundle `public/build/Road.js` que sirve el navegador no se recompila solo — hizo falta
   `docker compose exec webapp python manage.py rebuildplugins`.
2. El proceso de gunicorn llevaba horas con `coreplugins.road.sources` cacheado en memoria, así que
   `GET …/capabilities` seguía devolviendo `["break","surface"]`. Hizo falta
   `docker compose restart webapp` — el mismo gotcha que ya había mordido en el worker (T029), pero
   que no se había documentado para `webapp`.

Ambos quedan recogidos en la sección «Desarrollo» de [`README.md`](../../coreplugins/road/README.md).

## Escenario 6 — Verificación del worker (Principio IV, no negociable)

**Validado contra la instancia real, con Celery real (no `CELERY_TASK_ALWAYS_EAGER`)**, sobre
`Polideportivo María Puebla Vásquez`. Detalle completo, incluido un fallo real por caché de módulo
del worker y su corrección, en `tasks.md` T029.

Resumen: `status: "completed"`, `measured_count: 13` de 14 tramos, `duration: 8.66 s`, sin
`NameError` ni `ImportError` en el log del worker. El worker tenía salida de red
(`huggingface.co` → `200`); no se pudo observar el caso "sin red" de forma realista sin desconectar
el contenedor, así que ese camino queda verificado solo por el test unitario
(`test_missing_geodeep_library_raises_a_clear_error`), no por una prueba end-to-end real sin red.

## Escenario opcional — ¿sirve el modelo sobre ortofotos de dron reales? (D33)

**Validado contra datos reales.** Resultado completo en
[`research.md`](./research.md#d33--lo-que-sigue-sin-medirse-si-el-modelo-roads-sirve-sobre-ortofotos-de-dron-reales),
resolución del 2026-07-29. Resumen: el modelo mide de forma consistente (13/14 tramos) pero con un
sesgo sistemático hacia anchos mayores que `surface` (+1,80 m de media, hasta +4,36 m en un tramo).
La causa se determinó **inspeccionando la máscara** (2026-07-29, tarde): no era la acera, como se
supuso al principio, sino que el modelo clasifica como calzada el descampado de tierra contiguo a la
vía y zonas de tierra de un parque — 25,3 % del corredor marcado como `road`. Medido también que la
máscara vuelve a 20 cm/px frente a los 5 cm/px de la ortofoto (resolución nativa del modelo), lo que
acota la precisión del borde a ~20 cm.
No se pudo comparar contra el caso puro que motiva la feature (un tramo sin bordillo en absoluto)
por no haber, hoy, un eje trazado sobre un tramo así en la instancia.

---

## Pendiente antes de considerar la feature validada de cara al usuario final

- ~~Abrir el panel en un navegador real y confirmar visualmente el Escenario 5.~~ Hecho el
  2026-07-29; ver Escenario 5 arriba.
- Repetir el Escenario 6 con un eje más largo o forzando una descarga real del modelo desde cero,
  para observar el tramo de progreso de la segmentación (Escenario 4) con datos, no solo por diseño.
- Si aparece una tarea con un tramo cuyo borde sea *solo* cambio de textura (sin bordillo real), es
  el caso de validación que más falta —el que motiva la feature entera— y no se ha podido probar
  contra datos reales todavía, solo contra el DEM/máscara sintéticos de `SegmentationModeTest`.
