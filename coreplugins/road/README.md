# Road

Plugin para extraer características geométricas de un camino a partir de su eje y de un modelo de
elevación de la tarea: divide el eje en tramos configurables y reporta por tramo la cota, la
pendiente longitudinal, el ancho medido entre bordes detectados y la pendiente transversal,
pintándolos sobre el mapa 2D con un semáforo verde/amarillo/rojo y exportándolos a CSV y GeoJSON.
Documentación completa de diseño en [`specs/005-road-metrics/`](../../specs/005-road-metrics/):
[`spec.md`](../../specs/005-road-metrics/spec.md),
[`plan.md`](../../specs/005-road-metrics/plan.md),
[`data-model.md`](../../specs/005-road-metrics/data-model.md),
[`contracts/rest-api.md`](../../specs/005-road-metrics/contracts/rest-api.md) y
[`contracts/consumed-contracts.md`](../../specs/005-road-metrics/contracts/consumed-contracts.md).
El modo `surface` se añadió en [`specs/006-street-width/`](../../specs/006-street-width/) y el modo
`segmentation` en [`specs/007-road-edge-segmentation/`](../../specs/007-road-edge-segmentation/),
cada una con su propio `plan.md`, `research.md` y `data-model.md` como delta sobre la anterior.

## Qué hace

- **El eje entra por dos vías**: una polilínea 2D del plugin `annotations` de la misma tarea, o un
  GeoJSON con un `LineString` subido desde el panel. Sin `annotations` la vía del archivo sigue
  funcionando.
- **Tramificación por progresiva**: el eje se corta cada `segment_length` metros (5 m por defecto);
  el último tramo conserva su longitud real.
- **Bordes con tres criterios a elegir** (`edge_mode`): en el punto medio de cada tramo se recorre
  una transversal perpendicular hacia cada lado hasta `search_half_width`, y el borde es…
  - `break` (defecto): el arranque de la primera racha sostenida de pendiente local por encima de
    `break_threshold`. Busca **lo afilado**: talud, cuneta, berma. Es el criterio para caminos.
  - `surface`: el primer punto que se aparta más de `surface_tolerance` de una recta ajustada a la
    propia calzada, y se mantiene apartado. Busca **lo alto**: bordillo, acera. Es el criterio para
    calles, donde la fotogrametría difumina el escalón en una rampa suave que el quiebre no ve y el
    ruido produce picos más afilados que el propio bordillo. El ajuste absorbe el peralte y se
    rehace entre los bordes provisionales, así que tolera un eje descentrado.
  - `segmentation`: clasifica la ortofoto en calzada / no-calzada con el modelo `roads` de la
    librería `geodeep` (recortada al corredor del eje, no la ortofoto completa) y busca **el cambio
    de clasificación**, no un relieve. Es el criterio para una calzada cuyo límite es solo un cambio
    de textura o color —asfalto contra grava, sin bordillo ni talud— donde ni `break` ni `surface`
    encuentran nada porque no hay ninguna señal de elevación que buscar. No tiene parámetros
    propios: reutiliza `min_consecutive_samples` para filtrar píxeles aislados mal clasificados, y
    necesita que la tarea tenga ortofoto (`400 no_orthophoto` si no la tiene). Es **experimental**,
    y con dos límites medidos, no supuestos:

    - **Sobreclasifica.** El modelo se entrenó sobre imágenes de Google Earth, no sobre ortofotos
      de dron. Inspeccionando la máscara de una calle real, marca como calzada el descampado de
      tierra compactada contiguo a la vía y zonas de tierra de un parque — no solo la acera. De ahí
      que mida anchos sistemáticamente mayores que `surface` en el mismo tramo (9,35 m de media
      frente a 6,5-6,8 m). En esa escena clasificó como `road` el 25,3 % del corredor.
    - **Resolución.** El modelo corre a su resolución nativa de entrenamiento y devuelve la máscara
      a **20 cm/px**, sea cual sea el GSD de la ortofoto (medido: recorte de 1688×1919 a 5 cm/px →
      máscara de 422×479 a 20 cm/px). La precisión del borde queda acotada a ~20 cm, así que bajar
      `sample_step` por debajo de eso no aporta nada en este modo, aunque el panel lo permita. Es el
      comportamiento por defecto de GeoDeep, no una imposición: `segment()` acepta `resolution=`
      para forzarla. No se usa porque el modelo se entrenó a 21 cm/px y alimentarlo a 5 cm/px le
      cambia la escala de las formas que aprendió. Palanca disponible, sin medir.

    Documentado como límite conocido en
    [`specs/007-road-edge-segmentation/research.md`](../../specs/007-road-edge-segmentation/research.md)
    D33, no resuelto.

  Cuando no hay borde se dice por qué, por lado (ver «Motivos de "sin borde"» más abajo).
