"""
API REST (JSON) para la app Android del paseador.

El dueño de mascota NO usa estos endpoints: solo tiene la plataforma web
(ver views_web.py). Por eso aquí se fuerza rol == "paseador" tanto al
registrar como al iniciar sesión.
"""

import json

from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from usuarios import repository
from usuarios.api_auth import requiere_paseador
from usuarios.auth_token import generar_token

_CAMPOS_REQUERIDOS_REGISTRO = ('nombre', 'correo', 'contrasena', 'telefono')


def _leer_json(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None


@csrf_exempt
@require_http_methods(['POST'])
def registro_paseador(request):
    data = _leer_json(request)
    if data is None:
        return JsonResponse({'error': 'JSON inválido.'}, status=400)

    faltantes = [campo for campo in _CAMPOS_REQUERIDOS_REGISTRO if not data.get(campo)]
    if faltantes:
        return JsonResponse(
            {'error': f'Campos requeridos faltantes: {", ".join(faltantes)}.'},
            status=400,
        )

    if repository.obtener_por_correo(data['correo']):
        return JsonResponse({'error': 'Ya existe un usuario con ese correo.'}, status=409)

    usuario = repository.crear_usuario(
        nombre=data['nombre'],
        correo=data['correo'],
        contrasena_hash=make_password(data['contrasena']),
        telefono=data['telefono'],
        rol='paseador',
        direccion=data.get('direccion', ''),
        descripcion=data.get('descripcion', ''),
    )
    token = generar_token(usuario['_id'])
    return JsonResponse({'usuario': repository.a_json(usuario), 'token': token}, status=201)


@csrf_exempt
@require_http_methods(['POST'])
def login_paseador(request):
    data = _leer_json(request)
    if data is None:
        return JsonResponse({'error': 'JSON inválido.'}, status=400)

    correo = data.get('correo')
    contrasena = data.get('contrasena')
    if not correo or not contrasena:
        return JsonResponse({'error': 'correo y contrasena son requeridos.'}, status=400)

    usuario = repository.obtener_por_correo(correo)
    if not usuario or not check_password(contrasena, usuario['contrasena']):
        return JsonResponse({'error': 'Credenciales inválidas.'}, status=401)

    if usuario['rol'] != 'paseador':
        return JsonResponse(
            {'error': 'Esta cuenta no es de paseador. Usa la plataforma web de Canigo.'},
            status=403,
        )

    token = generar_token(usuario['_id'])
    return JsonResponse({'usuario': repository.a_json(usuario), 'token': token})


@require_http_methods(['GET'])
@requiere_paseador
def perfil_paseador(request):
    return JsonResponse({'usuario': repository.a_json(request.usuario)})
