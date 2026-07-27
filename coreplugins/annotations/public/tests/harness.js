/* Andamiaje mínimo para probar el JS del plugin en Node, sin runner ni dependencias nuevas
 * (Principio IV, nivel 0): `jsdom` y `leaflet` ya están en la imagen porque los usa el propio
 * build del core, y se resuelven subiendo desde esta carpeta hasta `/webodm/node_modules`.
 *
 * Los módulos del plugin se cargan tal cual están en `public/`, sin copiarlos ni adaptarlos: lo
 * único que se sustituye son los `import` que en producción resuelve webpack (`leaflet`,
 * `webodm/classes/plugins/API`, `webodm/classes/gettext`) y el jQuery global. Así lo que se
 * prueba es el archivo que se despliega, no una versión paralela que puede quedar desfasada.
 *
 * Estos tests los lanza `FrontendUnitTest` en `tests.py`, para que corran con el resto de la
 * suite del plugin (`webodm.sh test backend coreplugins.annotations.tests`).
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
  if (defaultClass){
    return out.replace('export default class', 'class') + '\nreturn ' + defaultClass[1] + ';';
  }
  return out.replace('export default {', 'return {');
}

/**
 * Carga `public/<relPath>` inyectando `stubs` ({nombre: valor}) como si fueran sus imports.
 * Devuelve lo que el módulo exporta por defecto.
 */
function loadModule(relPath, stubs = {}){
  const src = toEvaluable(fs.readFileSync(path.join(PLUGIN_PUBLIC_DIR, relPath), 'utf8'));
  const names = Object.keys(stubs);
  return new Function(...names, src)(...names.map(n => stubs[n]));
}

/** Mapa Leaflet real sobre un contenedor con tamaño fijo: jsdom reporta 0x0 y no proyectaría. */
function createMap(L, {width = 800, height = 600, center = [45, -122], zoom = 18} = {}){
  const el = document.createElement('div');
  document.body.appendChild(el);
  Object.defineProperty(el, 'clientWidth', {value: width});
  Object.defineProperty(el, 'clientHeight', {value: height});
  return L.map(el, {fadeAnimation: false, zoomAnimation: false}).setView(center, zoom);
}

// --- Mini-corredor de casos --------------------------------------------------------------------

let passed = 0;

function test(name, fn){
  try {
    fn();
    passed++;
    console.log('  ok - ' + name);
  } catch (e) {
    console.error('  FALLO - ' + name);
    console.error('    ' + (e && e.message ? e.message : e));
    if (e && e.stack) console.error(e.stack.split('\n').slice(1, 4).join('\n'));
    process.exitCode = 1;
  }
}

function summary(label){
  if (process.exitCode) console.error(label + ': hay comprobaciones fallidas');
  else console.log(label + ': ' + passed + ' comprobaciones OK');
}

module.exports = {setupDom, loadModule, createMap, test, summary};