- **Coherencia entre tramos** (`coherence_window`, apagada por defecto): el borde de una calle es
  una línea continua, y esta pasada lo usa — repara atípicos y huecos cortos con la mediana de la
  vecindad, **declarando cada reparación**: el origen de cada borde (`measured` | `inferred`) viaja
  en el tramo, el popup y la exportación. Solo los bordes medidos votan, así que un descampado de
  diez tramos jamás se rellena. Los tramos con algún borde inferido llevan estado `inferred` y
  trazo propio en el mapa.
- **Pendientes por mínimos cuadrados**, no por diferencia de extremos: la longitudinal sobre todas
  las muestras del eje del tramo, la transversal sobre las muestras entre bordes.
- **El ancho puede medirse varias veces por tramo** (`cross_section_spacing`): con el defecto a 0
  se mide una sola vez, en el punto medio, y entonces un bache justo ahí se lleva el tramo entero.
  Con un espaciado positivo se mide cada X metros y se reporta la **sección de ancho mediano** —la
  transversal entera, no un promedio—, más el rango medido y cuántas secciones llegaron a medir.
- **Nada se rellena**: una métrica que no se pudo medir viaja vacía, nunca interpolada ni a cero.
- **Dos semáforos en el cliente**, ambos con recoloreado inmediato y persistencia que no invalida
  el cálculo: el **eje** se colorea por pendiente y la **regla transversal** por ancho. Comparten
  paleta pero no criterio, y el del ancho va invertido — el rojo es quedarse corto.
- **Regla del ancho sobre el mapa**: cada tramo con ancho medido dibuja su transversal por debajo
  del eje coloreado, con el color que le da el semáforo de ancho. Se traza en el **punto medio del
  tramo** y **centrada en el eje**, con la mitad del ancho a cada lado. Ni el reparto entre lados
  ni el punto donde se midió la mueven de ahí: de borde a borde salía descolgada del eje en una
  calzada volcada, y plantada donde cayó la transversal mediana saltaba de sitio entre tramos
  vecinos — en los dos casos parecía un error de trazado. Es una decisión de dibujo y solo de
  dibujo: el reparto real (`offset_left`, `offset_right`), el punto de medición
  (`section_midpoint`) y los bordes reales siguen viajando en el tramo, en el popup y en las
  exportaciones.
- **Exportación**: CSV (una fila por tramo) y GeoJSON (tramos, transversales y puntos de borde).
- **Tramo bajo el cursor**: al pasar el ratón, el tramo gana un contorno blanco que lo separa de sus
  vecinos —dos tramos del mismo color dejan de parecer una sola línea— y al hacer clic aparecen sus
  métricas. El contorno se queda mientras el popup está abierto, para no perder de vista de qué
  tramo hablaba.

## Parámetros de cálculo

