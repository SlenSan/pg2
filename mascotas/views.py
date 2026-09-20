from django.shortcuts import redirect, render

from core.media import ErrorSubidaImagen, subir_imagen
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
        p['id_mascota'] for p in paseos_dueno if p['estado'] == 'en_vivo' and p.get('id_mascota')
    }
    items = [
        {'mascota': m, 'en_paseo': m['_id'] in ids_mascotas_en_paseo}
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
