# Guía de desarrollo de plugins para WebODM

## Requisitos previos

- Docker y Docker Compose instalados
- Un editor de código (VS Code, etc.)
- Git

## Inicio rápido

### 1. Iniciar WebODM en modo desarrollo

```bash
cd ~/Documents/Projects/WebODM
./webodm.sh start --dev --dev-watch-plugins
```

Flags:
- `--dev`: Monta tu carpeta local dentro del contenedor (los cambios en tu PC se reflejan adentro)
- `--dev-watch-plugins`: Webpack recompila automáticamente los assets JS/CSS/JSX

### 2. Crear tu plugin

Copia el plugin de ejemplo como base:

```bash
cp -r coreplugins/hello-world coreplugins/mi-plugin
```

### 3. Acceder a WebODM

Abre `http://localhost:8000` en tu navegador.

## Estructura de un plugin

```
mi-plugin/
├── __init__.py          # Exporta la clase Plugin
├── plugin.py            # Clase principal (extiende PluginBase)
├── manifest.json        # Metadatos del plugin
├── disabled             # (Opcional) Archivo vacío = deshabilitado por defecto
├── requirements.txt     # (Opcional) Dependencias Python
├── public/              # (Opcional) Assets estáticos
│   ├── main.js          #   JavaScript
│   ├── app.jsx          #   Componente React
│   ├── app.scss         #   Estilos
│   ├── package.json     #   Dependencias npm
│   └── build/           #   Generado por webpack
└── templates/           # (Opcional) Templates Django
    └── home.html
```

### Archivos requeridos

**`manifest.json`**

```json
{
    "name": "Mi Plugin",
    "webodmMinVersion": "0.7.1",
    "description": "Descripción de mi plugin",
    "version": "0.1.0",
    "author": "Tu Nombre",
    "email": "tu@email.com",
    "repository": "",
    "tags": ["custom"],
    "homepage": "",
    "experimental": true,
    "deprecated": false
}
```

**`__init__.py`**

```python
from .plugin import *
```

**`plugin.py`**

```python
from app.plugins import PluginBase, Menu, MountPoint
from django.shortcuts import render


class Plugin(PluginBase):

    def main_menu(self):
        return [Menu("Mi Plugin", self.public_url(""), "fa fa-puzzle-piece fa-fw")]

    def app_mount_points(self):
        def home(request):
            return render(request, self.template_path("home.html"), {
                'title': 'Mi Plugin'
            })
        return [MountPoint('$', home)]
```

## Cómo ver los cambios

### Templates HTML

Edita el archivo, refresca el navegador. Cambio inmediato.

### JavaScript / CSS

Con `--dev-watch-plugins` activo, webpack detecta cambios y recompila automáticamente (1-2 segundos). Refresca el navegador.

### JSX (React)

Webpack watch recompila automáticamente (2-5 segundos). Refresca el navegador.

### Código Python (`plugin.py`)

Django no detecta cambios en plugins automáticamente. Usa uno de estos métodos:

**Método 1 — Truco del `boot.py` (sin reiniciar):**

1. Abre `app/boot.py` en tu editor
2. Agrega una línea en blanco al final
3. Guarda el archivo
4. Quita la línea en blanco
5. Guarda de nuevo
6. Refresca el navegador

**Método 2 — Reiniciar el contenedor web:**

```bash
docker restart webapp
```

**Método 3 — Habilitar/deshabilitar el plugin:**

Ve a Admin → Plugins → tu plugin y desmarca/marca la casilla de habilitado.

## Logs y depuración

```bash
# Logs de la webapp (Django) en tiempo real
docker logs -f webapp

# Logs del worker (Celery)
docker logs -f worker

# Logs de todos los servicios
docker compose logs -f
```

Los errores de tu plugin aparecen en los logs de `webapp`.

### Shell interactiva

```bash
# Shell de Django (probar código Python)
docker exec -it webapp python manage.py shell

# Bash dentro del contenedor
docker exec -it webapp bash
```

