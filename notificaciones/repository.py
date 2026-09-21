"""Acceso a la coleccion `notificaciones` de MongoDB."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db


def crear(*, id_usuario, tipo, mensaje):
    """
    `tipo` debe ser uno de: "inicio_paseo", "fin_paseo", "emergencia",
    "calificacion" (ver esquema en el documento de grado).
    """
    notificacion = {
        'id_usuario': id_usuario if isinstance(id_usuario, ObjectId) else ObjectId(id_usuario),
        'tipo': tipo,
        'mensaje': mensaje,
        'fecha': datetime.now(timezone.utc),
    }
    resultado = get_db().notificaciones.insert_one(notificacion)
    notificacion['_id'] = resultado.inserted_id
    return notificacion


def listar_por_usuario(id_usuario):
    try:
        oid = ObjectId(id_usuario)
    except (InvalidId, TypeError):
        return []
    return list(get_db().notificaciones.find({'id_usuario': oid}).sort('fecha', -1))


def hay_no_leidas(id_usuario, ultima_vista):
    """
    True si el usuario tiene alguna notificacion mas nueva que
    `ultima_vista` (None = nunca visito la pantalla de notificaciones,
    asi que cualquier notificacion existente cuenta). Mismo mecanismo de
    "vista hasta" en sesion que ya usa notificaciones/views.py, extraido
    aca para que los dashboards (carga completa y polling) puedan
    reutilizarlo sin duplicar la comparacion.
    """
    try:
        oid = ObjectId(id_usuario)
    except (InvalidId, TypeError):
        return False
    query = {'id_usuario': oid}
    if ultima_vista is not None:
        query['fecha'] = {'$gt': ultima_vista}
    return get_db().notificaciones.find_one(query) is not None
