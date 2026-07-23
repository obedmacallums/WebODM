// Ajuste de una transformación de similitud 2D (traslación + rotación + escala uniforme)
// por mínimos cuadrados a partir de pares de puntos origen→destino.
//
// Módulo puro (sin Leaflet/React) para poder probarlo de forma ligera con Node en el host.
// El llamador proyecta lat/lng a un plano métrico (p. ej. `map.options.crs.project`) antes de
// pasar los pares aquí; los residuos y el RMSE salen en las mismas unidades de ese plano.
//
// Derivación (números complejos): con s = sx + i·sy, t = tx + i·ty, buscamos w = scale·e^{iθ}
// y traslación c que minimicen Σ|w·s + c − t|². La solución cerrada es
//   w = Σ conj(s−μs)·(t−μt) / Σ|s−μs|²,   c = μt − w·μs
// (equivalente al método de Umeyama para el caso 2D con escala).

const EPS = 1e-12;

// Aplica una transformación de similitud T a un punto (x, y).
export function applySimilarity(T, x, y) {
    return {
        x: T.scale * (T.cos * x - T.sin * y) + T.tx,
        y: T.scale * (T.sin * x + T.cos * y) + T.ty,
    };
}

// pairs: [{sx, sy, tx, ty}] en un plano métrico. useScale=true (default): similitud completa;
// false: transformación rígida (traslación+rotación, scale fijo en 1) — ver D9 en research.md.
// La rotación es idéntica en ambos modos (mismo numerador a/b, solo cambia la normalización).
// Devuelve { ok, degenerate, n, scale, rotation, rotationDeg, tx, ty, cos, sin,
//            residuals: [dist...], rmse }.
export function fitSimilarity(pairs, useScale = true) {
    const n = pairs.length;

    const base = {
        ok: false, degenerate: false, n,
        scale: 1, rotation: 0, rotationDeg: 0, tx: 0, ty: 0, cos: 1, sin: 0,
        residuals: [], rmse: null,
    };

    if (n === 0) {
        return { ...base, degenerate: true };
    }

    // Centroides.
    let musx = 0, musy = 0, mutx = 0, muty = 0;
    for (const p of pairs) { musx += p.sx; musy += p.sy; mutx += p.tx; muty += p.ty; }
    musx /= n; musy /= n; mutx /= n; muty /= n;

    let T;

    if (n === 1) {
        // Un solo par: únicamente traslación (rotación 0, escala 1) — FR-005.
        T = { scale: 1, cos: 1, sin: 0, tx: pairs[0].tx - pairs[0].sx, ty: pairs[0].ty - pairs[0].sy };
    } else {
        // Σ|s−μs|² y numerador complejo Σ conj(s−μs)·(t−μt).
        let sxx = 0; // Σ (dsx² + dsy²)
        let a = 0;   // parte real:  Σ (dsx·dtx + dsy·dty)
        let b = 0;   // parte imag.: Σ (dsx·dty − dsy·dtx)
        for (const p of pairs) {
            const dsx = p.sx - musx, dsy = p.sy - musy;
            const dtx = p.tx - mutx, dty = p.ty - muty;
            sxx += dsx * dsx + dsy * dsy;
            a += dsx * dtx + dsy * dty;
            b += dsx * dty - dsy * dtx;
        }

        if (sxx < EPS) {
            // Todos los orígenes coinciden: no se puede estimar escala/rotación (Edge Case).
            return { ...base, degenerate: true };
        }

        let scale, cos, sin;
        if (useScale) {
            const wx = a / sxx; // Re(w) = scale·cos θ
            const wy = b / sxx; // Im(w) = scale·sin θ
            scale = Math.hypot(wx, wy);
            if (scale < EPS) {
                return { ...base, degenerate: true };
            }
            cos = wx / scale;
            sin = wy / scale;
        } else {
            const norm = Math.hypot(a, b);
            if (norm < EPS) {
                return { ...base, degenerate: true };
            }
            scale = 1;
            cos = a / norm;
            sin = b / norm;
        }
        // c = μt − w·μs (w = scale·cos + i·scale·sin)
        const tx = mutx - (scale * cos * musx - scale * sin * musy);
        const ty = muty - (scale * sin * musx + scale * cos * musy);
        T = { scale, cos, sin, tx, ty };
    }

    // Residuos por punto (distancia destino ↔ imagen del origen) y RMSE.
    const residuals = [];
    let sumSq = 0;
    for (const p of pairs) {
        const q = applySimilarity(T, p.sx, p.sy);
        const dx = q.x - p.tx, dy = q.y - p.ty;
        const d = Math.hypot(dx, dy);
        residuals.push(d);
        sumSq += dx * dx + dy * dy;
    }
    const rmse = Math.sqrt(sumSq / n);
    const rotation = Math.atan2(T.sin, T.cos);

    return {
        ok: true, degenerate: false, n,
        scale: T.scale, rotation, rotationDeg: rotation * 180 / Math.PI,
        tx: T.tx, ty: T.ty, cos: T.cos, sin: T.sin,
        residuals, rmse,
    };
}
