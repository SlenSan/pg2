"""Context processors globales del proyecto."""

from datetime import datetime

from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings

from notificaciones import repository as notificaciones_repository
from paseos import repository as paseos_repository
from usuarios.decorators import es_correo_admin


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


def push(request):
    """
    Disponibiliza "vapid_public_key" en CUALQUIER render (Incremento 4,
    fase 2, punto E) - lo necesita el JS de activación de Web Push
    (notificaciones/templates/notificaciones/_activar_push.html,
    incluido en los dos dashboards) para pushManager.subscribe(). Sin
    costo de consulta (es una constante de settings, no de Mongo) - se
    expone global en vez de pasarlo a mano en cada vista que renderiza
    ese parcial. Cadena vacía si VAPID_PUBLIC_KEY no está configurada -
    el JS lo trata como "Web Push no disponible en este servidor".
    """
    return {'vapid_public_key': settings.VAPID_PUBLIC_KEY}


def es_admin(request):
    """
    Disponibiliza "es_admin" en cualquier render, para que el navbar
    (core/templates/base.html) muestre el link "Verificación de
    paseadores" SOLO a quienes son admin - sin esto, cada vista tendria
    que calcularlo a mano solo para el navbar.

    Reusa usuarios.decorators.es_correo_admin() (revisión de fase 2,
    punto (c)): antes esta función tenía su PROPIA copia de la misma
    comparación que ya hacía requiere_admin() - dos lugares decidiendo
    "es admin" por separado, que podían desincronizarse sin que nada lo
    avisara. Ahora hay una sola fuente de verdad.
    """
    return {'es_admin': es_correo_admin(request.session.get('correo'))}


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
