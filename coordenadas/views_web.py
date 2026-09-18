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
from mascotas import repository as mascotas_repository
from paseos import repository as paseos_repository
from usuarios import repository as usuarios_repository
from usuarios.decorators import requiere_dueno, requiere_paseador


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

    mascota = None
    paseador = None
    if paseo.get('id_mascota'):
        mascota = mascotas_repository.obtener_varias_por_id([paseo['id_mascota']]).get(paseo['id_mascota'])
    if paseo.get('id_paseador'):
        paseador = usuarios_repository.obtener_por_id(paseo['id_paseador'])

    return render(request, 'coordenadas/mapa.html', {
        'paseo': paseo,
        'id_paseo': str(paseo['_id']),
        'mascota': mascota,
        'paseador': paseador,
        'hora_inicio_iso': _fecha_iso_utc(paseo.get('hora_inicio')),
        'hora_fin_iso': _fecha_iso_utc(paseo.get('hora_fin')),
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
        'puntos': [repository.a_json(p) for p in puntos],
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
    return JsonResponse({'total_puntos': total_puntos}, status=201)
