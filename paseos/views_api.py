"""API REST (JSON) de paseos para la app Android del paseador."""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

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
