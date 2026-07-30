# Validación manual — `008-segmentation-mask-layer`

Registro honesto de qué se validó contra la instancia real y qué quedó cubierto solo por tests con
dobles. Mismo criterio que
[`007/validacion-manual.md`](../007-road-edge-segmentation/validacion-manual.md).

Fecha: 2026-07-30. Instancia local vía `docker compose` (`webapp`, `worker`, `db`, `broker`).

---

## Escenario 1 — Suite completa

**Automático.** `Ran 342 tests / OK`, desde los 310 con los que arrancó la feature: **+32** (29
backend nuevos y 3 casos de JS agrupados en `FrontendUnitTest`).

Comprobado además que los módulos nuevos **se ejecutan de verdad** y no son un verde falso: correrlos
por nombre da `Ran 29 tests / OK`, y el total de la suite subió en la misma medida. Es la trampa del
namespace package (`coreplugins/` sin `__init__.py`): un módulo que no se reexporte en
`tests/__init__.py` no se ejecuta y nadie se entera.

## Escenario 2 — La máscara se guarda y se sirve

**Validado contra la instancia real.** Análisis de segmentación relanzado sobre
`Polideportivo María Puebla Vásquez` con Celery real:

```
status: completed   error: null   has_mask: true
mask HTTP 200   features: 4   resolution_m: 0.19998   simplify_tolerance_m: 0.2
primer vértice: [-70.71342847998027, -33.355742878371004]
```

En disco, en la ruta del framework que exige la constitución:

```
16d6119b-…-….json        13K   (tramos)
16d6119b-…-….mask.json   20K   (máscara)
```

El primer vértice confirma en producción que el orden de ejes es **(lon, lat)** — ver el bug de más
abajo.

## Escenario 3 — Los tres estados no se confunden

**Automático** (`test_api_mask.py`, más el equivalente en `maskLayer.test.js`). Es donde era más
fácil mentirle al usuario, así que hay un test dedicado a que máscara vacía (`200`, `features: []`)
y máscara ausente (`404 mask_missing`) **no** respondan igual. Si lo hicieran, el panel diría «el
modelo no detectó calzada» cuando la verdad es que nunca se guardó nada.

Observado también en la instancia real: antes de recalcular, el análisis de `007` traía
`has_mask: false` — exactamente el caso de US3.

## Escenario 4 — No regresión

**Validado contra datos reales** (T033). Los 5 análisis de la instancia recalculados y comparados
**columna a columna** contra la línea base de T002: **5 comparados, 0 diferencias**, 20 columnas
cada uno.

Incluye el análisis de segmentación que se recalculó con el código de `008`: su CSV sale idéntico
al de antes de la feature. Es la mejor evidencia disponible de FR-019/FR-020.

Se comparó por columnas y no con `diff` en crudo a propósito: en `007` un `diff` truncado hizo
parecer regresión lo que era una discrepancia preexistente.

## Escenario 5 — Borrado en cascada

**Automático**, con un test por cada uno de los cinco caminos, incluidos los dos del worker
(cancelación y fallo) que son los que se olvidan porque solo se recorren cuando algo va mal.

**No verificado a mano contra la instancia**: los caminos de fallo y cancelación requieren provocar
un error real en el worker, y los tests los cubren de forma determinista.

## Escenario 6 — La capa se ve, y se ve bien

**Validado en el navegador real**, con inspección del DOM vivo en vez de solo mirar la captura:

| Comprobación | Resultado |
|---|---|
| Polígonos dibujados | 4 |
| ¿Capturan clics? | **0 de 4** interactivos, `pointer-events: none` |
| Tramos interactivos intactos | 16 |
| Orden de pintado | máscara en índice 0 del SVG, tramos desde el 19 → la máscara queda **detrás** |
| Encender / apagar | 4 → 0 → 4 polígonos, con el eje intacto (16 rutas) en todo momento |
| Ortofoto visible debajo | sí, `fillOpacity` 0.35 |
| Color | `#2b7fd4`, fuera de la paleta del semáforo |

Y lo que motiva la feature entera: sobre `Polideportivo María Puebla Vásquez` **se ve el derrame
sobre el descampado contiguo** a simple vista. Eso es `SC-001` cumplido: lo que antes exigía
rescatar un fichero temporal y renderizarlo a mano ahora se ve mirando el mapa.

## Escenario 7 — Aviso de precisión

**Validado en el navegador.** El panel muestra: *«Aproximación a 20 cm por píxel: los bordes no son
un contorno exacto de la calzada.»* El número sale de `resolution_m` de la respuesta
(`0.19998` → 20 cm), no de una constante del frontend.

## Escenario 8 — Análisis viejo sin máscara

**Parcialmente validado.** Se observó en la instancia real el estado de partida (`has_mask: false`
en el análisis de `007`) y se comprobó que al recalcular pasa a `true` y la capa queda disponible.

