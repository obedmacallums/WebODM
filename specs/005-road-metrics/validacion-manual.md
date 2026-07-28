# Resultados de la validación manual (T059)

**Fecha**: 2026-07-28 | **Guía**: [quickstart.md](./quickstart.md) | **Instancia**: desarrollo local
**Tarea usada**: `Noria - 3/17/2026` (`6e965174-…`), DTM de 2,2 cm, 14145×29379 px, con
realineación aplicada.

Este documento registra qué se comprobó **con los ojos en el navegador** y qué quedó cubierto solo
por la suite automatizada. La distinción importa: ningún test comprueba que el panel se vea bien, y
de hecho la validación manual encontró un defecto que los 200 tests no podían encontrar.

## Resumen

| # | Escenario | Estado | Cómo se comprobó |
|---|---|---|---|
| 1 | Análisis básico desde una anotación | ✅ | Navegador: capa dibujada, popup con las cuatro métricas |
| 2 | Tramos sin dato | ✅ | Datos reales: 17 de 33 tramos `no_edge`, con `break_at_axis` y `no_break` |
| 3 | Cancelación y exclusión mutua | ⚠️ parcial | Tests (incluido SC-008 < 5 s); no reproducido a mano |
| 4 | Exportación CSV y GeoJSON | ⚠️ parcial | Tests de extremo a extremo; **descarga no ejecutada** (requiere permiso explícito) |
| 5 | Semáforo y persistencia de umbrales | ✅ | Navegador: recoloreado con 0 peticiones y umbral persistido tras recargar |
| 6 | Recálculo que pisa | ⚠️ parcial | Tests; no reproducido a mano para no alterar los análisis del usuario |
| 7 | Eje subido por archivo | ⚠️ parcial | Tests (5 rechazos con 5 mensajes distintos); no reproducido a mano |
| 8 | Degradación sin plugins hermanos | ⚠️ parcial | Tests; deshabilitar un plugin es un cambio de configuración |
| 9 | Obsolescencia | ✅ | Medido sobre el DEM real tocando su `mtime` |
| 10 | Deshabilitar el plugin | ❌ pendiente | Requiere cambio de configuración en administración |

## Lo que solo pudo verse a ojo

### Escenario 1 — la capa y el popup

El análisis aparece sobre el mapa como **una sola anotación** en el panel de capas del core, con una
polilínea por tramo coloreada por pendiente. Al hacer clic en el tramo 12:

```
Tramo 12
Progresiva              55.0 m – 60.0 m
Longitud                          5.00 m
Cota                            588.74 m
Pendiente                 2.76 % (1.58°)
Ancho                             9.20 m
Izquierda                         5.00 m
Derecha                           4.20 m
Pendiente transversal            -1.10 %
```

Las cuatro métricas de FR-020 están, más la distancia a cada borde por separado — que es lo que
permite ver que la calzada es asimétrica en ese punto (5,00 m contra 4,20 m).

### Escenario 5 — el semáforo

Mover el umbral de aviso de 8 % a 4,5 % recoloreó 4 tramos de verde a amarillo (54 → 50 verdes,
4 → 8 amarillos) **con cero peticiones al servidor**. Tres segundos después había exactamente
**una**: el `PATCH` diferido que persiste el umbral. Tras recargar la página, los deslizadores
seguían en `4.5 / 12` para ese análisis y en `8 / 12` para el otro — los umbrales son por análisis,
no globales.

### Convivencia con `annotations` (T058) sobre datos reales

En el mismo mapa conviven 66 polilíneas de `road` (dos análisis de 33 tramos) y 1 de `annotations`
(la del eje, en naranja), cada una gestionada por su plugin sin interferencias.

### US5 sobre datos reales

La tarea Noria tiene una realineación aplicada, así que el contrato nuevo de `realign` se ejercitó
sin querer contra datos de verdad: `corrected_rasters` devuelve los tres productos y el panel ofrece
el selector de variante. Con una tarea sin realinear, el selector no aparece.

## Defecto encontrado

**El resumen del panel recortaba la pendiente máxima.** El texto
`33 tramos · 162 m · ancho medio 4,51 m · pendiente -22,8 % … 45,5 %` se salía del ancho del panel
y se cortaba justo en el máximo, además de sacarle una barra de scroll horizontal. El número perdido
es precisamente el que responde a la pregunta que motiva la feature.

Ningún test podía encontrarlo: el texto **sí estaba** en el DOM (`scrollWidth 381 > clientWidth 305`),
solo que invisible. Arreglado en `caca4b5e`.

## Nota de entorno

Al iterar sobre el frontend, el navegador cachea `/plugins/road/build/Road.css` y una recarga
forzada no siempre lo renueva. Para verificar un cambio de estilos conviene comprobar el estilo
computado, no solo mirar la pantalla. Además, `rm -rf` del directorio del plugin en caliente deja al
servidor de desarrollo con las rutas a medias: hay que reiniciar `webapp` después de desplegar.
