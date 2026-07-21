# Quickstart de validación: plugin viewshed

**Feature**: 001-viewshed-analysis | **Date**: 2026-07-21

Guía para probar de punta a punta que la feature funciona. Toda la verificación corre
**en Docker** (regla del proyecto — `docs/entorno-plugins.md`); nada se instala en el
host.

## Prerrequisitos

- Docker Desktop corriendo en el host.
- Un dataset de dron procesable (o una tarea ya procesada) **con DSM habilitado**
  (opción `dsm: true` al procesar; sin DSM/DTM la herramienta debe rehusarse con
  mensaje claro — eso también se valida).

## 1. Levantar el stack con el plugin

```bash
cd ~/Projects/WebODM
./webodm.sh restart --build   # o: docker compose up -d --build
```

Verificar que el plugin cargó y compiló sus assets:

```bash
docker compose logs webapp | grep -i viewshed   # sin errores de init/build del plugin
```

## 2. Validación funcional (escenarios del spec)

En `http://localhost:8000`, abrir la vista 2D de la tarea procesada:

| # | Escenario (spec) | Acción | Resultado esperado |
|---|---|---|---|
| 1 | US1-AS1 | Activar control viewshed, clic en un punto del área | Capa de zonas visibles aparece sobre la ortofoto; coherente con el terreno (una colina intermedia oculta lo que hay detrás) |
| 2 | US1-AS2 | Durante el cálculo | Indicador de progreso; el mapa sigue navegable |
| 3 | US2-AS1/2 | Repetir con altura 30 en el campo (default visible: 1.60) | Área visible ≥ que con 1,60 m |
| 4 | US2-AS3 | Ingresar altura −5 o "abc" | Mensaje de validación; no se lanza el cálculo |
| 5 | US3-AS1/2 | Limpiar capa; generar dos análisis seguidos | El mapa queda limpio; solo se muestra el último resultado |
| 6 | US1-AS4 / edge | Tarea sin DSM/DTM; clic fuera del área con datos | Mensaje claro y accionable en ambos casos; cero fallos silenciosos |

## 3. Tests automatizados (en Docker)

Suite del plugin con el stack levantado:

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.viewshed.tests
```

Suite completa autocontenida (construye, corre y limpia):

```bash
./run_tests_in_docker.sh backend coreplugins.viewshed.tests
```

**Criterio**: exit code 0 y salida de tests visible en el reporte de verificación
(regla de `verification-before-completion`).

## 4. Verificación del worker (Principio IV.3 — obligatoria)

El cálculo corre en el contenedor worker; hay que demostrar que ejecuta sin errores:

```bash
# 1. Worker arriba y sin errores de import al arrancar
docker compose logs worker --tail 50

# 2. Lanzar un análisis desde la UI y confirmar que el job corrió en el worker
docker compose logs worker --tail 50 | grep -iE "viewshed|error"
```

**Criterio**: el job del análisis aparece ejecutado en el worker sin trazas de
`ImportError`/`ModuleNotFoundError`/fallos de GDAL, y el resultado llegó al mapa.

## 5. Criterios de éxito medibles (spec)

- SC-001: generar el primer análisis toma ≤ 3 interacciones (activar → clic).
- SC-002: con el dataset típico de prueba, el resultado aparece en < 15 s desde el clic.
- SC-003/005: los escenarios 5 y 6 de la tabla pasan al 100%.
