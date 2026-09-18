from datetime import datetime, timezone

from django.shortcuts import render

from notificaciones import repository
from usuarios.decorators import requiere_autenticacion


@requiere_autenticacion
def lista_notificaciones(request):
    notificaciones = repository.listar_por_usuario(request.session['id_usuario'])
    # Marca "vistas hasta ahora" en la sesion: el esquema de `notificaciones`
    # no tiene un campo `leido` (ver decision del Paso previo), asi que el
    # punto naranja del dashboard se calcula comparando la fecha de la
    # notificacion mas reciente contra esta marca de tiempo.
    request.session['notificaciones_vistas_hasta'] = (
        datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    )
    return render(request, 'notificaciones/lista.html', {'notificaciones': notificaciones})
