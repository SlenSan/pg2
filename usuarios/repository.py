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


def agregar_certificado_paseador(id_usuario, *, tipo, nombre, entidad, fecha_expedicion, url, public_id, formato):
    """
    $push a `usuarios.certificados` (array, solo rol=paseador) - cada
    certificado tiene su propio `id` (un ObjectId nuevo, no el `_id` del
    usuario) para poder borrarlo individualmente despues (ver
    eliminar_certificado_paseador). No hay "editar" un certificado
    existente - se borra y se sube de nuevo.
    """
    oid = id_usuario if isinstance(id_usuario, ObjectId) else ObjectId(id_usuario)
    certificado = {
        'id': ObjectId(),
        'tipo': tipo,
        'nombre': nombre,
        'entidad': entidad,
        'fecha_expedicion': fecha_expedicion,
        'url': url,
        'public_id': public_id,
        'formato': formato,
        'subido_en': datetime.now(timezone.utc),
    }
    get_db().usuarios.update_one({'_id': oid}, {'$push': {'certificados': certificado}})
    return certificado


def eliminar_certificado_paseador(id_usuario, id_certificado):
    """
    $pull por `id` del subdocumento - acotado a `_id: oid_usuario` en el
    filtro, asi que un paseador solo puede borrar certificados de SU
    PROPIO arreglo (la vista ya lo limita a su propia sesion, pero el
    filtro de Mongo lo hace doblemente seguro). Devuelve el certificado
    borrado (o None si no existia) para poder limpiar su archivo en
    Cloudinary sin una consulta aparte.
    """
    oid = id_usuario if isinstance(id_usuario, ObjectId) else ObjectId(id_usuario)
    try:
        oid_certificado = ObjectId(id_certificado)
    except (InvalidId, TypeError):
        return None
    usuario = get_db().usuarios.find_one_and_update(
        {'_id': oid},
        {'$pull': {'certificados': {'id': oid_certificado}}},
    )
    if not usuario:
        return None
    return next((c for c in usuario.get('certificados', []) if c['id'] == oid_certificado), None)


def listar_paseadores(verificado=None):
    """
    Paseadores para el panel de administracion (RF14). `verificado`:
    None = todos, True = solo verificados, False = solo pendientes.
    """
    query = {'rol': 'paseador'}
    if verificado is not None:
        query['verificado'] = verificado
    return list(get_db().usuarios.find(query).sort('fecha_registro', -1))


def _entrada_verificacion(*, estado, revisado_por, observacion):
    return {
        'estado': estado,
        'revisado_por': revisado_por,
        'fecha': datetime.now(timezone.utc),
        'observacion': (observacion or '').strip(),
    }


def marcar_verificado(id_usuario, *, revisado_por, observacion=''):
    """
    Marca a un paseador como verificado (RF14). La regla "debe tener al
    menos un certificado de primeros auxilios" NO se valida aca - es una
    regla de negocio que valida la vista (administracion/views_web.py)
    antes de llamar a esta funcion; este repository solo escribe.
    `revisado_por` es el CORREO del admin (o "sistema" para el retiro
    automatico - ver retirar_verificado()). Guarda el estado actual en
    `verificacion` y agrega la misma entrada al final de
    `verificacion_historial` ($push), para no perder el historial previo.
    """
    entrada = _entrada_verificacion(estado='verificado', revisado_por=revisado_por, observacion=observacion)
    oid = id_usuario if isinstance(id_usuario, ObjectId) else ObjectId(id_usuario)
    get_db().usuarios.update_one(
        {'_id': oid},
        {'$set': {'verificado': True, 'verificacion': entrada}, '$push': {'verificacion_historial': entrada}},
    )
    return entrada


def retirar_verificado(id_usuario, *, revisado_por, observacion=''):
    """
    Retira la verificacion - usada tanto por un admin desde el panel
    como automaticamente por el sistema (`revisado_por='sistema'`)
    cuando un paseador verificado borra su ultimo certificado de
    primeros auxilios (ver eliminar_certificado_paseador en
    usuarios/views_web.py).
    """
    entrada = _entrada_verificacion(estado='no_verificado', revisado_por=revisado_por, observacion=observacion)
    oid = id_usuario if isinstance(id_usuario, ObjectId) else ObjectId(id_usuario)
    get_db().usuarios.update_one(
        {'_id': oid},
        {'$set': {'verificado': False, 'verificacion': entrada}, '$push': {'verificacion_historial': entrada}},
    )
    return entrada


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
