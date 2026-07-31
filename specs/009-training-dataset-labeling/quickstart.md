# Quickstart — Validación de `009-training-dataset-labeling`

Guía para comprobar que la feature funciona de punta a punta. Cubre US1 + US2, que es el alcance de
esta entrega.

## Requisitos previos

Stack levantado (`webapp`, `worker`, `db`, `broker`) y al menos una tarea con ortofoto procesada. La
de referencia es **Mina La Coipa**: 1087 × 1402 m, GSD 6,35 cm/px, 616 teselas a 10 cm/px.

```bash
docker compose ps
```

## Aviso que evita perder datos reales

**Nunca** uses `./run_tests_in_docker.sh`. Hace `docker compose down -v`, que borra los volúmenes y
con ellos las tareas reales de la instancia. Los tests se corren contra el stack vivo:

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests
```

## Suite completa

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests
```

**Esperado**: `OK`, y el total de la suite sube exactamente en el número de tests nuevos.

**Comprobación que no es opcional**: `coreplugins/` es un *namespace package* sin `__init__.py`. Un
módulo de test que no se reexporte en `tests/__init__.py` **no se ejecuta y la suite sigue en verde**.
Pasó en `008`. Verifica que cada módulo corre por su nombre:

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests.test_rasterize
```

## Escenario 1 — Crear un dataset y etiquetar (US1)

1. Menú principal → entrada del plugin → crear dataset con clases `background` (0) y `road` (1),
   resolución 10 cm/px, añadiendo la tarea de la mina.
2. Abrir la tarea, abrir el panel del plugin.
3. Con la clase `background` seleccionada, dibujar un polígono grande sobre toda la zona de trabajo.
4. Cambiar a `road` y pintar con el pincel sobre una pista, con radio ~3 m.
5. Recargar la página.

**Esperado**: las etiquetas siguen ahí, con su clase y su color. El trazo de pincel se dibuja con el
grosor que le corresponde sobre el terreno, y **no cambia de anchura aparente al hacer zoom**
(FR-010).

**El caso que más fácil se rompe**: borrar con el borrador debe dejar la zona **sin etiquetar**, no
marcada como fondo. La diferencia no se ve en el mapa; se ve en la máscara exportada, donde debe
salir 255 y no 0. Es el Escenario 3.

## Escenario 2 — La precedencia por orden

Dibujar un polígono de `road` y encima uno de `background` que lo tape parcialmente.

**Esperado**: en la zona solapada gana el último dibujado (FR-012). Es lo que hace barato pintar el
fondo: un polígono enorme de clase 0 y encima los caminos.

## Escenario 3 — Exportar y verificar la máscara (US2)

Lanzar la exportación desde la página del dataset y descargar el paquete.

```bash
unzip -l dataset-*.zip | head -20
python3 -c "
import json, zipfile
z = zipfile.ZipFile('dataset-....zip')
m = json.loads(z.read('manifest.json'))
print('esquema     :', m['schema_version'])
print('resolucion  :', m['resolution_cm_px'], 'cm/px')
print('tesela      :', m['tile_size_px'], 'px')
print('ignore_index:', m['ignore_index'])
print('clases      :', [(c['index'], c['name']) for c in m['classes']])
print('teselas     :', len(m['tiles']))
img = sum(1 for n in z.namelist() if n.startswith('images/'))
lab = sum(1 for n in z.namelist() if n.startswith('labels/'))
print('imagenes    :', img, '| mascaras:', lab, '| emparejadas:', img == lab == len(m['tiles']))
"
```

**Esperado**: `schema_version: 1`, `ignore_index: 255`, tantas imágenes como máscaras como entradas
en `tiles`.

Verificar los valores de una máscara:

```bash
python3 -c "
import zipfile, io, numpy as np
from PIL import Image
z = zipfile.ZipFile('dataset-....zip')
name = [n for n in z.namelist() if n.startswith('labels/')][0]
a = np.array(Image.open(io.BytesIO(z.read(name))))
print(name, a.shape, a.dtype)
vals, counts = np.unique(a, return_counts=True)
print('valores:', dict(zip(vals.tolist(), counts.tolist())))
"
```

**Esperado**: valores dentro de `{0, 1, 255}` y ninguno más. La presencia del **255** es la prueba de
FR-026: lo no etiquetado no se disfrazó de fondo.

**Esperado también**: una tesela de 512 px a 10 cm/px cubre 51,2 m de terreno; la imagen es RGB de 3
canales (el alfa de la ortofoto no se exporta) y la máscara es de un solo canal.

## Escenario 4 — Verificación del worker (Principio IV, NO NEGOCIABLE)

Es el riesgo principal del plan y **ningún test de la suite lo cubre**: `run_function_async`
recompila la función por código fuente en un espacio de nombres vacío, así que un import mal colocado
falla solo en ejecución real.

```bash
docker compose restart webapp worker
# lanzar una exportación desde la interfaz, esperar a que termine
docker compose logs worker --since 10m | grep -cE "NameError|ImportError|AttributeError|Traceback"
```

**Esperado**: `0`. Y la exportación en estado `completed` con `error: null`.

Sin esta evidencia, la feature no está completa. No vale el reporte de la suite.

## Escenario 5 — Coste de exportar un dataset grande

No se ha medido todavía (riesgo abierto en `research.md`). Medir sobre la mina:

```bash
docker compose logs worker --since 15m | grep -iE "export|progress" | tail -20
```

**A registrar**: tiempo total, número de teselas que superaron los filtros frente a las 616 de la
rejilla completa, tamaño del `.zip`, y memoria máxima del worker. La aritmética dice que la memoria
está acotada porque se rasteriza tesela a tesela; el tiempo está por medir.

## Escenario 6 — La tarea desaparece

Quitar del dataset la única tarea, o borrar la tarea desde WebODM.

**Esperado**: el dataset **sigue abriéndose**, marca esa tarea como no disponible y la excluye de la
exportación en vez de fallar. Es lo que distingue este plugin de `road` y `annotations`, donde el
borrado en cascada por tarea es la respuesta correcta y aquí no lo es.

## Escenario 7 — No regresión

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.road.tests
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.annotations.tests
```

**Esperado**: ambas en `OK`, sin cambios. FR-036 exige que esta feature no altere nada existente, y
el plugin nuevo no toca a ninguno de los dos.
