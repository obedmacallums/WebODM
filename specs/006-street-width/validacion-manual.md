# Validación de `006-street-width` — registro honesto

**Fecha**: 2026-07-28. Todos los comandos corrieron contra el stack vivo (OrbStack, arm64); las
cifras son medidas, no estimadas. Donde un criterio de éxito **falla tal como está escrito**, se
dice y se explica — la spec la escribimos antes de tener estos datos, y parte de sus umbrales
resultaron mal derivados del comportamiento del detector anterior.

## Escenario 1 — Suite completa ✅

```
docker compose exec -T webapp /webodm/webodm.sh test backend coreplugins.road.tests
Ran 243 tests ... OK
```

243 frente a los 201 del cierre de `005`: +42 (13 de `test_surface`, 11 de `test_coherence`, y el
resto repartido entre compute, params, capabilities, export, lifecycle y los JS nuevos).

## Escenario 2 — No regresión del modo por defecto (SC-004) ✅

Baseline capturado **antes de tocar código** (T001): recálculo de los análisis reales de `Noria`
(59 tramos) y `ruta de zona 1` (50 tramos) con sus parámetros originales, a precisión completa
(`repr` de cada float). Tras implementar la feature entera, mismo recálculo y `diff`:

```
noria-dtm-45260e6c:        IDENTICO tramo a tramo (diff limpio)
ruta-zona-1-dsm-c20e8cfe:  IDENTICO tramo a tramo (diff limpio)
```

Byte a byte, no "dentro de tolerancia". Los CSV viven en [`baseline/`](./baseline/).

## Verificación del worker (Principio IV) ✅

Análisis real en modo `surface` con `coherence_window=2` sobre la calle Polideportivo, lanzado por
`run_function_async` y ejecutado por el **contenedor worker** (no eager):

```
celery task 74fa950f: state=SUCCESS result={'segments': 27}
analysis: status=completed params.edge_mode=surface coherence_window=2
resumen: tramos=27 measured=16 inferred=11 no_edge=0
```

Sin `ImportError` ni `NameError`: el módulo nuevo `coherence` llega al worker a través del import
de módulo de `compute`, que `run_analysis` importa absoluto y dentro del cuerpo (D23).

**Gotcha que costó una iteración**: el worker es un proceso vivo con los módulos ya importados —
`docker cp` no le cambia lo que tiene en memoria. La primera verificación ejecutó el código viejo
(la pista: 6/27 medidos, exactamente lo que da el modo `break` con ese semiancho). Tras
`docker compose restart worker`, el código nuevo. El análisis de verificación queda en la tarea
como **"Calle (modo superficie, 006)"**, con identidad de eje propia para no pisar el análisis
existente del usuario.

## Escenario 3 — La calle en modo superficie (SC-001, SC-002, SC-003) ⚠️

Parámetros: `surface`, tolerancia 0,06, ventana 2, paso 0,05, **semiancho 8 m** — no los 5 m que
proponía el quickstart: con el eje descentrado, el borde este cae a 5,5–6,4 m del eje y un radio de
5 m lo dejaba fuera del alcance (el primer intento salió lleno de `no_break` por eso; el radio del
quickstart estaba mal elegido, no el detector).

Resultado global, frente al modo `break` con defectos:

| | `break` (antes) | `surface` + coherencia (ahora) |
|---|---|---|
| Tramos con ancho | 22/27, rango **0,70–10,55 m**, sd 2,21 | **27/27** (16 medidos + 11 inferidos), sd 1,83 |
| Zona sin árboles (0–90, 115–130) | saltos sin sentido físico | **6,05–7,00 m** sostenidos |
| El 10,55 m inventado en la progresiva 45 | publicado como `measured` | desaparecido: ahí salen 6,30–6,68 coherentes con los vecinos |

Los criterios formales, uno a uno:

- **SC-001** (sd ≤ 0,25 en 75–85 y 115–130): **sd 0,31 — falla por 0,06 m.** Anchos
  [6,65, 6,05, 6,45, 6,80, 6,95]. El umbral se calibró sobre la repetibilidad del modo `break` en
  6 tramos escogidos; la dispersión real del borde este —que ahí no es bordillo sino fin de la
  franja plana— es algo mayor.
