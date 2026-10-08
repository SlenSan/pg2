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

# Las 17 comunas oficiales de Bucaramanga (division politico-urbana de la
# Alcaldia, bucaramanga.gov.co/division-politico-urbana), en este orden
# exacto - se eligio la division oficial completa (no una lista curada de
# sectores populares) para que ningun sector de la ciudad quede sin
# cobertura posible. Fuente unica de verdad reusada por el formulario de
# publicar horario (choices) y por el filtro del dueño (validacion) -
# ninguna otra lista de zonas en el proyecto.
ZONAS_VALIDAS = (
    'Norte', 'Nororiental', 'San Francisco', 'Occidental', 'García Rovira',
    'La Concordia', 'La Ciudadela', 'Sur Occidente', 'La Pedregosa', 'Provenza',
    'Sur', 'Cabecera del Llano', 'Oriental', 'Morrorico', 'Centro',
    'Lagos del Cacique', 'Mutis',
)


def crear_disponibilidad(*, id_paseador, horario_desde, horario_hasta, zonas=None):
    """
    horario_desde/horario_hasta: horario PROPUESTO por el paseador para
    este horario publicado (naive UTC, igual que el resto de las fechas
    de esta coleccion) - distintos de hora_inicio/hora_fin, que son el
    momento REAL en que el paseo paso a en_vivo/historico. Un paseador
    puede tener varios documentos 'disponible' al mismo tiempo (varios
    horarios publicados); ya no hay limite de uno solo.

    zonas: 0 a N valores de ZONAS_VALIDAS - se elige CADA VEZ que se
    publica un horario (no es un dato fijo del perfil del paseador), y es
    opcional: [] significa "no especifico zona", nunca "todas las zonas".
    La validacion de que cada valor pertenezca a la lista fija la hace el
    formulario (PublicarHorarioForm), no esta funcion.
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
        'zonas': list(zonas) if zonas else [],
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


def listar_disponibles_con_cupo(zona=None):
    """
    Paseos publicados que TODAVIA aceptan inscripciones nuevas - ya no es
    "sin asignar" (antes solo id_mascotas=[]; ahora un horario con 3/8
    mascotas de otro dueño sigue apareciendo aca para que un dueño
    DISTINTO tambien pueda inscribir, mientras no llegue a
    MAXIMO_MASCOTAS_POR_PASEO ni el paseador lo haya cerrado). $expr
    porque el limite se compara contra el tamaño de un array del propio
    documento, algo que un filtro de igualdad simple no puede expresar.

    zona: si se da, solo horarios que tengan ESA zona entre las suyas
    (filtro del dueño en "Paseadores disponibles" - ver CLAUDE.md/Incremento 1
    de zonas de servicio). {'zonas': zona} matchea automaticamente si el
    array la contiene, sin sintaxis especial. El llamador (lista_disponibles())
    ya valida que `zona` sea una de ZONAS_VALIDAS antes de llegar aca.
    """
    filtro = {
        'estado': 'disponible',
        'acepta_inscripciones': True,
        '$expr': {'$lt': [{'$size': '$id_mascotas'}, MAXIMO_MASCOTAS_POR_PASEO]},
    }
    if zona:
        filtro['zonas'] = zona
    return list(get_db().paseos.find(filtro).sort('fecha', -1))


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


def listar_activos_por_dueno(id_dueno):
    """
    Paseos de este dueño que siguen "activos" - 'disponible' (agendado,
    esperando que empiece) o 'en_vivo' (en curso ahora mismo). Para
    "Paseos activos" (antes "Mis paseos" - ver reporte de hallazgos,
    punto (d)): lo que ya termino ('historico') vive SOLO en Historial,
    nunca aca - cada paseo aparece en una sola de las dos pantallas.
    Filtro hecho aca (Mongo), no en la vista ni en la plantilla - mismo
    criterio de repository pattern estricto que el resto del proyecto.
    No reemplaza listar_por_dueno() (sigue haciendo falta sin filtrar de
    estado en incidentes/, notificaciones/ y el dashboard del dueño).
    """
    try:
        oid = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return []
    return list(get_db().paseos.find({
        'id_duenos': oid,
        'estado': {'$in': ['disponible', 'en_vivo']},
    }).sort('fecha', -1))


def listar_por_paseador(id_paseador):
    return list(get_db().paseos.find({'id_paseador': id_paseador}).sort('fecha', -1))


def contar_completados_por_paseador(id_paseador):
    """Cuenta de paseos con estado='historico' de este paseador (estadistica de perfil/dashboard)."""
    return get_db().paseos.count_documents({'id_paseador': id_paseador, 'estado': 'historico'})


def listar_por_paseador_con_horario_en(id_paseador, desde_utc, hasta_utc):
    """
    Paseos de este paseador cuyo horario_desde cae en [desde_utc, hasta_utc)
    - un horario SIEMPRE se publica "para hoy" (ver PublicarHorarioForm),
    asi que esto sirve para "cuantas mascotas se inscribieron para hoy"
    (estadistica "Solicitudes hoy" del dashboard del paseador) sin
    necesitar un campo nuevo de "fecha de inscripcion" que el esquema no
    tiene.
    """
    return list(get_db().paseos.find({
        'id_paseador': id_paseador,
        'horario_desde': {'$gte': desde_utc, '$lt': hasta_utc},
    }))


def contar_historico_desde(id_paseador, desde_utc):
    """Cuenta de paseos 'historico' de este paseador con hora_fin >= desde_utc (p.ej. "esta semana")."""
    return get_db().paseos.count_documents({
        'id_paseador': id_paseador,
        'estado': 'historico',
        'hora_fin': {'$gte': desde_utc},
    })


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
