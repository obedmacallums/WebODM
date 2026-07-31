"""Reparto train/val por zonas geográficas (D19).

**El split aleatorio por tesela está prohibido aquí**, y no por purismo: con teselas solapadas
64 px, una tesela de train y su vecina de val comparten píxeles literales. El modelo los ha visto
durante el entrenamiento, la métrica de validación sube y la subida no significa nada. Es el modo
más fácil de convencerse de que un modelo funciona cuando no funciona.

Así que se reparten **bloques** de teselas contiguas, no teselas sueltas, y además se abre un
pasillo: una tesela de train que solape con cualquier bloque de val se descarta. Con eso ningún
píxel de validación aparece jamás en el entrenamiento, que es la propiedad que se quiere poder
afirmar sin matices.

El reparto es determinista a partir del identificador del dataset: dos exportaciones del mismo
dataset dan el mismo split, así que las métricas de dos entrenamientos son comparables (FR-031).
"""

import math
import random

TRAIN = 'train'
VAL = 'val'

DEFAULT_BLOCK_TILES = 4
DEFAULT_VAL_FRACTION = 0.20


def block_of(row, col, block_tiles):
    return (row // block_tiles, col // block_tiles)


def neighbour_reach(tile_size_px, stride_px):
    """Cuántas teselas de distancia alcanza el solape.

    Las teselas `r` y `r + k` comparten píxeles si `k * stride < tile_size`. Sin solape el stride
    iguala al tamaño, el alcance es 0 y no hace falta pasillo — el caso se resuelve solo.
    """
    if stride_px <= 0:
        return 0
    return max(0, int(math.ceil(float(tile_size_px) / stride_px)) - 1)


def assign_blocks(block_keys, val_fraction, seed):
    """`{bloque: 'train'|'val'}` sobre los bloques dados.

    Se baraja con una semilla estable y se corta, en vez de decidir bloque a bloque con una
    probabilidad: así la fracción pedida se cumple de verdad y no aproximadamente. Con pocos
    bloques —una ortofoto pequeña— la diferencia entre las dos cosas es enorme.
    """
    ordered = sorted(block_keys)
    if not ordered:
        return {}

    count = len(ordered)
    shuffled = list(ordered)
    random.Random(seed).shuffle(shuffled)

    wanted = int(round(float(val_fraction) * count))
    if val_fraction > 0 and count >= 2:
        # Siempre al menos un bloque de val y al menos uno de train: un split que deja un lado
        # vacío no es un split, y descubrirlo después de entrenar cuesta caro.
        wanted = max(1, min(wanted, count - 1))
    else:
        wanted = max(0, min(wanted, count))

    val = set(shuffled[:wanted])
    return {key: (VAL if key in val else TRAIN) for key in ordered}


def assign_tiles(tile_keys, block_tiles=DEFAULT_BLOCK_TILES,
                 val_fraction=DEFAULT_VAL_FRACTION, seed=0, reach=1):
    """`{(task_id, fila, columna): 'train'|'val'|None}`.

    `None` es una tesela de train descartada por el pasillo. Se devuelve explícitamente en vez de
    omitirla para que quien llama pueda contarlas y decir cuántas costó la garantía.

    Los bloques se numeran **por tarea**: dos ortofotos distintas no comparten rejilla, y mezclar
    sus índices habría puesto en el mismo bloque sitios que están a kilómetros.
    """
    block_keys = set()
    for task_id, row, col in tile_keys:
        block_keys.add((task_id,) + block_of(row, col, block_tiles))

    splits = assign_blocks(block_keys, val_fraction, seed)

    result = {}
    for key in tile_keys:
        task_id, row, col = key
        own = splits.get((task_id,) + block_of(row, col, block_tiles))

        if own == VAL:
            result[key] = VAL
            continue

        result[key] = TRAIN
        for delta_row in range(-reach, reach + 1):
            for delta_col in range(-reach, reach + 1):
                neighbour = (task_id,) + block_of(row + delta_row, col + delta_col, block_tiles)
                if splits.get(neighbour) == VAL:
                    result[key] = None
                    break
            if result[key] is None:
                break

    return result


def summarize(assignments):
    """`{train, val, dropped, val_fraction}` de un reparto ya hecho."""
    train = sum(1 for v in assignments.values() if v == TRAIN)
    val = sum(1 for v in assignments.values() if v == VAL)
    dropped = sum(1 for v in assignments.values() if v is None)
    total = train + val
    return {
        'train': train,
        'val': val,
        'dropped_by_gutter': dropped,
        'val_fraction': round(float(val) / total, 4) if total else 0.0,
    }
