/* Andamiaje mínimo para probar el JS del plugin en Node, sin runner ni dependencias nuevas
 * (FR-037): `jsdom` y `leaflet` ya están en la imagen porque los usa el propio build del core, y
 * se resuelven subiendo desde esta carpeta hasta `/webodm/node_modules`.
 *
 * Los módulos del plugin se cargan tal cual están en `public/`, sin copiarlos ni adaptarlos: lo
 * único que se sustituye son los `import` que en producción resuelve webpack (`leaflet`,
 * `webodm/classes/plugins/API`). Así lo que se prueba es el archivo que se despliega, no una
 * versión paralela que puede quedar desfasada.
 *
 * Copiado de `coreplugins/road/public/tests/harness.js`. Los lanza `FrontendUnitTest` en
 * `tests/test_frontend.py` para que corran con el resto de la suite del plugin.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const PLUGIN_PUBLIC_DIR = path.join(__dirname, '..');

/** DOM global antes de cargar Leaflet: al importarse toca `window` directamente. */
function setupDom(html = '<!doctype html><html><body></body></html>'){
  const dom = new JSDOM(html, {pretendToBeVisual: true});
  global.window = dom.window;
  global.document = dom.window.document;
  global.navigator = dom.window.navigator;
  return dom;
}

/** Un módulo ES del plugin convertido a algo que Node pueda evaluar. */
function toEvaluable(src){
  // Las líneas de `import` se quitan enteras: cada dependencia entra como parámetro de la
  // función, así el test decide qué stub recibe cada módulo.
  let out = src.replace(/^[ \t]*import[^\n]*\n/gm, '');

  const defaultClass = out.match(/export default class (\w+)/);
  const named = [
    ...Array.from(out.matchAll(/export\s+function\s+(\w+)/g), m => m[1]),
    ...Array.from(out.matchAll(/export\s+const\s+(\w+)/g), m => m[1])
  ];

  out = out.replace(/export\s+function\s/g, 'function ')
           .replace(/export\s+const\s/g, 'const ');

  if (defaultClass){
    out = out.replace('export default class', 'class');
    const exported = [defaultClass[1], ...named];
    return out + '\nreturn Object.assign(' + defaultClass[1] + ', {' + exported.join(', ') + '});';
  }
  if (named.length){
    return out + '\nreturn {' + named.join(', ') + '};';
  }
  return out.replace('export default {', 'return {');
}

/**
 * Carga `public/<relPath>` inyectando `stubs` ({nombre: valor}) como si fueran sus imports.
 * Devuelve lo que el módulo exporta.
 */
function loadModule(relPath, stubs = {}){
  const src = toEvaluable(fs.readFileSync(path.join(PLUGIN_PUBLIC_DIR, relPath), 'utf8'));
  const names = Object.keys(stubs);
  return new Function(...names, src)(...names.map(n => stubs[n]));
}

/** Mapa Leaflet real sobre un contenedor con tamaño fijo: jsdom reporta 0x0 y no proyectaría. */
function createMap(L, {width = 800, height = 600, center = [-33.35, -70.71], zoom = 19} = {}){
  const el = document.createElement('div');
  document.body.appendChild(el);
  Object.defineProperty(el, 'clientWidth', {value: width});
  Object.defineProperty(el, 'clientHeight', {value: height});
  return L.map(el, {fadeAnimation: false, zoomAnimation: false}).setView(center, zoom);
}

/**
 * Un `L` que proyecta de verdad pero no dibuja.
 *
 * jsdom no implementa el render SVG, así que añadir un `L.Polygon` real a un mapa revienta dentro
 * de `getRenderer`. El doble delega **todo** en Leaflet menos la creación de capas: las
 * proyecciones, el zoom y los eventos del mapa siguen siendo los auténticos, que es lo que estos
 * tests miden. Lo que se pierde —los píxeles pintados— no era observable en Node de ninguna forma.
 */
