# Quickstart — validación de la feature 004

**Feature**: `004-polyline-annotations` | **Fecha**: 2026-07-26

Guía para levantar, probar y validar el plugin. Los detalles de esquema están en `data-model.md` y
`contracts/`; aquí solo van los comandos y lo que debe observarse.

## 0. Prerrequisitos

- Stack en marcha: `docker compose ps` debe mostrar `webapp`, `worker`, `db` y `broker` arriba.
- Una tarea procesada **con DSM** para las historias 2 a 5. En el entorno de referencia:
  proyecto 10, tarea `6e965174-…` (DSM y DTM, EPSG:32719, 0,0222 m/px).
- Una tarea **sin DEM** (solo ortofoto) para validar la US1 y el escenario 5 de la US2.
- Nada se instala en el host: toda validación con dependencias nativas corre dentro de Docker
  (`docs/entorno-plugins.md`).

## 1. Desplegar el plugin sin reconstruir la imagen

`coreplugins/` va horneado en la imagen, así que un plugin nuevo no aparece hasta copiarlo:

```bash
# Evita el anidado <name>/<name>/ que produce docker cp cuando el destino existe
docker compose exec webapp rm -rf /webodm/coreplugins/annotations
docker compose cp ./coreplugins/annotations webapp:/webodm/coreplugins/annotations

# Carga el plugin y compila el JSX (init_plugins -> build_plugins)
docker compose restart webapp
docker compose logs webapp | grep -i "Registered .*annotations"
```

Debe aparecer `INFO Registered [coreplugins.annotations.plugin]` y, tras el arranque,
`coreplugins/annotations/public/build/Annotations.js` dentro del contenedor.

> **Requisito del cargador**: `coreplugins/annotations/__init__.py` tiene que contener
> `from .plugin import *`. El core hace `getattr(package, "Plugin")`; con un `__init__.py` vacío la
> instanciación falla con `module '…' has no attribute 'Plugin'`. Verificado: los `__init__.py` de
> `viewshed` y `realign` son exactamente esa línea.

El receptor de `task_removed` corre allí donde se borra la tarea, así que para validar el borrado en
cascada hay que copiar el plugin **también al worker**:

```bash
docker compose exec worker rm -rf /webodm/coreplugins/annotations
docker compose cp ./coreplugins/annotations worker:/webodm/coreplugins/annotations
docker compose restart worker
```

Todo esto es efímero: para persistirlo hay que commitear el plugin y reconstruir la imagen.

## 2. Tests automatizados

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.annotations.tests
```

Suite completa del repo (más lento, para antes de dar la feature por cerrada):

```bash
./run_tests_in_docker.sh
```

Los tests siguen el patrón de `coreplugins/realign/tests.py`: `BootTestCase`, `APIClient`,
`assign_perm` de guardian y tareas construidas con `available_assets` / `dsm_extent` / `epsg`. Los
DEM de prueba se generan al vuelo con `rasterio` dentro del contenedor —incluyendo uno con un parche
de `nodata`— y no se versiona ningún GeoTIFF en el repo.

Cobertura mínima esperada antes de cerrar:

| Área | Qué debe quedar cubierto |
|---|---|
| Validación de geometría | Menos de 2 vértices, vértices coincidentes, exceso de vértices (FR-002, FR-023) |
| Modos | Creación en ambos modos, `elevate`, `flatten`, y rechazo de `draped` sin DEM (FR-007 a FR-011) |
| Cobertura | Vértice fuera del ráster y hueco de `nodata`: respuesta `422`, `missing_ranges` correcto y **nada persistido** (FR-021, FR-022) |
| Paso | `step` por defecto, fuera de rango, y que `surface_length` cambia con el paso (FR-014, FR-015) |
| Permisos | Lectura con `view_project`, escritura sin `change_project` → `404` (FR-025) |
| Persistencia | Documento superviviente, borrado en cascada por `task_removed` (FR-024, FR-027) |
| Exportación | GeoJSON con `LineString` de 2 y 3 ordenadas y propiedades completas (FR-032 a FR-035) |
| Contrato | `contract_version`, `get_polylines`, `get_densified`, `elevate` (FR-036 a FR-040) |

## 3. Validación manual por historia

**US1 — trazar y conservar.** Abrir el mapa 2D de una tarea, trazar una polilínea de tres vértices,
nombrarla. Debe aparecer bajo *Annotations* en el panel de capas. Recargar: sigue ahí. Entrar con
otro usuario con acceso al proyecto: la ve. Intentar cerrar un trazado de un solo vértice: se
rechaza con explicación. Abrir la vista de proyecto con varias tareas: las líneas se ven agrupadas
por tarea y la herramienta de trazado **no** se ofrece (FR-031).

**US2 — elevación.** Con la tarea que tiene DSM y DTM, crear una línea en modo sobre el terreno; debe
poder elegirse el modelo. Comprobar que se muestran longitud sobre el terreno, longitud en planta,
desnivel acumulado **y el paso empleado**. Cambiar el paso y observar que la longitud sobre el
terreno cambia — es el comportamiento esperado, medido en `research.md` D4, no un error. Con la tarea
sin DEM, el modo no se ofrece y se explica por qué.

**US3 — exportar.** Descargar el GeoJSON con las dos variantes de `geometry`. Abrir en QGIS: se carga
sin errores, las líneas caen en su sitio, las elevadas conservan Z. Repetir desde el botón de
descarga del panel *Annotations* del propio WebODM: mismo resultado (FR-032).

**US4 — editar.** Arrastrar un vértice a una zona de cota distinta: las magnitudes se recalculan.
Insertar y borrar vértices. Renombrar y borrar desde el panel de capas del core —esos botones solo
funcionan si los manejadores están registrados (`contracts/plugin-contract.md` §2.2)—. Convertir una
plana a elevada y volver: el trazado en planta no cambia.

**US5 — consumo.** Desde el shell de Django, ejercitar el contrato sin pasar por la interfaz:

```bash
docker compose exec webapp /webodm/webodm.sh shell
```

```python
from app.plugins.functions import get_plugin_by_name
p = get_plugin_by_name("annotations")
print(p.contract_version())
lines = p.get_polylines("<task_id>")
print([(l["name"], l["mode"]) for l in lines])
print(p.get_densified("<task_id>", lines[0]["id"])["sample_count"])
```

## 4. Comprobaciones de la Constitución

**Principio IV — dependencias (nivel 0).** La feature no añade ninguna dependencia: ni
`requirements.txt` de plugin, ni `Dockerfile`, ni paquetes npm. Comprobable:

```bash
git diff --stat master -- requirements.txt Dockerfile docker-compose.yml   # debe salir vacío
ls coreplugins/annotations/requirements.txt 2>/dev/null                    # no debe existir
ls coreplugins/annotations/public/package.json 2>/dev/null                 # no debe existir
```

Verificación de que lo que se usa ya está en la imagen, en **ambos** contenedores:

```bash
for c in webapp worker; do
  docker compose exec -T $c python -c "import rasterio, numpy; from rasterio.warp import transform; print('$c OK', rasterio.__version__)"
done
```

**Principio I — solo plugins.** Ningún archivo del core tocado:

```bash
git diff --name-only master -- app/ webodm/ worker/ nodeodm/ nginx/   # debe salir vacío
```

**Deshabilitación limpia (SC-010).** Desactivar el plugin desde *Administration → Plugins* y
recargar el mapa 2D: debe seguir funcionando, con el panel de capas intacto y sin errores en la
consola del navegador. Las polilíneas dejan de verse; el documento persistido no se borra.
