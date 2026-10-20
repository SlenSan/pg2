"""
Acceso a la coleccion `paseos` de MongoDB (coleccion central del sistema).

Fase 1: solo cubre el estado "disponible" (publicar disponibilidad,
listar paseadores libres, inscribir una mascota). Iniciar/finalizar el
paseo ("en_vivo"/"historico") se agrega en una fase posterior.
"""

from datetime import datetime, timedelta, timezone

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

# Ajustes del 19 de octubre, punto 4 - mismo criterio que
# incidentes.repository._SEGUNDOS_DUPLICADO_INCIDENTE: el botón
# "Publicar horario" ya se deshabilita mientras se envía (ver
# base.html), pero esta es la defensa de fondo en el BACKEND para un
# doble toque que igual llegue a mandar dos POST - sin esto, publicar
# dos veces el MISMO horario (mismo paseador, mismo horario_desde/
# horario_hasta) creaba dos documentos 'disponible' idénticos.
_SEGUNDOS_DUPLICADO_HORARIO = 10

# Incremento 4 fase 3, punto A7 - lista CERRADA de duraciones que un
# dueño puede acordar al inscribir (minutos). "Solo se ofrecen las que
# caben entre la hora de inicio y la de fin del horario publicado" - ver
# duraciones_acordadas_disponibles() más abajo, que filtra esta lista
# según cada horario puntual (no es una elección libre de minutos).
#
# Ajuste del 20 de octubre, punto 1 - la autora bajó el máximo de 3 horas
# a 2 (decisión suya, sin motivo técnico): se QUITARON 150 y 180 de esta
# lista, así que ya no se ofrecen ni se aceptan en una inscripción nueva
# (TypedChoiceField en InscribirMascotaForm arma sus choices desde
# duraciones_acordadas_disponibles() más abajo, que a su vez sale de
# esta tupla - un valor fuera de ella ya no es una choice válida, el
# backend la rechaza automáticamente sin código extra).
DURACIONES_ACORDADAS_CON_ETIQUETA = (
    (30, '30 minutos'),
    (60, '1 hora'),
    (90, '1 hora y media'),
    (120, '2 horas'),
)
DURACIONES_ACORDADAS_VALIDAS = tuple(m for m, _ in DURACIONES_ACORDADAS_CON_ETIQUETA)
_DURACION_MINIMA_INSCRIBIBLE_MIN = DURACIONES_ACORDADAS_VALIDAS[0]  # 30 - "si la franja dura menos, no se puede inscribir"

# Compatibilidad: una inscripción de ANTES de este ajuste puede tener
# 150 o 180 guardado en `duracion_acordada_min` - "las inscripciones que
# ya tengan 150 o 180 se siguen mostrando con su valor" (pedido
# explícito). Esas etiquetas YA NO se ofrecen (no están en
# DURACIONES_ACORDADAS_CON_ETIQUETA de arriba, así que
# duraciones_acordadas_disponibles() nunca las incluye), pero
# etiqueta_duracion_acordada() debe seguir reconociéndolas donde ya
# existan - de ahí esta tabla aparte, nunca fusionada con la de arriba.
_ETIQUETAS_DURACION_DESCONTINUADAS = {
    150: '2 horas y media',
    180: '3 horas',
}
_ETIQUETA_POR_DURACION = {**dict(DURACIONES_ACORDADAS_CON_ETIQUETA), **_ETIQUETAS_DURACION_DESCONTINUADAS}


def etiqueta_duracion_acordada(minutos):
    """
    Formato ÚNICO para mostrar una duración acordada ("1 hora y media")
    - mismo patrón que etiqueta_zona()/etiqueta_tipo_incidente(). Si
    `minutos` no es uno de los valores válidos (no debería pasar, pero
    nunca se asume), o es None (paseo de antes de este punto, sin
    duración acordada), devuelve None - el llamador decide qué mostrar
    en ese caso.
    """
    return _ETIQUETA_POR_DURACION.get(minutos)


