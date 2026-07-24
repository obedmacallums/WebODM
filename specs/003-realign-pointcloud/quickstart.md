# Phase 1 — Guía de validación: corrección de la nube de puntos

**Feature**: `003-realign-pointcloud` | **Fecha**: 2026-07-23

Continúa la guía de 002 (`specs/002-realign-products/quickstart.md`); aquí solo se documenta lo
que agrega esta feature.

## Prerrequisitos

- Stack levantado (`./webodm.sh start`) con el plugin `realign` activo.
- Una tarea procesada que tenga **nube de puntos** (`georeferenced_model.laz` entre sus assets)
  y al menos un producto ráster 2D.
- Una realineación **ya aplicada en modo rígido** sobre esa tarea: pares de puntos marcados,
  "Usar escala" **destildado**, botón Aplicar pulsado y terminado.
- Herramienta externa para inspeccionar el LAZ descargado (CloudCompare, QGIS) o el CLI `pdal`
  dentro del contenedor.

## 1. Validación funcional (escenarios del spec)

| # | Escenario (spec) | Acción | Resultado esperado |
|---|---|---|---|
| 1 | US1-AS1 | Abrir el panel de realineación con la corrección aplicada en modo rígido | Aparece la sección de nube de puntos con la acción de generar habilitada |
| 2 | US1-AS2 | Pulsar generar | La generación arranca en segundo plano; el panel muestra progreso; la interfaz sigue navegable |
| 3 | US1-AS3 | Esperar a que termine | El panel informa que está lista y ofrece la descarga |
| 4 | US1-AS4 | Descargar el LAZ y abrirlo junto a la ortofoto corregida | Un rasgo común coincide en XY dentro del RMSE informado |
| 5 | US1-AS5 | Comparar elevaciones con el original (`pdal info --summary`) | `minz`/`maxz` idénticos; `max\|ΔZ\| = 0` |
| 6 | US1-AS6 | Comparar cantidad de puntos y atributos | Mismo `num_points`; `Intensity`, `Classification`, `GpsTime`, RGB preservados; misma `scale`, `dataformat_id` y SRS |
| 7 | US1-AS7 / FR-017 | Abrir el panel en una tarea **sin nube de puntos** | La acción no se ofrece; mensaje claro (`no_pointcloud`) |
| 8 | US2-AS1 / SC-009 | Con "Usar escala" **tildado** y aplicado, abrir el panel | La acción aparece bloqueada con la explicación y el camino a seguir (`scale_enabled`) |
| 9 | US2-AS2 | Destildar la escala, volver a Aplicar | La acción de nube queda disponible |
| 10 | US2-AS3 | Con una nube ya generada, tildar la escala y volver a Aplicar | Deja de ofrecerse la nube anterior, con explicación |
| 11 | FR-005 | Con la realineación solo **previsualizada** (sin aplicar) | La acción no está disponible (`not_applied`) |
| 12 | US3-AS1 / FR-011 | Con una generación en curso, recargar la página y reabrir el panel | El estado mostrado refleja el progreso real; el sondeo se reanuda |
| 13 | US3-AS2 / FR-012 | Con la nube lista, mover un par de puntos | Deja de ofrecerse como descargable; indica que hay que regenerarla |
| 14 | US3-AS3 / FR-013 | Pulsar **Revertir** | La nube corregida se elimina y el espacio se libera |
| 15 | US3-AS4 / FR-014 | Provocar un fallo (p. ej. sin espacio en disco) | Se informa la causa y **no** se ofrece descarga; no queda `.tmp.laz` |
| 16 | FR-015 | Pedir una segunda generación con una en curso | Se rechaza (`already_running`); no se lanza un segundo proceso |
| 17 | FR-016 | Como usuario de **solo lectura**: intentar generar, luego descargar un resultado existente | Generar bloqueado (403); descargar permitido |
| 18 | FR-018 | Leer el panel y abrir la vista 3D | El panel avisa que la corrección afecta solo al archivo descargable; el visor 3D sigue mostrando la nube original |

## 2. Verificación del resultado con `pdal`

Comparación directa entre el original y el corregido dentro del contenedor:

