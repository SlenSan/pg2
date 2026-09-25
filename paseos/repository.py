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


def crear_disponibilidad(*, id_paseador, horario_desde, horario_hasta):
    """
    horario_desde/horario_hasta: horario PROPUESTO por el paseador para
    este horario publicado (naive UTC, igual que el resto de las fechas
    de esta coleccion) - distintos de hora_inicio/hora_fin, que son el
    momento REAL en que el paseo paso a en_vivo/historico. Un paseador
    puede tener varios documentos 'disponible' al mismo tiempo (varios
    horarios publicados); ya no hay limite de uno solo.
    """
    paseo = {
        'id_paseador': id_paseador,
        'id_mascotas': [],
        'id_dueno': None,
        'estado': 'disponible',
        'fecha': datetime.now(timezone.utc),
        'horario_desde': horario_desde,
        'horario_hasta': horario_hasta,
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
    inscrito todavia (id_mascotas sigue vacio). Atomico via
    find_one_and_delete: si un dueño lo inscribio justo antes de que este
    filtro corriera, el filtro no matchea y no se borra nada. Devuelve el
    documento borrado, o None si no se cumplen las condiciones (no existe,
    no es suyo, ya no esta 'disponible', o ya tiene mascotas asignadas).
    """
    try:
        oid_paseo = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None

    return get_db().paseos.find_one_and_delete({
        '_id': oid_paseo,
        'id_paseador': id_paseador,
        'estado': 'disponible',
        'id_mascotas': [],
    })


def obtener_en_vivo_de_paseador(id_paseador):
    """
    El paseo 'en_vivo' de este paseador, si tiene uno (a lo sumo uno: un
    paseador es una sola persona, no puede caminar dos perros de dueños
    distintos en paralelo - ver iniciar_paseo()).
    """
    return get_db().paseos.find_one({'id_paseador': id_paseador, 'estado': 'en_vivo'})


def listar_disponibles_de_paseador(id_paseador):
    """
    TODOS los horarios 'disponible' publicados por este paseador ahora
    mismo (puede tener varios simultaneos), tengan o no mascota(s)
    inscrita(s) - el dashboard del paseador necesita ver ambos casos
    (horario libre vs. solicitud pendiente). Quien solo quiera los libres
    (el lado del dueño) filtra id_mascotas=[] sobre el resultado.
    """
    return list(get_db().paseos.find({
        'id_paseador': id_paseador,
        'estado': 'disponible',
    }).sort('horario_desde', 1))


def listar_disponibles_sin_asignar():
    """Paseos publicados y que ningun dueño ha inscrito todavia."""
    return list(get_db().paseos.find({
        'estado': 'disponible',
        'id_mascotas': [],
    }).sort('fecha', -1))


def obtener_por_id(id_paseo):
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None
    return get_db().paseos.find_one({'_id': oid})


def inscribir_mascotas(*, id_paseo, id_dueno, ids_mascota):
    """
    Asigna dueño y una o varias mascotas (del mismo dueño, ya validadas
    por el llamador) a un paseo 'disponible' sin asignar. Es atomico: si
    otro dueño ya lo tomo entre que se listo y se envio el formulario, el
    filtro no matchea y no se sobreescribe nada.
    """
    try:
        oid_paseo = ObjectId(id_paseo)
        oid_dueno = ObjectId(id_dueno)
        oids_mascota = [ObjectId(i) for i in ids_mascota]
    except (InvalidId, TypeError):
        return False
    if not oids_mascota:
        return False

    resultado = get_db().paseos.update_one(
        {'_id': oid_paseo, 'estado': 'disponible', 'id_mascotas': []},
        {'$set': {'id_dueno': oid_dueno, 'id_mascotas': oids_mascota}},
    )
    return resultado.modified_count == 1


def iniciar_paseo(*, id_paseo, id_paseador):
    """
    Pasa un paseo de 'disponible' a 'en_vivo' y registra hora_inicio.
    Solo si le pertenece a ese paseador, ya tiene una mascota inscrita
    (no tiene sentido iniciar un paseo que nadie tomo todavia), y el
    paseador no tiene YA otro paseo 'en_vivo' - una persona no puede
    caminar dos perros de dueños distintos en paralelo. Antes esto era
    imposible sin querer (solo se permitia un 'disponible' a la vez); con
    varios horarios simultaneos hace falta este chequeo explicito.
    Devuelve el documento actualizado, o None si no se cumplen las
    condiciones (no existe, no es suyo, ya no esta 'disponible', no tiene
    ninguna mascota asignada, o ya hay otro paseo en_vivo).

    Nota: el chequeo de "otro paseo en_vivo" es un find_one previo, no
    parte del filtro atomico de mas abajo (que solo puede mirar ESTE
    documento) - queda una ventana muy chica de condicion de carrera
    (dos clics de iniciar simultaneos en dos horarios distintos), acorde
    al volumen de esta plataforma.
    """
    if obtener_en_vivo_de_paseador(id_paseador):
        return None

    try:
        oid_paseo = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None

    return get_db().paseos.find_one_and_update(
        {
            '_id': oid_paseo,
            'id_paseador': id_paseador,
            'estado': 'disponible',
            'id_mascotas': {'$ne': []},
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
    for campo_ref in ('id_paseador', 'id_dueno'):
        data[campo_ref] = str(data[campo_ref]) if data.get(campo_ref) else None
    data['id_mascotas'] = [str(i) for i in data.get('id_mascotas', [])]
    for campo_fecha in ('fecha', 'horario_desde', 'horario_hasta', 'hora_inicio', 'hora_fin'):
        if isinstance(data.get(campo_fecha), datetime):
            data[campo_fecha] = data[campo_fecha].isoformat()
    return data
