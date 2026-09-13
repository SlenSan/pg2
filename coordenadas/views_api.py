"""API REST (JSON) para que la app Android del paseador envie puntos GPS."""

import json
from datetime import datetime

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from coordenadas import repository
from paseos import repository as paseos_repository
from usuarios.api_auth import requiere_paseador


def _leer_json(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None


def _parsear_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
    except ValueError:
        return None


@csrf_exempt
@require_http_methods(['POST'])
@requiere_paseador
def registrar_coordenada(request, id_paseo):
    paseo = paseos_repository.obtener_por_id(id_paseo)
    if not paseo or paseo['id_paseador'] != request.usuario['_id'] or paseo['estado'] != 'en_vivo':
        return JsonResponse({
            'error': 'Este paseo no existe, no es tuyo, o no está "en_vivo".',
        }, status=409)

    data = _leer_json(request)
    if data is None:
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

    punto = repository.registrar_punto(
        id_paseo=paseo['_id'],
        latitud=latitud,
        longitud=longitud,
        altitud=altitud,
        fecha_captura=_parsear_fecha(data.get('fecha_captura')),
    )
    total_puntos = paseos_repository.incrementar_total_puntos(paseo['_id'])
    return JsonResponse(
        {'punto': repository.a_json(punto), 'total_puntos': total_puntos},
        status=201,
    )
