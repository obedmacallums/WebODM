/* Apilado de paneles entre plugins: el último que se abre queda por encima.
 *
 * La alternativa —un z-index fijo más alto para este plugin— solo traslada el problema al
 * siguiente que haga lo mismo, así que lo que se prueba aquí es que el orden lo decide quién
 * abrió más tarde, y que cerrar devuelve el control a su nivel base.
 */
const assert = require('assert');
const {setupDom, loadModule, test, summary} = require('./harness');

setupDom();
const stacking = loadModule('panelStacking.js', {});

function control(){
  const el = document.createElement('div');
  // Igual que en el CSS del control: sin la marca `important` un inline no lo pisaría.
  el.style.setProperty('z-index', '999', 'important');
  document.body.appendChild(el);
  return el;
}

const zOf = (el) => parseInt(el.style.getPropertyValue('z-index'), 10);

test('abrir un panel lo pone por encima del nivel base de los controles', () => {
  delete window.__webodmPluginPanelZ;
  const a = control();
  stacking.bringToFront(a);
  assert.ok(zOf(a) > 999, 'quedó en ' + zOf(a));
  assert.strictEqual(a.style.getPropertyPriority('z-index'), 'important',
    'sin `important` la regla del control seguiría ganando');
});

test('el último en abrirse gana, sin que ningún plugin conozca a los otros', () => {
  delete window.__webodmPluginPanelZ;
  const primero = control(), segundo = control();
  stacking.bringToFront(primero);
  stacking.bringToFront(segundo);
  assert.ok(zOf(segundo) > zOf(primero),
    'segundo=' + zOf(segundo) + ' primero=' + zOf(primero));

  // Y si se vuelve al primero, vuelve a mandar: el orden no queda congelado.
  stacking.bringToFront(primero);
  assert.ok(zOf(primero) > zOf(segundo));
});

test('cerrar devuelve el control a su nivel base', () => {
  delete window.__webodmPluginPanelZ;
  const el = control();
  stacking.bringToFront(el);
  stacking.sendToBack(el);
  assert.strictEqual(el.style.getPropertyValue('z-index'), '',
    'un panel cerrado no debe seguir tapando a los botones vecinos');
});

test('el contador es compartido entre bundles vía window', () => {
  // Cada plugin se empaqueta por separado: dos copias del módulo tienen que seguir turnándose.
  delete window.__webodmPluginPanelZ;
  const otroPlugin = loadModule('panelStacking.js', {});
  const mio = control(), ajeno = control();
  stacking.bringToFront(mio);
  otroPlugin.bringToFront(ajeno);
  assert.ok(zOf(ajeno) > zOf(mio),
    'una copia del módulo ignoró lo que había hecho la otra: ' + zOf(ajeno) + ' vs ' + zOf(mio));
});

test('un contenedor ausente no rompe nada', () => {
  assert.strictEqual(stacking.bringToFront(null), null);
  stacking.sendToBack(undefined);
});

summary('panelStacking');
