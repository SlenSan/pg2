"""
Vistas web (Django Templates + Bootstrap) de autenticación y dashboards.

Compartidas por dueño y paseador: ambos usan la misma plataforma web (ya
no existe una app Android separada para el paseador — ver CLAUDE.md).
registro()/login()/logout() son comunes a los dos roles; cada uno tiene
su propio dashboard (bienvenida / bienvenida_paseador) protegido por su
decorator correspondiente (ver usuarios/decorators.py).
"""

from datetime import datetime, timezone

from bson import ObjectId
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.shortcuts import redirect, render

from calificaciones import repository as calificaciones_repository
from core.media import ErrorSubidaImagen, subir_imagen
from incidentes.forms import ReportarIncidenteForm
from mascotas import repository as mascotas_repository
from notificaciones import repository as notificaciones_repository
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
    """
    BUG corregido: antes, si no llegaba un `rol` valido (por ejemplo,
    entrando por /cuentas/registro/ sin pasar por la pantalla de
    seleccion), se asumia 'dueno' en silencio - sin ningun indicio visual
    de que el formulario habia cambiado de tipo. La cuenta quedaba creada
    de verdad como rol="dueño" en Mongo, asi que el redirect posterior
    (aca y en login) era tecnicamente correcto para esa cuenta - el
    problema era que el rol nunca se habia elegido explicitamente. Ahora,
    sin un rol valido, se manda a la pantalla de seleccion en vez de
    adivinar.
    """
    rol = request.POST.get('rol') or request.GET.get('rol')
    if rol not in _ROLES_VALIDOS:
        return redirect('home')
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


def _paseo_activo_dueno(id_dueno, paseos_dueno=None):
    """
    Paseo en_vivo actual del dueño, con los datos que necesita el banner
    naranja del dashboard. None si no tiene ninguno en curso ahora mismo.
    Compartida por bienvenida() (carga completa de la pagina) y
    estado_bienvenida() (polling) para que ambas calculen exactamente lo
    mismo. Si el llamador ya tiene `paseos_dueno` cargado (bienvenida lo
    necesita ademas para otras secciones), se reutiliza en vez de volver
    a consultar Mongo.
    """
    if paseos_dueno is None:
        paseos_dueno = paseos_repository.listar_por_dueno(id_dueno)

    paseo_en_vivo = next((p for p in paseos_dueno if p['estado'] == 'en_vivo'), None)
    if not paseo_en_vivo:
        return None

    mascota = None
    if paseo_en_vivo.get('id_mascota'):
        mascota = mascotas_repository.obtener_varias_por_id([paseo_en_vivo['id_mascota']]).get(
            paseo_en_vivo['id_mascota']
        )
    paseador = None
    if paseo_en_vivo.get('id_paseador'):
        paseador = repository.obtener_por_id(paseo_en_vivo['id_paseador'])

    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    hora_inicio = paseo_en_vivo.get('hora_inicio')
    minutos = int((ahora - hora_inicio).total_seconds() // 60) if hora_inicio else 0
    return {
        'id_paseo': str(paseo_en_vivo['_id']),
        'mascota_nombre': mascota['nombre'] if mascota else 'tu mascota',
        'paseador_nombre': paseador['nombre'] if paseador else '',
        'minutos': max(minutos, 0),
    }


@requiere_dueno
def bienvenida(request):
    id_dueno = request.session['id_usuario']
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)

    paseos_dueno = paseos_repository.listar_por_dueno(id_dueno)
    mascotas_dueno = mascotas_repository.listar_por_dueno(id_dueno)

    paseo_activo = _paseo_activo_dueno(id_dueno, paseos_dueno=paseos_dueno)

    # --- "Mis mascotas" (maximo 3 tarjetas) ---
    ids_mascotas_en_paseo = {
        p['id_mascota'] for p in paseos_dueno if p['estado'] == 'en_vivo' and p.get('id_mascota')
    }
    ultimo_paseo_por_mascota = {}
    for p in paseos_dueno:  # ya viene ordenado por fecha desc
        if p['estado'] == 'historico' and p.get('id_mascota') and p['id_mascota'] not in ultimo_paseo_por_mascota:
            ultimo_paseo_por_mascota[p['id_mascota']] = p

    mascotas_tarjetas = [
        {
            'mascota': m,
            'en_paseo': m['_id'] in ids_mascotas_en_paseo,
            'fecha_ultimo_paseo': (ultimo_paseo_por_mascota.get(m['_id']) or {}).get('hora_fin'),
        }
        for m in mascotas_dueno[:3]
    ]

    # --- accion rapida "Calificar paseo": el historico mas reciente sin calificar ---
    ids_historico = [p['_id'] for p in paseos_dueno if p['estado'] == 'historico']
    ids_calificados = {
        c['id_paseo'] for c in calificaciones_repository.listar_por_paseos(ids_historico)
    }
    id_paseo_sin_calificar = next((pid for pid in ids_historico if pid not in ids_calificados), None)

    # --- estadisticas (calculo simple, sobre los paseos ya cargados) ---
    paseos_este_mes = sum(
        1 for p in paseos_dueno
        if p['estado'] == 'historico' and p.get('hora_fin')
        and p['hora_fin'].year == ahora.year and p['hora_fin'].month == ahora.month
    )
    calificacion_promedio_dada = calificaciones_repository.calcular_promedio_dado_por_dueno(id_dueno)
    paseadores_distintos = len({p['id_paseador'] for p in paseos_dueno if p.get('id_paseador')})

    # --- notificaciones sin leer: aproximado por sesion (ver notificaciones/repository.py) ---
    ultima_vista_str = request.session.get('notificaciones_vistas_hasta')
    ultima_vista = datetime.fromisoformat(ultima_vista_str) if ultima_vista_str else None
    hay_notificaciones_sin_leer = notificaciones_repository.hay_no_leidas(id_dueno, ultima_vista)

    return render(request, 'usuarios/bienvenida.html', {
        'nombre': request.session.get('nombre'),
        'paseo_activo': paseo_activo,
        'mascotas_tarjetas': mascotas_tarjetas,
        'id_paseo_sin_calificar': str(id_paseo_sin_calificar) if id_paseo_sin_calificar else None,
        'paseos_este_mes': paseos_este_mes,
        'calificacion_promedio_dada': calificacion_promedio_dada,
        'paseadores_distintos': paseadores_distintos,
        'hay_notificaciones_sin_leer': hay_notificaciones_sin_leer,
    })


