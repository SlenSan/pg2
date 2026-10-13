"""
Acceso a la coleccion `incidentes` de MongoDB (RF12/RF16 - nucleo
diferenciador del proyecto). A diferencia de coordenadas_detalle, un
incidente "queda permanente": no tiene indice TTL ni se borra nunca.
"""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db

TIPOS_VALIDOS = (
    'fuga_animal',
    'mordedura_agresion',
    'accidente_animal',
    'accidente_paseador',
    'otro',
)


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
