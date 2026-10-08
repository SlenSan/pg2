from django.contrib import messages
from django.shortcuts import redirect, render

from core.media import ErrorSubidaImagen, eliminar_imagen, subir_imagen
from mascotas import repository
from mascotas.forms import MascotaForm
from paseos import repository as paseos_repository
from usuarios.decorators import requiere_dueno


@requiere_dueno
def lista_mascotas(request):
    id_dueno = request.session['id_usuario']
    mascotas = repository.listar_por_dueno(id_dueno)

    # mismo calculo que usuarios.views_web.bienvenida, para reutilizar el
    # badge "en paseo"/"en casa" del dashboard tambien aqui.
    paseos_dueno = paseos_repository.listar_por_dueno(id_dueno)
    ids_mascotas_en_paseo = {
        mid for p in paseos_dueno if p['estado'] == 'en_vivo' for mid in p.get('id_mascotas', [])
    }
    items = [
        {'id': str(m['_id']), 'mascota': m, 'en_paseo': m['_id'] in ids_mascotas_en_paseo}
        for m in mascotas
    ]
    return render(request, 'mascotas/lista.html', {'items': items})


@requiere_dueno
def registrar_mascota(request):
    if request.method == 'POST':
        form = MascotaForm(request.POST, request.FILES)
        if form.is_valid():
            foto_url = ''
            imagen = form.cleaned_data.get('foto')
            if imagen:
                try:
                    foto_url = subir_imagen(imagen, carpeta='mascotas')
                except ErrorSubidaImagen as exc:
                    form.add_error('foto', str(exc))

            if not form.errors:
                repository.crear_mascota(
                    id_dueno=request.session['id_usuario'],
                    nombre=form.cleaned_data['nombre'],
                    raza=form.cleaned_data['raza'],
                    edad=form.cleaned_data['edad'],
                    peso=form.cleaned_data['peso'],
                    observaciones=form.cleaned_data.get('observaciones', ''),
                    foto=foto_url,
                )
                return redirect('mascotas:lista')
    else:
        form = MascotaForm()
    return render(request, 'mascotas/registro.html', {'form': form})


@requiere_dueno
def editar_mascota(request, id_mascota):
    """
    Reusa MascotaForm (mismos campos/validaciones que registrar_mascota,
    `foto` ya era opcional ahi tambien) - dueño no editable (no es un
    campo del form, ver CLAUDE.md: la mascota no cambia de dueño).
    """
    mascota = repository.obtener_por_id_y_dueno(id_mascota, request.session['id_usuario'])
    if not mascota:
        messages.error(request, 'No encontramos esa mascota.')
        return redirect('mascotas:lista')

    if request.method == 'POST':
        form = MascotaForm(request.POST, request.FILES)
        if form.is_valid():
            foto_url = None  # None = no se reemplaza (se mantiene la actual)
            imagen = form.cleaned_data.get('foto')
            if imagen:
                try:
                    foto_url = subir_imagen(imagen, carpeta='mascotas')
                except ErrorSubidaImagen as exc:
                    form.add_error('foto', str(exc))

            if not form.errors:
                if foto_url and mascota.get('foto'):
                    eliminar_imagen(mascota['foto'])
                repository.actualizar_mascota(
                    id_mascota,
                    nombre=form.cleaned_data['nombre'],
                    raza=form.cleaned_data['raza'],
                    edad=form.cleaned_data['edad'],
                    peso=form.cleaned_data['peso'],
                    observaciones=form.cleaned_data.get('observaciones', ''),
                    foto=foto_url,
                )
                messages.success(request, f'Se actualizó el perfil de {form.cleaned_data["nombre"]}.')
                return redirect('mascotas:lista')
    else:
        form = MascotaForm(initial={
            'nombre': mascota['nombre'],
            'raza': mascota['raza'],
            'edad': mascota['edad'],
            'peso': mascota['peso'],
            'observaciones': mascota.get('observaciones', ''),
        })

    return render(request, 'mascotas/editar.html', {'form': form, 'mascota': mascota})
