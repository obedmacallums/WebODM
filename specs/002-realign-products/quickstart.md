# Quickstart de validación: plugin `realign`

**Feature**: 002-realign-products | **Date**: 2026-07-22

Guía para probar de punta a punta que la feature funciona. Toda la verificación corre **en
Docker** (regla del proyecto — `docs/entorno-plugins.md`); nada se instala en el host.

## Prerrequisitos

- Docker Desktop / OrbStack corriendo en el host.
- Una tarea **ya procesada con al menos un producto ráster 2D** (ortofoto y, si es posible, DSM
  y DTM) cuya ortofoto se vea **desplazada respecto al mapa base** (o se induce el desajuste para
  la prueba). Sin ningún ráster 2D la herramienta debe rehusarse — eso también se valida.
- Dos usuarios: uno con permiso de edición del proyecto (`change_project`) y otro de solo lectura
  (para validar permisos, FR-014).

## 1. Levantar el stack con el plugin

```bash
cd ~/Projects/WebODM
./webodm.sh restart --build   # o: docker compose up -d --build
```

Verificar que el plugin cargó y compiló sus assets (sin errores de init/build):

```bash
docker compose logs webapp | grep -i realign
```

## 2. Validación funcional (escenarios del spec)

En `http://localhost:8000`, abrir la vista 2D de la tarea:

| # | Escenario (spec) | Acción | Resultado esperado |
|---|---|---|---|
| 1 | US1-AS1 | Activar el control `realign` | La ortofoto se muestra semitransparente sobre el mapa base; la herramienta espera pares de puntos |
| 2 | US1-AS2/3 | Marcar un par: clic en un rasgo de la ortofoto → clic en el mismo rasgo del mapa base | El par queda registrado como vector origen→destino |
| 3 | US1-AS3 | Marcar solo 1 par | La previsualización solo traslada las capas (sin giro ni escala) |
| 4 | US1-AS4 | Marcar 2–4 pares | Similitud ajustada; las capas ráster se mueven **juntas** acercándose al mapa base; aparece residuo por punto + RMSE |
| 5 | US1-AS5 | Mover o eliminar un punto | Transformación, previsualización y errores se recalculan (< 1 s) |
| 6 | US2-AS1 | Pulsar **Aplicar** (usuario editor) | Progreso; al terminar, la vista muestra los productos corregidos que cuadran con el mapa base; originales intactos |
| 7 | US2-AS2 | Reeditar puntos y **Aplicar** de nuevo | La corrección se recalcula desde los originales (no se acumula) |
| 8 | US2-AS3 / US3-AS3 | Como usuario de solo lectura, intentar Aplicar/Revertir | Bloqueado con mensaje (403), pero puede previsualizar |
| 9 | US2-AS4 / edge | Aplicar con 0 puntos o puntos degenerados (coincidentes) | Bloqueado; indica la causa / puntos faltantes |
| 10 | US3-AS1/2 | Pulsar **Revertir** | Vista y productos vuelven al original; corregidos dejan de usarse |
| 11 | US4-AS1/2 | Recargar la tarea / abrirla con otro usuario con acceso | Se recuperan puntos, errores y estado idénticos |
| 12 | US1-AS6 / edge | Abrir una tarea **sin productos ráster 2D** | La herramienta no se activa e informa que no hay nada que realinear |
| 13 | US5-AS1 | Con la herramienta activa y sin puntos, abrir el panel | El interruptor "Usar escala" aparece tildado por defecto |
| 14 | US5-AS2 | Con 2+ pares marcados, destildar "Usar escala" | La transformación pasa a rígida (escala mostrada = 1.0000); residuos y RMSE se recalculan (< 1 s) |
| 15 | US5-AS3 | Volver a tildar "Usar escala" | La transformación vuelve a similitud completa; residuos y RMSE se recalculan |
| 16 | US5-AS4 | Con exactamente 1 par, alternar el interruptor | El resultado no cambia (solo traslación en ambos casos) |
| 17 | US5-AS5/6 | Elegir un modo, **Aplicar**, recargar la tarea | Los corregidos usan el modo elegido; al recargar, el interruptor se recupera en el mismo estado |

Descarga corregida: comprobar que `…/realign/download/orthophoto` entrega un GeoTIFF cuya
georreferenciación coincide con la corrección (abrir en QGIS y verificar que cuadra).

## 3. Tests automatizados (en Docker)

Suite del plugin con el stack levantado:

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.realign.tests
```

Suite completa autocontenida (construye, corre y limpia):

```bash
./run_tests_in_docker.sh backend coreplugins.realign.tests
```

Cobertura mínima esperada:
- **Paridad de similitud** JS↔Python sobre los mismos casos (traslación pura, similitud conocida,
  caso degenerado) — mismos parámetros y RMSE dentro de tolerancia.
- **Paridad del modo rígido** (`use_scale=false`) JS↔Python sobre los mismos casos que el modo con
  escala — mismos `cos`/`sin`/traslación/RMSE dentro de tolerancia, `scale=1.0` exacto.
- **Pipeline GDAL** con un GeoTIFF pequeño de fixture: aplicar una similitud conocida y verificar
  que el COG corregido queda north-up y desplazado la cantidad esperada; el original no cambia.
- **Persistencia**: guardar estado → recuperarlo idéntico; revertir limpia corregidos.
- **Permisos**: Aplicar/Revertir devuelven 403 sin `change_project`.

**Criterio**: exit code 0 y salida de tests visible en el reporte (regla
`verification-before-completion`).

## 4. Verificación del worker (Principio IV.3 — obligatoria)

El pipeline de corrección (GDAL) corre en el contenedor **worker**; hay que demostrar que ejecuta
sin errores de import ni de GDAL:

```bash
# 1. Worker arriba y sin errores al arrancar
docker compose logs worker --tail 50

# 2. Lanzar un Aplicar desde la UI y confirmar que el job corrió en el worker
docker compose logs worker --tail 80 | grep -iE "realign|gdalwarp|error"

# 3. Confirmar que el COG corregido se escribió en el volumen compartido
docker compose exec worker ls -la /webodm/app/media/plugins/realign/task_<pk>/
```

**Criterio**: el job aparece ejecutado en el worker sin `ImportError`/`ModuleNotFoundError`/
fallos de `gdalwarp`, el/los `*.tif` corregidos existen en el directorio persistente, y la webapp
los sirve por tiles/descarga.

## 5. Criterios de éxito medibles (spec)

- **SC-001**: corregir una ortofoto claramente desplazada con 2–4 pares en < 3 min.
- **SC-002**: residuos/RMSE y previsualización se actualizan en < 1 s tras marcar/mover/eliminar
  un punto (cálculo en cliente).
- **SC-003**: tras aplicar, los corregidos cuadran con el mapa base dentro de la tolerancia del
  RMSE alcanzado (verificación visual + QGIS).
- **SC-004**: Revertir restaura el original el 100% de las veces sin alterar los assets originales.
- **SC-005**: el estado se recupera idéntico al reabrir/otro usuario (escenario 11) al 100%.
- **SC-006**: ortofoto, DSM y DTM corregidos quedan alineados entre sí (sin desfase relativo).
