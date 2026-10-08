from datetime import datetime

from django.contrib import messages
from django.shortcuts import redirect, render

from core.media import ErrorArchivoInvalido, ErrorSubidaImagen, eliminar_archivo, eliminar_imagen, subir_certificado, subir_imagen
from mascotas import repository
from mascotas.forms import CertificadosMascotaForm, MascotaForm
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
        {
            'id': str(m['_id']),
            'mascota': m,
            'en_paseo': m['_id'] in ids_mascotas_en_paseo,
            'estado_salud': repository.estado_certificado_salud(m.get('certificado_salud')),
            'tiene_carne': bool(m.get('carne_vacunacion')),
        }
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

    return render(request, 'mascotas/editar.html', {
        'form': form,
        'mascota': mascota,
        'id_mascota': id_mascota,
        'estado_salud': repository.estado_certificado_salud(mascota.get('certificado_salud')),
        'tiene_carne': bool(mascota.get('carne_vacunacion')),
    })


@requiere_dueno
def certificados_mascota(request, id_mascota):
    """
    Certificado de salud y carné de vacunación de una mascota (Ley 2480
    de 2025, Ley Kiara) - formulario independiente del de editar_mascota
    (distinta naturaleza: archivos regulados con sus propias reglas de
    formato/tamaño/vigencia, no datos de perfil). Cada archivo es
    independiente: si uno falla, no se guarda ninguno de los dos en esta
    misma subida (evita un estado a medias "se subio uno pero no el
    otro" sin que el formulario lo refleje).
    """
    mascota = repository.obtener_por_id_y_dueno(id_mascota, request.session['id_usuario'])
    if not mascota:
        messages.error(request, 'No encontramos esa mascota.')
        return redirect('mascotas:lista')

    if request.method == 'POST':
        form = CertificadosMascotaForm(request.POST, request.FILES)
        if form.is_valid():
            archivo_salud = form.cleaned_data.get('certificado_salud')
            archivo_vacunacion = form.cleaned_data.get('carne_vacunacion')

            subido_salud = None
            if archivo_salud:
                try:
                    subido_salud = subir_certificado(archivo_salud, carpeta='certificados_mascotas')
                except ErrorArchivoInvalido as exc:
                    form.add_error('certificado_salud', str(exc))

            subido_vacunacion = None
            if archivo_vacunacion and not form.errors:
                try:
                    subido_vacunacion = subir_certificado(archivo_vacunacion, carpeta='certificados_mascotas')
                except ErrorArchivoInvalido as exc:
                    form.add_error('carne_vacunacion', str(exc))

            if not form.errors:
                if subido_salud:
                    certificado_salud_anterior = mascota.get('certificado_salud') or {}
                    if certificado_salud_anterior.get('public_id'):
                        eliminar_archivo(certificado_salud_anterior['public_id'])
                    fecha = form.cleaned_data['fecha_expedicion_salud']
                    repository.actualizar_certificado_salud(
                        id_mascota,
                        url=subido_salud['url'],
                        public_id=subido_salud['public_id'],
                        formato=subido_salud['formato'],
                        fecha_expedicion=datetime.combine(fecha, datetime.min.time()),
                    )
                if subido_vacunacion:
                    carne_anterior = mascota.get('carne_vacunacion') or {}
                    if carne_anterior.get('public_id'):
                        eliminar_archivo(carne_anterior['public_id'])
                    repository.actualizar_carne_vacunacion(
                        id_mascota,
                        url=subido_vacunacion['url'],
                        public_id=subido_vacunacion['public_id'],
                        formato=subido_vacunacion['formato'],
                    )
                messages.success(request, 'Certificados actualizados.')
                return redirect('mascotas:editar', id_mascota=id_mascota)
    else:
        form = CertificadosMascotaForm()

    return render(request, 'mascotas/certificados.html', {
        'form': form,
        'mascota': mascota,
        'id_mascota': id_mascota,
        'estado_salud': repository.estado_certificado_salud(mascota.get('certificado_salud')),
    })
