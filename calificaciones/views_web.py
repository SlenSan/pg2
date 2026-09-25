"""Vista web (dueño): calificar un paseo ya finalizado (RF13)."""

from bson import ObjectId
from django.contrib import messages
from django.shortcuts import redirect, render
from pymongo.errors import DuplicateKeyError

from calificaciones import repository
from calificaciones.forms import CalificacionForm
from notificaciones import repository as notificaciones_repository
from paseos import repository as paseos_repository
from usuarios import repository as usuarios_repository
from usuarios.decorators import requiere_dueno


@requiere_dueno
def calificar_paseo(request, id_paseo):
    paseo = paseos_repository.obtener_por_id(id_paseo)
    id_dueno = request.session['id_usuario']
    # Este dueño debe ser UNO de los (posiblemente varios) dueños del
    # paseo - ver CLAUDE.md, "Corrección de alcance 2026-09-25".
    es_dueno_del_paseo = paseo and ObjectId(id_dueno) in paseo.get('id_duenos', [])
    if not es_dueno_del_paseo or paseo['estado'] != 'historico':
        messages.error(request, 'Este paseo no se puede calificar.')
        return redirect('paseos:mis_paseos')

    if repository.obtener_por_paseo_y_dueno(id_paseo, id_dueno):
        messages.info(request, 'Ya calificaste este paseo.')
        return redirect('paseos:mis_paseos')

    paseador = usuarios_repository.obtener_por_id(paseo['id_paseador'])
    duracion_min = None
    if paseo.get('hora_inicio') and paseo.get('hora_fin'):
        duracion_min = int((paseo['hora_fin'] - paseo['hora_inicio']).total_seconds() // 60)

    if request.method == 'POST':
        form = CalificacionForm(request.POST)
        if form.is_valid():
            puntuacion = int(form.cleaned_data['puntuacion'])
            try:
                repository.crear(
                    id_paseo=id_paseo,
                    id_dueno=request.session['id_usuario'],
                    id_paseador=paseo['id_paseador'],
                    puntuacion=puntuacion,
                    comentario=form.cleaned_data.get('comentario', ''),
                )
            except DuplicateKeyError:
                messages.info(request, 'Ya calificaste este paseo.')
                return redirect('paseos:mis_paseos')
            promedio = repository.calcular_promedio(paseo['id_paseador'])
            usuarios_repository.actualizar_calificacion_promedio(paseo['id_paseador'], promedio)
            notificaciones_repository.crear(
                id_usuario=paseo['id_paseador'],
                tipo='calificacion',
                mensaje=f'Recibiste una calificación de {puntuacion}/5.',
            )
            # Pantalla de confirmacion en vez de redirect+flash: se renderiza
            # directamente (no hay un segundo POST que evitar) y no hace
            # falta una URL nueva. Un refresh del navegador reenviaria el
            # POST, pero repository.crear() ya lo cubre con el
            # DuplicateKeyError de arriba.
            return render(request, 'calificaciones/calificacion_enviada.html')
    else:
        form = CalificacionForm()

    return render(request, 'calificaciones/calificar.html', {
        'form': form,
        'paseador': paseador,
        'duracion_min': duracion_min,
    })
