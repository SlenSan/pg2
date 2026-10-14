"""
Vistas web del panel de administracion (RF14 - verificacion de
paseadores). Esta app no tiene colecciones propias en Mongo: todo el
acceso pasa por usuarios.repository (que administra `usuarios`,
incluidos los campos `verificado`/`verificacion`/`verificacion_historial`)
y notificaciones.repository (para avisar al paseador) - por eso no hay
un `administracion/repository.py`.
"""

import secrets
import string

from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from administracion.forms import AsignarContrasenaTemporalForm, ObservacionForm
from notificaciones import repository as notificaciones_repository
from usuarios import repository as usuarios_repository
from usuarios.decorators import requiere_admin
from usuarios.forms import TIPO_PRIMEROS_AUXILIOS

# Mejora 2 - sin 0/O/1/l/I (se confunden fácil al leerlos de un correo o
# dictarlos por teléfono). 12 caracteres de este alfabeto: suficiente
# entropía para una contraseña de un solo uso que se cambia en el
# siguiente login (ver ExigirCambioContrasenaMiddleware).
_ALFABETO_CONTRASENA_TEMPORAL = (string.ascii_letters + string.digits).translate(
    str.maketrans('', '', '0O1lI')
)


def _generar_contrasena_temporal():
    return ''.join(secrets.choice(_ALFABETO_CONTRASENA_TEMPORAL) for _ in range(12))

# "Pendientes" por defecto (no "Todos") - es el filtro mas util para un
# admin que entra a revisar: paseadores que todavia no tienen una
# decision tomada.
_FILTROS_VALIDOS = {'pendientes': False, 'verificados': True, 'todos': None}


def _tiene_primeros_auxilios(paseador):
    return any(c['tipo'] == TIPO_PRIMEROS_AUXILIOS for c in paseador.get('certificados', []))


@requiere_admin
def verificacion(request):
    filtro = request.GET.get('filtro', 'pendientes')
    if filtro not in _FILTROS_VALIDOS:
        filtro = 'pendientes'

    paseadores = usuarios_repository.listar_paseadores(verificado=_FILTROS_VALIDOS[filtro])
    items = [
        {
            'id': str(p['_id']),
            'paseador': p,
            'certificados': p.get('certificados', []),
            'tiene_primeros_auxilios': _tiene_primeros_auxilios(p),
        }
        for p in paseadores
    ]

    return render(request, 'administracion/verificacion.html', {
        'items': items,
        'filtro': filtro,
        'form_observacion': ObservacionForm(),
    })


@require_POST
@requiere_admin
def marcar_verificado(request, id_paseador):
    paseador = usuarios_repository.obtener_por_id(id_paseador)
    if not paseador or paseador.get('rol') != 'paseador':
        messages.error(request, 'Ese paseador no existe.')
        return redirect('administracion:verificacion')

    form = ObservacionForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'La observación no es válida (máximo 300 caracteres).')
        return redirect('administracion:verificacion')

    # Regla de negocio (no se valida en el repository, que solo escribe):
    # no se puede verificar sin al menos un certificado de primeros
    # auxilios. El boton ya aparece deshabilitado en el frontend si no lo
    # tiene (ver verificacion.html) - esto es la capa obligatoria, un
    # POST directo sin ese certificado tambien se rechaza aca.
    if not _tiene_primeros_auxilios(paseador):
        messages.error(
            request,
            f'No se puede verificar a {paseador["nombre"]}: no tiene un certificado de '
            '"Primeros auxilios para perros" cargado.',
        )
        return redirect('administracion:verificacion')

    usuarios_repository.marcar_verificado(
        id_paseador,
        revisado_por=request.session['correo'],
        observacion=form.cleaned_data['observacion'],
    )
    notificaciones_repository.crear(
        id_usuario=id_paseador,
        tipo='verificacion',
        mensaje='¡Tu perfil fue verificado por Canigo!',
    )
    messages.success(request, f'{paseador["nombre"]} fue marcado como verificado.')
    return redirect('administracion:verificacion')


@require_POST
@requiere_admin
def retirar_verificado(request, id_paseador):
    paseador = usuarios_repository.obtener_por_id(id_paseador)
    if not paseador or paseador.get('rol') != 'paseador':
        messages.error(request, 'Ese paseador no existe.')
        return redirect('administracion:verificacion')

    form = ObservacionForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'La observación no es válida (máximo 300 caracteres).')
        return redirect('administracion:verificacion')

    usuarios_repository.retirar_verificado(
        id_paseador,
        revisado_por=request.session['correo'],
        observacion=form.cleaned_data['observacion'],
    )
    notificaciones_repository.crear(
        id_usuario=id_paseador,
        tipo='verificacion',
        mensaje='Tu verificación en Canigo fue retirada.',
    )
    messages.success(request, f'Se retiró la verificación de {paseador["nombre"]}.')
    return redirect('administracion:verificacion')


@requiere_admin
def asignar_contrasena_temporal(request):
    """
    Mejora 2 (hallazgos de la prueba con un usuario final, 14 de
    octubre) - versión provisional de "¿Olvidaste tu contraseña?": un
    admin busca la cuenta por correo y le asigna una contraseña
    temporal generada por el servidor (nunca elegida a mano, para que
    no sea algo débil como "123456"). Se muestra en pantalla UNA SOLA
    VEZ, vía `messages.success` (no se guarda en ningún lado en texto
    plano, ni se imprime/registra en ningún log) - el admin la copia de
    ahí y se la comparte al usuario por su cuenta.

    `usuarios_repository.obtener_por_correo()` ya hace el lookup
    case-insensitive (ver su propio docstring) - no hace falta
    normalizar el correo acá antes de buscar.
    """
    if request.method == 'POST':
        form = AsignarContrasenaTemporalForm(request.POST)
        if form.is_valid():
            usuario = usuarios_repository.obtener_por_correo(form.cleaned_data['correo'])
            if not usuario:
                messages.error(request, 'No existe ninguna cuenta con ese correo.')
            else:
                contrasena_temporal = _generar_contrasena_temporal()
                usuarios_repository.asignar_contrasena_temporal(
                    usuario['_id'],
                    nuevo_hash=make_password(contrasena_temporal),
                    asignado_por=request.session['correo'],
                )
                messages.success(
                    request,
                    f'Contraseña temporal para {usuario["nombre"]} ({usuario["correo"]}): '
                    f'{contrasena_temporal} — cópiala ahora, no se va a volver a mostrar. '
                    'Se le pedirá cambiarla en su próximo inicio de sesión.',
                )
                form = AsignarContrasenaTemporalForm()
    else:
        form = AsignarContrasenaTemporalForm()

    return render(request, 'administracion/contrasenas.html', {'form': form})
