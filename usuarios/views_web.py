"""
Vistas web (Django Templates + Bootstrap) de autenticación y dashboards.

Compartidas por dueño y paseador: ambos usan la misma plataforma web (ya
no existe una app Android separada para el paseador — ver CLAUDE.md).
registro()/login()/logout() son comunes a los dos roles; cada uno tiene
su propio dashboard (bienvenida / bienvenida_paseador) protegido por su
decorator correspondiente (ver usuarios/decorators.py).
"""

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone as django_timezone

from calificaciones import repository as calificaciones_repository
from core.media import ErrorSubidaImagen, subir_imagen
from incidentes.forms import ReportarIncidenteForm
from mascotas import repository as mascotas_repository
from notificaciones import repository as notificaciones_repository
from paseos import repository as paseos_repository
from paseos.forms import PublicarHorarioForm
from usuarios import repository
from usuarios.decorators import requiere_dueno, requiere_paseador
from usuarios.forms import EditarPerfilPaseadorForm, LoginForm, RegistroDuenoForm, RegistroPaseadorForm

_ROLES_VALIDOS = ('dueno', 'paseador')
_ROL_MONGO = {'dueno': 'dueño', 'paseador': 'paseador'}


def _url_dashboard(rol):
    return 'usuarios:bienvenida_paseador' if rol == 'paseador' else 'usuarios:bienvenida'