def formatear_duracion_real(minutos):
    """
    Formato de la duración REAL de un paseo/tramo ("1 h 05 min", "58
    min") - punto A7, para mostrar junto a `etiqueta_duracion_acordada()`
    en el historial del dueño ("Duración acordada: 1 hora · Duración
    real: 58 min"). Misma lógica que `formatearDuracion()` en
    `coordenadas/templates/coordenadas/mapa.html` (el timer en vivo del
    mapa), reescrita en Python porque el historial es una lista
    estática, sin JS - las dos deberían verse igual, así que si se
    ajusta una hay que ajustar la otra. `None` si `minutos` es `None`
    (todavía no hay una duración real que mostrar).
    """
    if minutos is None:
        return None
    horas, resto = divmod(minutos, 60)
    return f'{horas} h {resto:02d} min' if horas else f'{resto} min'


def duraciones_acordadas_disponibles(horario_desde, horario_hasta):
    """
    Subconjunto de DURACIONES_ACORDADAS_CON_ETIQUETA que cabe entre
    `horario_desde` y `horario_hasta` de un horario puntual (no son
    minutos libres - Incremento 4 fase 3, punto A7). Vacío si la franja
    dura menos de 30 minutos (la más corta de la lista) - el llamador
    debe tratar eso como "este horario no se puede inscribir", no como
    "sin duración obligatoria".
    """
    minutos_disponibles = (horario_hasta - horario_desde).total_seconds() / 60
    return tuple(
        (m, etiqueta) for m, etiqueta in DURACIONES_ACORDADAS_CON_ETIQUETA if m <= minutos_disponibles
    )

# Las 17 comunas oficiales de Bucaramanga, CON su numero oficial
# (bucaramanga.gov.co/el-mapa/division-politico-urbana - confirmado ahi
# antes de escribir esto, Incremento 4 punto G: el numero de cada una
# coincide exactamente con el orden en que ya estaban listadas aca desde
# el Incremento 1, asi que no fue necesario reordenar nada, solo hacer
# explicito lo que antes era implicito en la posicion). Se eligio la
# division oficial completa (no una lista curada de sectores populares)
# para que ningun sector de la ciudad quede sin cobertura posible.
# Fuente unica de verdad: el numero y el nombre de una comuna SIEMPRE
# salen de aca, nunca hardcodeados en una plantilla - ver etiqueta_zona().
ZONAS_VALIDAS_CON_NUMERO = (
    (1, 'Norte'), (2, 'Nororiental'), (3, 'San Francisco'), (4, 'Occidental'),
    (5, 'García Rovira'), (6, 'La Concordia'), (7, 'La Ciudadela'), (8, 'Sur Occidente'),
    (9, 'La Pedregosa'), (10, 'Provenza'), (11, 'Sur'), (12, 'Cabecera del Llano'),
    (13, 'Oriental'), (14, 'Morrorico'), (15, 'Centro'), (16, 'Lagos del Cacique'),
    (17, 'Mutis'),
)

# Derivada de ZONAS_VALIDAS_CON_NUMERO (no una segunda fuente de verdad):
# el valor que se guarda en `paseos.zonas` SIGUE siendo solo el nombre -
# el numero es puramente de presentación (ver etiqueta_zona()), nunca se
# migra lo ya guardado en Mongo. Reusada por el formulario de publicar
# horario (choices) y por el filtro del dueño (validacion) - ninguna
# otra lista de zonas en el proyecto.
ZONAS_VALIDAS = tuple(nombre for _, nombre in ZONAS_VALIDAS_CON_NUMERO)

_NUMERO_POR_ZONA = {nombre: numero for numero, nombre in ZONAS_VALIDAS_CON_NUMERO}


def numero_de_zona(nombre_zona):
    """El numero oficial de comuna para un valor de ZONAS_VALIDAS, o None
    si no es uno de ellos (nunca se inventa un numero)."""
    return _NUMERO_POR_ZONA.get(nombre_zona)


def etiqueta_zona(nombre_zona):
    """
    Formato UNICO para mostrar una zona en cualquier pantalla (publicar
    horario, tarjetas de "Paseadores disponibles", perfil público de un
    paseador, detalle de un horario, filtro) - Incremento 4, punto G.
    Una sola función de la que sale el texto, para que nunca se vea un
    número desincronizado entre dos pantallas. "Comuna 15. Centro" - si
    `nombre_zona` no es una de las 17 válidas, se devuelve tal cual (no
    se inventa "Comuna None").
    """
    numero = numero_de_zona(nombre_zona)
    return f'Comuna {numero}. {nombre_zona}' if numero else nombre_zona


