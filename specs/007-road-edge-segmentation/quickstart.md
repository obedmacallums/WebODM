# Quickstart — validación de `007-road-edge-segmentation`

Escenarios ejecutables que demuestran que la feature funciona. Cada uno dice qué se corre y qué se
espera ver; ninguno se da por bueno sin ejecutar el comando y mostrar su salida, incluido el exit
code (Flujo de desarrollo de la constitución).

A diferencia de `006`, esta feature no tiene todavía una tarea de referencia con ortofoto sobre la
que se haya validado el modelo `roads` (`research.md` D33). Los escenarios 1 a 5 son de aceptación y
no dependen de eso; el escenario 6 sí, y queda marcado como pendiente de una tarea real.

## Prerrequisitos

- Stack levantado: `docker compose ps` con `webapp`, `worker`, `db` y `broker` en `running`.
- Al menos una tarea con **ortofoto** y polilínea de eje trazada en `annotations`, para los
  escenarios que necesitan lanzar un análisis en modo `segmentation` de verdad (2, 3, 4, 5). Las
  tareas de referencia de `006` (`Polideportivo María Puebla Vásquez`, `Noria`, `ruta de zona 1`)
  sirven si tienen ortofoto generada; si no, cualquier tarea de la instancia con ortofoto y un eje
  trazado basta.
- Código desplegado en los contenedores. `coreplugins/` va horneado en la imagen:

  ```bash
  for s in webapp worker; do
    docker compose exec -T "$s" rm -rf /webodm/coreplugins/road
    docker compose cp coreplugins/road "$s:/webodm/coreplugins/road"
  done
  docker compose restart webapp     # reconstruye el bundle de frontend
  ```

> ⚠️ **No usar `run_tests_in_docker.sh` en esta instancia** si hay tareas reales que no se quieren
> perder: termina con `docker compose down -v`. La suite del plugin se corre contra el stack vivo.

---

## Escenario 1 — La suite completa del plugin

```bash
docker compose exec -T webapp /webodm/webodm.sh test backend coreplugins.road.tests
```

**Esperado**: `OK`, exit code 0, con el número de tests mayor que el de `006` por los casos nuevos
de `test_profile.py` (`detect_edges_segmentation`) y del módulo `segmentation.py` (con `geodeep`
mockeado — ver nota de test debajo).

> Los tests unitarios y de integración de esta feature **no dependen de tener `geodeep` instalado ni
> de red**: donde se necesita el resultado de `geodeep.segment`, el test lo sustituye por un doble
> que devuelve una máscara sintética. Los tests que sí ejercitan la librería real y la descarga del
> modelo son los del escenario 6 (verificación del worker), deliberadamente fuera de la suite
> automática.

Recordatorio de `005`/`006`: `coreplugins/` es un paquete de espacio de nombres; una clase de test
nueva que no se re-exporte desde `tests/__init__.py` no se ejecuta y no falla. Comprobar que el
recuento de tests sube.

---

## Escenario 2 — No regresión de los dos modos existentes (`007/User Story 4`)

El requisito más importante, heredado sin cambios de `006/FR-002`: `break` y `surface` no pueden
cambiar de resultado por la existencia de un tercer modo.

1. Antes de tocar nada, con el código actual, recalcular un análisis existente en `break` o en
   `surface` y guardar el resultado.
2. Con el código nuevo, recalcular el mismo análisis con los mismos parámetros.
3. Comparar tramo a tramo. **Esperado**: cero diferencias.

---

## Escenario 3 — Disponibilidad de ortofoto, verificada antes de lanzar (contrato §`POST analyses`)

1. Sobre una tarea **sin** ortofoto, lanzar `POST task/<pk>/analyses` con
   `params.edge_mode = "segmentation"`.

   **Esperado**: `400` con `{"code": "no_orthophoto"}`, sin que se cree ningún análisis ni se toque
   el candado de ejecución (`GET task/<pk>/analyses` sigue sin `running` tras el intento).

2. Sobre una tarea **con** ortofoto, la misma petición.

   **Esperado**: `202` con `analysis_id` y `celery_task_id`, igual que ya responde hoy para `break`
   y `surface` (contrato de `005`).

