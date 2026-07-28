# Quickstart: validar el plugin `road`

**Feature**: 005-road-metrics | **Contrato**: [contracts/rest-api.md](./contracts/rest-api.md) |
**Modelo**: [data-model.md](./data-model.md)

Guía para desplegar el plugin en el entorno de desarrollo y comprobar que la feature funciona de
punta a punta. No contiene código de implementación.

## Prerrequisitos

- Stack de WebODM levantado (`docker compose up -d`) y una tarea procesada **con DSM o DTM**.
- Para la vía cómoda del eje, el plugin `annotations` habilitado y una polilínea **2D** trazada a lo
  largo de un camino de esa tarea.
- Para la variante realineada, una realineación aplicada con `realign` sobre esa misma tarea.
- Sin dependencias nuevas: `rasterio`, `numpy` y GDAL ya están en la imagen
  ([docs/entorno-plugins.md](../../docs/entorno-plugins.md)).

## Desplegar sin reconstruir la imagen

`coreplugins/` va horneado en la imagen, así que un plugin nuevo no aparece por el bind mount:

```bash
docker compose cp coreplugins/road webapp:/webodm/coreplugins/road
docker compose restart webapp
```

Comprobar que el plugin carga y que su `__init__.py` existe (sin él, el paquete no se importa y el
plugin desaparece del listado sin error visible):

```bash
docker compose exec webapp python -c "from app.plugins.functions import get_plugin_by_name; \
  p = get_plugin_by_name('road'); print(p, p.is_persistent() if p else None)"
```

Para que el worker vea el plugin —imprescindible, porque el cálculo corre allí— hay que copiarlo
también a su contenedor y reiniciarlo:

```bash
docker compose cp coreplugins/road worker:/webodm/coreplugins/road
docker compose restart worker
```

## Tests

Suite del plugin (backend + los tests de frontend que la suite de Django lanza, siguiendo el patrón
que `annotations` estableció):

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.road.tests
```

Suite completa, que es la verificación oficial antes de dar la feature por cerrada:

```bash
./run_tests_in_docker.sh
```

Como esta feature añade un contrato a `realign`, su suite también debe seguir en verde:

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.realign.tests
```

## Verificación del worker (Principio IV, no negociable)

La feature no añade dependencias, pero sí una función nueva ejecutada por
`run_function_async`, que reejecuta el código fuente en un namespace vacío: un import relativo o una
referencia a un global del módulo solo falla allí, en tiempo de ejecución. Lanzar un análisis real y
leer el log del worker es la única prueba que lo cubre:

```bash
docker compose logs -f worker | grep -i "road\|Traceback"
```

Debe verse el análisis completarse sin `ImportError` ni `NameError`.

## Escenarios de validación manual

Con la tarea abierta en la vista 2D y el panel del plugin desplegado.

### 1. Análisis básico desde una anotación (US1)

1. Elegir la polilínea 2D del camino y dejar los parámetros por defecto.
2. Lanzar. **Esperado**: barra de progreso que avanza, botón de cancelar activo, interfaz utilizable
   mientras tanto.
3. Al terminar: el camino aparece dividido en tramos de 5 m coloreados en verde, amarillo y rojo.
4. Clic sobre un tramo: progresiva, longitud real, cota, pendiente en % y grados, ancho, distancias
   a cada borde y pendiente transversal.
5. Contrastar el ancho de un par de tramos con una medición manual sobre el DSM en QGIS: la
   diferencia debe quedar por debajo de 0,5 m (SC-003).

### 2. Tramos sin dato (US1, FR-021)

Analizar un camino que en algún punto salga de la cobertura del vuelo o discurra a nivel del terreno
circundante. **Esperado**: esos tramos con estilo distinto de los tres colores, sin ancho, y con el
motivo por lado —`sin quiebre` frente a `sin datos de elevación`— visible al consultarlos.

### 3. Cancelación y exclusión mutua (FR-034, FR-036)

1. Lanzar sobre un camino largo y cancelar a media ejecución. **Esperado**: se detiene en segundos,
   lo dice, y no queda análisis a medias en la lista.
2. Lanzar otro análisis mientras uno corre. **Esperado**: no se inicia, avisa de que ya hay uno en
   curso y ofrece cancelarlo (`409 analysis_running`).

### 4. Exportación (US2)

Descargar CSV y GeoJSON. **Esperado**: el CSV abre en una hoja de cálculo con una fila por tramo y
las celdas sin dato **vacías**, no a cero; el GeoJSON abre en QGIS mostrando tramos, transversales y
puntos de borde, y en ambos aparecen los parámetros del análisis.

### 5. Semáforo y persistencia de umbrales (US3, FR-029, FR-030)

Mover los dos umbrales. **Esperado**: recoloreado inmediato, sin barra de progreso ni nueva llamada
de cálculo. Recargar la página: el camino conserva los colores elegidos.

### 6. Recálculo que pisa (FR-037)

Volver a analizar el mismo eje con otro `break_threshold`. **Esperado**: aviso de que sustituirá el
resultado anterior; al confirmar, la lista sigue teniendo un único análisis para ese eje, con los
parámetros nuevos y, previsiblemente, otro número de tramos con borde detectado.

### 7. Eje subido por archivo (US4)

Subir un GeoJSON con un `LineString` 2D sobre el mismo camino. **Esperado**: mismo tipo de
resultado. Probar además los rechazos, cada uno con su causa concreta: un polígono, un archivo con
dos líneas, una línea fuera de la zona del vuelo, y un GeoJSON con un `crs` declarado distinto.

### 8. Degradación sin plugins hermanos (FR-005, FR-008)

Deshabilitar `annotations` desde la administración y recargar. **Esperado**: el panel sigue
abriéndose, explica que no hay anotaciones que elegir y deja subir un archivo. Con `realign`
deshabilitado o sin realineación aplicada, la variante realineada no aparece como opción.

### 9. Obsolescencia (FR-038)

Reprocesar la tarea, o tocar la marca de tiempo del DEM, y volver al panel. **Esperado**: el
análisis se muestra como desactualizado, sigue consultable y exportable, y recalcularlo es decisión
del usuario.

### 10. Deshabilitar el plugin (FR-041)

Deshabilitar `road`. **Esperado**: sus capas desaparecen del mapa, `annotations` y `realign` siguen
funcionando con normalidad, y ninguna otra parte de la aplicación se rompe.
