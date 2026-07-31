import L from 'leaflet';

/**
 * Dibujo de las etiquetas existentes sobre el mapa.
 *
 * La regla que gobierna este módulo es FR-010: **el radio del pincel es una medida sobre el
 * terreno**. Un grosor fijo en píxeles se vería igual a cualquier zoom y mentiría sobre lo que
 * el usuario pintó — a zoom alejado un trazo de 3 m aparentaría cubrir decenas de metros, que es
 * justo el caso que la spec recoge en sus Edge Cases. Por eso el grosor se recalcula en cada
 * cambio de zoom a partir de los metros por píxel de la proyección.
 */

// Circunferencia de la Tierra en el ecuador, la que usa Web Mercator. La resolución de la
// proyección a un zoom dado sale de aquí, y es exacta para EPSG:3857, no una aproximación.
const EQUATOR_METERS = 40075016.686;
const TILE_SIZE = 256;

// Ignorar no es una clase: se dibuja distinto a propósito, porque confundirlo con la clase 0
// arruinaría el entrenamiento (FR-014, FR-026) y el usuario debe poder verlo en el mapa.
export const ERASER_COLOR = '#ffffff';
export const ERASER_DASH = '4 4';

// El área revisada tampoco es una clase, y además suele abarcar media pantalla: va en gris neutro,
// con trazo largo discontinuo y casi sin relleno, para que se lea como un límite y no tape las
// etiquetas que hay dentro. El gris no compite con ninguna clase ni con el semáforo de `road`.
export const REVIEW_COLOR = '#9aa0a6';
export const REVIEW_DASH = '10 6';
// El negativo difícil se distingue por el relleno, no por el color: sigue siendo un área revisada,
// solo que una que interesa contar aparte (FR-043).
export const REVIEW_HARD_FILL_OPACITY = 0.18;
export const REVIEW_FILL_OPACITY = 0.05;

/** Metros de terreno que mide un píxel de pantalla al zoom actual, en esa latitud. */
export function metersPerPixel(map, lat){
  const zoom = map.getZoom();
  return EQUATOR_METERS * Math.cos(lat * Math.PI / 180) / (TILE_SIZE * Math.pow(2, zoom));
}

/**
 * Grosor en píxeles con el que dibujar un trazo de `radiusM` metros de radio.
 *
 * Es el diámetro, no el radio: Leaflet mide `weight` de borde a borde, así que usar el radio
 * pintaría la mitad de lo que el usuario dibujó y la máscara exportada no coincidiría con lo
 * que vio en pantalla.
 */
export function strokeWeightPx(map, radiusM, lat){
  const perPixel = metersPerPixel(map, lat);
  if (!perPixel) return 1;
  return Math.max(1, (2 * radiusM) / perPixel);
}

/** Color de una clase. `null` es la etiqueta de ignorar. */
export function classColor(classes, classIndex){
  if (classIndex === null || classIndex === undefined) return ERASER_COLOR;
  const found = (classes || []).find(c => c.index === classIndex);
  return found ? found.color : '#888888';
}

/**
 * Etiquetas en orden de composición ascendente (FR-012).
 *
 * El orden importa también al dibujar y no solo al rasterizar: si la última dibujada no quedara
 * encima en el mapa, el usuario vería algo distinto de lo que va a exportar.
 */
export function sortByOrder(labels){
  return (labels || []).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
}

function toLatLngs(geometry){
  return (geometry || []).map(p => [p[1], p[0]]);   // el almacén guarda [lon, lat]
}

function centerLat(geometry){
  if (!geometry || !geometry.length) return 0;
  return geometry.reduce((sum, p) => sum + p[1], 0) / geometry.length;
}

/**
 * Capa que mantiene dibujadas las etiquetas de una tarea.
 *
 * `Lib` se inyecta para poder probar el módulo sin el render SVG de Leaflet, que en jsdom no
 * produce nada observable.
 */
export function createLabelLayer(map, options = {}){
  const Lib = options.L || L;
  const group = Lib.layerGroup().addTo(map);
  const onSelect = options.onSelect || function(){};
  let current = [];
  let classes = [];
  let selectedId = null;

  function styleFor(label){
    const selected = label.id === selectedId;

    if (label.kind === 'review'){
      return {
        color: selected ? '#ffffff' : REVIEW_COLOR,
        weight: selected ? 4 : 2,
        fillColor: REVIEW_COLOR,
        fillOpacity: label.hard_negative ? REVIEW_HARD_FILL_OPACITY : REVIEW_FILL_OPACITY,
        dashArray: REVIEW_DASH
      };
    }

    const color = classColor(classes, label.class_index);
    const dashArray = label.class_index === null || label.class_index === undefined
      ? ERASER_DASH : null;

    if (label.kind === 'stroke'){
      return {
        color: color,
        weight: strokeWeightPx(map, label.radius_m || 0, centerLat(label.geometry)),
        opacity: selected ? 1 : 0.75,
        lineCap: 'round',
        lineJoin: 'round',
        dashArray: dashArray
      };
    }
    return {
      color: selected ? '#ffffff' : color,
      // La seleccionada se marca con un borde blanco más grueso y no con otro color de relleno:
      // el relleno **es** la clase, y cambiarlo haría dudar de qué clase tiene la etiqueta.
      weight: selected ? 4 : 2,
      fillColor: color,
      fillOpacity: selected ? 0.55 : 0.4,
      dashArray: dashArray
    };
  }

  function draw(){
    group.clearLayers();
    sortByOrder(current).forEach(label => {
      const latlngs = toLatLngs(label.geometry);
      if (latlngs.length < 2) return;
      const layer = label.kind === 'stroke'
        ? Lib.polyline(latlngs, styleFor(label))
        : Lib.polygon(latlngs, styleFor(label));
      layer.labelId = label.id;
      // El hit-test lo hace Leaflet, que ya sabe si un punto cae dentro de un polígono o sobre
      // una polilínea de grosor dado. Reimplementarlo aquí habría sido código propio para
      // resolver algo que la librería resuelve mejor.
      layer.on('click', e => {
        if (Lib.DomEvent) Lib.DomEvent.stop(e);
        onSelect(label, layer, e);
      });
      group.addLayer(layer);
    });
  }

  // El grosor de los trazos depende del zoom, así que hay que repintar cuando cambia. Sin esto
  // el trazo conservaría el grosor en píxeles del zoom anterior, que es exactamente el error
  // que FR-010 prohíbe.
  function onZoom(){ draw(); }
  map.on('zoomend', onZoom);

  return {
    setClasses(next){ classes = next || []; draw(); },
    setLabels(next){ current = next || []; draw(); },
    getLabels(){ return current; },
    setSelected(labelId){
      if (selectedId === labelId) return;
      selectedId = labelId;
      draw();
    },
    getSelected(){ return selectedId; },
    layerFor(labelId){
      return group.getLayers().find(l => l.labelId === labelId) || null;
    },
    redraw: draw,
    remove(){
      map.off('zoomend', onZoom);
      group.clearLayers();
      map.removeLayer(group);
    }
  };
}
