from datetime import datetime

from django.contrib import messages
from django.shortcuts import redirect, render

from core.media import ErrorArchivoInvalido, ErrorSubidaImagen, eliminar_archivo, eliminar_imagen, subir_certificado, subir_imagen
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


def _subir_certificados_del_form(form):
    """
    Sube certificado_salud/carne_vacunacion si se adjuntaron en el
    formulario (MascotaForm - hallazgos del 9 oct, punto 2: ya no viven
    en una pantalla aparte). Devuelve (certificado_salud, carne_vacunacion,
    hubo_error) - cada uno None si no se subio nada para ese campo. Si
    alguno falla, agrega el error al form y hubo_error queda True; el
    llamador decide que hacer con lo que SI se alcanzo a subir (ver
    atomicidad en registrar_mascota()/editar_mascota()).
    """
    certificado_salud = None
    archivo_salud = form.cleaned_data.get('certificado_salud')
    if archivo_salud:
        try:
            subido = subir_certificado(archivo_salud, carpeta='certificados_mascotas')
        except ErrorArchivoInvalido as exc:
            form.add_error('certificado_salud', str(exc))
        else:
            fecha = form.cleaned_data['fecha_expedicion_salud']
            certificado_salud = {
                'url': subido['url'],
                'public_id': subido['public_id'],
                'formato': subido['formato'],
                'fecha_expedicion': datetime.combine(fecha, datetime.min.time()),
            }

    carne_vacunacion = None
    archivo_vacunacion = form.cleaned_data.get('carne_vacunacion')
    if archivo_vacunacion:
        try:
            subido = subir_certificado(archivo_vacunacion, carpeta='certificados_mascotas')
        except ErrorArchivoInvalido as exc:
            form.add_error('carne_vacunacion', str(exc))
        else:
            carne_vacunacion = {
                'url': subido['url'],
                'public_id': subido['public_id'],
                'formato': subido['formato'],
            }

    return certificado_salud, carne_vacunacion, bool(form.errors)


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

            certificado_salud, carne_vacunacion, _ = _subir_certificados_del_form(form)

            if not form.errors:
                repository.crear_mascota(
                    id_dueno=request.session['id_usuario'],
                    nombre=form.cleaned_data['nombre'],
                    raza=form.cleaned_data['raza'],
                    edad=form.cleaned_data['edad'],
                    peso=form.cleaned_data['peso'],
                    observaciones=form.cleaned_data.get('observaciones', ''),
                    foto=foto_url,
                    certificado_salud=certificado_salud,
                    carne_vacunacion=carne_vacunacion,
                )
                return redirect('mascotas:lista')
            else:
                # Atomicidad (hallazgos del 9 oct, punto 2 - decision
                # explicita: "no se crea nada" en vez de "se crea a
                # medias"): si un archivo YA se subio a Cloudinary pero la
                # mascota no se va a crear porque outro campo fallo, hay
                # que borrar lo que se alcanzo a subir - si no, queda un
                # archivo huerfano sin ningun documento que lo referencie.
                if certificado_salud:
                    eliminar_archivo(certificado_salud['public_id'])
                if carne_vacunacion:
                    eliminar_archivo(carne_vacunacion['public_id'])
    else:
        form = MascotaForm()
    return render(request, 'mascotas/registro.html', {'form': form})


@requiere_dueno
def editar_mascota(request, id_mascota):
    """
    Reusa MascotaForm (mismos campos/validaciones que registrar_mascota,
    incluidos certificado_salud/carne_vacunacion - hallazgos del 9 oct,
    punto 2) - dueño no editable (no es un campo del form, ver
    CLAUDE.md: la mascota no cambia de dueño).
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

            certificado_salud, carne_vacunacion, _ = _subir_certificados_del_form(form)

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
                if certificado_salud:
                    anterior = mascota.get('certificado_salud') or {}
                    if anterior.get('public_id'):
                        eliminar_archivo(anterior['public_id'])
                    repository.actualizar_certificado_salud(id_mascota, **certificado_salud)
                if carne_vacunacion:
                    anterior = mascota.get('carne_vacunacion') or {}
                    if anterior.get('public_id'):
                        eliminar_archivo(anterior['public_id'])
                    repository.actualizar_carne_vacunacion(id_mascota, **carne_vacunacion)
                messages.success(request, f'Se actualizó el perfil de {form.cleaned_data["nombre"]}.')
                return redirect('mascotas:lista')
            else:
                # Misma atomicidad que registrar_mascota(): si algo mas
                # del formulario fallo, no se aplica NINGUN cambio - los
                # archivos que ya se hubieran subido en esta misma
                # peticion se borran, para no dejarlos huerfanos.
                if certificado_salud:
                    eliminar_archivo(certificado_salud['public_id'])
                if carne_vacunacion:
                    eliminar_archivo(carne_vacunacion['public_id'])
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
