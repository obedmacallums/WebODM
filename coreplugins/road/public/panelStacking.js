// Apilado de los paneles de plugin en el mapa: el último que se abre queda por encima.
//
// Todos los controles de plugin comparten la esquina `topright` con el mismo `z-index: 999
// !important` (convención de contours/viewshed/objdetect/realign), así que a igualdad de nivel
// decide el orden del DOM: el botón de un plugin puede acabar dibujado *dentro* del panel
// abierto de otro, que es más ancho. Darle a uno un número fijo más alto solo traslada el
// problema al siguiente plugin que haga lo mismo.
//
// Aquí el nivel se asigna al abrir y se devuelve al cerrar, de modo que el panel visible siempre
// gana sin que ningún plugin tenga que conocer a los demás. El contador vive en `window` porque
// cada plugin se empaqueta en su propio bundle: no hay módulo compartido entre ellos, y `window`
// es el único canal común.

const BASE_Z = 1000;
const COUNTER = '__webodmPluginPanelZ';

// Sube el contenedor del control por encima de cualquier otro panel de plugin abierto.
export function bringToFront(container){
  if (!container || !container.style) return null;
  const next = Math.max(window[COUNTER] || BASE_Z, BASE_Z) + 1;
  window[COUNTER] = next;
  // `setProperty` con la marca `important`: la regla del control la lleva, y un estilo inline
  // sin ella no la pisaría.
  container.style.setProperty('z-index', String(next), 'important');
  return next;
}

// Devuelve el contenedor a su nivel base (el del CSS), para que un panel cerrado no siga
// tapando a los botones vecinos.
export function sendToBack(container){
  if (!container || !container.style) return;
  container.style.removeProperty('z-index');
}
