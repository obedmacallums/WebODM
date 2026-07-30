# Quickstart — validación de `008-segmentation-mask-layer`

Escenarios que prueban que la feature funciona de extremo a extremo. Los que se pueden automatizar
están marcados; el resto son manuales por naturaleza (una capa que se mira no se valida con
`assert`).

**Prerrequisitos**: stack levantado (`webapp`, `worker`, `db`, `broker`), una tarea con ortofoto y un
eje trazado. Los dos corredores de referencia usados en el diseño son
`Polideportivo María Puebla Vásquez` (66 m) y `Noria - 3/17/2026` (293 m).

> **Antes de validar nada a mano**: copiar el código a los contenedores **no lo despliega**. Hace
> falta `docker compose restart webapp worker` (los procesos cachean módulos en memoria) y, si se
> tocó JS/JSX, `python manage.py rebuildplugins` más un recarga forzada del navegador. Está
> documentado en la sección «Desarrollo» de [`README.md`](../../coreplugins/road/README.md); se
> repite aquí porque en `007` costó una sesión entera de confusión.

---

## Escenario 1 — Suite completa (automatizable)

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.road.tests
```

**Esperado**: todo en verde, y el recuento por encima de los 310 tests con los que arranca esta
feature. Ningún test debe necesitar el modelo real ni salida a red: la segmentación se sustituye por
un doble, igual que en `007`.

---

## Escenario 2 — La máscara se guarda y se sirve (automatizable)

1. Lanzar un análisis en modo `segmentation` sobre una tarea con ortofoto.
2. Comprobar que junto al documento de tramos aparece el de máscara, en la ruta del framework:

```bash
docker compose exec webapp sh -c 'ls -lh /webodm/app/media/plugins/road/task_*/ | grep mask'
```

3. Pedir la máscara por la API y comprobar que trae polígonos en EPSG:4326.

**Esperado**: fichero `<analysis_id>.mask.json` de decenas de KB; el endpoint responde `200` con
`features` no vacío y coordenadas en grados; el análisis viene con `has_mask: true`.

---

## Escenario 3 — Los tres estados no se confunden (automatizable)

Cubre `FR-017`, que es donde es fácil mentirle al usuario.

| Caso | Cómo provocarlo | Esperado |
|---|---|---|
| Máscara con calzada | Análisis de segmentación normal | `has_mask: true`, `200`, `features` con contenido |
| Máscara vacía | Corredor donde el modelo no detecta calzada (o doble que devuelve máscara sin unos) | `has_mask: true`, `200`, `features: []` |
| Sin máscara | Análisis de modo `break`, o uno de segmentación anterior a esta feature | `has_mask` falso/ausente, `404` con código `mask_missing` |

**Lo importante**: los dos últimos NO deben producir la misma respuesta. Una máscara vacía es un
resultado; la ausencia de máscara no lo es.

---

## Escenario 4 — Nada de lo anterior se rompe (automatizable + datos reales)

1. Suite completa (Escenario 1) para `break` y `surface`.
2. Recalcular los análisis reales existentes de la instancia y comparar campo a campo contra su
   estado previo, como se hizo en `007`/T027.

**Esperado**: cero diferencias en `width`, `offset_left`, `offset_right`, `cross_slope`, `status`,
motivos y orígenes. Las exportaciones CSV y GeoJSON, byte a byte iguales (`FR-020`).

---

## Escenario 5 — Borrar un análisis se lleva su máscara (automatizable)

Cubre `FR-005`. Hay **cinco** caminos que borran el documento de tramos (tres en la capa de API, dos
en el worker: cancelación y fallo). Todos deben borrar también la máscara.

```bash
docker compose exec webapp sh -c 'ls /webodm/app/media/plugins/road/task_*/ | grep -c mask'
```

**Esperado**: tras borrar los análisis, cero ficheros `.mask.json` huérfanos. Conviene probar
explícitamente el camino de **cancelación** y el de **fallo**, no solo el borrado normal — son los
que se olvidan.

---

## Escenario 6 — La capa se ve, y se ve bien (manual)

El corazón de la feature. No se puede automatizar: consiste en mirar.

1. Abrir un análisis de segmentación y encender la capa desde el panel.
2. Comprobar que:
   - Los polígonos cubren lo que el modelo clasificó como calzada, dentro del corredor.
   - **Se ve la ortofoto por debajo** (`FR-011`). Si la capa es opaca, la feature no sirve para nada.
   - El eje y las reglas de ancho siguen legibles y por encima (`FR-013`).
   - El color no se confunde con el verde/amarillo/rojo de la pendiente (`FR-012`).
   - Clicar sobre un tramo **sigue abriendo su popup** — la máscara no debe capturar el clic (D39).
   - Apagarla la quita sin tocar nada más (`FR-010`).
3. Usar el corredor de `Polideportivo María Puebla Vásquez`, donde se sabe que el modelo
   sobreclasifica: **el descampado contiguo debe verse marcado**. Ese es el caso que motiva la
   feature entera, y verlo a simple vista es la prueba de `SC-001`.

---

## Escenario 7 — El aviso de precisión (manual)

1. Con la capa activa, hacer zoom al máximo.
2. Comprobar que los bordes escalonados son coherentes con la resolución que la interfaz anuncia, y
   que esa resolución se comunica al usuario (`FR-016`) sin obligarle a leer documentación.

---

## Escenario 8 — Análisis viejo sin máscara (manual)

1. Abrir un análisis de segmentación anterior a esta feature.
2. Comprobar que la interfaz explica que no hay máscara y que recalcular la genera (`FR-018`), en vez
   de ofrecer un control que dibuja nada.
3. Recalcularlo y comprobar que la capa pasa a estar disponible.

---

## Escenario 9 — Corredor largo (manual, con cronómetro)

Cubre el riesgo medido en D40 y, de paso, el Escenario 4 que quedó pendiente en `007`.

1. Lanzar un análisis de segmentación sobre el eje de 293 m de `Noria`.
2. Medir el tamaño del `.mask.json` resultante.
3. Observar la barra de progreso durante la fase de segmentación.

**Esperado**: máscara en torno a **76,9 KB** (medido en diseño), no cientos ni miles. Y como la
segmentación de ese corredor tarda **~13,5 s** frente a los 0,66 s del corto, la fase de progreso
debería por fin ser **observable** — en `007` no se pudo comprobar porque todo terminaba demasiado
rápido.

---

## Escenario 10 — Verificación del worker (Principio IV, no negociable)

La constitución exige demostrar con evidencia que el worker ejecuta la feature sin errores de
import. Es el punto donde más veces ha fallado este plugin.

1. `docker compose restart worker` tras copiar el código.
2. Lanzar un análisis real con Celery de verdad (no `CELERY_TASK_ALWAYS_EAGER`).
3. Revisar el log del worker.

**Esperado**: análisis `completed`, máscara escrita, y **ningún** `NameError` ni `ImportError`. El
riesgo concreto es que la vectorización dependa de algo que `run_analysis` no importa: al ser
self-contained se recompila en un espacio de nombres vacío (D41). Un test que pase en la suite no
prueba nada sobre esto — la suite no usa el worker real.
