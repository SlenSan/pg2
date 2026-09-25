from datetime import datetime, timezone

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from notificaciones import repository
from paseos import repository as paseos_repository
from usuarios.decorators import requiere_autenticacion

_TIPO_INFO = {
    'inicio_paseo': {'titulo': 'Paseo iniciado', 'icono': 'bi-play-circle-fill', 'color': 'verde'},
    'fin_paseo': {'titulo': 'Paseo finalizado', 'icono': 'bi-flag-fill', 'color': 'ambar'},
    'emergencia': {'titulo': '¡Emergencia reportada!', 'icono': 'bi-exclamation-triangle-fill', 'color': 'rojo'},
    'calificacion': {'titulo': 'Nueva calificación', 'icono': 'bi-star-fill', 'color': 'amarillo'},
}


def _url_destino(tipo, rol, id_usuario):
    """
    A donde lleva un clic en una notificacion, segun su tipo Y el rol de
    quien la esta viendo (la plantilla es compartida entre dueño y
    paseador). El esquema de `notificaciones` no guarda un id_paseo (ver
    CLAUDE.md), asi que no se puede enlazar al paseo exacto - se enlaza al
    lugar mas relevante segun el tipo: el paseo en vivo si hay uno, o el
    historial/listado correspondiente si no.
    """
    if rol == 'dueño':
        if tipo in ('inicio_paseo', 'fin_paseo'):
            paseo_en_vivo = next(
                (p for p in paseos_repository.listar_por_dueno(id_usuario) if p['estado'] == 'en_vivo'),
                None,
            )
            if paseo_en_vivo:
                return reverse('coordenadas:mapa_paseo', args=[str(paseo_en_vivo['_id'])])
            return reverse('paseos:historial')
        if tipo == 'emergencia':
            return reverse('incidentes:lista')
        return reverse('paseos:historial')

    # paseador
    if tipo == 'calificacion':
        return reverse('paseos:historial_paseador')
    return reverse('usuarios:bienvenida_paseador')


@requiere_autenticacion
def lista_notificaciones(request):
    id_usuario = request.session['id_usuario']
    rol = request.session.get('rol')
    notificaciones = repository.listar_por_usuario(id_usuario)

    # El esquema de `notificaciones` no tiene un campo `leido` (ver
    # decision de un Paso previo), asi que "no leida" se aproxima
    # comparando la fecha contra la marca de "vista hasta" de la sesion.
    # Se lee ANTES de pisarla con la fecha de esta misma visita, para que
    # esta pantalla pueda mostrar que fue lo nuevo desde la ultima vez.
    ultima_vista_str = request.session.get('notificaciones_vistas_hasta')
    ultima_vista = datetime.fromisoformat(ultima_vista_str) if ultima_vista_str else None

    items = []
    no_leidas = 0
    for n in notificaciones:
        leida = ultima_vista is not None and n['fecha'] <= ultima_vista
        if not leida:
            no_leidas += 1
        info = _TIPO_INFO.get(n['tipo'], {'titulo': 'Notificación', 'icono': 'bi-bell-fill', 'color': 'naranja'})
        # pymongo devuelve datetimes naive en UTC (ver mapa.html/coordenadas
        # para el mismo problema ya resuelto ahi): sin marcar tzinfo=utc
        # explicitamente, el filtro `naturaltime` (USE_TZ=True) asume que
        # es hora LOCAL (America/Bogota) y calcula mal "hace X" (se ve
        # como si fuera en el futuro).
        fecha_utc = n['fecha'].replace(tzinfo=timezone.utc)
        items.append({
            'notificacion': {**n, 'fecha': fecha_utc},
            'leida': leida,
            'titulo': info['titulo'],
            'icono': info['icono'],
            'color': info['color'],
            'url_destino': _url_destino(n['tipo'], rol, id_usuario),
        })

    request.session['notificaciones_vistas_hasta'] = (
        datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    )
    return render(request, 'notificaciones/lista.html', {'items': items, 'no_leidas': no_leidas})


@requiere_autenticacion
def estado_no_leidas(request):
    """
    Poller GENERICO del punto de notificaciones del navbar (ver
    core/templates/base.html) - cubre cualquier pantalla que no tenga ya
    su propia peticion periodica con este dato incluido (dashboards,
    mapa en vivo - ver esos templates, que dejan vacio el bloque
    "polling_notificaciones" para no duplicar la peticion contra este
    endpoint). Sirve para cualquiera de los dos roles.
    """
    id_usuario = request.session['id_usuario']
    ultima_vista_str = request.session.get('notificaciones_vistas_hasta')
    ultima_vista = datetime.fromisoformat(ultima_vista_str) if ultima_vista_str else None
    return JsonResponse({'hay_notificaciones_sin_leer': repository.hay_no_leidas(id_usuario, ultima_vista)})