| Parámetro | Unidad | Defecto | Rango | Qué controla |
|---|---|---|---|---|
| `segment_length` | m | 5,0 | 0,5 – 100 | cada cuánto se corta el eje |
| `search_half_width` | m | 10,0 | 1 – 50 | hasta dónde se busca el borde a cada lado |
| `sample_step` | m | `max(resolución, 0,1)` | resolución – 5 | separación entre muestras |
| `cross_section_spacing` | m | 0,0 | 0 – 20 | cada cuánto se mide el ancho dentro del tramo (0 = una vez, en el punto medio) |
| `width_aggregation` | — | `median` | `median` \| `mean` | cómo se resume el ancho de las transversales del tramo |
| `break_threshold` | % | 15,0 | 2 – 200 | pendiente local que cuenta como quiebre (solo `break`) |
| `min_consecutive_samples` | muestras | 3 | 1 – 20 | longitud mínima de la racha que confirma el borde (los tres modos) |
| `edge_mode` | — | `break` | `break` \| `surface` \| `segmentation` | criterio de borde |
| `surface_tolerance` | m | 0,06 | 0,02 – 0,5 | separación de la calzada que cuenta como borde (solo `surface`) |
| `coherence_window` | tramos | 0 | 0 – 5 | vecinos a cada lado para reparar atípicos y huecos (0 = apagada) |
| `smooth_window` | m | 0,0 | 0 – 5 | ventana de la mediana móvil que suaviza el perfil antes de detectar (`break`/`surface`; sin efecto en `segmentation`, que no detecta sobre una señal continua) |

`segmentation` no añade ningún parámetro propio (a diferencia de `break_threshold` y
`surface_tolerance`): el panel oculta ambos cuando este modo está seleccionado, con el mismo
mecanismo que ya oculta el uno cuando el otro modo está activo.

`cross_section_spacing` existe porque el ancho era la peor muestreada de las métricas del tramo:
la pendiente longitudinal se ajusta sobre **todas** las muestras del eje (unas 50 en un tramo de
5 m a paso 0,1) mientras el ancho salía de **una sola** transversal. Va en metros y no como un
conteo por tramo para que quede independiente de `segment_length` — acortar el tramo para medir el
ancho más a menudo degradaría la pendiente, que necesita base larga: con ruido de ±2 cm, un
desnivel medido sobre 1 m tiene cinco veces más error de pendiente que sobre 5 m.

Por defecto se reporta la **sección mediana**: se elige la transversal cuyo ancho es la mediana y
se reporta entera —lados, bombeo y puntos de borde—, así que `width == offset_left + offset_right`
sigue siendo exacto y los bordes dibujados están sobre el terreno. `width_aggregation: mean`
promedia en su lugar cada lado por separado —la media de las sumas es la suma de las medias, así
que la coherencia interna se mantiene— a cambio de dos cosas: el resultado es sensible a un solo
bache, y los puntos de borde pasan a ser construidos, porque no hay ninguna transversal donde el
camino tuviera exactamente esas dos distancias. El selector existe para comparar ambos criterios
sobre el mismo DEM sin volver a volar; con una transversal por tramo devuelven lo mismo y el panel
lo esconde. La dispersión viaja aparte (`width_min`,
`width_max`, `width_measured_sections` / `width_sections`), en el popup y en las exportaciones: la
mediana sin el rango escondería justo el estrechamiento que se buscaba. Y un tramo cuya sección
central no encuentra borde ya no se pierde — basta con que otra lo encuentre.

Todas las transversales de un tramo comparten la **normal del tramo** —perpendicular a su cuerda,
decisión D6— en vez de calcular la tangente local de cada una. Con tramos cortos son
indistinguibles; en un tramo largo **y** curvo las transversales de los extremos quedan algo
oblicuas y miden de más. El remedio es el de siempre: acortar el tramo.

El suelo de `sample_step` es la **resolución del ráster**, no una constante: muestrear más fino que
el píxel inventa detalle que no existe. Y `segment_length` nunca puede ser menor que `sample_step`,
o un tramo puede quedarse sin muestras que ajustar. Los valores y rangos vigentes los sirve
`GET capabilities`, para que el panel no duplique constantes.