## Funcionalidades disponibles para plugins

### Menú lateral

```python
def main_menu(self):
    return [Menu("Label", self.public_url(""), "fa fa-icon fa-fw")]
```

### Vistas web (`/plugins/mi-plugin/...`)

```python
def app_mount_points(self):
    def mi_vista(request):
        return render(request, self.template_path("pagina.html"), {'data': 123})
    return [MountPoint('ruta/$', mi_vista)]
```

### API REST (`/api/plugins/mi-plugin/...`)

```python
def api_mount_points(self):
    from rest_framework.response import Response
    from rest_framework.views import APIView

    class MiAPI(APIView):
        def get(self, request):
            return Response({"mensaje": "Hola!"})

    return [MountPoint('endpoint/?$', MiAPI.as_view())]
```

### Archivos JS/CSS

```python
def include_js_files(self):
    return ['main.js']

def include_css_files(self):
    return ['style.css']
```

### Componentes React (JSX)

```python
def build_jsx_components(self):
    return ['app.jsx']
```

### Almacenamiento de datos

```python
# Global (compartido entre usuarios)
ds = self.get_global_data_store()
ds.set_string("clave", "valor")
valor = ds.get_string("clave", default="")
ds.set_json("config", {"a": 1})

# Por usuario
uds = self.get_user_data_store(request.user)
uds.set_int("contador", 42)
```

### Señales (eventos del servidor)

```python
from django.dispatch import receiver
from app.plugins.signals import task_completed, task_failed

@receiver(task_completed)
def on_task_complete(sender, task_id, **kwargs):
    print(f"Tarea {task_id} completada!")
```

Señales disponibles: `task_completed`, `task_failed`, `task_removing`, `task_removed`, `task_duplicated`, `processing_node_removed`

### Tareas asíncronas (Celery)

```python
from app.plugins.worker import run_function_async

def operacion_larga(datos, progress_callback=None):
    import time  # imports DENTRO de la función
    time.sleep(10)
    progress_callback("Procesando...", 50)
    return {'resultado': 'listo'}

task_id = run_function_async(operacion_larga, datos="input").task_id
```

### Dependencias Python aisladas

Crea un `requirements.txt` en la raíz del plugin e importa con el context manager:

```python
with self.python_imports():
    import mi_paquete
```

### Hooks del lado cliente (JavaScript)

```javascript
PluginsAPI.Map.willAddControls([
    '/plugins/mi-plugin/build/app.js'
], function(args) {
    // Agregar controles al mapa
});
```

## Reconstruir plugins

Si los assets se corrompen o quieres un build limpio:

```bash
docker exec -it webapp python manage.py rebuildplugins
```

## Distribución

### Como archivo .zip

```bash
cd coreplugins/
zip -r mi-plugin.zip mi-plugin/
```

Los usuarios lo instalan desde Admin → Plugins → Load Plugin (.zip).

### Como Pull Request

Agrega tu plugin a `coreplugins/` y haz PR al repositorio de WebODM.

## Plugins de referencia

Revisa estos plugins existentes como ejemplo:

| Plugin | Ubicación | Complejidad |
|---|---|---|
| `hello-world` | `coreplugins/hello-world/` | Básica — menú, vista, JSX |
| `measure` | `coreplugins/measure/` | Media — API, tareas async |
| `dronedb` | `coreplugins/dronedb/` | Alta — múltiples vistas, formularios, almacenamiento |

## Referencia rápida de comandos

```bash
# Iniciar en modo desarrollo
./webodm.sh start --dev --dev-watch-plugins

# Detener
./webodm.sh stop

# Reiniciar solo la webapp
docker restart webapp

# Ver logs
docker logs -f webapp

# Shell Django
docker exec -it webapp python manage.py shell

# Reconstruir plugins
docker exec -it webapp python manage.py rebuildplugins

# Reiniciar todo
./webodm.sh restart
```
