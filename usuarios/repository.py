"""
Acceso a la coleccion `usuarios` de MongoDB.

Esta capa no sabe nada de HTTP ni de la vista web/API que la llama:
solo lee y escribe documentos en la coleccion `usuarios`, siguiendo el
esquema definido en el documento de grado.
"""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db, mapear_por_id


def obtener_por_correo(correo):
    return get_db().usuarios.find_one({'correo': correo})


def obtener_por_id(id_usuario):
    try:
        oid = ObjectId(id_usuario)
    except (InvalidId, TypeError):
        return None
    return get_db().usuarios.find_one({'_id': oid})


def obtener_varios_por_id(ids):
    """Devuelve {ObjectId: usuario} para una lista de ids (p.ej. id_paseador)."""
    return mapear_por_id('usuarios', ids)


def crear_usuario(*, nombre, correo, contrasena_hash, telefono, rol, direccion='', descripcion=''):
    """Inserta un usuario nuevo. `rol` debe ser 'dueño' o 'paseador'."""
    usuario = {
        'nombre': nombre,
        'correo': correo,
        'contrasena': contrasena_hash,
        'telefono': telefono,
        'rol': rol,
        'foto_perfil': '',
        'direccion': direccion,
        'fecha_registro': datetime.now(timezone.utc),
    }
    if rol == 'paseador':
        usuario.update({
            'calificacion_promedio': None,
            'verificado': False,
            'descripcion': descripcion,
        })

    resultado = get_db().usuarios.insert_one(usuario)
    usuario['_id'] = resultado.inserted_id
    return usuario


def actualizar_calificacion_promedio(id_paseador, promedio):
    oid = id_paseador if isinstance(id_paseador, ObjectId) else ObjectId(id_paseador)
    get_db().usuarios.update_one({'_id': oid}, {'$set': {'calificacion_promedio': promedio}})


def actualizar_perfil_paseador(*, id_usuario, telefono, descripcion, foto_perfil):
    """
    Solo los campos que el propio paseador puede editar (ver
    usuarios.forms.EditarPerfilPaseadorForm): correo/rol/
    calificacion_promedio/verificado se quedan fuera a propósito.
    """
    oid = id_usuario if isinstance(id_usuario, ObjectId) else ObjectId(id_usuario)
    get_db().usuarios.update_one(
        {'_id': oid},
        {'$set': {'telefono': telefono, 'descripcion': descripcion, 'foto_perfil': foto_perfil}},
    )


def a_json(usuario):
    """Representacion de un usuario segura para exponer por la API (sin la contrasena)."""
    data = {k: v for k, v in usuario.items() if k != 'contrasena'}
    data['_id'] = str(data['_id'])
    if isinstance(data.get('fecha_registro'), datetime):
        data['fecha_registro'] = data['fecha_registro'].isoformat()
    return data