`smooth_window` existe por los DTM fotogramétricos sobre rodadura rugosa (caminos mineros): sus
rachas de ruido superan el filtro de `min_consecutive` y producen bordes falsos pegados al eje. Es
una **mediana** a propósito —preserva los bordes reales en su sitio— y alimenta solo la detección:
cotas, pendientes y bombeo se siguen midiendo sobre el dato crudo. Una ventana que no cubra al
menos tres muestras al paso vigente no filtra nada.

El panel ofrece además el preset **"camino minero"**: semiancho 20 m, paso 0,5 m, umbral 25 %,
**4 muestras seguidas**, **suavizado 2 m**, **ancho medido cada 1 m** por **mediana** y coherencia
3. La geometría sale de perfiles sintéticos de rampa de 25 m —el semiancho por defecto de 10 m
hace inmedible cualquier calzada de más de 20, que es el fallo típico al analizar una rampa con
valores de calle— y el antirruido, de un DTM minero real en el que las diez transversales de un
tramo devolvían anchos de 1,5 a 12 m sobre una calzada de ancho constante. De los cuatro, el que
más rinde es `min_consecutive_samples`: es el único filtro antirruido que tiene el criterio
`break`, y con 2 muestras bastan dos saltos ruidosos seguidos para inventar un borde.

## Umbrales de color

Ninguno de los dos pares **interviene en el cálculo**: moverlos recolorea en el cliente y se
persisten sin invalidar nada.

Y son **de la tarea, no de cada análisis**: viven en `thresholds` del documento del almacén, así
que un solo juego de deslizadores gobierna todos los caminos procesados y un análisis nuevo hereda
el criterio que el usuario ya tenía puesto. Son una preferencia de lectura, no una propiedad de un
camino; repetir el ajuste en cada uno era trabajo inventado, y comparar dos caminos con escalas
distintas, engañoso. Un documento anterior a este cambio siembra sus umbrales desde el análisis más
reciente que los llevara, para no revertir ajustes al actualizar. El `PATCH` sigue yendo a la ruta
de un análisis porque es desde su ficha desde donde se mueven, pero escribe en la tarea.

| Campo | Colorea | Forma | Defecto |
|---|---|---|---|
| `color_thresholds` | el eje, por pendiente | `[aviso, alerta]` en %, `0 < aviso < alerta ≤ 100` | `[8, 12]` |
| `width_thresholds` | la regla transversal, por ancho | `[mínimo, holgado]` en m, `0 < mínimo < holgado ≤ 100` | deducido |

El del ancho se lee **al revés** que el de pendiente: por debajo del mínimo es rojo, porque en un
camino el problema es quedarse corto. Ambos umbrales son inclusivos por arriba.

Y no tiene defecto fijo porque no puede tenerlo: con umbrales de calle una mina sale toda verde y
con umbrales de mina una calle sale toda roja, así que el control nacería inútil en la mitad de los
casos. Se **deducen del ancho medio del propio análisis** —`[0,8 × medio, medio]`— y no se guardan
mientras el usuario no los toque, de forma que un recálculo que cambie la calzada los vuelve a
centrar solo. En cuanto mueve un deslizador, su valor se persiste y manda. El recorrido de los
deslizadores también sale del camino (0 … 2× el ancho medio): en un recorrido fijo de 0-100 m
ajustar una calle de 6 m sería cuestión de puntería.

## Rutas

Todas cuelgan de `/api/plugins/road/task/<task_id>/…`. Esquema completo, incluidos los códigos de
error, en [`contracts/rest-api.md`](../../specs/005-road-metrics/contracts/rest-api.md).

