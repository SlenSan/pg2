"""
Vistas web (Django Templates + Bootstrap) de autenticación.

Compartidas por dueño y paseador: ambos usan la misma plataforma web (ya
no existe una app Android separada para el paseador — ver CLAUDE.md).
registro()/login()/logout() son comunes a los dos roles; el resto de
vistas de este archivo (bienvenida, etc.) siguen siendo del dueño por
ahora. El dashboard propio del paseador es un paso pendiente: hoy, si un
paseador inicia sesión, `usuarios.decorators.requiere_dueno` lo rebota de
vuelta al login en cualquier página protegida (bienvenida incluida),
porque sigue exigiendo rol == "dueño".
"""

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import redirect, render

from usuarios import repository
from usuarios.decorators import requiere_dueno
from usuarios.forms import LoginForm, RegistroDuenoForm, RegistroPaseadorForm

_ROLES_VALIDOS = ('dueno', 'paseador')
_ROL_MONGO = {'dueno': 'dueño', 'paseador': 'paseador'}


def seleccionar_rol(request):
    """
    Pantalla de entrada del sitio ("¿Eres paseador o dueño?"). Si ya hay
    sesion activa, no tiene sentido mostrarla: se salta directo al
    dashboard. Los botones de rol solo afectan el flujo de REGISTRO (que
    formulario mostrarle a alguien nuevo) - el login es el mismo para
    cualquier rol.
    """
    if request.session.get('id_usuario'):
        return redirect('usuarios:bienvenida')
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
                return redirect('usuarios:bienvenida')
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
                return redirect('usuarios:bienvenida')
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


def _iniciar_sesion(request, usuario):
    request.session['id_usuario'] = str(usuario['_id'])
    request.session['nombre'] = usuario['nombre']
    request.session['rol'] = usuario['rol']
