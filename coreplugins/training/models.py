"""Entidades puras del plugin (`data-model.md`), sin ORM de Django.

Ninguna entidad es un modelo de Django a propósito: el plugin no añade migraciones (Principio I).
Un dataset es un diccionario JSON que vive en `GlobalDataStore` y una etiqueta es un diccionario
JSON que vive en un fichero. Este módulo es lo único que decide qué forma válida tienen, de modo
que la API y el exportador comparten una sola definición.

La validación devuelve `ValidationError` con un `code`, no con un mensaje: `contracts/rest-api.md`
fija que el frontend distingue por `code` y muestra `error`, así que cambiar la redacción de un
mensaje no puede romper la interfaz.
"""

import datetime
import math
import uuid

SCHEMA_VERSION = 2

# 255 significa «no revisado» y no puede ser el índice de ninguna clase (FR-026). Es la convención
# `ignore_index` de PyTorch, que es exactamente por lo que vale ese número y no otro.
IGNORE_INDEX = 255

# 0 es el fondo, y es una etiqueta real: terreno que alguien miró y declaró que no es camino. No
# confundirlo con 255 es el punto del que depende la calidad del dataset entero (FR-040).
BACKGROUND_INDEX = 0

DEFAULT_RESOLUTION_CM_PX = 10.0   # FR-005
DEFAULT_TILE_SIZE_PX = 512        # FR-024
# El solape por defecto es una **fracción** de la tesela, no 64 px fijos: sobre la tesela de 512 de
# la especificación da exactamente los 64 pedidos, y sobre una tesela pequeña no degenera. Con un
# valor fijo, un dataset de 64 px de tesela habría heredado 64 px de solape, o sea paso 1 px y una
# rejilla de decenas de miles de teselas sobre el mismo sitio.
DEFAULT_TILE_OVERLAP_FRACTION = 0.125   # FR-039: 64 / 512
DEFAULT_MIN_REVIEWED_FRACTION = 0.90  # FR-041
DEFAULT_MIN_VALID_FRACTION = 0.80     # FR-027: como mucho un 20 % sin datos

DEFAULT_ELEVATION_SOURCE = 'dtm'  # FR-044
ELEVATION_SOURCES = ('dtm', 'dsm', 'none')

DEFAULT_VAL_FRACTION = 0.20       # FR-042
DEFAULT_SPLIT_BLOCK_TILES = 4     # FR-042

# Ancho total por defecto de un camino trazado por su línea central (FR-011b). 12 m es el ancho
# típico de una pista minera de doble sentido; el anotador lo ajusta por trazo.
DEFAULT_STROKE_WIDTH_M = 12.0

PIXEL_DTYPES = ('float32', 'uint16')
DEFAULT_PIXEL_DTYPE = 'float32'

KIND_POLYGON = 'polygon'
KIND_STROKE = 'stroke'
KIND_REVIEW = 'review'
KINDS = (KIND_POLYGON, KIND_STROKE, KIND_REVIEW)

SOURCE_MANUAL = 'manual'
SOURCE_IMPORT = 'import'
SOURCE_MODEL = 'model'
# Etiqueta creada por selección asistida (`010`). Es una etiqueta corriente en todo lo demás —
# `kind` sigue siendo `polygon`— y por eso el contrato del paquete exportado no cambia. La marca
# sirve para poder medir más adelante la calidad de la asistencia sin volver a etiquetar, y deja
# `SOURCE_MODEL` libre para lo que sí produce un modelo (fase 3 de `009`).
SOURCE_ASSISTED = 'assisted'
SOURCES = (SOURCE_MANUAL, SOURCE_IMPORT, SOURCE_MODEL, SOURCE_ASSISTED)
# Las que un cliente puede declarar. Ver `validate_source`.
CLIENT_SOURCES = (SOURCE_MANUAL, SOURCE_ASSISTED)

# --- Ajustes de selección asistida (`010`) -----------------------------------------------
#
# Los nombres se definen aquí y los píxeles de paso que les corresponden en `superpixels.py`. La
# separación es a propósito: este módulo lo importan la API y el exportador y tiene que poder
# cargarse sin rasterio ni scikit-image, que es justo lo que `superpixels` arrastra.
# `tests/test_superpixels.py` comprueba que las dos listas no se separen.
GRANULARITIES = ('fine', 'medium', 'coarse')
DEFAULT_GRANULARITY = 'medium'
DEFAULT_TOLERANCE = 0.0          # 0 selecciona exactamente una región
DEFAULT_ELEVATION_WEIGHT = 1.0   # 0 desactiva los canales de terreno