| Método y ruta | Qué hace |
|---|---|
| `GET capabilities` | modelos, variantes, ejes, defectos y rangos |
| `GET analyses` | índice de la tarea, sin tramos, más el candado de ejecución |
| `POST analyses` | lanza un análisis (JSON o `multipart/form-data` con `file`) |
| `POST analyses/estimate` | coste previo sin lanzar nada |
| `GET analyses/<id>` | el análisis con sus tramos |
| `PATCH analyses/<id>` | solo `name`, `color_thresholds` y `width_thresholds` |
| `DELETE analyses/<id>` | borra índice y archivo de tramos |
| `POST analyses/<id>/cancel` | cancela; idempotente |
| `GET analyses/<id>/export?format=csv\|geojson` | descarga |

`?format=` en la exportación necesita desactivar la negociación de contenido de DRF en esa vista:
`format` es un nombre reservado (`URL_FORMAT_OVERRIDE`) y DRF responde `404` ante un valor que no
corresponde a ningún renderer, antes de ejecutar la vista.

## Motivos de "sin borde"

| Motivo | Qué ocurrió | Qué suele significar |
|---|---|---|
| `no_break` | se recorrió todo el semiancho sin quiebre, sin separación o sin cambio de clasificación, según el modo | el camino se funde con el terreno (o, en `segmentation`, la ortofoto sigue viéndose como calzada) |
| `no_data` | el DEM se quedó sin dato | el recorrido llegó al borde del vuelo (no aplica a `segmentation`) |
| `break_at_axis` | el borde arranca sobre el propio eje | el eje no pasa por la calzada ahí |
| `no_orthophoto` | la etapa de segmentación no cubre este lado del tramo | el corredor recortado no llega hasta ahí (solo en `segmentation`; distinto de que la tarea no tenga ortofoto en absoluto, que se rechaza antes de lanzar el análisis con `400 no_orthophoto`) |

El motivo dice por qué no hay borde **medido**; con la coherencia activada, un lado puede llevar a
la vez su motivo y una distancia inferida de los vecinos — "no se pudo medir aquí, el valor viene
de al lado". El límite conocido del modo `surface`, documentado y no resuelto: una calzada que se
hunde suavemente hacia una cuneta sin escalón nunca se aparta de su propia referencia y sale
`no_break` donde el modo `break` sí acierta — por eso `break` sigue siendo el defecto. Y al revés,
en terreno rural el modo `surface` corta en el primer resalte de 6 cm (rodera, montículo), midiendo
la franja plana y no la calzada entera: los dos criterios responden preguntas distintas. `no_data`
no se usa en modo `segmentation`: cualquier hueco de cobertura dentro del corredor recortado se
reporta como `no_orthophoto`, sin distinguir si viene de fuera de la ortofoto o de un `nodata`
interno de la propia imagen — esa distinción no cambia lo que el usuario puede hacer al respecto.

Un fallo **total** de la etapa de segmentación —la librería `geodeep` no está instalada, o no hay
red para descargar el modelo `roads`— no produce tramos con motivo: hace fallar el análisis
**completo** (`status: "failed"`), con el mismo mecanismo que cualquier otra excepción del
pipeline. `no_orthophoto` por tramo es solo para cuando la etapa sí terminó pero un tramo concreto
queda fuera del corredor recortado.

## Almacenamiento

Dos niveles, para no meter megabytes en una fila de texto que se reescribe en cada actualización de
progreso:

| Almacén | Qué guarda | Dónde |
|---|---|---|
| Índice | metadatos de cada análisis, los umbrales de color de la tarea y el candado de ejecución | `GlobalDataStore('road')`, clave `task_<pk>` |
| Tramos | la colección de tramos de un análisis terminado | `get_plugins_persistent_path('road', 'task_<pk>')/<analysis_id>.json` |

Ninguna tabla ni migración propia. Al eliminarse la tarea, el receptor de `task_removed` borra
ambos.

## Plugins hermanos

`road` es **consumidor**: no expone contrato Python a otros plugins.

- `annotations` (`CONTRACT_VERSION = 2`): de él salen los ejes disponibles, solo los `mode == "flat"`.
- `realign` (`CONTRACT_VERSION = 1`): de él sale la variante realineada del DEM, vía
  `corrected_rasters(task_id)`.

