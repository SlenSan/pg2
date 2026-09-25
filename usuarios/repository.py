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


def resolver_lista(ids_usuario, usuarios_por_id):
    """
    Lista ORDENADA de documentos de usuario a partir de una lista de ids
    (p.ej. paseos.id_duenos) y un mapa {ObjectId: usuario} ya resuelto
    (ver obtener_varios_por_id) - un usuario que ya no exista se omite en
    vez de romper la pantalla. Mismo patron que
    mascotas.repository.resolver_lista(), para los mismos casos donde un
    paseo tiene varios dueños (ver CLAUDE.md, "Corrección de alcance
    2026-09-25").
    """
    return [usuarios_por_id[uid] for uid in (ids_usuario or []) if uid in usuarios_por_id]


def nombres_unidos(usuarios):
    """
    'Andrea, Carlos' (o '' si la lista esta vacia) a partir de una lista
    de documentos de usuario. Mismo patron que
    mascotas.repository.nombres_unidos() - una sola forma de unir nombres
    en todo el proyecto, sea de mascotas o de dueños.
    """
    return ', '.join(u['nombre'] for u in usuarios)


def a_json(usuario):
    """Representacion de un usuario segura para exponer por la API (sin la contrasena)."""
    data = {k: v for k, v in usuario.items() if k != 'contrasena'}
    data['_id'] = str(data['_id'])
    if isinstance(data.get('fecha_registro'), datetime):
        data['fecha_registro'] = data['fecha_registro'].isoformat()
    return data
