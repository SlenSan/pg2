"""
Vistas web (Django Templates + Bootstrap) para el dueño de mascota.

El paseador NO usa estas vistas: solo tiene la app Android (ver
views_api.py). Por eso aquí se valida explícitamente rol == "dueño".
"""

from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import redirect, render

from usuarios import repository
from usuarios.decorators import requiere_dueno
from usuarios.forms import LoginForm, RegistroDuenoForm


def seleccionar_rol(request):
    """
    Pantalla de entrada del sitio ("¿Eres paseador o dueño?"). Si ya hay
    sesion activa, no tiene sentido mostrarla: se salta directo al
    dashboard. Los botones de rol todavia no distinguen el flujo de
    autenticacion (eso llega en un paso posterior) - por ahora solo
    marcan la eleccion en la URL de login via ?rol=.
    """
    if request.session.get('id_usuario'):
        return redirect('usuarios:bienvenida')
    return render(request, 'usuarios/seleccionar_rol.html')


def registro_dueno(request):
    if request.method == 'POST':
        form = RegistroDuenoForm(request.POST)
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
                    rol='dueño',
                    direccion=form.cleaned_data.get('direccion', ''),
                )
                _iniciar_sesion(request, usuario)
                messages.success(request, f'¡Bienvenido, {usuario["nombre"]}! Tu cuenta fue creada.')
                return redirect('usuarios:bienvenida')
    else:
        form = RegistroDuenoForm()
    return render(request, 'usuarios/registro.html', {'form': form, 'modo': 'registro'})


def login_dueno(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            usuario = repository.obtener_por_correo(form.cleaned_data['correo'])
            contrasena = form.cleaned_data['contrasena']
            if not usuario or not check_password(contrasena, usuario['contrasena']):
                form.add_error(None, 'Correo o contraseña incorrectos.')
            elif usuario['rol'] != 'dueño':
                form.add_error(None, 'Esta cuenta es de paseador. Usa la app de Canigo para paseadores.')
            else:
                _iniciar_sesion(request, usuario)
                return redirect('usuarios:bienvenida')
    else:
        form = LoginForm()
    return render(request, 'usuarios/login.html', {'form': form, 'modo': 'login'})


def logout_dueno(request):
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
