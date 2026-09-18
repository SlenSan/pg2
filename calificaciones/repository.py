"""Acceso a la coleccion `calificaciones` de MongoDB (RF13)."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db


def obtener_por_paseo(id_paseo):
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None
    return get_db().calificaciones.find_one({'id_paseo': oid})


def listar_por_paseos(ids_paseo):
    ids_validos = [i for i in ids_paseo if isinstance(i, ObjectId)]
    if not ids_validos:
        return []
    return list(get_db().calificaciones.find({'id_paseo': {'$in': ids_validos}}))


def crear(*, id_paseo, id_dueno, id_paseador, puntuacion, comentario=''):
    calificacion = {
        'id_paseo': id_paseo if isinstance(id_paseo, ObjectId) else ObjectId(id_paseo),
        'id_dueno': id_dueno if isinstance(id_dueno, ObjectId) else ObjectId(id_dueno),
        'id_paseador': id_paseador if isinstance(id_paseador, ObjectId) else ObjectId(id_paseador),
        'puntuacion': puntuacion,
        'comentario': comentario,
        'fecha': datetime.now(timezone.utc),
    }
    resultado = get_db().calificaciones.insert_one(calificacion)
    calificacion['_id'] = resultado.inserted_id
    return calificacion


def calcular_promedio(id_paseador):
    """Promedio de puntuacion de un paseador (redondeado a 1 decimal), o None si no tiene ninguna."""
    oid = id_paseador if isinstance(id_paseador, ObjectId) else ObjectId(id_paseador)
    pipeline = [
        {'$match': {'id_paseador': oid}},
        {'$group': {'_id': None, 'promedio': {'$avg': '$puntuacion'}}},
    ]
    resultado = list(get_db().calificaciones.aggregate(pipeline))
    return round(resultado[0]['promedio'], 1) if resultado else None


def calcular_promedio_dado_por_dueno(id_dueno):
    """
    Promedio de las puntuaciones que ESTE dueño le ha dado a sus
    paseadores (no la de un paseador especifico) - estadistica del
    dashboard del dueño. None si todavia no ha calificado ningun paseo.
    """
    oid = id_dueno if isinstance(id_dueno, ObjectId) else ObjectId(id_dueno)
    pipeline = [
        {'$match': {'id_dueno': oid}},
        {'$group': {'_id': None, 'promedio': {'$avg': '$puntuacion'}}},
    ]
    resultado = list(get_db().calificaciones.aggregate(pipeline))
    return round(resultado[0]['promedio'], 1) if resultado else None
