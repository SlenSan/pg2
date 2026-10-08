from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

# Panel propio de cada rol - usado para redirigir a alguien AUTENTICADO
# pero con el rol equivocado (ver _requiere_rol mas abajo) y por
# usuarios.views_web._url_dashboard() (registro/login), para no tener la
# misma correspondencia rol->URL duplicada en dos archivos.
URL_DASHBOARD_POR_ROL = {
    'dueño': 'usuarios:bienvenida',
    'paseador': 'usuarios:bienvenida_paseador',
}


def requiere_autenticacion(view_func):
    """Protege una vista web: exige sesion activa, de cualquier rol (dueño o paseador)."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.session.get('id_usuario'):
            return redirect('usuarios:login')
        return view_func(request, *args, **kwargs)

    return wrapper


def _requiere_rol(rol_esperado):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.session.get('id_usuario'):
                return redirect('usuarios:login')
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
