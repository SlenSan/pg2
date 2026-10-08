"""Acceso a la coleccion `mascotas` de MongoDB."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db, mapear_por_id


def crear_mascota(*, id_dueno, nombre, raza, edad, peso, observaciones='', foto=''):
    mascota = {
        'id_dueno': ObjectId(id_dueno),
        'nombre': nombre,
        'raza': raza,
        'edad': edad,
        'peso': peso,
        'foto': foto,
        'observaciones': observaciones,
        'fecha_registro': datetime.now(timezone.utc),
    }
    resultado = get_db().mascotas.insert_one(mascota)
    mascota['_id'] = resultado.inserted_id
    return mascota


def listar_por_dueno(id_dueno):
    try:
        oid = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return []
    return list(get_db().mascotas.find({'id_dueno': oid}).sort('fecha_registro', -1))


def obtener_por_id_y_dueno(id_mascota, id_dueno):
    """
    None si la mascota no existe O no es de ese dueño - la vista usa el
    mismo mensaje para los dos casos (no hay motivo para distinguirle a
    quien manipula el id en la URL si el id existe pero es ajeno).
    """
    try:
        oid = ObjectId(id_mascota)
        oid_dueno = ObjectId(id_dueno)
    except (InvalidId, TypeError):
        return None
    return get_db().mascotas.find_one({'_id': oid, 'id_dueno': oid_dueno})


def actualizar_mascota(id_mascota, *, nombre, raza, edad, peso, observaciones='', foto=None):
    """
    `foto=None` significa "no reemplazar" (se deja la que ya tenia) -
    distinto de `foto=''`, que si se guardaria como "sin foto". Edicion
    reusa MascotaForm, donde `foto` ya es opcional (igual que en
    registro), asi que no reemplazarla es el camino normal, no una
    excepcion.
    """
    cambios = {
        'nombre': nombre,
        'raza': raza,
        'edad': edad,
        'peso': peso,
        'observaciones': observaciones,
    }
    if foto is not None:
        cambios['foto'] = foto
    get_db().mascotas.update_one({'_id': ObjectId(id_mascota)}, {'$set': cambios})


def obtener_varias_por_id(ids):
    """Devuelve {ObjectId: mascota} para una lista de ids."""
    return mapear_por_id('mascotas', ids)


def obtener_varias_por_id_y_dueno(ids, id_dueno):
    """
    Devuelve SOLO las mascotas de esa lista que pertenecen a ese dueño -
    evita inscribir mascotas ajenas. Se valida la lista COMPLETA (el
    llamador compara len(resultado) == len(ids) pedidos) en vez de una
    mascota a la vez, porque ahora un paseo puede llevar varias juntas.
    """
    try:
        oid_dueno = ObjectId(id_dueno)
        oids = [ObjectId(i) for i in ids]
    except (InvalidId, TypeError):
        return []
    if not oids:
        return []
    return list(get_db().mascotas.find({'_id': {'$in': oids}, 'id_dueno': oid_dueno}))


def resolver_lista(ids_mascota, mascotas_por_id):
    """
    Lista ORDENADA de documentos de mascota a partir de una lista de ids
    (paseos.id_mascotas) y un mapa {ObjectId: mascota} ya resuelto (ver
    obtener_varias_por_id) - una mascota que ya no exista se omite en vez
    de romper la pantalla. Usado en cada lugar que antes mostraba "la
    mascota" de un paseo y ahora muestra "las mascotas".
    """
    return [mascotas_por_id[mid] for mid in (ids_mascota or []) if mid in mascotas_por_id]


def nombres_unidos(mascotas):
    """'Dobby, Luna' (o '' si la lista esta vacia) a partir de una lista de documentos de mascota."""
    return ', '.join(m['nombre'] for m in mascotas)
