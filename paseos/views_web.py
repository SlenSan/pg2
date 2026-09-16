"""
Vistas web del modulo de paseos.

Dueño: listar paseadores disponibles, ver su perfil, inscribir una
mascota, y ver el estado de "mis paseos".
Paseador: publicar disponibilidad y ver su historial de paseos.
"""

from bson import ObjectId
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from calificaciones import repository as calificaciones_repository
from mascotas import repository as mascotas_repository
from paseos import repository
from paseos.forms import InscribirMascotaForm
from usuarios import repository as usuarios_repository
from usuarios.decorators import requiere_dueno, requiere_paseador


@requiere_dueno
def lista_disponibles(request):
    paseos = repository.listar_disponibles_sin_asignar()
    paseadores_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_paseador'] for p in paseos]
    )
    items = [
        {'id_paseo': str(p['_id']), 'paseador': paseadores_por_id.get(p['id_paseador'])}
        for p in paseos
    ]
    return render(request, 'paseos/lista_disponibles.html', {'items': items})


@requiere_dueno
def detalle_paseador(request, id_paseo):
    paseo = repository.obtener_por_id(id_paseo)
    if not paseo or paseo['estado'] != 'disponible' or paseo.get('id_mascota'):
        messages.error(request, 'Este paseador ya no está disponible.')
        return redirect('paseos:lista_disponibles')

    paseador = usuarios_repository.obtener_por_id(paseo['id_paseador'])
    mis_mascotas = mascotas_repository.listar_por_dueno(request.session['id_usuario'])

    if request.method == 'POST':
        form = InscribirMascotaForm(request.POST, mascotas=mis_mascotas)
        if form.is_valid():
            id_mascota = form.cleaned_data['id_mascota']
            mascota = mascotas_repository.obtener_por_id_y_dueno(
                id_mascota, request.session['id_usuario']
            )
            if not mascota:
                form.add_error('id_mascota', 'Mascota inválida.')
            else:
                asignado = repository.inscribir_mascota(
                    id_paseo=id_paseo,
                    id_dueno=request.session['id_usuario'],
                    id_mascota=id_mascota,
                )
                if asignado:
                    messages.success(
                        request,
                        f'Inscribiste a {mascota["nombre"]} con {paseador["nombre"]}.',
                    )
                    return redirect('paseos:mis_paseos')
                form.add_error(None, 'Este paseador ya no está disponible.')
    else:
        form = InscribirMascotaForm(mascotas=mis_mascotas)

    return render(request, 'paseos/detalle_paseador.html', {
        'paseo': paseo,
        'paseador': paseador,
        'form': form,
    })


@requiere_dueno
def mis_paseos(request):
    paseos = repository.listar_por_dueno(request.session['id_usuario'])
    paseadores_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_paseador'] for p in paseos]
    )
    mascotas_por_id = mascotas_repository.obtener_varias_por_id(
        [p['id_mascota'] for p in paseos if p.get('id_mascota')]
    )
    ids_calificados = {
        c['id_paseo'] for c in calificaciones_repository.listar_por_paseos([p['_id'] for p in paseos])
    }
    items = [
        {
            'id_paseo': str(p['_id']),
            'paseo': p,
            'paseador': paseadores_por_id.get(p['id_paseador']),
            'mascota': mascotas_por_id.get(p['id_mascota']),
            'calificado': p['_id'] in ids_calificados,
        }
        for p in paseos
    ]
    return render(request, 'paseos/mis_paseos.html', {'items': items})


@require_POST
@requiere_paseador
def publicar_disponibilidad(request):
    """
    Boton "Publicar disponibilidad" del dashboard del paseador. Reutiliza
    la misma logica de negocio que ya usaba la API (paseos.repository):
    no publica una segunda vez si ya tiene un paseo activo.
    """
    id_paseador = ObjectId(request.session['id_usuario'])
    if not repository.obtener_activo_de_paseador(id_paseador):
        repository.crear_disponibilidad(id_paseador=id_paseador)
    return redirect('usuarios:bienvenida_paseador')


@requiere_paseador
def historial_paseador(request):
    id_paseador = ObjectId(request.session['id_usuario'])
    paseos = repository.listar_por_paseador(id_paseador)
    duenos_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_dueno'] for p in paseos if p.get('id_dueno')]
    )
    mascotas_por_id = mascotas_repository.obtener_varias_por_id(
        [p['id_mascota'] for p in paseos if p.get('id_mascota')]
    )
    items = [
        {
            'paseo': p,
            'dueno': duenos_por_id.get(p.get('id_dueno')),
            'mascota': mascotas_por_id.get(p.get('id_mascota')),
        }
        for p in paseos
    ]
    return render(request, 'paseos/historial_paseador.html', {'items': items})
