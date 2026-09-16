"""Acceso a la coleccion `coordenadas_detalle` de MongoDB."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db


def registrar_punto(*, id_paseo, latitud, longitud, altitud=None, fecha_captura=None):
    ahora = datetime.now(timezone.utc)
    punto = {
        'id_paseo': id_paseo if isinstance(id_paseo, ObjectId) else ObjectId(id_paseo),
        'latitud': latitud,
        'longitud': longitud,
        'altitud': altitud,
        'fecha_captura': fecha_captura or ahora,
        'fecha_recepcion': ahora,
    }
    resultado = get_db().coordenadas_detalle.insert_one(punto)
    punto['_id'] = resultado.inserted_id
    return punto


def obtener_ultimo_punto(id_paseo):
    """El punto GPS mas reciente de un paseo, o None si todavia no hay ninguno."""
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None
    return get_db().coordenadas_detalle.find_one(
        {'id_paseo': oid},
        sort=[('fecha_captura', -1)],
    )


def listar_por_paseo(id_paseo):
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return []
    return list(get_db().coordenadas_detalle.find({'id_paseo': oid}).sort('fecha_captura', 1))


def a_json(punto):
    fecha_captura = punto.get('fecha_captura')
    return {
        'latitud': punto['latitud'],
        'longitud': punto['longitud'],
        'altitud': punto.get('altitud'),
        'fecha_captura': fecha_captura.isoformat() if isinstance(fecha_captura, datetime) else fecha_captura,
    }
