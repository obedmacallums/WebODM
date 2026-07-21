<!--
Sync Impact Report
==================
- Version change: (plantilla sin ratificar) → 1.0.0
- Modified principles: n/a (adopción inicial)
- Added sections:
  - Core Principles I–IV (Desarrollo solo-plugins; Compatibilidad con upstream;
    Convenciones de plugin; Gestión de dependencias de plugins)
  - Restricciones de infraestructura
  - Flujo de desarrollo
  - Governance
- Removed sections: n/a
- Templates:
  - .specify/templates/plan-template.md ✅ compatible (Constitution Check se deriva
    dinámicamente de este archivo; sin cambios necesarios)
  - .specify/templates/spec-template.md ✅ compatible (sin secciones obligatorias nuevas)
  - .specify/templates/tasks-template.md ✅ compatible (las convenciones de rutas se
    ajustan por plan.md; los planes deben usar coreplugins/<nombre>/ como estructura)
  - .claude/skills/speckit-* ✅ referencias genéricas a .specify/memory/constitution.md
- Follow-up TODOs: ninguno
-->

# Constitución del Fork de WebODM

Este repositorio es un fork de [OpenDroneMap/WebODM](https://github.com/OpenDroneMap/WebODM).
Su único propósito es desarrollar plugins personalizados sobre el framework de plugins de
WebODM, manteniendo el core sincronizable con upstream.

## Core Principles

### I. Desarrollo solo-plugins (NO NEGOCIABLE)

Toda funcionalidad nueva DEBE implementarse como un plugin que extiende `PluginBase`
(`app/plugins/plugin_base.py`). Está prohibido modificar el código del core upstream —
`app/`, `webodm/`, `worker/`, `nodeodm/`, `nginx/` y los scripts raíz — salvo que sea
estrictamente necesario para habilitar un plugin. Cuando una excepción sea inevitable, el
cambio DEBE ser mínimo, quedar registrado en la sección Complexity Tracking del plan de la
feature con su justificación, y diseñarse para minimizar conflictos de merge.

**Razón**: el valor del fork está en sus plugins; cada línea tocada en el core es deuda de
merge frente a upstream y riesgo de regresión al sincronizar.

### II. Compatibilidad con upstream

La rama `master` DEBE mantenerse mergeable con `OpenDroneMap/WebODM`. Los merges de
upstream se integran de forma regular y NUNCA se reescriben commits ya publicados de
upstream. Cualquier cambio que previsiblemente genere conflictos de merge (ediciones a
archivos del core, reordenamientos, renombres) DEBE justificarse bajo el Principio I antes
de implementarse. Los archivos propios del fork (plugins nuevos, esta constitución,
`.specify/`) DEBEN vivir en rutas que upstream no toca.

**Razón**: un fork que no puede absorber upstream se congela; la mergeabilidad es la
condición de supervivencia del proyecto.

### III. Convenciones de plugin

Cada plugin DEBE seguir la estructura estándar del framework, tomando `coreplugins/` como
referencia:

- Directorio propio en `coreplugins/<nombre>/` con nombre distintivo que no colisione con
  plugins existentes de upstream, versionado en el repo del fork.
- `manifest.json` completo (nombre, descripción, versión, autor, `webodmMinVersion`).
- `plugin.py` con una clase `Plugin(PluginBase)`; la integración con WebODM ocurre solo a
  través de los puntos de extensión del framework: `api_mount_points`,
  `app_mount_points`, `root_mount_points`, hooks de `enable()`/`disable()` y señales.
- Assets de frontend en `public/`; si requieren build, DEBEN ser compatibles con el
  mecanismo `build_plugins` existente (webpack).
- Cada plugin DEBE poder deshabilitarse sin romper el resto del sistema.

**Razón**: seguir el contrato del framework garantiza que los plugins sobrevivan
actualizaciones de upstream sin adaptaciones y se comporten como los plugins oficiales.

### IV. Gestión de dependencias de plugins

Escalera de decisión obligatoria, en este orden:

1. **Dependencias Python puras** → `requirements.txt` dentro del plugin. El mecanismo
   nativo (`PluginBase.check_requirements()`) las instala en
   `MEDIA_ROOT/plugins/<nombre>/site-packages`, volumen compartido entre webapp y
   workers, accesibles vía `python_imports()`. Está prohibido agregarlas al
   `requirements.txt` global o a la imagen Docker cuando este mecanismo basta.
2. **Dependencias de sistema** (paquetes apt, binarios, librerías nativas, paquetes
   Python no instalables con `pip --target`) → se agregan al `Dockerfile` del fork dentro
   de un bloque único claramente delimitado (`# BEGIN FORK PLUGIN DEPS` /
   `# END FORK PLUGIN DEPS`), con un comentario por dependencia indicando qué plugin la
   necesita. Fuera de ese bloque, el `Dockerfile` no se toca.
3. **Verificación de workers (NO NEGOCIABLE)**: webapp y workers comparten la misma
   imagen (`opendronemap/webodm_webapp` en `docker-compose.yml`). Toda feature que
   introduzca dependencias nuevas DEBE, antes de considerarse completa: reconstruir la
   imagen si aplica el punto 2, y demostrar con evidencia (logs/salida de comandos) que
   el contenedor worker arranca y ejecuta una tarea del plugin sin errores de import.

**Razón**: los fallos de dependencias en workers son silenciosos hasta runtime; la
escalera evita engordar la imagen innecesariamente y el paso 3 convierte el fallo tardío
en una verificación temprana obligatoria.

## Restricciones de infraestructura

- Los cambios a `docker-compose*.yml` DEBEN ser aditivos (nuevos servicios, volúmenes o
  variables) y nunca alterar la semántica de los servicios upstream existentes.
- Si el fork publica una imagen Docker propia, DEBE derivar de la imagen upstream
  (`FROM opendronemap/webodm_webapp` o build del `Dockerfile` del fork) y quedar
  etiquetada con un tag propio; webapp y worker DEBEN usar siempre la misma imagen.
- Datos persistentes de plugins van en `get_persistent_path()` / la base de datos vía
  los mecanismos del framework (`plugin_data_store`), nunca en rutas ad-hoc del contenedor.

## Flujo de desarrollo

- Toda feature sigue el flujo Spec Kit: `/speckit-specify` → `/speckit-plan` →
  `/speckit-tasks` → `/speckit-implement`. El Constitution Check del plan DEBE validar
  explícitamente los Principios I–IV antes de la fase de investigación.
- Ninguna tarea, checkpoint o feature se marca como completa sin ejecutar el comando que
  la verifica y mostrar su salida (incluido exit code) en el mismo reporte.
- Los tests de plugins siguen el patrón existente del repo (`coreplugins/test/`,
  `run_tests_in_docker.sh`) cuando la feature los requiera.

## Governance

Esta constitución prevalece sobre cualquier otra práctica del repositorio. Las enmiendas
se realizan vía `/speckit-constitution`, documentando el cambio en el Sync Impact Report y
versionando con SemVer: MAJOR para eliminaciones o redefiniciones incompatibles de
principios, MINOR para principios o secciones nuevas o ampliadas materialmente, PATCH para
clarificaciones de redacción. Todo plan y PR DEBE verificar cumplimiento de los Principios
I–IV; las violaciones solo se aceptan justificadas en Complexity Tracking.

**Version**: 1.0.0 | **Ratified**: 2026-07-21 | **Last Amended**: 2026-07-21
