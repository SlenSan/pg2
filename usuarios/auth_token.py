"""
Token de sesion para la app Android del paseador.

En vez de agregar una coleccion nueva de sesiones/tokens en MongoDB (el
esquema del proyecto define exactamente 7 colecciones), usamos un token
firmado con la SECRET_KEY de Django (django.core.signing): el servidor no
necesita guardar nada, solo verificar la firma y la fecha de emision. La
app guarda este token como `token_sesion` en su cache local
(`cache_perfil_usuario`, ver CLAUDE.md) y lo reenvia en cada request como
`Authorization: Bearer <token>`.
"""

from django.core import signing

_SALT = 'usuarios.paseador.token_sesion'
_MAX_AGE_SEGUNDOS = 60 * 60 * 24 * 30  # 30 dias


def generar_token(id_usuario):
    return signing.dumps({'id_usuario': str(id_usuario)}, salt=_SALT)


def verificar_token(token):
    """Devuelve el id_usuario codificado en el token, o None si es invalido/expiro."""
    try:
        data = signing.loads(token, salt=_SALT, max_age=_MAX_AGE_SEGUNDOS)
    except signing.BadSignature:
        return None
    return data.get('id_usuario')
