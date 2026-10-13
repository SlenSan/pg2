"""Context processors globales del proyecto."""

from datetime import datetime

from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings

from notificaciones import repository as notificaciones_repository
from paseos import repository as paseos_repository


def notificaciones(request):
    """
    Disponibiliza "hay_notificaciones_sin_leer" en CUALQUIER render (el
    punto del navbar compartido - ver core/templates/base.html - se
    muestra en toda pantalla autenticada, de cualquier rol), sin que cada
    vista tenga que calcularlo y pasarlo a mano. Mismo mecanismo de "vista
    hasta" en sesion que ya usan notificaciones/repository.py y las
    vistas de dashboard.
    """
    id_usuario = request.session.get('id_usuario')
    if not id_usuario:
        return {}
    ultima_vista_str = request.session.get('notificaciones_vistas_hasta')
    ultima_vista = datetime.fromisoformat(ultima_vista_str) if ultima_vista_str else None
    return {
        'hay_notificaciones_sin_leer': notificaciones_repository.hay_no_leidas(id_usuario, ultima_vista),
    }


def es_admin(request):
    """
    Disponibiliza "es_admin" en cualquier render, para que el navbar
    (core/templates/base.html) muestre el link al panel de verificacion
    SOLO a quienes son admin (ver usuarios.decorators.requiere_admin) -
    sin esto, cada vista tendria que calcularlo a mano solo para el
    navbar.
    """
    correo_sesion = (request.session.get('correo') or '').strip().lower()
    return {'es_admin': bool(correo_sesion) and correo_sesion in settings.CANIGO_ADMIN_EMAILS}


def id_paseo_en_vivo_del_paseador(request):
    """
    Disponibiliza "id_paseo_en_vivo_del_paseador" en CUALQUIER render,
    para que core/templates/base.html pueda incluir el emisor de GPS una
    sola vez, sin importar en que pantalla este el paseador (Incremento
    4, punto D1 - "un solo emisor, que no se corte al salir de
    bienvenida_paseador.html" - INC-04 del 12 oct: antes el envio vivia
    SOLO ahi, asi que abrir el formulario de emergencia, subir una foto,
    o ir a cualquier otra pantalla lo cortaba por completo).

    Una consulta mas por pagina, pero SOLO para un paseador autenticado
    (el mismo filtro id_paseador+estado que ya tiene indice compuesto,
    ver core/management/commands/crear_indices.py) - None para
    cualquier otro caso (dueño, sin sesion, paseador sin paseo en_vivo
    ahora mismo), que es la inmensa mayoria de las paginas vistas.
    """
    if request.session.get('rol') != 'paseador':
        return {}
    id_usuario = request.session.get('id_usuario')
    if not id_usuario:
        return {}
    try:
        oid = ObjectId(id_usuario)
    except (InvalidId, TypeError):
        return {}
    paseo = paseos_repository.obtener_en_vivo_de_paseador(oid)
    return {'id_paseo_en_vivo_del_paseador': str(paseo['_id'])} if paseo else {}
