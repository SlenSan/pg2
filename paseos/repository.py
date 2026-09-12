"""
Acceso a la coleccion `paseos` de MongoDB (coleccion central del sistema).

Fase 1: solo cubre el estado "disponible" (publicar disponibilidad,
listar paseadores libres, inscribir una mascota). Iniciar/finalizar el
paseo ("en_vivo"/"historico") se agrega en una fase posterior.
"""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db


def crear_disponibilidad(id_paseador):
    paseo = {
        'id_paseador': id_paseador,
        'id_mascota': None,
        'id_dueno': None,
        'estado': 'disponible',
        'fecha': datetime.now(timezone.utc),
        'hora_inicio': None,
        'hora_fin': None,
        'total_puntos': 0,
        'emergencia': False,
        'fotos': [],
    }
    resultado = get_db().paseos.insert_one(paseo)
    paseo['_id'] = resultado.inserted_id
    return paseo


def obtener_activo_de_paseador(id_paseador):
    """Paseo en 'disponible' o 'en_vivo' que ya tenga ese paseador, si existe."""
    return get_db().paseos.find_one({
        'id_paseador': id_paseador,
        'estado': {'$in': ['disponible', 'en_vivo']},
    })


def listar_disponibles_sin_asignar():
    """Paseos publicados y que ningun dueño ha inscrito todavia."""
    return list(get_db().paseos.find({
        'estado': 'disponible',
        'id_mascota': None,
    }).sort('fecha', -1))


def obtener_por_id(id_paseo):
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None
    return get_db().paseos.find_one({'_id': oid})


def inscribir_mascota(*, id_paseo, id_dueno, id_mascota):
    """
    Asigna dueño y mascota a un paseo 'disponible' sin asignar. Es atomico:
    si otro dueño ya lo tomo entre que se listo y se envio el formulario,
    el filtro no matchea y no se sobreescribe nada.
    """
    try:
        oid_paseo = ObjectId(id_paseo)
        oid_dueno = ObjectId(id_dueno)
        oid_mascota = ObjectId(id_mascota)
    except (InvalidId, TypeError):
        return False

    resultado = get_db().paseos.update_one(
        {'_id': oid_paseo, 'estado': 'disponible', 'id_mascota': None},
        {'$set': {'id_dueno': oid_dueno, 'id_mascota': oid_mascota}},
    )
    return resultado.modified_count == 1


def listar_por_dueno(id_dueno):
    try:
        oid = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return []
    return list(get_db().paseos.find({'id_dueno': oid}).sort('fecha', -1))


def a_json(paseo):
    data = dict(paseo)
    data['_id'] = str(data['_id'])
    for campo_ref in ('id_paseador', 'id_mascota', 'id_dueno'):
        data[campo_ref] = str(data[campo_ref]) if data.get(campo_ref) else None
    for campo_fecha in ('fecha', 'hora_inicio', 'hora_fin'):
        if isinstance(data.get(campo_fecha), datetime):
            data[campo_fecha] = data[campo_fecha].isoformat()
    return data
