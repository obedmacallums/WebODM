# Phase 0 — Investigación: corrección de la nube de puntos

**Feature**: `003-realign-pointcloud` | **Fecha**: 2026-07-23

Todas las decisiones de este documento se validaron ejecutando comandos dentro del contenedor
`webapp` sobre la nube real de una tarea procesada (proyecto 10, tarea `6e965174-…`,
`odm_georeferenced_model.laz`, **280.315.960 bytes / 61.780.499 puntos**, LAS 1.4 formato 7,
`scale = 0.001`, `offset = (352300, 6295657, 0)`, EPSG:32719). Los resultados medidos se citan
en cada decisión.

## D1 — Herramienta para transformar la nube

- **Decisión**: invocar el **CLI `pdal`** (2.3.0, ya en la imagen) por `subprocess` con un
  pipeline JSON `readers.las → filters.transformation → writers.las`.
- **Rationale**: `filters.transformation` aplica exactamente una matriz 4×4 por punto, que es
  justo el modelo que 002 ya calcula. Los bindings `python-pdal` **no** están instalados
  (`docs/entorno-plugins.md`) y no hacen falta: se mantiene el **nivel 0** de la escalera del
  Principio IV (cero dependencias nuevas). El repo ya tiene precedente de invocar binarios
  geoespaciales así: `coreplugins/contours/api.py:59-97` llama `gdalwarp`/`gdal_contour`/`ogr2ogr`
  con `subprocess.Popen` chequeando `returncode` y devolviendo `stderr` dentro de `{'error': …}`.
  Esto también confirma lo anticipado por la **D8 de 002**.
- **Alternativas descartadas**: `laspy` (dependencia nueva; recorrer 61,7 M de puntos en Python
  puro es órdenes de magnitud más lento que el pipeline nativo); `python-pdal` (dependencia nueva
  sin ninguna ganancia sobre el CLI para este caso de un solo pipeline).

## D2 — Forma de la matriz: rígida en XY, Z intacta

- **Decisión**: matriz 4×4 *row-major* construida con los `cos`, `sin`, `tx`, `ty` que 002 ya
  persiste, con la fila Z en identidad:

  ```text
  cos  -sin   0   tx
  sin   cos   0   ty
   0     0    1    0
   0     0    0    1
  ```

  Son **los mismos cuatro números** que `corrections.py` pasa al pipeline ráster (`T`), lo que
  satisface la FR-002 por construcción: no se recalcula nada, se reutiliza la transformación
  vigente. El campo `scale` se ignora porque la FR-004 restringe la feature al modo rígido
  (`scale == 1`).
- **Verificado**: sobre 50.000 puntos, `max |Z_original − Z_corregido| = 0.0` **exacto**. La
  fila Z en identidad más el `offset_z`/`scale_z` heredados (D3) hacen que cada Z se
  re-cuantice al mismo entero, así que la SC-002 se cumple de forma estructural, no aproximada.
- **Nota importante para quien implemente**: `tx`/`ty` son la forma afín **respecto al origen de
  coordenadas**, no el desplazamiento visible. Para una rotación de 0,5° sobre coordenadas UTM,
  `tx ≈ 54.955 m` aunque el desplazamiento real de la nube sea de ~2 m. No es un error: es la
  compensación de rotar alrededor del origen. Los `double` de PDAL (≈15-16 dígitos
  significativos sobre valores de ~6,3 M) dejan la precisión en el orden de 1e-9 m, muy por
  debajo del paso de cuantización.

## D3 — Preservación de cabecera y precisión (el punto delicado)

- **Decisión**: `writers.las` con `forward="all"`, `compression="LASZIP"` y **`offset_x`/`offset_y`
  explícitos**, calculados de la caja envolvente transformada. `offset_z` y las tres escalas se
  dejan heredar.
- **Rationale y dos trampas verificadas**:

  1. **El default de `scale_x` es `0.01`** (1 cm). La nube de ODM usa `0.001` (1 mm). Sin
     `forward`, la corrección degradaría la precisión un orden de magnitud de forma silenciosa.
     `forward="all"` hereda escalas, `offset_z`, `dataformat_id` (7 = RGB + GpsTime), la versión
     LAS 1.4 y el SRS.
  2. **Heredar `offset_x`/`offset_y` puede desbordar el `int32` de LAS.** Comprobado: con una
     matriz cuya salida cae lejos del offset heredado, PDAL aborta con
     `Unable to convert scaled value (-3194975013) to int32 for dimension 'X'`. Con
     `scale = 0.001` el rango útil alrededor del offset es de solo ±2.147.483 m. Por eso los
     offsets XY se calculan explícitamente: se transforman las **4 esquinas del bbox leído de la
     cabecera** (sin ninguna pasada por los datos), se toma el centro redondeado y se valida el
     rango `int32` **antes** de lanzar el pipeline.