---

## Escenario 4 — El progreso no se congela durante la segmentación (`007/FR-009`, `007/FR-016a`)

Sobre una tarea con ortofoto y un eje de longitud suficiente para que el análisis tarde más de
unos segundos:

1. Lanzar un análisis en modo `segmentation`.
2. Sondear `GET task/<pk>/analyses/<analysis_id>` repetidamente mientras `status == "running"`.

**Esperado**: el campo `progress` avanza de forma monótona durante toda la ejecución, incluida la
fase inicial de segmentación — no se queda en `0` o en un valor fijo mientras el modelo corre y solo
salta al terminar. En el panel: la barra de progreso ya existente se mueve visiblemente desde el
lanzamiento, sin que el usuario tenga la sensación de que el análisis está colgado.

---

## Escenario 5 — Parámetros propios de otro modo, ocultos (`007/FR-015a`)

En el panel, con un eje seleccionado:

1. Elegir modo **quiebre**. Comprobar que se ve "Umbral de quiebre (%)" y **no** se ve "Tolerancia
   de separación (m)".
2. Elegir modo **superficie**. Al revés: se ve la tolerancia, no el umbral.
3. Elegir modo **segmentación**. **Esperado**: ni el umbral de quiebre ni la tolerancia de
   separación se muestran. Los campos compartidos (semiancho de búsqueda, muestras consecutivas,
   ventana de coherencia, suavizado, separación entre transversales, agregación del ancho) siguen
   visibles y editables igual que en los otros dos modos.

---

## Escenario 6 — Verificación del worker (Principio IV, no negociable) — **con riesgo de red nuevo**

**Sin esta evidencia la feature no se cierra.** A diferencia de `006`, aquí sí hay una dependencia
de terceros involucrada (`geodeep`, ya presente en `requirements.txt` del core —
`research.md` D32), y una descarga de modelo la primera vez que se usa.

1. Lanzar desde la interfaz un análisis real en modo `segmentation`, sobre una tarea con ortofoto.
2. Seguir el log del worker:

   ```bash
   docker compose logs -f worker
   ```

**Esperado, primer intento**: el worker descarga el modelo `roads` (requiere que el contenedor
tenga salida de red hacia el repositorio de modelos de GeoDeep), progresa y termina, sin
`NameError` ni `ImportError` — el riesgo de `research.md` D31, el mismo mecanismo de `006/D23` pero
sobre el módulo `segmentation.py` en vez de `coherence.py`. El resultado aparece en el mapa, con la
capa dibujada de forma distinguible del resto (reutiliza el estilo ya existente por `edge_mode`, sin
requisito nuevo de estilo en esta feature).

**Esperado, si el worker no tiene salida de red**: el análisis termina en `status: "failed"` con un
mensaje de error identificable en `analysis.error` (`research.md` D28, caso 1) — no un análisis
colgado en `running`, ni tramos con datos incompletos.

Pegar en el reporte el fragmento del log que demuestra el resultado obtenido.

---

## Escenario opcional — ¿sirve el modelo sobre ortofotos de dron reales? (D33)

No es criterio de aceptación: es la medición que la feature deja pendiente a propósito, igual que
`006/D24` dejó pendiente si hacían falta dos modos antes de medirlo.

Sobre una calle real con un tramo cuyo borde es solo cambio de textura (sin bordillo ni talud, el
caso que motiva la feature — ver `spec.md`, User Story 1) y, si existe, otro tramo con bordillo real
medible también en modo `surface`:

1. Analizar en modo `segmentation` y anotar qué tramos reportan ancho.
2. Comparar contra el mismo eje en modo `surface`: ¿el modo segmentación mide donde `surface` no
   podía? ¿Coincide razonablemente donde los dos sí miden, aunque no se exija coincidencia exacta
   (`spec.md`, User Story 1, escenario 3)?
3. Si el modelo no reconoce calzada de forma útil sobre la ortofoto de dron (resolución nativa muy
   distinta de los 21 cm/px de entrenamiento, `research.md` D28 de la spec / Assumptions), queda
   documentado con datos reales, y el modo segmentación pasa de hipótesis a hecho medido — para bien
   o para mal.