- **SC-002** (ningún ancho en 45–60): **falla tal como está escrito** — salen 6,30 / 6,45 / 6,68.
  Pero la lectura importa: la premisa "ahí no hay nada que medir" se derivó del 10,55 inventado
  por `break`. El DTM muestra que la franja plana termina de forma **consistente** a ~5,0–5,3 m al
  este en toda la mitad norte, y el criterio de superficie la encuentra tramo tras tramo con
  desviaciones de centímetros. No es un número inventado: es el borde de la plataforma plana
  (calzada + berma), que es exactamente lo que FR-006 define. El daño que SC-002 quería evitar —un
  valor plausible y falso publicado como medido— sí está resuelto.
- **SC-003** (sd de `offset_left` ≤ 0,40): **sd 0,448 — falla por 0,048 m.** La serie es
  2,10 → 0,55 m en deriva suave y monótona: el eje dibujado a mano se acerca a la solera hacia el
  sur, y la sd mide esa geometría real, no ruido del detector. El salto medio entre tramos
  vecinos es ~0,11 m (antes, saltos de 1,15 m). El umbral medía lo que no era.

**Los tres umbrales los fijamos antes de medir; la conclusión honesta es que el detector cumple el
objetivo de la feature y que SC-001/002/003 necesitan re-derivarse de estos datos si se quieren
mantener como criterios formales.** Queda a decisión del usuario en la revisión.

## Escenario 4 — Garantías de la coherencia (SC-006) ✅

Sobre el análisis real: 11 inferidos, cada uno a ≤ 2 tramos de un `measured` del mismo lado
(sin cascada); los `no_break` que quedaron en el primer intento (radio 5 m) mostraron el otro lado
de la garantía: 10+ tramos consecutivos sin evidencia no recibieron ni un solo relleno. En
sintético, las tres garantías están fijadas por `test_coherence.py` (hueco largo, votos, identidad
con ventana 0).

## Escenario 5 — El origen llega al usuario (SC-005) ✅ (por tests) / ⚠️ (visual pendiente)

CSV con `left_edge_source`/`right_edge_source` al final, GeoJSON con `source` en los puntos de
borde, popup con la marca "(inferido: motivo)", estilo `12,4` distinguible: todo cubierto por
tests (`test_export`, `segmentStyle.test.js`, `roadBridge.test.js`) que corren en la suite.
**La comprobación visual en el navegador no se hizo** — la pestaña del proyecto estaba cerrada.
El análisis "Calle (modo superficie, 006)" está publicado en la tarea para hacerla en un minuto:
abrir el mapa, hard reload (`Cmd+Shift+R`, el bundle se cachea), y mirar un tramo a rayas largas.

## Escenario 6 — Coste (SC-007) ✅

Mismos parámetros, los dos modos, sobre las tres tareas reales:

```
noria  (59 tramos): break 0,58 s | surface 0,31 s   (-46 %)
zona1  (50 tramos): break 0,18 s | surface 0,13 s   (-30 %)
calle  (27 tramos): break 0,13 s | surface 0,07 s   (-45 %)
```

El techo era +25 %; el modo nuevo es **más rápido** (su recorrido se detiene antes). La memoria de
la retención (D22) en estos tamaños es despreciable (≤ 1 MB).

## Escenario opcional — D24: ¿hacen falta dos modos? ✅ respondida: SÍ

Comparación tramo a tramo sobre los dos rurales reales:

```
noria: ambos miden 47/59 | |delta ancho| medio 1,95 m, max 9,60 m | solo surface: 12
zona1: ambos miden 40/50 | |delta ancho| medio 2,50 m, max 8,30 m | solo surface: 10
```

En rural los dos criterios **no miden lo mismo**: `surface` encuentra "borde" en todos los tramos
—corta en el primer resalte de 6 cm: rodera, montículo, matorral— y sus anchos difieren en ~2 m de
media de los del talud. Unificar en un solo criterio cambiaría sustancialmente los resultados
rurales ya entregados. La deuda registrada en Complexity Tracking queda saldada **a favor de los
dos modos**, ahora con números en vez de con un supuesto.

## Pendiente

- Comprobación visual del popup/estilo `inferred` en el navegador (escenario 5).
- Decisión del usuario sobre re-derivar SC-001/002/003 con los datos de arriba.