@requiere_dueno
def estado_bienvenida(request):
    """
    Polling del dashboard del dueño (cada 12s desde bienvenida.html): solo
    lo necesario para que el banner de "paseo activo" aparezca/desaparezca
    solo cuando el paseador inicia/finaliza el paseo, y para el punto de
    notificaciones sin leer - no la pagina completa. Misma logica que
    bienvenida(), factorizada en _paseo_activo_dueno()/hay_no_leidas().
    """
    id_dueno = request.session['id_usuario']
    paseo_activo = _paseo_activo_dueno(id_dueno)

    ultima_vista_str = request.session.get('notificaciones_vistas_hasta')
    ultima_vista = datetime.fromisoformat(ultima_vista_str) if ultima_vista_str else None
    hay_notificaciones_sin_leer = notificaciones_repository.hay_no_leidas(id_dueno, ultima_vista)

    return JsonResponse({
        'paseo_activo': paseo_activo,
        'hay_notificaciones_sin_leer': hay_notificaciones_sin_leer,
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

    # --- estadisticas del paseador (solo datos que ya existen) ---
    usuario = repository.obtener_por_id(id_paseador)
    paseos_completados = paseos_repository.contar_completados_por_paseador(id_paseador)

    return render(request, 'usuarios/bienvenida_paseador.html', {
        'nombre': request.session.get('nombre'),
        'paseo_activo': paseo_activo,
        'incidente_form': incidente_form,
        'paseos_completados': paseos_completados,
        'calificacion_promedio': usuario.get('calificacion_promedio'),
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

    paseos_completados = paseos_repository.contar_completados_por_paseador(ObjectId(request.session['id_usuario']))

    return render(request, 'usuarios/perfil_paseador.html', {
        'usuario': usuario,
        'form': form,
        'paseos_completados': paseos_completados,
    })


def _iniciar_sesion(request, usuario):
    request.session['id_usuario'] = str(usuario['_id'])
    request.session['nombre'] = usuario['nombre']
    request.session['rol'] = usuario['rol']
