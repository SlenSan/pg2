from django.shortcuts import redirect, render

from mascotas import repository
from mascotas.forms import MascotaForm
from usuarios.decorators import requiere_dueno


@requiere_dueno
def lista_mascotas(request):
    mascotas = repository.listar_por_dueno(request.session['id_usuario'])
    return render(request, 'mascotas/lista.html', {'mascotas': mascotas})


@requiere_dueno
def registrar_mascota(request):
    if request.method == 'POST':
        form = MascotaForm(request.POST)
        if form.is_valid():
            repository.crear_mascota(
                id_dueno=request.session['id_usuario'],
                nombre=form.cleaned_data['nombre'],
                raza=form.cleaned_data['raza'],
                edad=form.cleaned_data['edad'],
                peso=form.cleaned_data['peso'],
                observaciones=form.cleaned_data.get('observaciones', ''),
            )
            return redirect('mascotas:lista')
    else:
        form = MascotaForm()
    return render(request, 'mascotas/registro.html', {'form': form})