- **Verificado** (50.000 puntos, transformación realista de 0,5° + 2 m):

  | Variante | error XY máx. | Z | Observación |
  |---|---|---|---|
  | `forward=all` (offsets heredados) | 0,00050 m | 0.0 exacto | óptimo, pero desborda con transformaciones grandes |
  | `forward=all` + `offset=auto` | 0,00089 m | 0.0 exacto | PDAL avisa `Auto offset … in stream mode` y usa un valor aproximado, no determinista |
  | **`forward=all` + offsets explícitos** | **0,00050 m** | **0.0 exacto** | elegida: óptima y a prueba de desbordes |

  0,0005 m es exactamente **medio paso de cuantización** — el redondeo mínimo posible, no un
  error del método. Atributos `Intensity`, `Classification`, `GpsTime`, `Red`, `Green`, `Blue`
  idénticos punto a punto (FR-008).
- **Alternativas descartadas**: `offset_x="auto"` (peor alineación de rejilla y no determinista);
  no usar `forward` (pierde precisión, SRS y formato de punto).

## D4 — Dónde se escribe y atomicidad

- **Decisión**: escribir en el mismo directorio persistente del plugin que ya usan los rásteres
  (`get_plugins_persistent_path('realign', 'task_<pk>')`), con nombre temporal
  **`<final>.tmp.laz`** y `os.replace()` al nombre definitivo solo tras un `returncode == 0`.
- **Rationale**: la FR-014 exige que un fallo o un `kill` nunca deje un archivo con pinta de
  válido; `os.replace` es atómico dentro del mismo filesystem, así que el nombre final **solo
  existe si el pipeline terminó bien**. El directorio persistente es el volumen compartido
  webapp↔worker, que es lo que permite cumplir la FR-011 (el resultado sobrevive a recargas y lo
  ve cualquier usuario con acceso a la tarea).
- **Detalle verificado**: el temporal debe conservar la extensión `.laz`. Con `.part`, `pdal info`
  falla al inferir el driver (`JSONDecodeError` porque no emite JSON); escribir sí funciona
  porque el pipeline declara `writers.las` explícitamente, pero cualquier verificación posterior
  se rompe.
- **Alternativas descartadas**: escribir directo al nombre final (deja restos descargables ante
  fallo); usar `settings.MEDIA_TMP` como `contours` (ver D5).

## D5 — Persistencia del resultado: por qué NO se copia el patrón de `contours`

- **Decisión**: la descarga **no** cuelga del `celery_task_id`. Se sirve desde un endpoint propio
  que lee el archivo del directorio persistente, igual que `RealignDownload` hace hoy con los
  GeoTIFF (`coreplugins/realign/api.py:341-351`).
- **Rationale**: `contours` escribe en `MEDIA_TMP` y descarga vía `GetTaskResult` con el
  `celery_task_id` (`contours/api.py:143-150`). Eso es correcto para un resultado efímero, pero
  incumpliría la **FR-011** y la **FR-012**: el resultado de Celery expira y el `task_id` se
  pierde al recargar la página, con lo que la nube dejaría de ser descargable aunque el archivo
  siguiera en disco, y otro usuario con acceso a la tarea nunca podría bajarla.
- **Qué sí se toma de `contours`**: la convención de retorno `{'file': …}` / `{'error': …}` y el
  chequeo de `CheckTask` (`app/api/workers.py:43`), que ya responde `"Cannot generate file"` si la
  ruta no existe — refuerzo gratuito de la FR-014.

## D6 — Progreso y cancelación

- **Decisión**: `run_function_async(..., with_progress=True, with_cancel=True)`
  (`app/plugins/worker.py:29-43`) y un bucle de sondeo sobre el `Popen` que hace dos cosas a la
  vez: consultar `should_cancel()` y estimar el avance como
  `tamaño(.tmp.laz) / tamaño(original)`.
- **Rationale**: `pdal pipeline --progress <fifo>` **no sirve para esto**. Verificado: el FIFO
  recibió 63 bytes en total, solo `READYFILE:<archivo>` y `DONEFILE:<archivo>` — eventos de
  inicio/fin, sin porcentaje. En cambio, la salida crece de forma sostenida (~5,7 MB/s medidos,
  muestreados cada 5 s) y el archivo final pesa **280.632.581 B frente a 280.315.960 B de
  entrada: 1,001×**. Con el mismo códec y la misma cantidad de puntos, el tamaño de entrada es un
  denominador fiable. El bucle de sondeo hace falta igual para `should_cancel()`, así que el
  progreso sale sin coste adicional.
