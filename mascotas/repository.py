"""Acceso a la coleccion `mascotas` de MongoDB."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db, mapear_por_id


def crear_mascota(*, id_dueno, nombre, raza, edad, peso, observaciones='', foto=''):
    mascota = {
        'id_dueno': ObjectId(id_dueno),
        'nombre': nombre,
        'raza': raza,
        'edad': edad,
        'peso': peso,
        'foto': foto,
        'observaciones': observaciones,
        'fecha_registro': datetime.now(timezone.utc),
    }
    resultado = get_db().mascotas.insert_one(mascota)
    mascota['_id'] = resultado.inserted_id
    return mascota


def listar_por_dueno(id_dueno):
    try:
        oid = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return []
    return list(get_db().mascotas.find({'id_dueno': oid}).sort('fecha_registro', -1))


def obtener_por_id_y_dueno(id_mascota, id_dueno):
    """Devuelve la mascota solo si pertenece a ese dueño (evita inscribir mascotas ajenas)."""
    try:
        oid_mascota = ObjectId(id_mascota)
        oid_dueno = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return None
    return get_db().mascotas.find_one({'_id': oid_mascota, 'id_dueno': oid_dueno})


def obtener_varias_por_id(ids):
    """Devuelve {ObjectId: mascota} para una lista de ids."""
    return mapear_por_id('mascotas', ids)
