/* Estilo y construcción de la capa de máscara del modelo (`008` US1/US2, `research.md` D39).
 *
 * Separado del dibujo por la misma razón que `segmentStyle.js` y `widthTick.js`: siendo funciones
 * puras se prueban con jsdom, sin navegador ni mapa.
 *
 * La capa muestra **qué consideró calzada el modelo**, para que el usuario pueda contrastar el
 * ancho que se le reporta. En la calle de referencia el modelo marcó como calzada un descampado
 * de tierra contiguo a la vía; sin ver la máscara, esa desviación de metros es indetectable desde
 * la interfaz.
 */

import L from 'leaflet';
import { _ } from 'webodm/classes/gettext';

/* Azul deliberadamente **fuera** de la paleta del semáforo de `segmentStyle.colors()`
 * (`#2e9e4f` verde, `#e8b900` amarillo, `#d9422b` rojo, `#8a8a8a` gris). Esos colores significan
 * pendiente en el eje y ancho en las reglas; usar cualquiera de ellos aquí leería como una tercera
 * métrica que no existe (`FR-012`). */
export const MASK_COLOR = '#2b7fd4';

/* Translúcido de verdad: el propósito de la capa es **comparar** lo que el modelo dijo con la
 * ortofoto que hay debajo (`FR-011`). Un relleno opaco tapa justo la evidencia que se quiere
 * mostrar y vuelve la feature inútil. */
export const MASK_FILL_OPACITY = 0.35;

export function maskStyle(){
  return {
    color: MASK_COLOR,
    weight: 1,
    opacity: 0.9,
    fillColor: MASK_COLOR,
    fillOpacity: MASK_FILL_OPACITY,
    /* **No negociable.** `roadBridge` monta un manejo fino de clic y hover sobre los tramos —una
     * polilínea `hit` invisible de `weight: 20` por tramo, halos, `pinnedLayer`—. Un polígono
     * encima capturando eventos rompería los popups y el resaltado. La máscara es para mirarla. */
    interactive: false
  };
}

/** `L.GeoJSON` con los polígonos de calzada, o `null` si no hay ninguno que dibujar. */
export function buildMaskLayer(features){
  if (!Array.isArray(features) || features.length === 0) return null;
  return L.geoJSON({type: 'FeatureCollection', features}, {
    style: maskStyle,
    interactive: false
  });
}

/* Los tres estados que no son lo mismo (`FR-017`). Confundir «vacía» con «ausente» le haría creer
 * al usuario que el modelo no vio calzada en su calle cuando la verdad es que nunca se guardó
 * nada. */
export const MASK_STATE = {
  READY: 'ready',        // hay máscara y tiene calzada
  EMPTY: 'empty',        // el modelo corrió y no reconoció calzada: es un resultado
  MISSING: 'missing'     // no se guardó máscara: no es un resultado
};

export function maskState(document){
  if (!document) return MASK_STATE.MISSING;
  const features = document.features;
  if (!Array.isArray(features) || features.length === 0) return MASK_STATE.EMPTY;
  return MASK_STATE.READY;
}

/** Texto que acompaña a la capa, según el estado. Nunca presenta «ausente» como un resultado. */
export function maskMessage(state, resolutionM){
  if (state === MASK_STATE.MISSING){
    return _('Este análisis no guardó la máscara del modelo. Vuelve a calcularlo para obtenerla.');
  }
  if (state === MASK_STATE.EMPTY){
    return _('El modelo no reconoció calzada en este corredor.');
  }
  return resolutionAdvice(resolutionM);
}

/* El aviso de precisión (`FR-016`) toma la resolución de **los datos**, no de una constante de
 * este archivo: la máscara vuelve a la resolución nativa del modelo (medido: 20 cm/px aunque la
 * ortofoto sea de 5 cm/px), y un número escrito a mano aquí dejaría de ser cierto en cuanto el
 * modelo cambiara, sin que nadie se entere. */
export function resolutionAdvice(resolutionM){
  const value = Number(resolutionM);
  if (!isFinite(value) || value <= 0){
    return _('Aproximación del modelo: los bordes no son un contorno exacto de la calzada.');
  }
  return _('Aproximación a %(res)s cm por píxel: los bordes no son un contorno exacto de la calzada.')
    .replace('%(res)s', String(Math.round(value * 100)));
}
