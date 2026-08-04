# Guía de validación

Cómo comprobar que la selección asistida funciona, de la verificación más barata a la más cara.

> ⚠️ **Nunca `./run_tests_in_docker.sh`** en esta instancia: hace `docker compose down -v` y borraría
> las tareas reales del usuario. Las suites de plugin son seguras.

> ⚠️ **No etiquetar sobre datos reales del usuario al validar.** Crear un dataset de prueba con un
> nombre identificable (`ZZ-prueba-010`) y borrar solo lo propio. Un polígono ajeno borrado por
> descuido no se recupera.

---

## 0. Requisito previo: el gate de dependencias (Principio IV)

Es lo primero porque, si falla, todo lo demás da resultados engañosos.

```bash
docker compose exec -T webapp python - <<'PY'
import numpy, scipy, sys
sys.path.insert(0, '/webodm/app/media/plugins/training/site-packages')
import importlib; importlib.reload(numpy)
PY
```

Lo que hay que confirmar, y que el test automatizado `tests/test_requirements.py` afirma:

1. La versión de numpy y scipy dentro de `site-packages` del plugin **coincide** con la de la imagen
   (hoy 1.26.2 y 1.11.3).
2. `import rasterio` funciona con el directorio del plugin al frente de `sys.path`.
3. `from skimage.segmentation import slic` funciona.

**Si (1) falla, parar.** Significa que un merge de upstream movió numpy y los pines del plugin
quedaron obsoletos: la próxima llamada a `rasterio` dentro de `python_imports()` va a reventar con
`numpy.dtype size changed` (research.md D1).

### Verificación de workers (paso 3, no negociable)

```bash
docker compose exec -T worker python -c "
from coreplugins.training import superpixels; print('worker importa superpixels OK')"
docker compose logs --tail=50 worker
```

---

## 1. Suite automatizada

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests
```

Debe salir en verde e incluir los módulos nuevos. **Recordatorio del README del plugin**: un módulo
de test que no se reexporte en `tests/__init__.py` no se ejecuta y la suite sigue en verde — el fallo
más silencioso de este plugin.

Los tests de JavaScript de `public/tests/` corren dentro de esa misma orden vía
`tests/test_frontend.py` (se saltan si no hay `node`).

---

## 2. Las tres propiedades que definen la feature

Son las que distinguen «funciona» de «parece que funciona». Las tres tienen test automatizado; esta
sección es cómo comprobarlas a mano.

### 2.1 Determinismo (FR-007, SC-002)

```bash
TASK=<uuid>; DS=<dataset_id>
for i in 1 2 3; do
  curl -s -X POST "http://localhost:8000/api/plugins/training/datasets/$DS/tasks/$TASK/regions" \
    -H 'Content-Type: application/json' -b cookies.txt \
    -d '{"points":[{"lat":-33.4569,"lon":-70.6483}],"tolerance":0.0}' \
    | md5sum
