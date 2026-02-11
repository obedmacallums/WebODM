# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WebODM is a web-based drone image processing platform built on Django + React. It connects to processing nodes (NodeODM) to generate orthophotos, 3D models, point clouds, and DEMs from aerial imagery.

**Development focus**: This is the complete WebODM project, but our work is focused exclusively on plugin development. We are building and modifying plugins — not changing the core WebODM application. All code changes should be within `coreplugins/` or `plugins/`. When developing plugins, look at existing `coreplugins/` for real-world examples of how to use the plugin API, and refer to `docs/src/content/docs/plugin-development-guide.md` for the full plugin development guide.

## Architecture

**Services** (Docker Compose):
- **webapp**: Django 2.2 + Gunicorn serving the web UI and REST API
- **worker**: Celery background tasks (image processing, result handling)
- **db**: PostgreSQL + PostGIS (geospatial data)
- **broker**: Redis (Celery message broker)

**Tech Stack**: Django REST Framework, React 16.4, Webpack 5, Leaflet, CesiumJS, Three.js, GDAL/PDAL for geospatial processing. Python 3.9, Node 20.

**Key directories**:
- `app/` — Main Django app: models, views, REST API (`app/api/`), plugin framework (`app/plugins/`), React components (`app/static/app/js/`)
- `webodm/` — Django project settings, URL routing
- `coreplugins/` — 23 built-in plugins (measure, dronedb, etc.)
- `worker/` — Celery task definitions
- `nodeodm/` — Processing node integration
- `nginx/` — Reverse proxy and SSL config

**Webpack entry points**: main, Console, Dashboard, MapView, ModelView — outputs to `app/static/app/bundles/`

**API**: REST endpoints at `/api/`, Swagger docs at `/swagger/`, admin at `/admin/`

## Common Commands

### Running (Docker-based)
```bash
./webodm.sh start                          # Production
./webodm.sh start --dev --dev-watch-plugins # Development (live reload)
./webodm.sh stop
./webodm.sh down                           # Remove containers
./webodm.sh rebuild
```

### Testing
```bash
./webodm.sh test                           # All tests (in Docker)
./webodm.sh test frontend                  # Jest only
./webodm.sh test backend                   # Django only
python manage.py test app.tests.test_name  # Single Django test module
npm run test                               # Jest frontend tests
```

### Building
```bash
webpack --mode production                  # Build frontend bundles
python manage.py collectstatic             # Collect static files
python manage.py rebuildplugins            # Rebuild all plugins
```

### Debugging
```bash
docker logs -f webapp                      # App logs
docker logs -f worker                      # Celery worker logs
docker exec -it webapp bash                # Shell into container
docker exec -it webapp python manage.py shell  # Django shell
```

## Plugin System

Plugins live in `coreplugins/` (built-in) or `plugins/` (user-installed). Each plugin is a Python package with a `PluginBase` subclass in `plugin.py` and a `manifest.json`.

Key extension points: `main_menu()`, `app_mount_points()`, `api_mount_points()`, `include_js_files()`, `build_jsx_components()`. Plugins can have their own `public/` directory with JSX/SCSS (webpack-compiled), `templates/`, `requirements.txt`, and global/user data stores.

Use `coreplugins/hello-world/` as a starter template. For medium complexity, reference `coreplugins/measure/`.

To rebuild a plugin after changes: `docker exec -it webapp python manage.py rebuildplugins`

## Environment Variables

Key settings (via `.env` or environment):
- `WO_HOST`, `WO_PORT` — Hostname and port (default: localhost:8000)
- `WO_DEBUG`, `WO_DEV` — Debug/dev mode flags
- `WO_BROKER` — Redis URL (default: redis://broker)
- `WO_SSL` — Enable SSL
- `WO_MEDIA_DIR`, `WO_DB_DIR` — Data storage paths

## Development Notes

- Backend changes with `--dev`: modify Python, then touch `app/boot.py` or `docker restart webapp`
- Frontend changes with `--dev-watch-plugins`: webpack auto-recompiles JSX/SCSS in plugin `public/` dirs
- Django settings in `webodm/settings.py`, overrides in `webodm/settings_override.py`
- Database migrations: `python manage.py makemigrations` / `python manage.py migrate`
- The project uses PostGIS — models use geospatial fields via `django.contrib.gis`