**Pendiente**: no se llegó a ver con los ojos el mensaje de «recalcular» en el panel, porque el
único análisis que estaba en ese estado se recalculó durante la verificación del worker. El mensaje
está cubierto por test (`maskLayer.test.js` comprueba que difiere del de máscara vacía y que ofrece
recalcular), pero no se observó renderizado.

## Escenario 9 — Corredor largo

**Validado con el código de producción** sobre `Noria` (eje de 293 m, semiancho 25 m):

```
segmentación : 12,35 s
vectorizado  :  0,059 s  (0,48 % del total)
polígonos    : 14        resolución 0,1999 m/px
MÁSCARA      : 77,0 KB   tramos: 41,2 KB   ratio 1,87x  (SC-003 exige <= 2x)
progreso     : 13 reportes a lo largo de 9,41 s
```

77,0 KB frente a los 76,9 KB estimados en diseño: la medición del plan era correcta.

Los 13 reportes de progreso en 9,41 s **cierran de paso el Escenario 4 que quedó pendiente en
`007`**, donde no se pudo observar la fase de segmentación porque todo terminaba en menos de un
segundo.

**Decisión consciente**: no se lanzó este análisis por la interfaz. El análisis guardado de `Noria`
es de modo `break` y anterior a `006`; recalcularlo como segmentación lo habría destruido, y no se
justifica perder datos del usuario por una medición que el código de producción da igual de bien
sin persistir nada.

## Escenario 10 — Verificación del worker (Principio IV, no negociable)

**Validado con Celery real** (no `CELERY_TASK_ALWAYS_EAGER`), tras
`docker compose restart webapp worker`:

- `POST analyses` → `202` con `celery_task_id` real (`30ba3efc-…`)
- Resultado: `completed`, `error: null`, 14 de 14 tramos, `has_mask: true`
- Log del worker: **0** ocurrencias de `NameError`, `ImportError`, `AttributeError` o `Traceback`

Era el riesgo principal del plan: `run_analysis` es self-contained y se recompila en un espacio de
nombres vacío, así que un import mal colocado da un fallo que **ningún test de la suite detecta**.
La mitigación (D41: los imports nuevos en `segmentation.py`, no en `run_analysis`) funcionó.

---

## Bugs propios encontrados durante la implementación

Se dejan escritos porque los tres los cazó el propio trabajo, no una revisión posterior:

1. **Ejes invertidos (el grave).** `GEOSGeometry.geojson` serializa vía OGR, que respeta el orden de
   ejes oficial de EPSG:4326 —latitud primero— y devuelve las coordenadas **al revés**. Verificado
   aislando el caso: `[-93.0, 45.0]` entra y sale `[45.0, -93.0]`, con y sin `srid`. Los polígonos
   habrían aparecido en otro punto del planeta. Lo cazó el primer test de vectorización. Corregido
   construyendo el GeoJSON desde `.coords` (`_geos_to_geojson_geometry`).
2. **`SyntaxError` en el panel oculto por el propio comando de build.** Faltaba la flecha en una
   propiedad de clase (`showMask = (...) => {`). `manage.py rebuildplugins` **salió con código 0 y
   dijo `[cached]`** aunque no escribió el bundle. Solo se detectó al comprobar el artefacto con
   `grep`. Documentado como gotcha permanente en el README.
3. **Sombra del `document` global.** El parámetro se llamaba `document` dentro de un componente de
   navegador. Renombrado a `maskDoc`.

## Premisas mías que los tests corrigieron

- Una máscara de semiancho 0 **no está vacía** (la celda `d == 0` cuenta).
- Un rectángulo alineado a la rejilla **no se puede simplificar** por debajo de 5 vértices; hizo
  falta un borde diagonal para probar la simplificación de verdad.
- El filtro de área mínima **no controla el tamaño**: no descarta ni un polígono en corredores
  reales, porque `geodeep` ya aplica el suyo. Queda como red de seguridad, y así está documentado.
- `run_analysis` importa el módulo por dentro: hay que parchear el atributo del módulo, no
  `compute.compute`.
- Reemplazar un análisis exige `confirm=True` y **reutiliza el mismo id**.

---

## Pendiente

- Ver renderizado el mensaje de «recalcular» de un análisis sin máscara (Escenario 8). Está cubierto
  por test, pero no observado en pantalla.
- No se han medido corredores de más de 293 m. El crecimiento es aproximadamente lineal con la
  longitud, así que un eje de 1 km rondaría los 250 KB; el plan acepta ese riesgo residual
  explícitamente y no implementa tolerancia adaptativa (D40).
- El caso «el modelo no reconoce calzada en absoluto» (máscara vacía) solo se ha probado con datos
  sintéticos. No ha aparecido todavía un corredor real donde ocurra.