def _rango_dia_utc(fecha_bogota):
    """
    El rango [inicio, fin) de un dia CALENDARIO de Bogota, como datetimes
    naive en UTC (mismo formato que el resto de la coleccion `paseos` -
    ver core/mongo.py) - para filtrar por un dia especifico sin el bug ya
    conocido de comparar fechas naive-UTC como si fueran hora local.
    Mismo patron de conversion que _horario_a_utc() en paseos/views_web.py.
    """
    inicio_aware = django_timezone.make_aware(datetime.combine(fecha_bogota, datetime.min.time()))
    fin_aware = inicio_aware + timedelta(days=1)
    return (
        inicio_aware.astimezone(timezone.utc).replace(tzinfo=None),
        fin_aware.astimezone(timezone.utc).replace(tzinfo=None),
    )


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

    # SOLO las mascotas de ESTE dueño - el paseo en vivo puede llevar
    # mascotas de OTROS dueños tambien (hasta 8, Ley Kiara - ver
    # CLAUDE.md, "Corrección de alcance 2026-09-25"); el banner del
    # dashboard no debe mostrarle a un dueño el nombre de una mascota
    # ajena.
    mascotas_por_id = {
        m['_id']: m
        for m in mascotas_repository.obtener_varias_por_id_y_dueno(paseo_en_vivo.get('id_mascotas', []), id_dueno)
    }
    mascotas = mascotas_repository.resolver_lista(paseo_en_vivo.get('id_mascotas'), mascotas_por_id)
    paseador = None
    if paseo_en_vivo.get('id_paseador'):
        paseador = repository.obtener_por_id(paseo_en_vivo['id_paseador'])

    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    hora_inicio = paseo_en_vivo.get('hora_inicio')
    minutos = int((ahora - hora_inicio).total_seconds() // 60) if hora_inicio else 0
    return {
        'id_paseo': str(paseo_en_vivo['_id']),
        'mascota_nombre': mascotas_repository.nombres_unidos(mascotas) or 'tu mascota',
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
        mid for p in paseos_dueno if p['estado'] == 'en_vivo' for mid in p.get('id_mascotas', [])
    }
    ultimo_paseo_por_mascota = {}
    for p in paseos_dueno:  # ya viene ordenado por fecha desc
        if p['estado'] != 'historico':
            continue
        for mid in p.get('id_mascotas', []):
            if mid not in ultimo_paseo_por_mascota:
                ultimo_paseo_por_mascota[mid] = p

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
    # "Calificado" es siempre relativo a ESTE dueño (id_dueno=oid_dueno) -
    # un paseo compartido (hasta 8 mascotas, Ley Kiara) puede tener la
    # calificacion de OTRO dueño sin que este haya calificado todavia.
    oid_dueno = ObjectId(id_dueno)
    ids_calificados = {
        c['id_paseo'] for c in calificaciones_repository.listar_por_paseos(ids_historico)
        if c['id_dueno'] == oid_dueno
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
    hay_notificaciones_sin_leer = _hay_notificaciones_sin_leer(request, id_dueno)

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
    hay_notificaciones_sin_leer = _hay_notificaciones_sin_leer(request, id_dueno)

    return JsonResponse({
        'paseo_activo': paseo_activo,
        'hay_notificaciones_sin_leer': hay_notificaciones_sin_leer,
    })


def _horarios_disponibles_paseador(id_paseador):
    """
    Horarios 'disponible' de este paseador, con nombre de dueños/mascotas
    ya resueltos para la plantilla (los que ya tienen mascota(s)
    inscrita(s) son la tarjeta "Nueva solicitud"; los demas, "esperando
    dueño"). El paseador ve TODOS los dueños/mascotas de cada horario sin
    filtrar (a diferencia del lado del dueño, no hay nada que ocultarle -
    el se los va a llevar a todos juntos). Usada tanto por
    bienvenida_paseador() (carga completa) como por
    estado_bienvenida_paseador() (polling), para que ambas calculen
    exactamente lo mismo - mismo patron que _paseo_activo_dueno().
    """
    horarios_crudos = paseos_repository.listar_disponibles_de_paseador(id_paseador)
    duenos_por_id = repository.obtener_varios_por_id(
        [did for h in horarios_crudos for did in h.get('id_duenos', [])]
    )
    mascotas_por_id = mascotas_repository.obtener_varias_por_id(
        [mid for h in horarios_crudos for mid in h.get('id_mascotas', [])]
    )
    horarios = []
    for h in horarios_crudos:
        mascotas_horario = mascotas_repository.resolver_lista(h.get('id_mascotas'), mascotas_por_id)
        duenos_horario = repository.resolver_lista(h.get('id_duenos'), duenos_por_id)
        duenos_nombres = repository.nombres_unidos(duenos_horario)
        horarios.append({
            'id_paseo': str(h['_id']),
            'horario_desde': h['horario_desde'].replace(tzinfo=timezone.utc) if h.get('horario_desde') else None,
            'horario_hasta': h['horario_hasta'].replace(tzinfo=timezone.utc) if h.get('horario_hasta') else None,
            'mascota_nombre': mascotas_repository.nombres_unidos(mascotas_horario) or None,
            'dueno_nombre': duenos_nombres or None,
            'cupos_ocupados': len(h.get('id_mascotas', [])),
            'cupos_totales': paseos_repository.MAXIMO_MASCOTAS_POR_PASEO,
            'acepta_inscripciones': h.get('acepta_inscripciones', True),
        })
    return horarios


def _hay_notificaciones_sin_leer(request, id_usuario):
    ultima_vista_str = request.session.get('notificaciones_vistas_hasta')
    ultima_vista = datetime.fromisoformat(ultima_vista_str) if ultima_vista_str else None
    return notificaciones_repository.hay_no_leidas(id_usuario, ultima_vista)


@requiere_paseador
def bienvenida_paseador(request):
    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = paseos_repository.obtener_en_vivo_de_paseador(id_paseador)

    paseo_activo = None
    incidente_form = None
    if paseo:
        # El paseador SI ve todas las mascotas/dueños de su propio paseo en
        # vivo, sin filtrar - se los esta llevando a todos juntos.
        mascotas_por_id = mascotas_repository.obtener_varias_por_id(paseo.get('id_mascotas', []))
        mascotas_paseo = mascotas_repository.resolver_lista(paseo.get('id_mascotas'), mascotas_por_id)
        duenos_por_id = repository.obtener_varios_por_id(paseo.get('id_duenos', []))
        duenos_paseo = repository.resolver_lista(paseo.get('id_duenos'), duenos_por_id)
        duenos_nombres = repository.nombres_unidos(duenos_paseo)
        fotos_existentes = {f['momento'] for f in paseo.get('fotos', [])}
        paseo_activo = {
            'id_paseo': str(paseo['_id']),
            'estado': paseo['estado'],
            'mascota_nombre': mascotas_repository.nombres_unidos(mascotas_paseo) or None,
            'dueno_nombre': duenos_nombres or None,
            'fotos_pendientes': [
                m for m in paseos_repository.MOMENTOS_FOTO_VALIDOS if m not in fotos_existentes
            ],
        }
        # mascotas=mascotas_paseo: si el paseo lleva mas de una, el form
        # agrega el radio "¿a cual mascota afecta?" (ver ReportarIncidenteForm);
        # con una sola, ese campo ni se crea - se asigna sola en la vista.
        incidente_form = ReportarIncidenteForm(mascotas=mascotas_paseo)

    # --- horarios publicados (varios simultaneos posibles) - solo si no
    # esta caminando ahora mismo, mismo criterio que ya tenia esta
    # pantalla de mostrar una cosa u otra, no las dos a la vez ---
    horarios_disponibles = []
    form_horario = PublicarHorarioForm()
    if not paseo_activo:
        horarios_disponibles = _horarios_disponibles_paseador(id_paseador)

    # --- estadisticas del dashboard: actividad RECIENTE, no totales de
    # siempre (esos ya estan en "Mi perfil" y en "Mis paseos") ---
    # "Solicitudes hoy": un horario SIEMPRE se publica para HOY (ver
    # PublicarHorarioForm) - el esquema no guarda una fecha de
    # inscripcion por separado, asi que se cuenta el total de mascotas
    # inscritas en los horarios de HOY (sea cual sea su estado actual).
    hoy_bogota = django_timezone.localtime(django_timezone.now()).date()
    inicio_hoy_utc, fin_hoy_utc = _rango_dia_utc(hoy_bogota)
    paseos_hoy = paseos_repository.listar_por_paseador_con_horario_en(id_paseador, inicio_hoy_utc, fin_hoy_utc)
    solicitudes_hoy = sum(len(p.get('id_mascotas', [])) for p in paseos_hoy)

    hace_7_dias = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    paseos_esta_semana = paseos_repository.contar_historico_desde(id_paseador, hace_7_dias)

    return render(request, 'usuarios/bienvenida_paseador.html', {
        'nombre': request.session.get('nombre'),
        'paseo_activo': paseo_activo,
        'incidente_form': incidente_form,
        'horarios_disponibles': horarios_disponibles,
        'form_horario': form_horario,
        'solicitudes_hoy': solicitudes_hoy,
        'paseos_esta_semana': paseos_esta_semana,
    })


@requiere_paseador
def estado_bienvenida_paseador(request):
    """
    Polling del dashboard del paseador (cada 12s desde
    bienvenida_paseador.html, solo mientras NO esta caminando - ver esa
    plantilla): asi el paseador ve aparecer "Nueva solicitud" en cuanto un
    dueño inscribe una mascota en alguno de sus horarios, sin recargar.

    Mientras SI esta caminando (en_vivo), esta seccion ni se muestra en la
    pantalla, asi que este polling tampoco corre ahi - el punto de
    notificaciones sin leer se actualiza en ese caso aprovechando el POST
    de GPS que ya se manda cada 10s (ver registrar_coordenada), en vez de
    sumar una peticion nueva aparte.

    Devuelve el fragmento de HTML ya renderizado (no JSON con los datos
    sueltos) porque la lista de horarios cambia de tamaño y de contenido -
    mas facil y consistente re-renderizar el mismo template que ya usa la
    carga completa, que reconstruir ese HTML a mano en JS.
    """
    id_paseador = ObjectId(request.session['id_usuario'])
    horarios_disponibles = _horarios_disponibles_paseador(id_paseador)
    horarios_html = render_to_string(
        'usuarios/_horarios_paseador.html',
        {'horarios_disponibles': horarios_disponibles},
        request=request,
    )
    return JsonResponse({
        'horarios_html': horarios_html,
        'hay_notificaciones_sin_leer': _hay_notificaciones_sin_leer(request, id_paseador),
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

    oid_paseador = ObjectId(request.session['id_usuario'])
    paseos_completados = paseos_repository.contar_completados_por_paseador(oid_paseador)

    # "Mis reseñas": mismo criterio que ya usa paseos/views_web.py en
    # detalle_paseador() (el perfil que ve el DUEÑO de este paseador) -
    # esa vista si lo tenia, pero nunca se replico aca, en "Mi perfil" (la
    # vista del propio paseador sobre si mismo). Duplicado a proposito en
    # vez de importarlo de la app paseos, mismo criterio que
    # _hay_notificaciones_sin_leer en coordenadas/views_web.py: evitar una
    # dependencia cruzada entre apps por unas pocas lineas.
    calificaciones_con_comentario = [
        c for c in calificaciones_repository.listar_por_paseador(oid_paseador) if c.get('comentario')
    ][:5]
    duenos_por_id = repository.obtener_varios_por_id(
        [c['id_dueno'] for c in calificaciones_con_comentario]
    )
    resenas = [
        {'calificacion': c, 'dueno': duenos_por_id.get(c['id_dueno'])}
        for c in calificaciones_con_comentario
    ]

    # "Miembro desde": pymongo devuelve fecha_registro naive (UTC, ver
    # core/mongo.py) - se marca tzinfo=utc explicitamente antes de pasarla
    # al filtro `|date` de Django, o el naive datetime se formatea tal
    # cual (asumido ya en hora local) en vez de convertirse a
    # America/Bogota - mismo problema ya resuelto para horario_desde/
    # horario_hasta y las notificaciones (ver CLAUDE.md).
    fecha_registro = usuario.get('fecha_registro')
    miembro_desde = fecha_registro.replace(tzinfo=timezone.utc) if fecha_registro else None

    return render(request, 'usuarios/perfil_paseador.html', {
        'usuario': usuario,
        'form': form,
        'paseos_completados': paseos_completados,
        'resenas': resenas,
        'miembro_desde': miembro_desde,
    })


def _iniciar_sesion(request, usuario):
    request.session['id_usuario'] = str(usuario['_id'])
    request.session['nombre'] = usuario['nombre']
    request.session['rol'] = usuario['rol']