```bash
docker compose exec webapp bash -lc '
ORIG=<ruta del asset original>
CORR=<ruta del corregido en el dir. persistente del plugin>
for f in "$ORIG" "$CORR"; do
  pdal info --summary "$f" | python3 -c "
import json,sys
d=json.load(sys.stdin)[\"summary\"]; b=d[\"bounds\"]
print(d[\"num_points\"], b[\"minz\"], b[\"maxz\"], round(b[\"minx\"],3), round(b[\"miny\"],3))"
done'
```

**Esperado**: `num_points`, `minz` y `maxz` idénticos entre ambos; `minx`/`miny` desplazados
según la transformación aplicada. Referencia medida durante la investigación (D7) sobre la nube
real de 61.780.499 puntos: los tres primeros valores coincidieron exactamente y el XY se
desplazó ~4 m.

Cabecera preservada:

```bash
docker compose exec webapp bash -lc 'pdal info --metadata <corregido> | python3 -c "
import json,sys
m=json.load(sys.stdin)[\"metadata\"]
print({k:m.get(k) for k in [\"count\",\"scale_x\",\"scale_z\",\"offset_z\",\"dataformat_id\",\"minor_version\"]})"'
```

**Esperado**: `scale_x = scale_z = 0.001` (**no** `0.01`, que es el default de PDAL y sería una
pérdida de precisión silenciosa — ver D3), `offset_z` igual al del original, `dataformat_id` y
`minor_version` iguales a los del original.

## 3. Tests automatizados (en Docker)

```bash
docker compose exec webapp python manage.py test coreplugins/realign
```

> Usar la forma con `/`, no `coreplugins.realign`: `coreplugins` es un *namespace package* sin
> `__init__.py` y la forma con puntos rompe el descubrimiento de tests.

Cobertura que agrega esta feature (fixtures LAZ generados al vuelo con `readers.faux`, sin
binarios versionados — D10):

- transformación de un LAZ sintético: `num_points` idéntico, `max|ΔZ| == 0`, XY dentro de medio
  paso de cuantización respecto al valor calculado en Python;
- cabecera preservada (`scale_*`, `offset_z`, `dataformat_id`, `minor_version`, SRS);
- construcción de la matriz 4×4 a partir del `transform` persistido (fila Z en identidad);
- cálculo de los offsets XY desde el bbox de la cabecera y **rechazo previo** de una
  transformación que desbordaría el `int32` de LAS;
- las cuatro causas de inelegibilidad (`no_pointcloud`, `not_applied`, `scale_enabled`,
  `already_running`) devuelven 400 con su `reason`;
- permisos: generar exige `change_project`; descargar no;
- obsolescencia: tras cambiar los puntos, `stale == true` y la descarga responde 404;
- atomicidad: ante un fallo del pipeline no queda archivo final y sí se limpia el `.tmp.laz`.

## 4. Verificación del worker (Principio IV.3 — obligatoria)

La feature no agrega dependencias (nivel 0: el CLI `pdal` ya está en la imagen), pero el
Principio IV.3 exige demostrar con evidencia que el **worker** ejecuta el pipeline sin errores de
import ni de entorno:

```bash
docker compose exec webapp bash -lc 'pdal --version'
docker compose exec worker bash -lc 'pdal --version'
docker compose logs --tail=50 worker
```

Además, tras la primera generación real, confirmar en los logs del worker que el pipeline
terminó con `returncode 0` y que el archivo final existe en el directorio persistente
(compartido webapp↔worker).

## 5. Criterios de éxito medibles (spec)

| SC | Cómo se verifica | Referencia medida |
|---|---|---|
| SC-001 | Rasgo común nube ↔ ortofoto corregida, dentro del RMSE | escenario 4 |
| SC-002 | `max\|ΔZ\|` entre original y corregido | **0.0 exacto** (D2/D3) |
| SC-003 | `num_points` y atributos punto a punto | idénticos (D3) |
| SC-004 | md5 del asset original antes y después de todo el ciclo | sin cambios |
| SC-005 | Navegar durante la generación; consultar estado sin recargar | escenarios 2 y 12 |
| SC-006 | Tiempo total para ~250 MB | **48 s** para 268 MB / 61,7 M de puntos (D7) |
| SC-007 | Tras un fallo, no hay descarga ofrecida ni archivo final | escenario 15 |
| SC-008 | Tras cambiar puntos o revertir, no se ofrece la nube previa | escenarios 13 y 14 |
| SC-009 | Mensaje explicativo con la escala habilitada | escenario 8 |
