"""
API REST para la app Android del paseador: boton de emergencia (RF12) y
consulta de su propio historial de incidentes (RF16).

A diferencia de los demas endpoints del paseador (JSON puro), este envia
multipart/form-data porque incluye una foto de evidencia.
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.media import ErrorSubidaImagen, subir_imagen
from incidentes import repository
from notificaciones import repository as notificaciones_repository
from paseos import repository as paseos_repository
from usuarios.api_auth import requiere_paseador


@csrf_exempt
@require_http_methods(['POST'])
@requiere_paseador
def reportar_incidente(request, id_paseo):
    paseo = paseos_repository.obtener_por_id(id_paseo)
    if not paseo or paseo['id_paseador'] != request.usuario['_id'] or paseo['estado'] != 'en_vivo':
        return JsonResponse({
            'error': 'Este paseo no existe, no es tuyo, o no está "en_vivo".',
        }, status=409)

    tipo = request.POST.get('tipo')
    if tipo not in repository.TIPOS_VALIDOS:
        return JsonResponse({
            'error': f'tipo debe ser uno de: {", ".join(repository.TIPOS_VALIDOS)}.',
        }, status=400)

    descripcion = request.POST.get('descripcion', '').strip()
    if not descripcion:
        return JsonResponse({'error': 'descripcion es requerida.'}, status=400)

    try:
        latitud = float(request.POST['latitud'])
        longitud = float(request.POST['longitud'])
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {'error': 'latitud y longitud son requeridos y deben ser numéricos.'},
            status=400,
        )
    if not (-90 <= latitud <= 90) or not (-180 <= longitud <= 180):
        return JsonResponse({'error': 'latitud/longitud fuera de rango.'}, status=400)

    foto = request.FILES.get('foto')
    if not foto:
        return JsonResponse({'error': 'foto (evidencia) es requerida.'}, status=400)

    try:
        evidencia_url = subir_imagen(foto, carpeta='incidentes')
    except ErrorSubidaImagen as exc:
        return JsonResponse({'error': str(exc)}, status=502)

    incidente = repository.crear(
        id_paseo=paseo['_id'],
        tipo=tipo,
        descripcion=descripcion,
        evidencia_foto=evidencia_url,
        latitud=latitud,
        longitud=longitud,
    )

    paseos_repository.marcar_emergencia(paseo['_id'])

    if paseo.get('id_dueno'):
        notificaciones_repository.crear(
            id_usuario=paseo['id_dueno'],
            tipo='emergencia',
            mensaje=f'{request.usuario["nombre"]} reportó un incidente ({tipo}) durante el paseo.',
        )
        repository.marcar_notificado(incidente['_id'])
        incidente['notificado'] = True

    return JsonResponse({'incidente': repository.a_json(incidente)}, status=201)


@require_http_methods(['GET'])
@requiere_paseador
def mis_incidentes(request):
    paseos = paseos_repository.listar_por_paseador(request.usuario['_id'])
    ids_paseo = [p['_id'] for p in paseos]
    incidentes = repository.listar_por_paseos(ids_paseo)
    return JsonResponse({'incidentes': [repository.a_json(i) for i in incidentes]})