def crear_disponibilidad(*, id_paseador, horario_desde, horario_hasta, zonas=None):
    """
    horario_desde/horario_hasta: horario PROPUESTO por el paseador para
    este horario publicado (naive UTC, igual que el resto de las fechas
    de esta coleccion) - distintos de hora_inicio/hora_fin, que son el
    momento REAL en que el paseo paso a en_vivo/historico. Un paseador
    puede tener varios documentos 'disponible' al mismo tiempo (varios
    horarios publicados); ya no hay limite de uno solo.

    zonas: 1 a N valores de ZONAS_VALIDAS (al menos una es obligatoria
    desde INC-09) - se elige CADA VEZ que se publica un horario (no es
    un dato fijo del perfil del paseador). La validacion de que cada
    valor pertenezca a la lista fija la hace el formulario
    (PublicarHorarioForm), no esta funcion.

    Ajustes del 19 de octubre, punto 4 - si este MISMO paseador ya
    publicó un horario idéntico (mismo horario_desde/horario_hasta) hace
    menos de `_SEGUNDOS_DUPLICADO_HORARIO`, se devuelve ESE documento en
    vez de crear uno nuevo - defensa de backend contra un doble envío del
    modal "Publicar horario" (el botón ya se deshabilita en el frontend,
    pero esto cubre un doble POST real). No compara `zonas`: publicar el
    mismo horario con otras zonas tan rápido no tiene un caso de uso
    real, y así la protección no depende de que el dueño del doble clic
    haya tocado las mismas casillas las dos veces.
    """
    reciente = get_db().paseos.find_one({
        'id_paseador': id_paseador,
        'estado': 'disponible',
        'horario_desde': horario_desde,
        'horario_hasta': horario_hasta,
        'fecha': {'$gte': datetime.now(timezone.utc) - timedelta(seconds=_SEGUNDOS_DUPLICADO_HORARIO)},
    }, sort=[('fecha', -1)])
    if reciente:
        return reciente

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

    `horario_hasta >= ahora` (hallazgo del 9 oct): un horario "disponible"
    cuya hora de fin ya pasó SIN que el paseador lo haya iniciado se
    queda en "disponible" para siempre (nada lo cambia de estado solo):
    sin este filtro, se seguia OFRECIENDO a los dueños indefinidamente.
    `horario_hasta` se guarda naive en UTC (ver _horario_a_utc en
    views_web.py), igual que `ahora` aca - comparacion directa, sin
    conversion de zona horaria.

    zona: si se da, solo horarios que tengan ESA zona entre las suyas
    (filtro del dueño en "Paseadores disponibles" - ver CLAUDE.md/Incremento 1
    de zonas de servicio). {'zonas': zona} matchea automaticamente si el
    array la contiene, sin sintaxis especial. El llamador (lista_disponibles())
    ya valida que `zona` sea una de ZONAS_VALIDAS antes de llegar aca.
    """
    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    filtro = {
        'estado': 'disponible',
        'acepta_inscripciones': True,
        'horario_hasta': {'$gte': ahora_utc},
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


def inscribir_mascotas(
    *, id_paseo, id_dueno, ids_mascota, direccion, comuna, indicaciones, telefono,
    duracion_acordada_min=None,
):
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

    Incremento 4 fase 3, punto A1 - además de id_mascotas/id_duenos,
    mantiene `paseos.recogidas`: UNA entrada por dueño (no una por
    inscripción - "vuelve a este horario a sumar otra" de arriba sigue
    siendo el mismo caso real). Como Mongo no tiene un "upsert sobre un
    elemento de un array" en una sola operación, son DOS intentos:
    primero intenta ACTUALIZAR una entrada ya existente de este dueño
    (`array_filters`) con los datos de contacto recién enviados (puede
    haber cambiado la dirección desde la última vez) y sumarle las
    mascotas nuevas; si no modificó nada (este dueño no tenía entrada
    todavía), el segundo intento agrega una entrada nueva. Mismo filtro
    $expr de cupo en los dos intentos - un doble envío nunca se cuela
    por la segunda rama si la primera ya lo cubrió.
    """
    try:
        oid_paseo = ObjectId(id_paseo)
        oid_dueno = ObjectId(id_dueno)
        oids_mascota = [ObjectId(i) for i in ids_mascota]
    except (InvalidId, TypeError):
        return False
    if not oids_mascota:
        return False

    filtro_base = {
        '_id': oid_paseo,
        'estado': 'disponible',
        'acepta_inscripciones': True,
        '$expr': {
            '$lte': [
                {'$add': [{'$size': '$id_mascotas'}, len(oids_mascota)]},
                MAXIMO_MASCOTAS_POR_PASEO,
            ],
        },
    }

    resultado = get_db().paseos.update_one(
        {**filtro_base, 'recogidas.id_dueno': oid_dueno},
        {
            '$addToSet': {
                'id_mascotas': {'$each': oids_mascota},
                'recogidas.$[entrada].id_mascotas': {'$each': oids_mascota},
            },
            '$set': {
                'recogidas.$[entrada].direccion': direccion,
                'recogidas.$[entrada].comuna': comuna,
                'recogidas.$[entrada].indicaciones': indicaciones,
                'recogidas.$[entrada].telefono': telefono,
                'recogidas.$[entrada].duracion_acordada_min': duracion_acordada_min,
            },
        },
        array_filters=[{'entrada.id_dueno': oid_dueno}],
    )
    if resultado.modified_count == 1:
        return True

    resultado = get_db().paseos.update_one(
        filtro_base,
        {
            '$addToSet': {
                'id_mascotas': {'$each': oids_mascota},
                'id_duenos': oid_dueno,
            },
            '$push': {
                'recogidas': {
                    'id_dueno': oid_dueno,
                    'id_mascotas': oids_mascota,
                    'direccion': direccion,
                    'comuna': comuna,
                    'indicaciones': indicaciones,
                    'telefono': telefono,
                    'duracion_acordada_min': duracion_acordada_min,
                    'estado': 'pendiente',
                    'hora_recogida': None,
                    'hora_entrega': None,
                    'motivo_no_recogida': None,
                },
            },
        },
    )
    return resultado.modified_count == 1


