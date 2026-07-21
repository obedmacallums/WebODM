# Fork de WebODM — instrucciones de proyecto

Este repositorio es un fork de OpenDroneMap/WebODM cuyo único objetivo es desarrollar
**plugins personalizados**. El core de upstream no se modifica.

Documentos que rigen el trabajo aquí — leerlos antes de planificar o implementar:

- **Constitución** (principios obligatorios, los valida el Constitution Check de
  Spec Kit): `.specify/memory/constitution.md` — desarrollo solo-plugins, mergeabilidad
  con upstream, convenciones de plugin, escalera de dependencias.
- **Entorno y tests**: `docs/entorno-plugins.md` — inventario de librerías geoespaciales
  disponibles en la imagen Docker (GDAL, PDAL CLI, Entwine, PostGIS/GeoDjango, rasterio…)
  y cómo correr los tests.
- **Feature activa de Spec Kit**: ver `.specify/feature.json` → directorio en `specs/`.

Reglas rápidas:

- Los tests oficiales se corren **en Docker** (`./run_tests_in_docker.sh` o
  `docker compose exec webapp /webodm/webodm.sh test …`). En el Mac local solo tests
  ligeros sin dependencias nativas; nunca instalar GDAL/PDAL/rasterio en el host.
- Dependencias nuevas de plugins: seguir la escalera del Principio IV de la constitución
  (requirements.txt del plugin → Dockerfile del fork → verificación de workers).