# Paleta por defecto de las clases. Evita deliberadamente la escala verde/amarillo/rojo con la que
# `road` pinta la pendiente (FR-007): un usuario con los dos plugins abiertos sobre el mismo mapa
# leería un tramo rojo de `road` como una clase de este plugin.
DEFAULT_CLASS_COLORS = [
    '#4a4a4a',  # 0 — fondo, gris neutro
    '#1f78ff',  # azul
    '#b15dff',  # violeta
    '#00c2c7',  # cian
    '#ff7ac8',  # rosa
    '#8c6d3f',  # marrón
]

# Grados de latitud por metro. La Tierra no es una esfera perfecta y esto es una aproximación, pero
# se usa solo para la tolerancia de `simplify` (FR-015), donde un 0,5 % de error no cambia qué
# vértice sobrevive.
_METERS_PER_DEGREE = 111320.0


class ValidationError(ValueError):
    """Error de validación con el `code` que la API expone."""

    def __init__(self, message, code, **extra):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra


def now_iso():
    return datetime.datetime.utcnow().isoformat() + 'Z'


# --- Clases ------------------------------------------------------------------------------

def normalize_classes(raw):
    """Valida y normaliza la lista de clases de un dataset (FR-003, FR-004, FR-007).

    Los índices se exigen consecutivos desde 0 y no se reasignan en silencio: el índice es lo que
    acaba grabado en las máscaras y en los metadatos del modelo entrenado, así que corregirlo por
    detrás produciría un dataset cuyas máscaras no coinciden con lo que el usuario cree haber
    definido.
    """
    if not isinstance(raw, (list, tuple)):
        raise ValidationError('Las clases deben ser una lista.', 'too_few_classes')
    if len(raw) < 2:
        raise ValidationError('Un dataset necesita al menos dos clases: el fondo y una más.',
                              'too_few_classes')

    classes = []
    names = set()
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError('Cada clase debe ser un objeto con índice y nombre.',
                                  'bad_class_indexes')
        try:
            index = int(item.get('index', position))
        except (TypeError, ValueError):
            raise ValidationError('El índice de clase debe ser un entero.', 'bad_class_indexes')

        name = str(item.get('name') or '').strip()
        if not name:
            raise ValidationError('Toda clase necesita un nombre.', 'bad_class_indexes')
        if name in names:
            raise ValidationError('Nombre de clase repetido: {}'.format(name),
                                  'bad_class_indexes')
        names.add(name)

        if index == IGNORE_INDEX:
            raise ValidationError(
                'El índice {} está reservado para «sin etiquetar».'.format(IGNORE_INDEX),
                'bad_class_indexes')

        color = str(item.get('color') or '').strip() or _default_color(index)
        classes.append({'index': index, 'name': name, 'color': color})

    indexes = [c['index'] for c in classes]
    if sorted(indexes) != list(range(len(classes))):
        raise ValidationError(
            'Los índices de clase deben ser consecutivos desde 0; llegaron {}.'.format(
                sorted(indexes)),
            'bad_class_indexes')

    classes.sort(key=lambda c: c['index'])
    return classes


def _default_color(index):
    if 0 <= index < len(DEFAULT_CLASS_COLORS):
        return DEFAULT_CLASS_COLORS[index]
    # Rueda de tonos evitando el verde-amarillo-rojo (30°–150°) que usa `road`.
    hue = (200 + index * 37) % 360
    if 30 <= hue <= 150:
        hue = (hue + 180) % 360
    return _hsl_to_hex(hue, 0.62, 0.52)