done
```

**Esperado**: los tres md5 idénticos. Repetir tras reiniciar `webapp` (caché fría) y comparar contra
los anteriores: **también** deben coincidir. Una caché que cambia el resultado es exactamente el
fallo que FR-007 prohíbe.

### 2.2 Independencia del encuadre (FR-008)

En el navegador: pinchar un punto reconocible del terreno a zoom 18, anotar la geometría; alejar a
zoom 15, encuadrar distinto, pinchar el mismo punto. **Esperado**: misma geometría.

### 2.3 Sin juntas visibles (FR-009)

El caso que la implementación existe para resolver. Localizar una pista que cruce el borde de una
celda de trabajo (51×51 m a la resolución por defecto) y seleccionarla desde los dos lados.

**Esperado**: la región sale entera y sin ningún borde recto en el punto donde cae la junta. Un tramo
recto de exactamente 51 m, o una región que termina en seco en una línea vertical u horizontal, es el
fallo que hay que buscar.

---

## 3. Recorrido funcional

Sobre un dataset de prueba propio, con una tarea que tenga ortofoto y DTM.

| # | Escenario | Esperado | Cubre |
|---|---|---|---|
| 1 | Activar el modo en la barra de herramientas | Aparece junto a polígono / pincel / borrador; el cursor cambia | FR-001 |
| 2 | Pinchar sobre una calzada | Se crea una etiqueta de la clase activa siguiendo el borde visible | US1-1 |
| 3 | Recargar la página | La etiqueta sigue ahí, misma geometría y clase | US1-3 |
| 4 | Volver a pinchar el mismo punto | Mismo resultado, sin duplicar la etiqueta | US1-2 |
| 5 | Pasarse del borde y retocar con el borrador | Se corrige el tramo sin perder el resto | US1-4 |
| 6 | Pinchar fuera de la huella del vuelo | No se crea etiqueta; mensaje claro, no un error | US1-5, FR-025 |
| 7 | Arrastrar a lo largo de una pista | Todas las regiones tocadas quedan etiquetadas | US2-1 |
| 8 | Rozar una región de refilón durante el arrastre | Entra entera, no una fracción | US2-3, FR-005 |
| 9 | Tolerancia al mínimo y pinchar | Exactamente una región | US3-1 |
| 10 | Subir la tolerancia y repetir en el mismo punto | La selección crece y se detiene en el borde | US3-2 |
| 11 | Comparar tolerancias A < B en el mismo punto | La de A está contenida en la de B | US3-3, FR-017 |
| 12 | Tolerancia alta sobre terreno muy uniforme | Se detiene en el tope y **avisa** (`truncated: true`) | US3-4, FR-018 |
| 13 | Tarea sin DTM ni DSM | Funciona con color; la interfaz lo declara | US4-1, FR-011 |
| 14 | Anular el peso de elevación | Las regiones se recalculan y el cambio se ve | US4-2, FR-012 |
| 15 | Cambiar granularidad, tolerancia o peso | **Ninguna etiqueta ya guardada cambia** | FR-023 |
| 16 | Volver al dataset en otra sesión | Los ajustes son los que se dejaron | US4-3, FR-022 |
| 17 | Comprobar `Shift` | Sigue haciendo selección múltiple y marcado de vértices, sin interferencia | FR-002 |
| 18 | Desactivar el plugin y reactivarlo | El etiquetado manual sigue funcionando en ambos casos | FR-026 |
| 19 | Exportar el dataset | Las etiquetas asistidas salen igual que las manuales | FR-020, SC-008 |

Registrar el resultado de cada uno. Un escenario «cubierto por la suite» no es un escenario validado
a mano: anotar cuál es cuál.

---

## 4. Criterios de éxito medibles

| SC | Cómo se comprueba | Referencia ya medida |
|---|---|---|
| SC-001 | Cronometrar una pista de ~100 m con el pincel de píxeles y con la selección asistida, mismo operador. Debe bajar a menos de la mitad | — |
| SC-002 | §2.1, con caché fría y caliente | **verificado** por HTTP: 3 respuestas idénticas y la misma con caché fría |
| SC-003 | Clic sobre celda ya preparada: sin espera perceptible | **0,012 s medianos** por HTTP (5 medidas) |
| SC-004 | Preparar una celda nueva < 5 s | **0,682 s medianos**, máx. 0,730 s por HTTP (5 medidas con caché vaciada) |
| SC-005 | En la pista de SC-001, contar qué fracción de regiones necesitó retoque. < 20 % | — |
| SC-006 | Escenario 13 completo sobre una tarea sin DEM | cubierto por `test_api_regions.RegionElevationTest`; falta a mano sobre una tarea real |
| SC-007 | Vigilar memoria durante una sesión larga sobre la ortofoto mayor (14145×29380 px) | **274 MB de RSS pico** del proceso entero (154 MB antes de la primera partición) |
| SC-008 | Comparar el `.zip` exportado con uno de etiquetas manuales: sin diferencia de formato | **verificado**: `test_export.AssistedLabelExportTest` compara las máscaras byte a byte |

```bash
# memoria durante la sesión (SC-007)
docker stats --no-stream webodm-webapp-1 webodm-worker-1
```

---

## 5. Rehacer las mediciones de la fase 0

Los números de research.md se sacaron con scripts sobre datos reales. Para repetirlos:

- **D2, convergencia del halo**: partir la misma ventana con halos de 0 a 16·S y comparar la
  partición del núcleo contra la del halo mayor, midiendo la fracción de pares de píxeles vecinos que
  discrepan sobre si están en el mismo segmento. **Esperado**: 0,000 % desde 8·S.
- **D4, coste por celda**: cronometrar por separado lectura de ortofoto, canales de DEM y partición
  sobre una ventana de 768×768 con 5 bandas. **Esperado**: ~0,95 s en total, con los canales de DEM
  como la parte más cara.

Si alguna de las dos deja de dar lo mismo tras un merge de upstream, la causa más probable es un
cambio de versión de `scikit-image` o de `rasterio`: comprobar §0 antes de investigar nada más.
