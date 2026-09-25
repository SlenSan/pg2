"""Context processors globales del proyecto."""

from datetime import datetime

from notificaciones import repository as notificaciones_repository


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
