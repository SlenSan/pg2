"""
Acceso a la coleccion `incidentes` de MongoDB (RF12/RF16 - nucleo
diferenciador del proyecto). A diferencia de coordenadas_detalle, un
incidente "queda permanente": no tiene indice TTL ni se borra nunca.
"""

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db

# INC-06 (13 oct, hallazgo de la caminata real) + limpieza: antes esta
# tupla (TIPOS_VALIDOS) y las choices de ReportarIncidenteForm
# (incidentes/forms.py) eran DOS listas independientes con el mismo
# contenido escrito dos veces - y esta de aca ni siquiera se usaba en
# ningún lado (confirmado con una búsqueda en todo el proyecto antes de
# tocarla), así que ya se habían desincronizado en los hechos: forms.py
# tenía las etiquetas legibles, esta no tenía ninguna. Ahora es la
# ÚNICA fuente de verdad (valor + etiqueta legible), igual que
# ZONAS_VALIDAS_CON_NUMERO en paseos/repository.py - forms.py importa
# de aca, no al revés.
TIPOS_VALIDOS_CON_ETIQUETA = (
    ('fuga_animal', 'Fuga del animal'),
    ('mordedura_agresion', 'Mordedura o agresión'),
    ('accidente_animal', 'Accidente del animal'),
    ('accidente_paseador', 'Accidente del paseador'),
    ('otro', 'Otro'),
)
TIPOS_VALIDOS = tuple(valor for valor, _ in TIPOS_VALIDOS_CON_ETIQUETA)
_ETIQUETA_POR_TIPO = dict(TIPOS_VALIDOS_CON_ETIQUETA)


def etiqueta_tipo_incidente(tipo):
    """
    Formato legible de un `tipo` de incidente ("mordedura_agresion" ->
    "Mordedura o agresión") - ÚNICA función de la que sale el texto,
    reusada en el detalle, la lista, y el mensaje de notificación (ver
    incidentes/templatetags/incidentes_tags.py para el filtro de
    plantilla). Si `tipo` no es uno de los válidos (no debería pasar,
    pero nunca se asume), devuelve el valor tal cual en vez de fallar.
    """
    return _ETIQUETA_POR_TIPO.get(tipo, tipo)


def crear(*, id_paseo, tipo, id_mascota, descripcion, evidencia_foto, latitud, longitud, direccion_aproximada=None):
    incidente = {
        'id_paseo': id_paseo if isinstance(id_paseo, ObjectId) else ObjectId(id_paseo),
        'tipo': tipo,
        # None solo para "accidente_paseador" - ver ReportarIncidenteForm.
        'id_mascota': id_mascota,
        'descripcion': descripcion,
        'evidencia_foto': evidencia_foto,
        'latitud': latitud,
        'longitud': longitud,
        # Geocodificacion inversa (Nominatim) al momento de guardar -
        # Incremento 4, punto C. None si no hay coordenadas, si el
        # servicio falla, o si tarda mas de 5s (ver core/geocoding.py) -
        # el incidente se guarda igual, nunca se bloquea por esto.
        'direccion_aproximada': direccion_aproximada,
        'fecha_hora': datetime.now(timezone.utc),
        'notificado': False,
    }
    resultado = get_db().incidentes.insert_one(incidente)
    incidente['_id'] = resultado.inserted_id
    return incidente


def marcar_notificado(id_incidente):
    get_db().incidentes.update_one({'_id': id_incidente}, {'$set': {'notificado': True}})


_SEGUNDOS_DUPLICADO_INCIDENTE = 10


def obtener_duplicado_reciente(*, id_paseo, tipo, id_mascota, descripcion):
    """
    Busca un incidente IDENTICO (mismo paseo, tipo, mascota afectada y
    descripción) creado hace menos de `_SEGUNDOS_DUPLICADO_INCIDENTE` -
    Incremento 4, fase 1, punto 3: el botón "Enviar reporte" se
    deshabilita mientras se envía (ver bienvenida_paseador.html), pero
    esto es la defensa de fondo en el BACKEND para un doble toque que
    igual llegue a mandar dos POST (red lenta, dos pestañas, etc.) - sin
    esto, un doble toque creaba dos incidentes idénticos y notificaba al
    dueño dos veces por el mismo hecho.
    """
    limite = datetime.now(timezone.utc) - timedelta(seconds=_SEGUNDOS_DUPLICADO_INCIDENTE)
    return get_db().incidentes.find_one({
        'id_paseo': id_paseo,
        'tipo': tipo,
        'id_mascota': id_mascota,
        'descripcion': descripcion,
        'fecha_hora': {'$gte': limite},
    }, sort=[('fecha_hora', -1)])


def obtener_por_id(id_incidente):
    try:
        oid = id_incidente if isinstance(id_incidente, ObjectId) else ObjectId(id_incidente)
    except (InvalidId, TypeError):
        return None
    return get_db().incidentes.find_one({'_id': oid})


def listar_por_paseo(id_paseo):
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return []
    return list(get_db().incidentes.find({'id_paseo': oid}).sort('fecha_hora', -1))


def listar_por_paseos(ids_paseo):
    """
    Incidentes de varios paseos a la vez, SIN filtrar por mascota - uso
    exclusivo del paseador (ve todos los incidentes de sus propios
    paseos, sin nada que ocultarle). El dueño NUNCA debe usar esta
    función directamente - ver listar_visibles_para_dueno().
    """
    ids_validos = [i for i in ids_paseo if isinstance(i, ObjectId)]
    if not ids_validos:
        return []
    return list(get_db().incidentes.find({'id_paseo': {'$in': ids_validos}}).sort('fecha_hora', -1))


def listar_visibles_para_dueno(ids_paseo, ids_mascota_dueno):
    """
    Incidentes de esos paseos que ESTE dueño puede ver (corrección de
    privacidad, 12 oct): solo los que afectan a una de SUS mascotas, o
    los que no afectan a ninguna mascota en particular (tipo
    "accidente_paseador" - ver CLAUDE.md, id_mascota=None, afecta a
    TODAS las mascotas del paseo por igual). Nunca el incidente de la
    mascota de OTRO dueño en un paseo multi-dueño (hasta 8 mascotas,
    Ley Kiara) - ni el documento, ni el hecho de que existe.
    """
    ids_paseo_validos = [i for i in ids_paseo if isinstance(i, ObjectId)]
    if not ids_paseo_validos:
        return []
    return list(get_db().incidentes.find({
        'id_paseo': {'$in': ids_paseo_validos},
        '$or': [
            {'id_mascota': {'$in': list(ids_mascota_dueno)}},
            {'id_mascota': None},
        ],
    }).sort('fecha_hora', -1))


def a_json(incidente):
    data = dict(incidente)
    data['_id'] = str(data['_id'])
    data['id_paseo'] = str(data['id_paseo'])
    if isinstance(data.get('fecha_hora'), datetime):
        data['fecha_hora'] = data['fecha_hora'].isoformat()
    return data