function stubLayers(L){
  // Emisor de eventos con la interfaz de Leaflet (`on`/`off`/`fire`): el código de producción
  // engancha `remove`, `mouseover`, `drag`, `contextmenu`… sobre las capas, así que un doble sin
  // eventos no probaría la parte que más importa de la edición.
  class FakeEvented {
    constructor(){ this._events = {}; }
    on(name, fn){ (this._events[name] = this._events[name] || []).push(fn); return this; }
    off(name, fn){
      const list = this._events[name];
      if (list){
        const i = list.indexOf(fn);
        if (i !== -1) list.splice(i, 1);
      }
      return this;
    }
    fire(name, data){
      (this._events[name] || []).slice()
        .forEach(fn => fn(Object.assign({target: this, originalEvent: {}}, data)));
      return this;
    }
    addTo(map){ this._map = map; return this; }
  }

  class FakePath extends FakeEvented {
    constructor(latlngs, options){
      super();
      this.options = Object.assign({}, options);
      this.setLatLngs(latlngs);
    }
    // Leaflet convierte lo que reciba a objetos `LatLng`; el doble hace lo mismo, porque el
    // código de producción lee `.lat`/`.lng` de lo que devuelve `getLatLngs()`.
    _normalize(latlngs){ return (latlngs || []).map(ll => L.latLng(ll)); }
    setLatLngs(latlngs){ this._latlngs = this._normalize(latlngs); return this; }
    getLatLngs(){ return this._latlngs; }
    setStyle(options){ Object.assign(this.options, options); return this; }
  }

  class FakePolyline extends FakePath {}

  class FakePolygon extends FakePath {
    // `getLatLngs()` de un polígono devuelve un array de **anillos**, no de vértices. Sin esta
    // diferencia el doble no distinguiría un polígono de una polilínea, que es justo lo que el
    // editor tiene que tratar aparte para saber si el mínimo son 3 vértices o 2.
    _normalize(latlngs){
      const list = latlngs || [];
      const nested = list.length && Array.isArray(list[0]) && Array.isArray(list[0][0]);
      const rings = nested ? list : [list];
      return rings.map(ring => ring.map(ll => L.latLng(ll)));
    }
  }

  class FakeMarker extends FakeEvented {
    constructor(latlng, options){
      super();
      this._latlng = latlng;
      this.options = Object.assign({}, options);
    }
    getLatLng(){ return this._latlng; }
    setLatLng(latlng){ this._latlng = latlng; return this; }
  }

  class FakeLayerGroup extends FakeEvented {
    constructor(){ super(); this._layers = []; }
    addLayer(layer){ this._layers.push(layer); return this; }
    clearLayers(){ this._layers = []; return this; }
    getLayers(){ return this._layers; }
  }

  return Object.assign(Object.create(L), {
    Polyline: FakePolyline,
    Polygon: FakePolygon,
    polyline: (latlngs, options) => new FakePolyline(latlngs, options),
    polygon: (latlngs, options) => new FakePolygon(latlngs, options),
    marker: (latlng, options) => new FakeMarker(latlng, options),
    layerGroup: () => new FakeLayerGroup()
  });
}

// --- Mini-corredor de casos --------------------------------------------------------------------

let passed = 0;
const pending = [];

function report(name, error){
  if (!error){
    passed++;
    console.log('  ok - ' + name);
    return;
  }
  console.error('  FALLO - ' + name);
  console.error('    ' + (error && error.message ? error.message : error));
  if (error && error.stack) console.error(error.stack.split('\n').slice(1, 4).join('\n'));
  process.exitCode = 1;
}

/** Acepta casos síncronos y `async`: un caso que devuelve promesa se espera antes del resumen. */
function test(name, fn){
  try {
    const result = fn();
    if (result && typeof result.then === 'function'){
      pending.push(result.then(() => report(name), e => report(name, e)));
      return;
    }
    report(name);
  } catch (e) {
    report(name, e);
  }
}

function assert(condition, message){
  if (!condition) throw new Error(message || 'condición falsa');
}

function assertClose(actual, expected, tolerance, message){
  if (Math.abs(actual - expected) > tolerance){
    throw new Error((message || 'valor inesperado') +
      ': ' + actual + ' no está a ' + tolerance + ' de ' + expected);
  }
}

function summary(label){
  // Se espera a los casos asíncronos antes de dar el veredicto: sin esto, un caso `async` que
  // falla imprimiría su error **después** del resumen en verde, y quien mire por encima leería
  // que todo pasó.
  return Promise.all(pending).then(function(){
    if (process.exitCode) console.error(label + ': hay comprobaciones fallidas');
    else console.log(label + ': ' + passed + ' comprobaciones OK');
  });
}

module.exports = {setupDom, loadModule, createMap, stubLayers, test, assert, assertClose, summary};
