"""
Acceso a la coleccion `paseos` de MongoDB (coleccion central del sistema).

Fase 1: solo cubre el estado "disponible" (publicar disponibilidad,
listar paseadores libres, inscribir una mascota). Iniciar/finalizar el
paseo ("en_vivo"/"historico") se agrega en una fase posterior.
"""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from core.mongo import get_db

MOMENTOS_FOTO_VALIDOS = ('inicio', 'mitad', 'fin')


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


def cancelar_disponibilidad(*, id_paseo, id_paseador):
    """
    Simetrica a crear_disponibilidad(): borra el documento 'disponible'
    que el propio paseador publico, siempre que ningun dueño lo haya
    inscrito todavia (id_mascota sigue en None). Atomico via
    find_one_and_delete: si un dueño lo inscribio justo antes de que este
    filtro corriera, el filtro no matchea y no se borra nada. Devuelve el
    documento borrado, o None si no se cumplen las condiciones (no existe,
    no es suyo, ya no esta 'disponible', o ya tiene mascota asignada).
    """
    try:
        oid_paseo = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None

    return get_db().paseos.find_one_and_delete({
        '_id': oid_paseo,
        'id_paseador': id_paseador,
        'estado': 'disponible',
        'id_mascota': None,
    })


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


def iniciar_paseo(*, id_paseo, id_paseador):
    """
    Pasa un paseo de 'disponible' a 'en_vivo' y registra hora_inicio.
    Solo si le pertenece a ese paseador y ya tiene una mascota inscrita
    (no tiene sentido iniciar un paseo que nadie tomo todavia).
    Devuelve el documento actualizado, o None si no se cumplen las
    condiciones (no existe, no es suyo, ya no esta 'disponible', o no
    tiene id_mascota asignado).
    """
    try:
        oid_paseo = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None

    return get_db().paseos.find_one_and_update(
        {
            '_id': oid_paseo,
            'id_paseador': id_paseador,
            'estado': 'disponible',
            'id_mascota': {'$ne': None},
        },
        {'$set': {'estado': 'en_vivo', 'hora_inicio': datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


def finalizar_paseo(*, id_paseo, id_paseador):
    """
    Pasa un paseo de 'en_vivo' a 'historico' y registra hora_fin. Solo si
    le pertenece a ese paseador y esta actualmente en curso. Devuelve el
    documento actualizado, o None si no se cumplen las condiciones.
    """
    try:
        oid_paseo = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None

    return get_db().paseos.find_one_and_update(
        {
            '_id': oid_paseo,
            'id_paseador': id_paseador,
            'estado': 'en_vivo',
        },
        {'$set': {'estado': 'historico', 'hora_fin': datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


def incrementar_total_puntos(id_paseo):
    """Suma 1 a total_puntos cada vez que llega una coordenada GPS nueva."""
    resultado = get_db().paseos.find_one_and_update(
        {'_id': id_paseo},
        {'$inc': {'total_puntos': 1}},
        return_document=ReturnDocument.AFTER,
    )
    return resultado['total_puntos'] if resultado else None


def agregar_foto(*, id_paseo, id_paseador, momento, url):
    """
    Agrega una foto (RF15) al arreglo `fotos` de un paseo propio y
    "en_vivo". El filtro 'fotos.momento': {'$ne': momento} hace que sea
    atomico y evite duplicar una foto del mismo momento (verificado
    manualmente: en Mongo, $ne sobre un campo dentro de un array de
    subdocumentos solo matchea si NINGUN elemento tiene ese valor).
    Devuelve el documento actualizado, o None si no se cumplen las
    condiciones (no existe, no es suyo, no esta "en_vivo", o ya tiene una
    foto de ese momento).
    """
    try:
        oid_paseo = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None

    return get_db().paseos.find_one_and_update(
        {
            '_id': oid_paseo,
            'id_paseador': id_paseador,
            'estado': 'en_vivo',
            'fotos.momento': {'$ne': momento},
        },
        {'$push': {'fotos': {'url': url, 'momento': momento}}},
        return_document=ReturnDocument.AFTER,
    )


def marcar_emergencia(id_paseo):
    """Deja registrado que se activo el boton de emergencia en este paseo."""
    get_db().paseos.update_one({'_id': id_paseo}, {'$set': {'emergencia': True}})


def listar_por_dueno(id_dueno):
    try:
        oid = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return []
    return list(get_db().paseos.find({'id_dueno': oid}).sort('fecha', -1))


def listar_por_paseador(id_paseador):
    return list(get_db().paseos.find({'id_paseador': id_paseador}).sort('fecha', -1))


def contar_completados_por_paseador(id_paseador):
    """Cuenta de paseos con estado='historico' de este paseador (estadistica de perfil/dashboard)."""
    return get_db().paseos.count_documents({'id_paseador': id_paseador, 'estado': 'historico'})


def a_json(paseo):
    data = dict(paseo)
    data['_id'] = str(data['_id'])
    for campo_ref in ('id_paseador', 'id_mascota', 'id_dueno'):
        data[campo_ref] = str(data[campo_ref]) if data.get(campo_ref) else None
    for campo_fecha in ('fecha', 'hora_inicio', 'hora_fin'):
        if isinstance(data.get(campo_fecha), datetime):
            data[campo_fecha] = data[campo_fecha].isoformat()
    return data
