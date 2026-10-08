"""Acceso a la coleccion `mascotas` de MongoDB."""

import calendar
from datetime import date, datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db, mapear_por_id

# Ley 2480 de 2025 (Ley Kiara): el certificado de salud vence a los 6
# MESES CALENDARIO de expedido (no dias) - ver estado_certificado_salud().
_MESES_VIGENCIA_CERTIFICADO_SALUD = 6


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


def actualizar_certificado_salud(id_mascota, *, url, public_id, formato, fecha_expedicion):
    get_db().mascotas.update_one({'_id': ObjectId(id_mascota)}, {'$set': {
        'certificado_salud': {
            'url': url,
            'public_id': public_id,
            'formato': formato,
            'fecha_expedicion': fecha_expedicion,
            'subido_en': datetime.now(timezone.utc),
        },
    }})


def actualizar_carne_vacunacion(id_mascota, *, url, public_id, formato):
    get_db().mascotas.update_one({'_id': ObjectId(id_mascota)}, {'$set': {
        'carne_vacunacion': {
            'url': url,
            'public_id': public_id,
            'formato': formato,
            'subido_en': datetime.now(timezone.utc),
        },
    }})


def _sumar_meses(fecha, meses):
    """Suma meses CALENDARIO a `fecha` (no dias) - un certificado expedido
    el 31 de enero vence el 31 de julio, no "31*6 dias despues". Si el mes
    de destino es mas corto (ej. expedido el 31 y destino es febrero), se
    ajusta al ultimo dia de ese mes."""
    mes_total = fecha.month - 1 + meses
    anio = fecha.year + mes_total // 12
    mes = mes_total % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def estado_certificado_salud(certificado_salud):
    """
    Estado del certificado de salud de una mascota (Ley Kiara: vence a
    los 6 meses calendario de expedido), SIEMPRE calculado al leer -
    nunca se guarda un campo "vencido"/"vigente" en Mongo, porque
    quedaria desactualizado con el simple paso del tiempo. Una sola
    funcion para las 3 pantallas que lo muestran (listado y edicion de
    mascotas del dueño, vista del paseador sobre su paseo), para que
    "vencido" signifique lo mismo en todas.

    Devuelve {'clave': 'sin_certificado'|'vigente'|'vencido', 'texto': ...}
    - `clave` para la clase CSS del badge, `texto` ya armado para mostrar.
    """
    if not certificado_salud or not certificado_salud.get('fecha_expedicion'):
        return {'clave': 'sin_certificado', 'texto': 'Sin certificado'}

    fecha_expedicion = certificado_salud['fecha_expedicion']
    if isinstance(fecha_expedicion, datetime):
        fecha_expedicion = fecha_expedicion.date()

    fecha_vencimiento = _sumar_meses(fecha_expedicion, _MESES_VIGENCIA_CERTIFICADO_SALUD)
    hoy = datetime.now(timezone.utc).date()
    if hoy >= fecha_vencimiento:
        return {'clave': 'vencido', 'texto': 'Vencido'}
    return {
        'clave': 'vigente',
        'texto': f'Vigente (vence el {fecha_vencimiento.strftime("%d/%m/%Y")})',
    }