def marcar_recogida(*, id_paseo, id_paseador, id_dueno):
    """
    Incremento 4 fase 3, punto A2 - "Recogido": la recogida de ESE dueño
    pasa de 'pendiente' a 'recogida' y se guarda `hora_recogida`. Atómico
    vía `array_filters` + el `estado` de la recogida en el filtro
    principal (si ya estaba 'recogida'/'no_recogida'/'entregada', o el
    paseo ya no es 'en_vivo' de este paseador, no modifica nada).
    Devuelve el documento actualizado, o None.
    """
    try:
        oid_paseo = ObjectId(id_paseo)
        oid_dueno = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return None
    return get_db().paseos.find_one_and_update(
        {
            '_id': oid_paseo,
            'id_paseador': id_paseador,
            'estado': 'en_vivo',
            'recogidas': {'$elemMatch': {'id_dueno': oid_dueno, 'estado': 'pendiente'}},
        },
        {'$set': {
            'recogidas.$[entrada].estado': 'recogida',
            'recogidas.$[entrada].hora_recogida': datetime.now(timezone.utc),
        }},
        array_filters=[{'entrada.id_dueno': oid_dueno}],
        return_document=ReturnDocument.AFTER,
    )


def marcar_no_recogida(*, id_paseo, id_paseador, id_dueno, motivo):
    """
    "No se pudo recoger": la recogida de ESE dueño pasa a 'no_recogida'
    con su motivo, y sus mascotas se QUITAN de `paseo.id_mascotas`
    (pedido explícito: "esas mascotas quedan fuera del paseo" - ya no se
    están caminando de verdad). La entrada de `recogidas` NO se borra -
    queda como registro permanente de que se intentó y no se pudo,
    visible para ese dueño. `id_duenos` no se toca (el dueño sigue
    "siendo parte" de este paseo a efectos de historial, aunque su
    mascota no haya caminado).
    """
    try:
        oid_paseo = ObjectId(id_paseo)
        oid_dueno = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return None
    paseo = get_db().paseos.find_one({
        '_id': oid_paseo,
        'id_paseador': id_paseador,
        'estado': 'en_vivo',
        'recogidas': {'$elemMatch': {'id_dueno': oid_dueno, 'estado': 'pendiente'}},
    })
    if not paseo:
        return None
    entrada = next(r for r in paseo['recogidas'] if r['id_dueno'] == oid_dueno)
    ids_mascotas_fuera = entrada.get('id_mascotas', [])
    return get_db().paseos.find_one_and_update(
        {'_id': oid_paseo},
        {
            '$set': {
                'recogidas.$[entrada].estado': 'no_recogida',
                'recogidas.$[entrada].motivo_no_recogida': motivo,
            },
            '$pullAll': {'id_mascotas': ids_mascotas_fuera},
        },
        array_filters=[{'entrada.id_dueno': oid_dueno}],
        return_document=ReturnDocument.AFTER,
    )


