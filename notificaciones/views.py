from django.shortcuts import render

from notificaciones import repository
from usuarios.decorators import requiere_autenticacion


@requiere_autenticacion
def lista_notificaciones(request):
    notificaciones = repository.listar_por_usuario(request.session['id_usuario'])
    return render(request, 'notificaciones/lista.html', {'notificaciones': notificaciones})