def _hsl_to_hex(h, s, light):
    c = (1 - abs(2 * light - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = light - c / 2
    rgb = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return '#{:02x}{:02x}{:02x}'.format(*[int(round((v + m) * 255)) for v in rgb])


def class_by_index(dataset, index):
    for c in dataset.get('classes') or []:
        if c['index'] == index:
            return c
    return None


# --- Dataset -----------------------------------------------------------------------------

def make_dataset(name, classes, tasks, resolution_cm_px=None, tile_size_px=None,
                 min_reviewed_fraction=None, min_valid_fraction=None, dataset_id=None,
                 created_by=None, tile_overlap_px=None, elevation_source=None,
                 val_fraction=None, split_block_tiles=None, pixel_dtype=None,
                 stroke_width_m=None):
    """Construye un dataset validado (`data-model.md` §Dataset)."""
    name = str(name or '').strip()
    if not name:
        raise ValidationError('El dataset necesita un nombre.', 'bad_name')

    resolution = validate_positive(resolution_cm_px, DEFAULT_RESOLUTION_CM_PX,
                                  'La resolución debe ser mayor que cero.', 'bad_resolution')
    tile_size = int(validate_positive(tile_size_px, DEFAULT_TILE_SIZE_PX,
                                     'El tamaño de tesela debe ser mayor que cero.',
                                     'bad_tile_size'))
    overlap = validate_overlap(tile_overlap_px, tile_size)

    source = str(elevation_source or DEFAULT_ELEVATION_SOURCE).strip().lower()
    if source not in ELEVATION_SOURCES:
        raise ValidationError(
            'La fuente de elevación debe ser una de {}.'.format(', '.join(ELEVATION_SOURCES)),
            'bad_elevation_source')

    dtype = str(pixel_dtype or DEFAULT_PIXEL_DTYPE).strip().lower()
    if dtype not in PIXEL_DTYPES:
        raise ValidationError(
            'El tipo de píxel debe ser uno de {}.'.format(', '.join(PIXEL_DTYPES)),
            'bad_pixel_dtype')

    return {
        'id': dataset_id or str(uuid.uuid4()),
        'name': name[:255],
        'created_at': now_iso(),
        'created_by': created_by,
        'resolution_cm_px': resolution,
        'tile_size_px': tile_size,
        'tile_overlap_px': overlap,
        'elevation_source': source,
        'pixel_dtype': dtype,
        'classes': normalize_classes(classes),
        'tasks': normalize_tasks(tasks),
        'assist': default_assist(),
        'min_reviewed_fraction': validate_fraction(min_reviewed_fraction, DEFAULT_MIN_REVIEWED_FRACTION,
                                           'min_reviewed_fraction'),
        'min_valid_fraction': validate_fraction(min_valid_fraction, DEFAULT_MIN_VALID_FRACTION,
                                        'min_valid_fraction'),
        'val_fraction': validate_fraction(val_fraction, DEFAULT_VAL_FRACTION, 'val_fraction'),
        'split_block_tiles': int(validate_positive(
            split_block_tiles, DEFAULT_SPLIT_BLOCK_TILES,
            'El bloque de split debe ser un número de teselas mayor que cero.',
            'bad_split_block')),
        'stroke_width_m': validate_positive(
            stroke_width_m, DEFAULT_STROKE_WIDTH_M,
            'El ancho por defecto del trazo debe ser mayor que cero.', 'bad_stroke_width'),
        'schema_version': SCHEMA_VERSION,
    }


def default_overlap(tile_size_px):
    return max(0, min(int(int(tile_size_px) * DEFAULT_TILE_OVERLAP_FRACTION),
                      int(tile_size_px) - 1))


def validate_overlap(value, tile_size_px):
    """Solape en píxeles, acotado a `tile_size - 1`.

    El tope no es defensivo por defecto: un solape igual al tamaño daría paso cero y una rejilla
    infinita sobre el mismo punto, así que se rechaza en vez de recortarlo en silencio.
    """
    if value is None or value == '':
        return default_overlap(tile_size_px)
    try:
        overlap = int(value)
    except (TypeError, ValueError):
        raise ValidationError('El solape debe ser un número entero de píxeles.', 'bad_overlap')
    if overlap < 0 or overlap >= int(tile_size_px):
        raise ValidationError(
            'El solape debe estar entre 0 y {} px.'.format(int(tile_size_px) - 1), 'bad_overlap')
    return overlap


def validate_positive(value, default, message, code):
    if value is None or value == '':
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(message, code)
    if not math.isfinite(number) or number <= 0:
        raise ValidationError(message, code)
    return number


def validate_fraction(value, default, field):
    if value is None or value == '':
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError('{} debe ser un número entre 0 y 1.'.format(field), 'bad_fraction')
    if not 0 <= number <= 1:
        raise ValidationError('{} debe ser un número entre 0 y 1.'.format(field), 'bad_fraction')
    return number


def validate_source(value):
    """Procedencia declarada por el cliente al crear una etiqueta.

    Solo se aceptan las dos que un cliente puede producir de verdad: a mano o con la selección
    asistida. `import` y `model` las escribe el servidor, y dejar que el navegador las declarase
    permitiría marcar como salida de un modelo algo dibujado a mano — o al revés. La procedencia
    solo vale para algo si no se puede falsear.
    """
    source = str(value or SOURCE_MANUAL).strip().lower()
    if source not in CLIENT_SOURCES:
        raise ValidationError(
            'La procedencia debe ser una de {}.'.format(', '.join(CLIENT_SOURCES)), 'bad_source')
    return source


def default_assist():
    """Ajustes de selección asistida por defecto (`010/data-model.md`)."""
    return {
        'granularity': DEFAULT_GRANULARITY,
        'tolerance': DEFAULT_TOLERANCE,
        'elevation_weight': DEFAULT_ELEVATION_WEIGHT,
    }


def normalize_assist(raw, current=None):
    """Valida el bloque `assist` de un dataset y devuelve uno completo.

    `current` permite aplicar un cambio parcial —la interfaz mueve un control cada vez— sin que los
    otros dos ajustes se pierdan por no venir en la petición.

    **Ninguno de los tres toca las etiquetas ya guardadas** (FR-023): describen cómo se calcularán
    las selecciones siguientes, no lo que el usuario ya decidió. Cambiarlos sí invalida la caché de
    mapas de regiones, pero eso sale gratis: los tres forman parte de la clave.
    """
    assist = dict(current or default_assist())
    if raw is None:
        return assist
    if not isinstance(raw, dict):
        raise ValidationError('Los ajustes de asistencia deben ser un objeto.', 'bad_settings')

    if 'granularity' in raw and raw['granularity'] is not None:
        granularity = str(raw['granularity']).strip().lower()
        if granularity not in GRANULARITIES:
            raise ValidationError(
                'La granularidad debe ser una de {}.'.format(', '.join(GRANULARITIES)),
                'bad_settings')
        assist['granularity'] = granularity

    for field in ('tolerance', 'elevation_weight'):
        if field in raw and raw[field] is not None:
            assist[field] = validate_unit_interval(raw[field], field)

    return assist


def validate_unit_interval(value, field):
    """Número en `[0, 1]`, o `ValidationError` con el código que fija el contrato."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError('{} debe ser un número entre 0 y 1.'.format(field), 'bad_settings')
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValidationError('{} debe ser un número entre 0 y 1.'.format(field), 'bad_settings')
    return number


def normalize_tasks(raw):
    """Lista de referencias a tareas del core (`data-model.md` §Tarea del dataset).

    `available` **no** se guarda: se calcula al leer (`store.describe_tasks`). Persistirlo daría un
    valor obsoleto en cuanto el usuario borrase la tarea por otra vía.
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValidationError('El dataset necesita al menos una tarea.', 'no_tasks')

    tasks = []
    seen = set()
    for item in raw:
        if isinstance(item, dict):
            task_id = str(item.get('task_id') or item.get('id') or '').strip()
            project_id = item.get('project_id')
        else:
            task_id, project_id = str(item).strip(), None
        if not task_id:
            raise ValidationError('Falta el identificador de una tarea.', 'no_tasks')
        if task_id in seen:
            continue
        seen.add(task_id)
        tasks.append({
            'task_id': task_id,
            'project_id': int(project_id) if project_id is not None else None,
            'added_at': now_iso(),
        })
    return tasks


def dataset_has_task(dataset, task_id):
    return any(t['task_id'] == str(task_id) for t in dataset.get('tasks') or [])


def with_defaults(dataset):
    """Rellena al leer los campos que un dataset de esquema 1 no tenía.

    Se hace **al leer** y no con una migración que reescriba el fichero porque un dataset guardado
    es el registro de lo que el usuario decidió; completarlo en memoria da compatibilidad sin
    inventar decisiones en disco. Si mañana cambia un valor por defecto, los datasets viejos lo
    heredan en vez de quedarse anclados a la elección de hoy.

    El único campo que cambia de nombre es `min_labeled_fraction` -> `min_reviewed_fraction`: mide
    lo mismo —lo que no es 255— pero ahora esa fracción la produce el área revisada, así que el
    valor viejo (0,01) sería un umbral absurdo y **no** se arrastra.
    """
    if not isinstance(dataset, dict):
        return dataset

    tile_size = int(dataset.get('tile_size_px') or DEFAULT_TILE_SIZE_PX)
    dataset.setdefault('tile_overlap_px', default_overlap(tile_size))
    dataset.setdefault('elevation_source', DEFAULT_ELEVATION_SOURCE)
    dataset.setdefault('pixel_dtype', DEFAULT_PIXEL_DTYPE)
    dataset.setdefault('min_reviewed_fraction', DEFAULT_MIN_REVIEWED_FRACTION)
    dataset.setdefault('val_fraction', DEFAULT_VAL_FRACTION)
    dataset.setdefault('split_block_tiles', DEFAULT_SPLIT_BLOCK_TILES)
    dataset.setdefault('stroke_width_m', DEFAULT_STROKE_WIDTH_M)
    # Un dataset creado antes de `010` no tiene el bloque. Se completa al leer, como todo lo demás:
    # el documento en disco sigue siendo el registro de lo que el usuario decidió.
    dataset['assist'] = normalize_assist(dataset.get('assist'), default_assist())

    if dataset.get('schema_version', 1) < 2:
        # El umbral de píxeles válidos sube de 0,50 a 0,80 (FR-027): «como mucho un 20 % sin
        # datos». Un dataset viejo con el valor por defecto antiguo lo adopta; uno que el usuario
        # hubiera ajustado a mano conserva lo suyo.
        if dataset.get('min_valid_fraction') == 0.50:
            dataset['min_valid_fraction'] = DEFAULT_MIN_VALID_FRACTION
    dataset.setdefault('min_valid_fraction', DEFAULT_MIN_VALID_FRACTION)

    dataset.pop('min_labeled_fraction', None)
    return dataset


# --- Etiquetas ---------------------------------------------------------------------------

def make_label(dataset, payload, order, label_id=None, source=SOURCE_MANUAL):
    """Valida y construye una etiqueta (`data-model.md` §Etiqueta).

    `class_index` a `None` es la etiqueta de «ignorar» (FR-014): al rasterizar devuelve esos
    píxeles a 255. No es lo mismo que pintar la clase 0 —que afirma «aquí no hay camino»— y
    confundirlos arruinaría el entrenamiento (FR-026), así que se acepta explícitamente en vez de
    tratarse como un valor ausente.

    Un área revisada (`KIND_REVIEW`) no lleva clase: no dice qué hay, dice que alguien lo miró.
    """
    kind = str(payload.get('kind') or '').strip()
    if kind not in KINDS:
        raise ValidationError('Tipo de etiqueta desconocido: {}'.format(kind or '(vacío)'),
                              'bad_geometry')

    class_index = payload.get('class_index', payload.get('classIndex'))
    if kind == KIND_REVIEW:
        class_index = None
    elif class_index is not None:
        try:
            class_index = int(class_index)
        except (TypeError, ValueError):
            raise ValidationError('El índice de clase debe ser un entero.', 'unknown_class')
        if class_by_index(dataset, class_index) is None:
            raise ValidationError('La clase {} no existe en este dataset.'.format(class_index),
                                  'unknown_class')

    geometry = validate_geometry(kind, payload.get('geometry'))

    radius_m = None
    if kind == KIND_STROKE:
        raw_radius = payload.get('radius_m', payload.get('radiusM'))
        try:
            radius_m = float(raw_radius)
        except (TypeError, ValueError):
            raise ValidationError('Un trazo necesita un radio en metros mayor que cero.',
                                  'bad_radius')
        if not math.isfinite(radius_m) or radius_m <= 0:
            raise ValidationError('Un trazo necesita un radio en metros mayor que cero.',
                                  'bad_radius')

    label = {
        'id': label_id or str(uuid.uuid4()),
        'class_index': class_index,
        'kind': kind,
        'geometry': simplify_geometry(geometry, kind, dataset.get('resolution_cm_px')),
        'radius_m': radius_m,
        'order': order,
        'source': source,
        'created_at': now_iso(),
        'updated_at': now_iso(),
    }

    if kind == KIND_REVIEW:
        # Marca de negativo difícil: terreno revisado sin camino pero **parecido** a uno —canchas
        # de acopio, plataformas, botaderos, cauces secos—. Se guarda en el área revisada y no en
        # la tesela porque la rejilla depende de la resolución y del solape, que el usuario puede
        # cambiar; el terreno no (FR-043).
        label['hard_negative'] = bool(payload.get('hard_negative',
                                                  payload.get('hardNegative', False)))

    return label


def validate_geometry(kind, geometry):
    """Coordenadas geográficas `[[lon, lat], ...]` con los vértices que su tipo exige.

    Se guardan en coordenadas geográficas y no en el CRS de la ortofoto (D4) para que las etiquetas
    sigan valiendo si la ortofoto se regenera; la reproyección al CRS métrico ocurre una sola vez,
    al exportar.
    """
    if not isinstance(geometry, (list, tuple)):
        raise ValidationError('La geometría debe ser una lista de coordenadas.', 'bad_geometry')

    points = []
    for point in geometry:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ValidationError('Cada vértice debe ser un par [lon, lat].', 'bad_geometry')
        try:
            lon, lat = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            raise ValidationError('Las coordenadas deben ser números.', 'bad_geometry')
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ValidationError('Las coordenadas deben ser números finitos.', 'bad_geometry')
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValidationError('Coordenadas fuera del rango geográfico.', 'bad_geometry')
        points.append([lon, lat])

    # Un anillo que repite el primer punto al final es lo que entrega GeoJSON; se normaliza a la
    # forma abierta para que el recuento de vértices signifique lo mismo en los dos casos.
    is_ring = kind in (KIND_POLYGON, KIND_REVIEW)
    if is_ring and len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]

    minimum = 3 if is_ring else 2
    if len(points) < minimum:
        raise ValidationError(
            'Un {} necesita al menos {} vértices.'.format(_KIND_NAMES[kind], minimum),
            'bad_geometry')

    return points


_KIND_NAMES = {
    KIND_POLYGON: 'polígono',
    KIND_STROKE: 'trazo',
    KIND_REVIEW: 'área revisada',
}


def simplify_geometry(points, kind, resolution_cm_px):
    """Descarta los vértices que la exportación no podría representar (FR-015).

    La tolerancia es la resolución del dataset. Por debajo de esa escala la etiqueta no contiene
    información que la máscara pueda expresar, así que esos vértices no se pierden: nunca llegaron
    a significar nada.

    **La conversión de unidades es el punto delicado.** Las etiquetas están en grados (D4) y la
    tolerancia en metros; aplicarla cruda simplificaría con una tolerancia cinco órdenes de
    magnitud mayor y dejaría el trazo reducido a sus extremos. Se convierte con los grados de
    latitud por metro, que es el factor **conservador**: un grado de longitud cubre menos metros
    fuera del ecuador, así que en esa dirección se simplifica algo menos de lo pedido, nunca más.
    """
    if not resolution_cm_px or len(points) <= 2:
        return points

    tolerance_deg = (float(resolution_cm_px) / 100.0) / _METERS_PER_DEGREE
    is_ring = kind in (KIND_POLYGON, KIND_REVIEW)
    simplified = _douglas_peucker(points, tolerance_deg, is_ring)

    minimum = 3 if is_ring else 2
    return simplified if len(simplified) >= minimum else points


def _douglas_peucker(points, tolerance, is_ring):
    """Ramer-Douglas-Peucker sobre coordenadas planas.

    Se implementa aquí en vez de usar `GEOSGeometry.simplify` porque este módulo lo importan tanto
    la API como el exportador y debe poder cargarse sin GEOS; el error frente a GEOS es nulo para
    el uso que se le da, que es descartar vértices por debajo de la resolución.
    """
    if is_ring:
        # Un anillo no tiene extremos que anclar, así que se parte por el vértice más lejano al
        # primero: sin eso, el algoritmo colapsaría el polígono contra la cuerda de longitud cero
        # que une el primer punto consigo mismo.
        pivot = max(range(1, len(points)), key=lambda i: _sq_distance(points[0], points[i]))
        first = _rdp(points[:pivot + 1], tolerance)
        second = _rdp(points[pivot:] + [points[0]], tolerance)
        return first[:-1] + second[:-1]
    return _rdp(points, tolerance)


def _rdp(points, tolerance):
    if len(points) < 3:
        return list(points)

    start, end = points[0], points[-1]
    index, worst = 0, -1.0
    for i in range(1, len(points) - 1):
        d = _perpendicular_distance(points[i], start, end)
        if d > worst:
            index, worst = i, d

    if worst <= tolerance:
        return [start, end]
    return _rdp(points[:index + 1], tolerance)[:-1] + _rdp(points[index:], tolerance)


def _sq_distance(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _perpendicular_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    if dx == 0 and dy == 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(point[0] - (start[0] + t * dx), point[1] - (start[1] + t * dy))
