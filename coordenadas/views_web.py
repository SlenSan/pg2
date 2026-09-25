"""
Vistas web:
- Dueño: pagina del mapa en vivo/historico y el endpoint JSON que
  consume el JavaScript de Leaflet para pintar la ruta.
- Paseador: endpoint que su navegador llama (via navigator.geolocation)
  cada 10s mientras el paseo esta "en_vivo", autenticado por sesion (no
  por token - la app Android ya no existe, ver CLAUDE.md).
"""

import json
from datetime import datetime

from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from coordenadas import repository
from incidentes import repository as incidentes_repository
from mascotas import repository as mascotas_repository
from notificaciones import repository as notificaciones_repository
from paseos import repository as paseos_repository
from usuarios import repository as usuarios_repository
from usuarios.decorators import requiere_dueno, requiere_paseador


def _hay_notificaciones_sin_leer(request, id_usuario):
    """
    Mismo mecanismo de "vista hasta" en sesion que usuarios/views_web.py -
    duplicada aca (no importada de ahi) para no crear una dependencia
    cruzada entre esas dos apps por una funcion de 3 lineas; ambas llaman
    al mismo notificaciones_repository.hay_no_leidas().
    """
    ultima_vista_str = request.session.get('notificaciones_vistas_hasta')
    ultima_vista = datetime.fromisoformat(ultima_vista_str) if ultima_vista_str else None
    return notificaciones_repository.hay_no_leidas(id_usuario, ultima_vista)

_TEXTO_INCIDENTE_GENERICO = 'Se reportó un incidente durante este paseo.'


def _texto_incidente(id_paseo):
    """
    Texto del banner de emergencia del mapa, o None si no hay que
    mostrarlo. El resultado de esta funcion es la UNICA fuente de verdad
    de si el banner se muestra - antes se llamaba solo cuando
    paseo.emergencia era truthy, pero si por algun motivo ese campo
    quedaba en True sin un documento real en `incidentes` (desincronia de
    datos), esta funcion igual devolvia el texto generico: se veia un
    banner "fantasma" sin nada detras. Ahora, sin incidentes reales,
    devuelve None sin importar lo que diga paseo.emergencia - "existe un
    documento real" es una condicion, no una opcional.

    Muestra a que mascota afecto el incidente MAS RECIENTE de este paseo
    (si tiene una asignada - ver CLAUDE.md, "accidente_paseador" no
    aplica a ningun animal en particular), o el mensaje generico si no.
    Reusado tanto en la carga inicial de la pagina como en el polling
    (coordenadas_de_paseo), para que el texto se actualice solo si llega
    un incidente nuevo mientras el dueño ya esta mirando el mapa.
    """
    incidentes = incidentes_repository.listar_por_paseo(id_paseo)
    if not incidentes:
        return None
    ultimo = incidentes[0]  # ya viene ordenado por fecha_hora desc
    if ultimo.get('id_mascota'):
        mascota = mascotas_repository.obtener_varias_por_id([ultimo['id_mascota']]).get(ultimo['id_mascota'])
        if mascota:
            return f'Se reportó un incidente que afecta a {mascota["nombre"]}.'
    return _TEXTO_INCIDENTE_GENERICO


def _paseo_del_dueno_o_none(request, id_paseo):
    paseo = paseos_repository.obtener_por_id(id_paseo)
    if not paseo or str(paseo.get('id_dueno')) != request.session.get('id_usuario'):
        return None
    return paseo


def _fecha_iso_utc(valor):
    """
    Los datetimes que devuelve pymongo son naive (UTC sin tzinfo - ver
    core/mongo.py): hay que marcarlos explicitamente como UTC ("Z") antes
    de mandarlos al navegador, o `new Date(...)` en JS los interpreta como
    hora LOCAL del navegador y el tiempo transcurrido queda mal calculado
    por el desfase horario (Colombia es UTC-5).
    """
    return valor.strftime('%Y-%m-%dT%H:%M:%SZ') if valor else None


