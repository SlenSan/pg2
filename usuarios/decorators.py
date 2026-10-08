from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

# Panel propio de cada rol - usado para redirigir a alguien AUTENTICADO
# pero con el rol equivocado (ver _requiere_rol mas abajo) y por
# usuarios.views_web._url_dashboard() (registro/login), para no tener la
# misma correspondencia rol->URL duplicada en dos archivos.
URL_DASHBOARD_POR_ROL = {
    'dueño': 'usuarios:bienvenida',
    'paseador': 'usuarios:bienvenida_paseador',
}


def _redirigir_a_login(request):
    """
    Incluye ?next= con la URL que se intentaba visitar, para que
    usuarios.views_web.login() pueda volver ahi despues de iniciar
    sesion en vez de siempre al dashboard del rol (ver ajustes antes del
    despliegue, octubre 2026 - este ?next= no existia antes: sin el, la
    regla de login "respeta next" no tenia nada que respetar).
    """
    destino = '{}?{}'.format(reverse('usuarios:login'), urlencode({'next': request.get_full_path()}))
    return redirect(destino)


def requiere_autenticacion(view_func):
    """Protege una vista web: exige sesion activa, de cualquier rol (dueño o paseador)."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.session.get('id_usuario'):
            return _redirigir_a_login(request)
        return view_func(request, *args, **kwargs)

    return wrapper


def _requiere_rol(rol_esperado):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.session.get('id_usuario'):
                return _redirigir_a_login(request)
            rol_sesion = request.session.get('rol')
            if rol_sesion != rol_esperado:
                # Autenticado, pero con el rol equivocado para ESTA vista -
                # ya no se manda a login (ahi no pasaria nada, ya tiene
                # sesion); se manda a su propio panel con un aviso, en vez
                # de dejarlo "atascado" pensando que no esta logueado.
                messages.warning(request, 'No tienes acceso a esa sección.')
                return redirect(URL_DASHBOARD_POR_ROL.get(rol_sesion, 'usuarios:login'))
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


requiere_dueno = _requiere_rol('dueño')
"""Protege una vista web: exige sesion activa de un usuario con rol 'dueño'."""

requiere_paseador = _requiere_rol('paseador')
"""Protege una vista web: exige sesion activa de un usuario con rol 'paseador'."""


def requiere_admin(view_func):
    """
    Protege el panel de administracion (RF14 - verificacion de
    paseadores). NO es un rol nuevo en `usuarios` (ver CLAUDE.md): una
    cuenta YA EXISTENTE (de cualquier rol) es administradora si su
    correo esta en settings.CANIGO_ADMIN_EMAILS.

    Sin sesion, va a login (igual que cualquier otra vista protegida,
    con ?next= para volver aca despues). CON sesion pero sin ser admin,
    404 - no se revela que la ruta existe a nadie que no sea admin (ni
    "no tienes permiso", que ya confirmaria que la URL es real).
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.session.get('id_usuario'):
            return _redirigir_a_login(request)
        correo_sesion = (request.session.get('correo') or '').strip().lower()
        if correo_sesion not in settings.CANIGO_ADMIN_EMAILS:
            raise Http404()
        return view_func(request, *args, **kwargs)

    return wrapper