def recogida_de_dueno(paseo, id_dueno):
    """
    Ajuste del 20 de octubre, punto 3 - entrada de `paseo['recogidas']`
    de ESE dueño, o `None` si el paseo es legacy (sin el campo) o si ese
    dueño no tiene ninguna entrada (no debería pasar para un
    `id_duenos` real, pero nunca se asume). Función PÚBLICA y
    compartida: a diferencia de los helpers `_privados` de cada app
    (que duplican a propósito este mismo recorrido para no cruzar
    imports entre apps - ver `_recogida_de_dueno()` en este mismo
    archivo, `views_web.py`), esta sí la necesitan otras apps
    (`coordenadas`, `usuarios`, `calificaciones`) para decidir el
    estado de ESE dueño sin repetir el array-scan cuatro veces - vive
    en `repository.py` como función pura (sin acceso a Mongo), mismo
    criterio que `etiqueta_duracion_acordada()`.
    """
    if 'recogidas' not in paseo:
        return None
    oid_dueno = id_dueno if isinstance(id_dueno, ObjectId) else ObjectId(id_dueno)
    return next((r for r in paseo['recogidas'] if r['id_dueno'] == oid_dueno), None)


def dueno_puede_calificar(paseo, id_dueno):
    """
    Punto 3 (20 oct) - "la calificación se habilita por dueño cuando su
    recogida está entregada, no cuando el paseo completo pasa a
    historico". Un paseo legacy (sin `recogidas`) mantiene la regla
    vieja: todo el paseo debe estar 'historico'. `no_recogida` NUNCA
    habilita calificar (pedido explícito: "no se puede calificar").
    """
    entrada = recogida_de_dueno(paseo, id_dueno)
    if entrada is None:
        return paseo['estado'] == 'historico'
    return entrada['estado'] == 'entregada'


def dueno_recogida_resuelta(paseo, id_dueno):
    """
    Punto 3 (20 oct) - True si para ESTE dueño ya no queda nada
    pendiente en este paseo ('entregada' O 'no_recogida' - los dos
    "se resuelven", aunque solo 'entregada' se pueda calificar, ver
    dueno_puede_calificar()) - usado para decidir si este paseo va en
    "Paseos activos" o en el historial de ESE dueño, que ya no depende
    de `paseo.estado` completo. Legacy: regla vieja, el paseo entero
    'historico'.
    """
    entrada = recogida_de_dueno(paseo, id_dueno)
    if entrada is None:
        return paseo['estado'] == 'historico'
    return entrada['estado'] in ('entregada', 'no_recogida')


def todas_las_recogidas_resueltas(paseo):
    """
    Punto 3 (20 oct) - True si NINGUNA recogida sigue 'pendiente' ni
    'recogida' - MISMO criterio que el filtro atómico de
    finalizar_paseo() (`$not`/`$elemMatch`), pero evaluado en Python
    sobre un documento ya en memoria (se usa para decidir si vale la
    pena INTENTAR el auto-finalizado tras marcar_entrega()/
    marcar_no_recogida(), sin otra consulta a Mongo de por medio - la
    condición real, atómica, sigue siendo la de finalizar_paseo()).
    """
    return not any(r['estado'] in ('pendiente', 'recogida') for r in paseo.get('recogidas', []))


