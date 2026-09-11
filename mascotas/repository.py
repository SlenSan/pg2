"""Acceso a la coleccion `mascotas` de MongoDB."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db


def crear_mascota(*, id_dueno, nombre, raza, edad, peso, observaciones=''):
    mascota = {
        'id_dueno': ObjectId(id_dueno),
        'nombre': nombre,
        'raza': raza,
        'edad': edad,
        'peso': peso,
        'foto': '',
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