Ambos se obtienen con `get_plugin_by_name` y se degradan en silencio si están ausentes,
deshabilitados o exponen un contrato mayor del que este plugin sabe leer.

## Ver lo que detectó el modelo (capa de máscara)

Un análisis en modo `segmentation` guarda, además de los tramos, **los polígonos que el modelo
consideró calzada**. El panel ofrece la casilla «Mostrar lo que detectó el modelo» y los dibuja
superpuestos a la ortofoto.

No es un adorno. El ancho que reporta este modo puede desviarse metros, y sin ver la máscara esa
desviación es **indetectable desde la interfaz**: en la calle de referencia se atribuyó por escrito
a que el modelo «incluía la acera», y resultó falso —marcaba como calzada un descampado de tierra
entero, el 25,3 % del corredor—. Averiguarlo requirió rescatar a mano un fichero temporal. Esta capa
convierte esa inspección en algo que el usuario hace mirando el mapa.

| | |
|---|---|
| Formato | Polígonos en EPSG:4326, junto al documento de tramos del análisis |
| Cuándo | Al calcular en modo `segmentation`; los otros modos no producen ninguna |
| Alcance | Solo el corredor analizado, no la ortofoto entera |
| Tamaño | 19,5 KB (corredor de 66 m) · 76,9 KB (293 m) — medido |
| Precisión | La del modelo, ~20 cm/px. El panel lo dice; no es un contorno exacto |

Tres estados que **no significan lo mismo**, y la interfaz los distingue:

- **Con calzada** — se dibuja la capa.
- **Vacía** — el modelo corrió y no reconoció calzada. Es un resultado, y explica por qué los tramos
  salieron sin borde.
- **Sin máscara** — no se guardó ninguna (análisis anterior a esta feature, u otro modo). No es un
  resultado; el panel ofrece recalcular.

Detalle de diseño en
[`specs/008-segmentation-mask-layer/`](../../specs/008-segmentation-mask-layer/research.md).

### Notas de implementación

- La máscara se vectoriza del **ráster que ya se calculó** (`rasterio.features.shapes`), no pidiendo
  el GeoJSON a `geodeep`: la detección de borde necesita el ráster para muestrear, y la librería
  devuelve una cosa **o** la otra. Pedir ambas costaría una segunda inferencia completa —13,49 s en
  el corredor de 293 m— para un resultado idéntico que la vectorización produce en 0,036 s.
- La simplificación usa una tolerancia de 0,20 m, que **es la resolución de la propia máscara**: por
  debajo no hay información que perder. Reduce 115 KB → 19,5 KB sin descartar nada real.
- **Trampa**: `GEOSGeometry.geojson` serializa por OGR y devuelve las coordenadas **invertidas**
  (orden de ejes oficial de EPSG:4326, latitud primero). Los polígonos aparecerían en otro
  hemisferio. Hay que construir el GeoJSON desde `.coords` — está encapsulado en
  `segmentation._geos_to_geojson_geometry()`.

## Rendimiento

El eje se recorre **por bloques de tramos**: por cada bloque se lee una única ventana del ráster a
un array de numpy y todas sus muestras —eje y transversales— se resuelven por indexación
vectorizada. `ds.sample()` haría una lectura por punto, que es el cuello de botella directo con
decenas de miles de muestras. El borde del bloque es además donde se reporta progreso y se
comprueba la cancelación.

Medido sobre un DTM de 2,2 cm: 1 km de eje con los valores por defecto son 200 tramos y 50.400
muestras en **0,37 s**, con 14 reportes de progreso.

## Desarrollo

`rasterio`, `numpy` y (desde `007`, modo `segmentation`) `geodeep`, los tres ya presentes en la
imagen — `geodeep` no se añadió para este plugin: ya estaba en el `requirements.txt` del core
porque lo usa `coreplugins/objdetect` (upstream). El único paquete de sistema nuevo que usa
`segmentation.py` es `gdalwarp`, también ya presente (lo usa `objdetect` desde antes).