- **Al cancelar**: `proc.terminate()` y borrado del `.tmp.laz` (nunca hubo nombre final, D4).
- **Frontend**: `Workers.waitForCompletion(id, cb, progress_cb)`
  (`app/static/app/js/classes/Workers.js:4`) ya sondea `/api/workers/check/` cada 2 s y reenvía
  `status`/`progress`; `Workers.cancel` ya existe. Es el mismo helper que usa
  `ContoursPanel.jsx:227`. **Realign no usa progreso hoy** — esta feature lo estrena en el plugin.
- **Sin límite de tiempo**: `WORKERS_MAX_TIME_LIMIT = None` (`webodm/settings.py:430`), así que
  una operación larga no la mata el worker.

## D7 — Rendimiento medido

- **Medición**: la nube completa (61.780.499 puntos, 268 MB) se transformó en **48 segundos**
  (`exit_code=0`), en el contenedor con 8 CPU disponibles.
- **Consecuencia**: la **SC-006** (< 10 min para ~250 MB) tiene más de un orden de magnitud de
  margen. No hace falta paralelizar, trocear ni usar modo streaming explícito.
- **Espacio**: la salida pesa prácticamente lo mismo que la entrada (1,001×), coherente con la
  suposición de duplicación de espacio de la spec.

## D8 — Detección de obsolescencia (FR-012)

- **Decisión**: guardar junto al resultado una **huella de la transformación** con la que se
  generó (`cos`, `sin`, `tx`, `ty` redondeados a una tolerancia fija, más `use_scale` y el número
  de pares habilitados) y compararla con la transformación vigente cada vez que se lee el estado.
  Si no coinciden, el estado pasa a `stale` y no se ofrece descarga.
- **Rationale**: los pares de puntos pueden editarse sin volver a aplicar, así que el disparador
  no puede ser "aplicar". Comparar la huella detecta exactamente la condición que importa —que el
  archivo ya no corresponda al ajuste vigente— y es inmune a relojes y a órdenes de escritura.
- **Alternativas descartadas**: borrar el archivo en cuanto cambie un punto (destruye un resultado
  caro por una edición que el usuario puede deshacer); comparar `updated_at` (frágil: cambia por
  ediciones que no alteran la transformación, como habilitar y volver a deshabilitar un punto).

## D9 — Elegibilidad y validación en el backend

- **Decisión**: la acción se ofrece solo si se cumplen las tres condiciones, y **el backend las
  revalida** sin confiar en la UI, devolviendo un mensaje distinto por causa:
  1. la tarea tiene `georeferenced_model.laz` en `available_assets` (FR-017);
  2. el estado de realineación es `applied` (FR-005);
  3. `transform.use_scale == false` (FR-004).
- **Rationale**: mismo criterio que ya aplica `RealignApply` (valida puntos y degeneración aunque
  el panel también lo haga). Los mensajes diferenciados son lo que sostiene la US2 y la SC-009.
- **Permisos**: generar exige `change_project` (`check_project_perms`), igual que Aplicar/Revertir
  (FR-016, D7 de 002); descargar solo exige acceso a la tarea.

## D10 — Estrategia de test

- **Decisión**: generar los LAZ de fixture **en tiempo de test** con `readers.faux` de PDAL, en
  vez de versionar binarios en el repo.
- **Verificado**: `readers.faux` está disponible en PDAL 2.3 y produce un LAZ válido con SRS,
  escalas y offsets controlados (probado: 1.000 puntos, 8.111 bytes, bounds correctos).
- **Qué se verifica en los tests**: cantidad de puntos idéntica, `max|ΔZ| == 0`, XY dentro de
  medio paso de cuantización respecto al valor esperado calculado en Python, cabecera preservada
  (`scale_*`, `offset_z`, `dataformat_id`, `minor_version`, SRS) y ausencia de archivo final tras
  un fallo simulado.
- **Herramientas de verificación**: `pdal info --summary` (puntos y bounds) y `pdal info
  --metadata` (cabecera), ambas ya usadas en esta investigación.

## Resumen de dependencias

**Nivel 0 de la escalera del Principio IV — cero dependencias nuevas.** El CLI `pdal` 2.3.0 ya
está en la imagen compartida webapp↔worker (`docs/entorno-plugins.md`); no se instalan bindings,
no se toca el `requirements.txt` global ni el `Dockerfile`. La verificación obligatoria de que el
worker ejecuta el pipeline sin errores queda documentada en `quickstart.md`.