@requiere_dueno
def mapa_paseo(request, id_paseo):
    paseo = _paseo_del_dueno_o_none(request, id_paseo)
    if not paseo:
        return redirect('paseos:mis_paseos')

    mascotas_por_id = mascotas_repository.obtener_varias_por_id(paseo.get('id_mascotas', []))
    mascotas = mascotas_repository.resolver_lista(paseo.get('id_mascotas'), mascotas_por_id)
    paseador = None
    if paseo.get('id_paseador'):
        paseador = usuarios_repository.obtener_por_id(paseo['id_paseador'])

    return render(request, 'coordenadas/mapa.html', {
        'paseo': paseo,
        'id_paseo': str(paseo['_id']),
        'mascotas': mascotas,
        'paseador': paseador,
        'hora_inicio_iso': _fecha_iso_utc(paseo.get('hora_inicio')),
        'hora_fin_iso': _fecha_iso_utc(paseo.get('hora_fin')),
        # None si no hay un incidente real (ver _texto_incidente) - esto
        # es lo unico que decide si el banner se muestra, no
        # paseo.emergencia por si solo.
        'texto_emergencia': _texto_incidente(paseo['_id']),
    })


@requiere_dueno
def coordenadas_de_paseo(request, id_paseo):
    paseo = _paseo_del_dueno_o_none(request, id_paseo)
    if not paseo:
        return JsonResponse({'error': 'No autorizado.'}, status=403)

    puntos = repository.listar_por_paseo(id_paseo)
    return JsonResponse({
        'estado': paseo['estado'],
        'emergencia': paseo.get('emergencia', False),
        # None si no hay un incidente real (ver _texto_incidente) - el JS
        # decide si mostrar el banner segun esto, no segun "emergencia".
        'texto_emergencia': _texto_incidente(paseo['_id']),
        'puntos': [repository.a_json(p) for p in puntos],
        # Esta pantalla ya hace polling cada 10s mientras el paseo esta
        # "en_vivo" - se aprovecha esa misma peticion para el punto de
        # notificaciones del navbar en vez de sumar una aparte (ver
        # mapa.html, que por eso deja vacio el poller generico de
        # base.html solo mientras esta en ese estado).
        'hay_notificaciones_sin_leer': _hay_notificaciones_sin_leer(request, paseo['id_dueno']),
    })


def _parsear_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
    except ValueError:
        return None


@require_POST
@requiere_paseador
def registrar_coordenada(request, id_paseo):
    """
    Recibe un punto GPS desde el navegador del propio paseador mientras
    su paseo esta "en_vivo" (autenticado por sesion).
    """
    paseo = paseos_repository.obtener_por_id(id_paseo)
    if not paseo or str(paseo.get('id_paseador')) != request.session.get('id_usuario') or paseo['estado'] != 'en_vivo':
        return JsonResponse({
            'error': 'Este paseo no existe, no es tuyo, o no está "en_vivo".',
        }, status=409)

    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido.'}, status=400)

    try:
        latitud = float(data['latitud'])
        longitud = float(data['longitud'])
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {'error': 'latitud y longitud son requeridos y deben ser numéricos.'},
            status=400,
        )
    if not (-90 <= latitud <= 90) or not (-180 <= longitud <= 180):
        return JsonResponse({'error': 'latitud/longitud fuera de rango.'}, status=400)

    altitud = data.get('altitud')
    try:
        altitud = float(altitud) if altitud is not None else None
    except (TypeError, ValueError):
        altitud = None

    repository.registrar_punto(
        id_paseo=paseo['_id'],
        latitud=latitud,
        longitud=longitud,
        altitud=altitud,
        fecha_captura=_parsear_fecha(data.get('fecha_captura')),
    )
    total_puntos = paseos_repository.incrementar_total_puntos(paseo['_id'])
    return JsonResponse({
        'total_puntos': total_puntos,
        # El dashboard del paseador no hace su propio polling de
        # notificaciones mientras esta "en_vivo" (no hay "nueva solicitud"
        # que mostrar ahi - ver estado_bienvenida_paseador()) - se
        # aprovecha este mismo POST de GPS, que ya se manda cada 10s, para
        # el punto del navbar en vez de sumar una peticion aparte.
        'hay_notificaciones_sin_leer': _hay_notificaciones_sin_leer(request, paseo['id_paseador']),
    }, status=201)
