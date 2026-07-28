# Quickstart — validación de `006-street-width`

Escenarios ejecutables que demuestran que la feature funciona. Cada uno dice qué se corre y qué se
espera ver; ninguno se da por bueno sin ejecutar el comando y mostrar su salida, incluido el exit
code (Flujo de desarrollo de la constitución).

## Prerrequisitos

- Stack levantado: `docker compose ps` con `webapp`, `worker`, `db` y `broker` en `running`.
- Las tres tareas de referencia presentes en la instancia:

  | Rol | Tarea | Modelos |
  |---|---|---|
  | Caso urbano | `Polideportivo María Puebla Vásquez` (proyecto `marcoleta`) | DSM y DTM a 5 cm |
  | No regresión rural | `Noria` (proyecto `los presidentes`) | DSM y DTM a 2,2 cm |
  | No regresión rural | `Task of 2026-07-24…` (proyecto `ruta de zona 1`) | DSM a 5 cm |

  Cada una con su polilínea de eje ya trazada en `annotations`.

- Código desplegado en los contenedores. `coreplugins/` va horneado en la imagen, así que tras editar
  hay que copiarlo y reiniciar; `docker compose cp` **añade dentro** del destino si ya existe, de
  modo que hay que borrarlo antes:

  ```bash
  for s in webapp worker; do
    docker compose exec -T "$s" rm -rf /webodm/coreplugins/road
    docker compose cp coreplugins/road "$s:/webodm/coreplugins/road"
  done
  docker compose restart webapp     # reconstruye el bundle de frontend
  ```

> ⚠️ **No usar `run_tests_in_docker.sh` en esta instancia**: termina con `docker compose down -v` y
> destruiría las tareas reales que estos escenarios necesitan. Se corre la suite contra el stack
> vivo, que para las suites de plugin es seguro.

---

## Escenario 1 — La suite completa del plugin

```bash
docker compose exec -T webapp /webodm/webodm.sh test backend coreplugins.road.tests
```

**Esperado**: `OK`, exit code 0, y el número de tests **mayor** que el de la feature anterior por los
casos nuevos de `test_coherence.py` y los añadidos a `test_profile.py`.

Recordatorio: `coreplugins/` es un paquete de espacio de nombres, así que una clase de test nueva que
no se re-exporte desde `tests/__init__.py` **no se ejecuta y no falla** — pasa desapercibida.
Comprobar que el recuento sube.

---

## Escenario 2 — No regresión del modo por defecto (FR-002, SC-004)

El más importante de todos: los análisis rurales ya entregados no pueden cambiar.

1. Antes de tocar nada, con el código actual, volcar el resultado de referencia de las dos tareas
   rurales con sus parámetros originales.
2. Con el código nuevo, recalcular exactamente los mismos análisis.
3. Comparar **tramo a tramo** todos los campos numéricos.

**Esperado**: cero diferencias. No "parecidos", no "dentro de tolerancia": iguales.

Comprobación complementaria, más barata y que debería correr en la suite: con
`coherence_window = 0`, la pasada de coherencia es la identidad sobre cualquier entrada.

---

## Escenario 3 — La calle, en modo superficie (SC-001, SC-002, SC-003)

Sobre `Polideportivo María Puebla Vásquez`, DTM, 27 tramos, con
`edge_mode=surface`, `surface_tolerance=0.06`, `coherence_window=2`, `search_half_width=5.0`,
`sample_step=0.05`, `segment_length=5.0`.

| Criterio | Umbral | Valor con el comportamiento actual |
|---|---|---|
| SC-001 — desviación típica del ancho en las progresivas 75–85 m y 115–130 m | ≤ 0,25 m | 0,11 m sobre esos seis tramos (6,50 / 6,70 / 6,80 y 6,60 / 6,70 / 6,80): ya se cumple, el listón es no estropearlo |
| SC-002 — ancho reportado en 45–60 m, donde el lado este es descampado | **ninguno** | 10,55 m en la progresiva 45: un número inventado |
| SC-003 — desviación típica de `offset_left` en todo el trazado | ≤ 0,40 m | 1,29 m |