def marcar_entrega(*, id_paseo, id_paseador, id_dueno):
    """
    "Entregado": la recogida de ESE dueño pasa de 'recogida' a
    'entregada' y se guarda `hora_entrega`. Solo si estaba 'recogida'
    (nunca desde 'pendiente' - no se puede entregar lo que no se
    recogió).
    """
    try:
        oid_paseo = ObjectId(id_paseo)
        oid_dueno = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return None
    return get_db().paseos.find_one_and_update(
        {
            '_id': oid_paseo,
            'id_paseador': id_paseador,
            'estado': 'en_vivo',
            'recogidas': {'$elemMatch': {'id_dueno': oid_dueno, 'estado': 'recogida'}},
        },
        {'$set': {
            'recogidas.$[entrada].estado': 'entregada',
            'recogidas.$[entrada].hora_entrega': datetime.now(timezone.utc),
        }},
        array_filters=[{'entrada.id_dueno': oid_dueno}],
        return_document=ReturnDocument.AFTER,
    )


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
    le pertenece a ese paseador y esta actualmente en curso.

    Incremento 4 fase 3, punto A2, punto 5 - además, SOLO si ninguna
    recogida sigue en 'pendiente' ni 'recogida' (toda mascota ya fue
    recogida-y-entregada, o se marcó explícitamente 'no_recogida'). Esto
    es la defensa de BACKEND, obligatoria - el frontend deshabilita el
    botón con el mismo criterio, pero un POST directo también se
    rechaza acá. `$not`/`$elemMatch`: ningún elemento de `recogidas`
    puede tener ese estado; un paseo SIN el campo `recogidas` (de antes
    de esta fase) o con `recogidas: []` no bloquea - un array ausente o
    vacío nunca matchea `$elemMatch`, así que `$not` sobre eso es
    verdadero.

    Devuelve el documento actualizado, o None si no se cumplen las
    condiciones.
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
            'recogidas': {'$not': {'$elemMatch': {'estado': {'$in': ['pendiente', 'recogida']}}}},
        },
        {'$set': {'estado': 'historico', 'hora_fin': datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER,
    )


def guardar_distancia(id_paseo, distancia_m):
    """
    Ajustes del 19 de octubre, punto 1 - se llama UNA vez, al finalizar
    el paseo (ver finalizar_paseo() en paseos/views_web.py), para que el
    historial no tenga que recalcular la distancia desde
    coordenadas_detalle cada vez que se consulta. `distancia_m` puede
    ser None (paseo con menos de 2 puntos GPS validos) - se guarda igual,
    para distinguir "se calculó y dio None" de "nunca se calculó"
    (paseos de ANTES de este punto, que no tienen el campo en absoluto -
    ver CLAUDE.md).
    """
    get_db().paseos.update_one({'_id': ObjectId(id_paseo)}, {'$set': {'distancia_m': distancia_m}})


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


def paseador_tiene_acceso_a_mascota(id_paseador, id_mascota):
    """
    True si existe AL MENOS UN paseo, en CUALQUIER estado, donde este
    paseador es el asignado (`id_paseador`) y esa mascota esta incluida
    (`id_mascotas`) - control de acceso para los certificados de la
    mascota (Ley Kiara). Una mascota se agrega a `id_mascotas` al
    inscribirse en un horario "disponible" (ver inscribir_mascotas()) y
    ese array ya NUNCA se modifica despues (ni al pasar a "en_vivo" ni a
    "historico") - por eso no hace falta filtrar por estado aca: "alguna
    vez la llevó o la va a llevar" es exactamente "aparece en algun
    documento con ese id_paseador".

    Una sola función, pensada para llamarse DESDE el backend antes de
    mostrar cualquier dato de certificado a un paseador - no basta con
    ocultar el link en la plantilla.
    """
    try:
        oid_paseador = id_paseador if isinstance(id_paseador, ObjectId) else ObjectId(id_paseador)
        oid_mascota = id_mascota if isinstance(id_mascota, ObjectId) else ObjectId(id_mascota)
    except (InvalidId, TypeError):
        return False
    return get_db().paseos.count_documents(
        {'id_paseador': oid_paseador, 'id_mascotas': oid_mascota},
        limit=1,
    ) > 0


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
