"""
Autenticacion por token para los endpoints de la API (app Android del
paseador). Compartido por usuarios/views_api.py y por la API de paseos.
"""

from functools import wraps

from django.http import JsonResponse

from usuarios import repository
from usuarios.auth_token import verificar_token


def usuario_desde_request(request):
    """Devuelve el usuario dueño del token Bearer, o None si falta/es invalido."""
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header.removeprefix('Bearer ').strip()
    id_usuario = verificar_token(token)
    if not id_usuario:
        return None
    return repository.obtener_por_id(id_usuario)


def requiere_paseador(view_func):
    """
    Protege un endpoint de la API: exige token valido de un usuario con rol
    'paseador' y lo deja disponible como request.usuario.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        usuario = usuario_desde_request(request)
        if not usuario:
            return JsonResponse({'error': 'Token inválido o expirado.'}, status=401)
        if usuario['rol'] != 'paseador':
            return JsonResponse({'error': 'Esta acción es solo para paseadores.'}, status=403)
        request.usuario = usuario
        return view_func(request, *args, **kwargs)

    return wrapper
