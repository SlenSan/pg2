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


def crear(*, id_paseo, tipo, id_mascota, descripcion, evidencia_foto, latitud, longitud):
    incidente = {
        'id_paseo': id_paseo if isinstance(id_paseo, ObjectId) else ObjectId(id_paseo),
        'tipo': tipo,
        # None solo para "accidente_paseador" - ver ReportarIncidenteForm.
        'id_mascota': id_mascota,
        'descripcion': descripcion,
        'evidencia_foto': evidencia_foto,
        'latitud': latitud,
        'longitud': longitud,
        'fecha_hora': datetime.now(timezone.utc),
        'notificado': False,
    }
    resultado = get_db().incidentes.insert_one(incidente)
    incidente['_id'] = resultado.inserted_id
    return incidente


def marcar_notificado(id_incidente):
    get_db().incidentes.update_one({'_id': id_incidente}, {'$set': {'notificado': True}})


def listar_por_paseo(id_paseo):
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return []
    return list(get_db().incidentes.find({'id_paseo': oid}).sort('fecha_hora', -1))


def listar_por_paseos(ids_paseo):
    """Incidentes de varios paseos a la vez (para armar un historial)."""
    ids_validos = [i for i in ids_paseo if isinstance(i, ObjectId)]
    if not ids_validos:
        return []
    return list(get_db().incidentes.find({'id_paseo': {'$in': ids_validos}}).sort('fecha_hora', -1))


def a_json(incidente):
    data = dict(incidente)
    data['_id'] = str(data['_id'])
    data['id_paseo'] = str(data['id_paseo'])
    if isinstance(data.get('fecha_hora'), datetime):
        data['fecha_hora'] = data['fecha_hora'].isoformat()
    return data
