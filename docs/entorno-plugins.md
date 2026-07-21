# Entorno disponible para plugins

Inventario de librerías y herramientas disponibles en los contenedores de WebODM,
relevante para planificar plugins. Los contenedores **webapp** y **worker** comparten la
misma imagen (`webodm/webodm_webapp`, Ubuntu 22.04, Python 3.9), así que todo lo listado
aquí está disponible en ambos.

**Fuentes**: `Dockerfile` y `requirements.txt`.
**Última revisión**: 2026-07-21 (master, tras commit `c7c7ce0e`). Reverificar tras merges
de upstream que toquen esos dos archivos.

## Nivel sistema (CLI y librerías nativas)

| Herramienta | Versión | Notas |
|---|---|---|
| GDAL | 3.4.x (paquete Ubuntu 22.04) | CLI completo (`gdal_translate`, `gdalwarp`, `gdaldem`, `ogr2ogr`…) y bindings Python `gdal[numpy]` instalados con la versión exacta de la lib: `from osgeo import gdal, ogr, osr` |
| PDAL | 2.3 (paquete Ubuntu 22.04) | **Solo el CLI `pdal`** — los bindings `python-pdal` NO están instalados. Desde un plugin: invocar por `subprocess` con pipelines JSON, o declarar bindings como dependencia |
| Entwine | build propio (branch `290` del fork de WebODM) | `/usr/bin/entwine`; indexa nubes de puntos a EPT (alimenta el visor Potree) |
| PROJ | libproj de Ubuntu 22.04 | `PROJ_LIB=/usr/share/proj` ya configurado |
| exiftool | paquete Ubuntu 22.04 | lectura/escritura de metadatos EXIF |
| ffmpeg | copiado desde la etapa de build | procesamiento de video |

## PostGIS y GeoDjango

La base de datos (`webodm/webodm_db`) es Postgres+PostGIS y Django usa el backend
`django.contrib.gis.db.backends.postgis` (`webodm/settings.py`). Disponible para plugins:

- `GEOSGeometry`, `GeometryField` y consultas espaciales del ORM (el core ya los usa en
  `app/models/task.py`).
- GEOS accesible vía GeoDjango sin dependencias adicionales.

## Nivel Python (`requirements.txt`)

| Paquete | Versión | Uso típico |
|---|---|---|
| rasterio | 1.3.10 | lectura/escritura de rásteres |
| rio-tiler | 2.1.2 (build custom con morecantile 3.2.0) | generación de tiles |
| rio-color | 1.0.4 | corrección de color de rásteres |
| numpy | 1.26.2 | arrays |
| scipy | 1.11.3 | procesamiento científico |
| geodeep | 0.9.12 | inferencia con IA sobre rásteres geoespaciales (detección de objetos) |
| pillow | 11.3.0 | imágenes |
| piexif | 1.1.3 | EXIF |

## No disponible (declarar en el plugin si se necesita)

Ninguna de estas está en la imagen Linux; todas son pip-instalables como wheels, así que
entran por el `requirements.txt` del plugin (Principio IV de la constitución, paso 1),
sin rebuild de imagen:

- **shapely** — en `requirements.txt` global solo está pineada para Windows
  (`sys_platform == "win32"`); en Linux no está garantizada. Alternativa sin dependencia:
  GEOS vía GeoDjango.
- **python-pdal**, **laspy** — manejo de LAZ/LAS desde Python. Alternativa sin
  dependencia: CLI `pdal` por `subprocess`.
- **geopandas**, **fiona**, **pyproj** — los wheels incluyen sus libs nativas.
- **opencv** (`opencv-python-headless`).

## Cómo agregar dependencias nuevas

Seguir la escalera del Principio IV de la constitución
(`.specify/memory/constitution.md`):

1. Python puro → `requirements.txt` del plugin (se instala solo, compartido con workers).
2. Dependencias de sistema → bloque `# BEGIN/END FORK PLUGIN DEPS` en el `Dockerfile`.
3. Siempre: verificar con evidencia que el worker arranca y ejecuta el plugin sin errores
   de import antes de dar la feature por completa.

## Cómo correr los tests

**Regla**: la verificación oficial de tests se ejecuta **dentro de Docker**. En la
máquina de desarrollo local (Mac Apple Silicon) solo se corren tests ligeros que no
requieran dependencias nativas — nunca se instalan librerías geoespaciales (GDAL, PDAL,
rasterio…) en el host para poder ejecutar un test: ese test pertenece a Docker.

- **Suite completa (oficial)**: `./run_tests_in_docker.sh [args]` — construye la imagen
  con `TEST_BUILD=ON`, levanta el stack de compose, ejecuta los tests dentro del
  contenedor webapp y limpia todo al salir (`docker compose down -v`). Los argumentos se
  pasan a `webodm.sh test`.
- **Con el stack ya levantado**:
  `docker compose exec webapp /webodm/webodm.sh test [frontend|backend] [args]`
  - Backend de un plugin específico: `... test backend coreplugins.<nombre>.tests`
  - Frontend: `... test frontend` (genera mocks de UI con Django y corre jest)
- **Local en el Mac (solo tests ligeros)**: `npm run qtest` (jest puro, sin Django) o
  tests unitarios de Python puro sin dependencias del stack.

Esta regla complementa el Principio IV de la constitución: la evidencia de verificación
(tests y arranque de workers) siempre proviene de los contenedores, que son el entorno
real de ejecución.
