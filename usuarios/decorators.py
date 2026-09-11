from functools import wraps

from django.shortcuts import redirect


def requiere_dueno(view_func):
    """Protege una vista web: exige sesion activa de un usuario con rol 'dueño'."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.session.get('id_usuario') or request.session.get('rol') != 'dueño':
            return redirect('usuarios:login')
        return view_func(request, *args, **kwargs)

    return wrapper
