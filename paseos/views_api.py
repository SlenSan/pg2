"""API REST (JSON) de paseos para la app Android del paseador."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from notificaciones import repository as notificaciones_repository
from paseos import repository
from usuarios.api_auth import requiere_paseador


@csrf_exempt
@require_http_methods(['POST'])
@requiere_paseador
def publicar_disponibilidad(request):
    activo = repository.obtener_activo_de_paseador(request.usuario['_id'])
    if activo:
        return JsonResponse({
            'error': 'Ya tienes un paseo activo (disponible o en curso).',
            'paseo': repository.a_json(activo),
        }, status=409)

    paseo = repository.crear_disponibilidad(id_paseador=request.usuario['_id'])
    return JsonResponse({'paseo': repository.a_json(paseo)}, status=201)


@require_http_methods(['GET'])
@requiere_paseador
def paseo_actual(request):
    """El paseo activo del paseador ('disponible' o 'en_vivo'), si tiene uno."""
    paseo = repository.obtener_activo_de_paseador(request.usuario['_id'])
    return JsonResponse({'paseo': repository.a_json(paseo) if paseo else None})


@csrf_exempt
@require_http_methods(['POST'])
@requiere_paseador
def iniciar_paseo(request, id_paseo):
    paseo = repository.iniciar_paseo(id_paseo=id_paseo, id_paseador=request.usuario['_id'])
    if not paseo:
        return JsonResponse({
            'error': (
                'No se pudo iniciar: el paseo no existe, no es tuyo, ya no está '
                '"disponible" o todavía no tiene una mascota inscrita.'
            ),
        }, status=409)

    notificaciones_repository.crear(
        id_usuario=paseo['id_dueno'],
        tipo='inicio_paseo',
        mensaje=f'{request.usuario["nombre"]} inició el paseo de tu mascota.',
    )
    return JsonResponse({'paseo': repository.a_json(paseo)})


@csrf_exempt
@require_http_methods(['POST'])
@requiere_paseador
def finalizar_paseo(request, id_paseo):
    paseo = repository.finalizar_paseo(id_paseo=id_paseo, id_paseador=request.usuario['_id'])
    if not paseo:
        return JsonResponse({
            'error': 'No se pudo finalizar: el paseo no existe, no es tuyo o no está "en_vivo".',
        }, status=409)

    notificaciones_repository.crear(
        id_usuario=paseo['id_dueno'],
        tipo='fin_paseo',
        mensaje=f'{request.usuario["nombre"]} finalizó el paseo de tu mascota.',
    )
    return JsonResponse({'paseo': repository.a_json(paseo)})
