from functools import wraps

from django.shortcuts import redirect


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
            if not request.session.get('id_usuario') or request.session.get('rol') != rol_esperado:
                return redirect('usuarios:login')
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


requiere_dueno = _requiere_rol('dueño')
"""Protege una vista web: exige sesion activa de un usuario con rol 'dueño'."""

requiere_paseador = _requiere_rol('paseador')
"""Protege una vista web: exige sesion activa de un usuario con rol 'paseador'."""