`coreplugins/` va horneado en la imagen, así que un plugin nuevo no aparece por el bind mount. Y
`docker compose cp origen destino` copia **dentro** del destino cuando este ya existe (deja un
`road/road/` anidado y el código viejo intacto), así que hay que borrarlo antes:

```bash
for s in webapp worker; do
  docker compose exec -T $s rm -rf /webodm/coreplugins/road
  docker compose cp coreplugins/road $s:/webodm/coreplugins/road
done
docker compose exec -T webapp python manage.py rebuildplugins   # solo si tocaste JS/JSX
docker compose restart webapp worker
```

**Copiar no es desplegar.** El `cp` deja los archivos en disco, pero ni el Python ni el JS que se
están sirviendo se enteran. Faltan dos pasos, y ninguno lo cubren los tests (que arrancan procesos
frescos y leen el disco, por lo que pasan en verde mientras la aplicación viva sigue con el código
viejo):

- **Módulos Python en memoria.** Tanto gunicorn (`webapp`) como Celery (`worker`) son procesos
  persistentes que conservan lo ya importado en `sys.modules`. Sin `restart`, la app y el worker
  siguen ejecutando la versión anterior indefinidamente. Los dos síntomas vistos durante `007`
  fueron desconcertantes justamente porque el código en disco ya era correcto: el worker lanzaba
  `analyze() got an unexpected keyword argument 'orthophoto_path'` con ese parámetro ya presente, y
  la API devolvía `edge_modes: ["break","surface"]` con `sources.EDGE_MODES` ya de tres elementos.
  Cuidado con verificar usando `manage.py shell`: arranca un proceso nuevo y **siempre** muestra el
  código de disco, así que confirma lo contrario de lo que quieres comprobar. Verifica contra el
  proceso vivo (una petición real al endpoint).
- **Bundle JS.** El navegador carga `public/build/Road.js`, no el `.jsx`. `build_plugins` solo
  invoca webpack `elif not plugin.path_exists("public/build")` (`app/plugins/functions.py`), o sea
  que si el `build` ya existe **un restart no recompila nada**. Hay que correr
  `manage.py rebuildplugins` (no admite filtrar por plugin: reconstruye los ~19, ~40 s). Y el
  navegador cachea el bundle, así que después hace falta un hard reload (`cmd+shift+r`).
- **`rebuildplugins` no falla cuando webpack falla.** Sale con código 0 y su resumen puede incluso
  decir `[cached]` aunque el bundle no se haya escrito por un error de sintaxis. Visto durante
  `008`: un `SyntaxError` en `RoadPanel.jsx` dejó `build/` sin `Road.js` y el comando no se quejó.
  **Verifica siempre el artefacto, no el código de salida**:
  ```bash
  docker compose exec -T webapp grep -c "<texto nuevo>" \
    /webodm/coreplugins/road/public/build/Road.js
  ```
  Para ver el error real, `cd /webodm/coreplugins/road/public && npx webpack-cli` (sin `--config`:
  lo toma solo, y con `--config` explícito falla al resolver módulos desde el webpack-cli global).

## Tests

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.road.tests
```

A diferencia de `annotations` y `realign`, que usan un `tests.py` plano, aquí los tests viven en un
paquete `tests/`. Eso obliga a **reexportar las clases desde `tests/__init__.py`**: el runner de
Django prueba primero `loadTestsFromName` y solo si eso devuelve 0 tests intenta `discover()`, que
aquí revienta porque `coreplugins/` no tiene `__init__.py` (es un namespace package). Un módulo de
test nuevo que no se importe en `__init__.py` sencillamente no se ejecuta.

Guía de despliegue, cobertura y validación manual en
[`quickstart.md`](../../specs/005-road-metrics/quickstart.md).