SC-002 es la mejora que más importa y la más fácil de leer: basta con que esos tramos salgan
`no_edge`.

---

## Escenario 4 — Las tres garantías de la coherencia (FR-013, FR-014, SC-006)

Sobre el mismo análisis del escenario 3, inspeccionando el documento de tramos:

1. **Un hueco largo no se rellena.** La secuencia de tramos sin bordillo este —diez o más
   consecutivos— no tiene ni un solo `right_edge_source: "inferred"`.
2. **No hay cascada.** Ningún tramo con `*_edge_source: "inferred"` está a más de
   `coherence_window` tramos del `measured` más próximo en ese mismo lado.
3. **Vecindad insuficiente.** El primer y el último tramo del eje, sin vecinos a un lado, conservan
   lo que dio la detección.

---

## Escenario 5 — El origen viaja hasta el usuario (FR-031, FR-032, FR-033, SC-005)

1. **En el mapa**: pasar el cursor por un tramo `inferred` y comprobar que se distingue a simple
   vista de uno `measured` y de uno `no_edge`. Hacer clic y ver, por lado, la distancia con la marca
   de inferida donde corresponda.
2. **En el CSV**: descargar y comprobar que las dos columnas nuevas van al final, que las celdas sin
   dato están vacías y no a cero, y que el pie incluye `edge_mode`, `surface_tolerance` y
   `coherence_window`.
3. **En el GeoJSON**: abrirlo y comprobar que los puntos `kind: "edge"` llevan `source`, de modo que
   un borde inferido no se confunda con uno medido.

> El bundle `Road.js` se cachea con fuerza. Si el mapa no refleja los cambios, `Cmd+Shift+R` antes
> de sospechar del código.

---

## Escenario 6 — Coste (SC-007)

Mismo análisis, mismos parámetros, los dos modos, cronometrado.

**Esperado**: el modo superficie no supera en más del 25 % al de quiebre. El sobrecoste por
transversal son dos ajustes lineales sobre un vector ya en memoria, frente a la lectura del ráster
que domina.

Comprobar además el consumo de memoria con `coherence_window > 0`: los perfiles retenidos deben
quedarse en el orden acotado en D22 (~640 kB en el caso habitual, ~16 MB en el peor caso realista).

---

## Verificación del worker (Principio IV, no negociable)

**Sin esta evidencia la feature no se cierra**, aunque no añada ninguna dependencia.

Motivo: `run_function_async` reejecuta la función del worker **por su código fuente** en un namespace
vacío. El módulo nuevo `coherence` solo es visible si se importa de forma absoluta y **dentro** del
cuerpo de la función. Un import a nivel de módulo, o relativo, pasa todos los tests —donde la función
se invoca directamente— y falla únicamente aquí.

1. Lanzar desde la interfaz un análisis real en modo `surface` con `coherence_window = 2`.
2. Seguir el log del worker:

   ```bash
   docker compose logs -f worker
   ```

**Esperado**: el análisis progresa y termina, sin `NameError` ni `ImportError`, y el resultado
aparece en el mapa. Pegar en el reporte el fragmento del log que lo demuestra.

---

## Escenario opcional — ¿de verdad hacen falta dos modos? (D24)

No es criterio de aceptación: es la medición que la feature dejó pendiente a propósito.

Correr el criterio de superficie sobre `Noria` y `ruta de zona 1` y comparar tramo a tramo contra el
criterio de quiebre.

- Si el modo superficie mide **igual o mejor** en tierra, la deuda registrada en Complexity Tracking
  se puede saldar: un solo criterio, un parámetro menos y la mitad de tests.
- Si sale peor —lo esperado, por las cunetas suaves sin escalón—, queda documentado con números y los
  dos modos dejan de ser un supuesto para pasar a ser un hecho medido.
