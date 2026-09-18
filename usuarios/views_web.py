"""
Vistas web (Django Templates + Bootstrap) de autenticación y dashboards.

Compartidas por dueño y paseador: ambos usan la misma plataforma web (ya
no existe una app Android separada para el paseador — ver CLAUDE.md).
registro()/login()/logout() son comunes a los dos roles; cada uno tiene
su propio dashboard (bienvenida / bienvenida_paseador) protegido por su
decorator correspondiente (ver usuarios/decorators.py).
"""

from bson import ObjectId
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import redirect, render

from core.media import ErrorSubidaImagen, subir_imagen
from incidentes.forms import ReportarIncidenteForm
from mascotas import repository as mascotas_repository
from paseos import repository as paseos_repository
from usuarios import repository
from usuarios.decorators import requiere_dueno, requiere_paseador
from usuarios.forms import EditarPerfilPaseadorForm, LoginForm, RegistroDuenoForm, RegistroPaseadorForm

_ROLES_VALIDOS = ('dueno', 'paseador')
_ROL_MONGO = {'dueno': 'dueño', 'paseador': 'paseador'}


def _url_dashboard(rol):
    return 'usuarios:bienvenida_paseador' if rol == 'paseador' else 'usuarios:bienvenida'


def seleccionar_rol(request):
    """
    Pantalla de entrada del sitio ("¿Eres paseador o dueño?"). Si ya hay
    sesion activa, no tiene sentido mostrarla: se salta directo al
    dashboard que corresponda. Los botones de rol solo afectan el flujo
    de REGISTRO (que formulario mostrarle a alguien nuevo) - el login es
    el mismo para cualquier rol.
    """
    if request.session.get('id_usuario'):
        return redirect(_url_dashboard(request.session.get('rol')))
    return render(request, 'usuarios/seleccionar_rol.html')


def registro(request):
    rol = request.POST.get('rol') or request.GET.get('rol')
    rol = rol if rol in _ROLES_VALIDOS else 'dueno'
    rol_mongo = _ROL_MONGO[rol]
    FormClass = RegistroPaseadorForm if rol == 'paseador' else RegistroDuenoForm

    if request.method == 'POST':
        form = FormClass(request.POST)
        if form.is_valid():
            correo = form.cleaned_data['correo']
            if repository.obtener_por_correo(correo):
                form.add_error('correo', 'Ya existe una cuenta registrada con este correo.')
            else:
                usuario = repository.crear_usuario(
                    nombre=form.cleaned_data['nombre'],
                    correo=correo,
                    contrasena_hash=make_password(form.cleaned_data['contrasena']),
                    telefono=form.cleaned_data['telefono'],
                    rol=rol_mongo,
                    direccion=form.cleaned_data.get('direccion', ''),
                    descripcion=form.cleaned_data.get('descripcion', ''),
                )
                _iniciar_sesion(request, usuario)
                messages.success(request, f'¡Bienvenido, {usuario["nombre"]}! Tu cuenta fue creada.')
                return redirect(_url_dashboard(rol_mongo))
    else:
        form = FormClass()

    return render(request, 'usuarios/registro.html', {
        'form': form,
        'modo': 'registro',
        'rol': rol,
    })


def login(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            usuario = repository.obtener_por_correo(form.cleaned_data['correo'])
            contrasena = form.cleaned_data['contrasena']
            if not usuario or not check_password(contrasena, usuario['contrasena']):
                form.add_error(None, 'Correo o contraseña incorrectos.')
            else:
                _iniciar_sesion(request, usuario)
                return redirect(_url_dashboard(usuario['rol']))
    else:
        form = LoginForm()
    return render(request, 'usuarios/login.html', {'form': form, 'modo': 'login'})


def logout(request):
    request.session.flush()
    return redirect('usuarios:login')


@requiere_dueno
def bienvenida(request):
    return render(request, 'usuarios/bienvenida.html', {
        'nombre': request.session.get('nombre'),
    })


@requiere_paseador
def bienvenida_paseador(request):
    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = paseos_repository.obtener_activo_de_paseador(id_paseador)

    paseo_activo = None
    if paseo:
        mascota = None
        dueno = None
        if paseo.get('id_mascota'):
            mascota = mascotas_repository.obtener_varias_por_id([paseo['id_mascota']]).get(paseo['id_mascota'])
        if paseo.get('id_dueno'):
            dueno = repository.obtener_por_id(paseo['id_dueno'])
        fotos_existentes = {f['momento'] for f in paseo.get('fotos', [])}
        paseo_activo = {
            'id_paseo': str(paseo['_id']),
            'estado': paseo['estado'],
            'mascota_nombre': mascota['nombre'] if mascota else None,
            'dueno_nombre': dueno['nombre'] if dueno else None,
            'fotos_pendientes': [
                m for m in paseos_repository.MOMENTOS_FOTO_VALIDOS if m not in fotos_existentes
            ],
        }

    incidente_form = None
    if paseo_activo and paseo_activo['estado'] == 'en_vivo':
        incidente_form = ReportarIncidenteForm()

    return render(request, 'usuarios/bienvenida_paseador.html', {
        'nombre': request.session.get('nombre'),
        'paseo_activo': paseo_activo,
        'incidente_form': incidente_form,
    })


@requiere_paseador
def perfil_paseador(request):
    usuario = repository.obtener_por_id(request.session['id_usuario'])
    tenia_descripcion = bool(usuario.get('descripcion'))

    if request.method == 'POST':
        form = EditarPerfilPaseadorForm(
            request.POST, request.FILES, tenia_descripcion=tenia_descripcion
        )
        if form.is_valid():
            foto_perfil_url = usuario.get('foto_perfil', '')
            foto = form.cleaned_data.get('foto_perfil')
            if foto:
                try:
                    foto_perfil_url = subir_imagen(foto, carpeta='usuarios')
                except ErrorSubidaImagen as exc:
                    form.add_error('foto_perfil', str(exc))

            if not form.errors:
                repository.actualizar_perfil_paseador(
                    id_usuario=request.session['id_usuario'],
                    telefono=form.cleaned_data['telefono'],
                    descripcion=form.cleaned_data['descripcion'],
                    foto_perfil=foto_perfil_url,
                )
                messages.success(request, 'Tu perfil se actualizó correctamente.')
                return redirect('usuarios:perfil_paseador')
    else:
        form = EditarPerfilPaseadorForm(
            initial={
                'telefono': usuario.get('telefono', ''),
                'descripcion': usuario.get('descripcion', ''),
            },
            tenia_descripcion=tenia_descripcion,
        )

    return render(request, 'usuarios/perfil_paseador.html', {'usuario': usuario, 'form': form})


def _iniciar_sesion(request, usuario):
    request.session['id_usuario'] = str(usuario['_id'])
    request.session['nombre'] = usuario['nombre']
    request.session['rol'] = usuario['rol']
