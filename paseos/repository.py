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

# Limite real de mascotas por paseo (Ley Kiara, ver Marco Normativo del
# documento de grado) - un horario publicado sigue abierto a nuevas
# inscripciones de OTROS dueños (no solo el primero que inscribio) hasta
# llegar a este total o hasta que el paseador lo cierre manualmente
# (acepta_inscripciones=False) - ver CLAUDE.md, "Corrección de alcance
# 2026-09-25".
MAXIMO_MASCOTAS_POR_PASEO = 8


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
        'id_duenos': [],
        'acepta_inscripciones': True,
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
    Boton "Despublicar"/"Cerrar a nuevas inscripciones" de un horario
    propio - dos comportamientos distintos segun si ya tiene mascotas:

    - Vacio (nadie inscrito todavia): se BORRA el documento entero, igual
      que siempre (find_one_and_delete, atomico).
    - Con mascotas ya inscritas: NO se borra (esas mascotas ya tienen un
      compromiso con el paseador) - solo se pone
      acepta_inscripciones=False, para que deje de aceptar inscripciones
      NUEVAS de otros dueños. El paseador puede seguir iniciando el paseo
      con lo que ya tiene inscrito.

    Ambos casos son atomicos por su propio filtro (uno hace match solo si
    esta vacio, el otro solo si no lo esta) - si un dueño inscribio justo
    antes de que este POST llegara, el primer intento no matchea y cae al
    segundo, en vez de perder esa inscripcion. Devuelve el documento
    borrado o actualizado, o None si no se cumplen las condiciones (no
    existe, no es suyo, o ya no esta 'disponible').
    """
    try:
        oid_paseo = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None

    filtro_base = {'_id': oid_paseo, 'id_paseador': id_paseador, 'estado': 'disponible'}

    borrado = get_db().paseos.find_one_and_delete({**filtro_base, 'id_mascotas': []})
    if borrado:
        return borrado

    return get_db().paseos.find_one_and_update(
        {**filtro_base, 'id_mascotas': {'$ne': []}},
        {'$set': {'acepta_inscripciones': False}},
        return_document=ReturnDocument.AFTER,
    )


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


def listar_disponibles_con_cupo():
    """
    Paseos publicados que TODAVIA aceptan inscripciones nuevas - ya no es
    "sin asignar" (antes solo id_mascotas=[]; ahora un horario con 3/8
    mascotas de otro dueño sigue apareciendo aca para que un dueño
    DISTINTO tambien pueda inscribir, mientras no llegue a
    MAXIMO_MASCOTAS_POR_PASEO ni el paseador lo haya cerrado). $expr
    porque el limite se compara contra el tamaño de un array del propio
    documento, algo que un filtro de igualdad simple no puede expresar.
    """
    return list(get_db().paseos.find({
        'estado': 'disponible',
        'acepta_inscripciones': True,
        '$expr': {'$lt': [{'$size': '$id_mascotas'}, MAXIMO_MASCOTAS_POR_PASEO]},
    }).sort('fecha', -1))


def obtener_por_id(id_paseo):
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None
    return get_db().paseos.find_one({'_id': oid})


def inscribir_mascotas(*, id_paseo, id_dueno, ids_mascota):
    """
    Suma una o varias mascotas (de UN dueño, ya validadas por el
    llamador) a un paseo 'disponible' - a las que ya haya de este u OTROS
    dueños (ver CLAUDE.md, "Corrección de alcance 2026-09-25"; hasta 8 en
    total, Ley Kiara). $push/$addToSet en vez de $set: NO sobreescribe lo
    que ya habia, se agrega. id_duenos usa $addToSet (no $push) porque un
    mismo dueño puede inscribir mascotas en mas de una ronda sobre el
    mismo horario - no tiene sentido duplicarlo ahi.

    Atomico via el filtro $expr (compara el tamaño de id_mascotas DESPUES
    de sumar las nuevas contra el maximo, evaluado por Mongo en el mismo
    paso que el update): si el cupo ya no alcanza, o si otro dueño lo
    tomo/lo dejo sin cupo entre que se listo y se envio el formulario, o
    si el paseador ya lo cerro (acepta_inscripciones=False), el filtro no
    matchea y no se modifica nada.

    id_mascotas tambien usa $addToSet (no $push a secas): si el MISMO
    dueño reenvia el mismo formulario dos veces (doble clic, o inscribe
    una mascota, y despues vuelve a este horario a sumar otra), una
    mascota que ya estaba no se duplica ni infla el conteo de cupos.
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
        {
            '_id': oid_paseo,
            'estado': 'disponible',
            'acepta_inscripciones': True,
            '$expr': {
                '$lte': [
                    {'$add': [{'$size': '$id_mascotas'}, len(oids_mascota)]},
                    MAXIMO_MASCOTAS_POR_PASEO,
                ],
            },
        },
        {
            '$addToSet': {
                'id_mascotas': {'$each': oids_mascota},
                'id_duenos': oid_dueno,
            },
        },
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
    """
    Paseos donde este dueño tiene AL MENOS una mascota inscrita - no
    necesariamente el UNICO dueño del paseo (ver CLAUDE.md, "Corrección de
    alcance 2026-09-25"). {'id_duenos': oid} matchea automaticamente
    contra el array sin sintaxis especial (Mongo compara "contiene" por
    default). Quien llame a esto y muestre nombres de mascotas debe
    filtrarlas a las de ESTE dueño (mascotas.obtener_varias_por_id_y_dueno),
    nunca a id_mascotas completo - puede haber mascotas de otros dueños
    en el mismo documento.
    """
    try:
        oid = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return []
    return list(get_db().paseos.find({'id_duenos': oid}).sort('fecha', -1))


def listar_por_paseador(id_paseador):
    return list(get_db().paseos.find({'id_paseador': id_paseador}).sort('fecha', -1))


def contar_completados_por_paseador(id_paseador):
    """Cuenta de paseos con estado='historico' de este paseador (estadistica de perfil/dashboard)."""
    return get_db().paseos.count_documents({'id_paseador': id_paseador, 'estado': 'historico'})


def a_json(paseo):
    data = dict(paseo)
    data['_id'] = str(data['_id'])
    data['id_paseador'] = str(data['id_paseador']) if data.get('id_paseador') else None
    data['id_duenos'] = [str(i) for i in data.get('id_duenos', [])]
    data['id_mascotas'] = [str(i) for i in data.get('id_mascotas', [])]
    for campo_fecha in ('fecha', 'horario_desde', 'horario_hasta', 'hora_inicio', 'hora_fin'):
        if isinstance(data.get(campo_fecha), datetime):
            data[campo_fecha] = data[campo_fecha].isoformat()
    return data
