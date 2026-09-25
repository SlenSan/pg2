"""
Vistas web del modulo de paseos.

Dueño: listar paseadores disponibles, ver su perfil, inscribir una
mascota, y ver el estado de "mis paseos".
Paseador: publicar disponibilidad y ver su historial de paseos.
"""

from datetime import datetime, timezone as dt_timezone

from bson import ObjectId
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone as django_timezone
from django.views.decorators.http import require_POST

from calificaciones import repository as calificaciones_repository
from coordenadas import repository as coordenadas_repository
from core.media import ErrorSubidaImagen, subir_imagen
from mascotas import repository as mascotas_repository
from notificaciones import repository as notificaciones_repository
from paseos import repository
from paseos.forms import InscribirMascotaForm, PublicarHorarioForm, SubirFotoPaseoForm
from paseos.repository import MAXIMO_MASCOTAS_POR_PASEO
from usuarios import repository as usuarios_repository
from usuarios.decorators import requiere_dueno, requiere_paseador


def _horario_a_utc(hora_desde, hora_hasta):
    """
    Combina las horas que eligio el paseador (sin fecha - ver
    PublicarHorarioForm) con el dia de HOY en hora de Bogota, y devuelve
    ambas como datetime naive en UTC (mismo formato que el resto de la
    coleccion `paseos`). Se hace en un solo lugar para no repetir la
    conversion de zona horaria - ver el comentario de PublicarHorarioForm
    sobre por que se evito un datetime-local.
    """
    hoy_bogota = django_timezone.localtime(django_timezone.now()).date()
    desde_aware = django_timezone.make_aware(datetime.combine(hoy_bogota, hora_desde))
    hasta_aware = django_timezone.make_aware(datetime.combine(hoy_bogota, hora_hasta))
    desde_utc = desde_aware.astimezone(dt_timezone.utc).replace(tzinfo=None)
    hasta_utc = hasta_aware.astimezone(dt_timezone.utc).replace(tzinfo=None)
    return desde_utc, hasta_utc


def _marcar_utc(paseo):
    """
    pymongo devuelve horario_desde/horario_hasta naive (ver
    _horario_a_utc) - antes de pasarlos a una plantilla hay que marcarlos
    tzinfo=utc explicitamente, para que el filtro `|time` de Django los
    convierta a hora de Bogota en vez de mostrar la hora UTC cruda (mismo
    bug ya encontrado y corregido en mapa.html y en notificaciones).
    """
    return {
        **paseo,
        'horario_desde': paseo['horario_desde'].replace(tzinfo=dt_timezone.utc) if paseo.get('horario_desde') else None,
        'horario_hasta': paseo['horario_hasta'].replace(tzinfo=dt_timezone.utc) if paseo.get('horario_hasta') else None,
    }


@requiere_dueno
def lista_disponibles(request):
    """
    Un paseador puede tener varios horarios publicados a la vez, asi que
    esto ya no es una fila por horario (se veria el mismo paseador
    repetido) - se agrupa por paseador, y el detalle de cada horario se
    ve al entrar a su perfil.
    """
    paseos = repository.listar_disponibles_con_cupo()
    paseadores_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_paseador'] for p in paseos]
    )

    horarios_por_paseador = {}
    for p in paseos:
        horarios_por_paseador.setdefault(p['id_paseador'], []).append(p)

    items = [
        {
            'id_paseador': str(id_paseador),
            'paseador': paseadores_por_id.get(id_paseador),
            'cantidad_horarios': len(horarios),
        }
        # El orden de horarios_por_paseador sigue el de `paseos` (mas
        # reciente primero), asi que esto ya queda ordenado por el
        # horario publicado mas recientemente de cada paseador.
        for id_paseador, horarios in horarios_por_paseador.items()
    ]
    return render(request, 'paseos/lista_disponibles.html', {'items': items})


@requiere_dueno
def detalle_paseador(request, id_paseador):
    paseador = usuarios_repository.obtener_por_id(id_paseador)
    if not paseador or paseador.get('rol') != 'paseador':
        messages.error(request, 'Este paseador no existe.')
        return redirect('paseos:lista_disponibles')

    oid_paseador = ObjectId(id_paseador)
    horarios = [
        _marcar_utc(h)
        for h in repository.listar_disponibles_de_paseador(oid_paseador)
        # "Tiene cupo" (ver CLAUDE.md, "Corrección de alcance 2026-09-25"):
        # ya no es "esta vacio" - un horario con 3/8 mascotas de OTRO dueño
        # sigue apareciendo aca, mientras el paseador no lo haya cerrado y
        # no haya llegado al maximo.
        if h.get('acepta_inscripciones', True) and len(h.get('id_mascotas', [])) < MAXIMO_MASCOTAS_POR_PASEO
    ]
    if not horarios:
        messages.error(request, 'Este paseador no tiene horarios disponibles en este momento.')
        return redirect('paseos:lista_disponibles')

    mis_mascotas = mascotas_repository.listar_por_dueno(request.session['id_usuario'])
    tiene_mascotas = bool(mis_mascotas)

    calificaciones_con_comentario = [
        c for c in calificaciones_repository.listar_por_paseador(oid_paseador) if c.get('comentario')
    ][:5]
    duenos_por_id = usuarios_repository.obtener_varios_por_id(
        [c['id_dueno'] for c in calificaciones_con_comentario]
    )
    resenas = [
        {'calificacion': c, 'dueno': duenos_por_id.get(c['id_dueno'])}
        for c in calificaciones_con_comentario
    ]

    items_horario = []
    for h in horarios:
        id_paseo = str(h['_id'])
        cupos_restantes = MAXIMO_MASCOTAS_POR_PASEO - len(h.get('id_mascotas', []))
        # prefix=id_paseo: hay un InscribirMascotaForm por horario en la
        # misma pagina, y sin un prefijo distinto todos terminarian con
        # los mismos ids="id_ids_mascota_N" (HTML invalido, labels rotos).
        items_horario.append({
            'id_paseo': id_paseo,
            'horario': h,
            'cupos_restantes': cupos_restantes,
            'cupos_totales': MAXIMO_MASCOTAS_POR_PASEO,
            # data-cupos-restantes en la plantilla: el JS deshabilita
            # casillas nuevas una vez marcadas tantas como quepan, para
            # que nadie termine seleccionando de mas y se lleve el
            # rechazo recien al enviar (ver inscribir_en_horario()).
            'form': InscribirMascotaForm(mascotas=mis_mascotas, prefix=id_paseo),
        })

    return render(request, 'paseos/detalle_paseador.html', {
        'id_paseador': id_paseador,
        'paseador': paseador,
        'horarios': items_horario,
        'tiene_mascotas': tiene_mascotas,
        'resenas': resenas,
    })


@require_POST
@requiere_dueno
def inscribir_en_horario(request, id_paseador, id_paseo):
    """
    Inscribe la mascota elegida en UN horario especifico de la lista que
    muestra detalle_paseador() - cada horario de esa lista tiene su
    propio mini-formulario, todos apuntando aca. Misma logica de
    inscripcion de siempre (InscribirMascotaForm + inscribir_mascota()),
    solo que ahora vive en su propio endpoint en vez de compartir el GET
    de la pagina, porque la pagina ya no representa un unico horario.
    """
    paseo = repository.obtener_por_id(id_paseo)
    if not paseo or str(paseo.get('id_paseador')) != id_paseador:
        messages.error(request, 'Este horario ya no está disponible.')
        return redirect('paseos:detalle_paseador', id_paseador=id_paseador)

    mis_mascotas = mascotas_repository.listar_por_dueno(request.session['id_usuario'])
    # Mismo prefix=id_paseo que uso detalle_paseador() al renderizar este
    # formulario, para leer los campos con el nombre namespaced correcto.
    form = InscribirMascotaForm(request.POST, mascotas=mis_mascotas, prefix=id_paseo)
    if not form.is_valid():
        messages.error(request, 'Selecciona al menos una mascota válida.')
        return redirect('paseos:detalle_paseador', id_paseador=id_paseador)

    ids_mascota = form.cleaned_data['ids_mascota']
    mascotas_elegidas = mascotas_repository.obtener_varias_por_id_y_dueno(
        ids_mascota, request.session['id_usuario']
    )
    if len(mascotas_elegidas) != len(ids_mascota):
        # Alguna de las ids no es del dueño (o ya no existe) - las
        # opciones del form ya vienen filtradas a sus propias mascotas,
        # asi que esto solo pasaria con un POST forjado.
        messages.error(request, 'Una o más mascotas no son válidas.')
        return redirect('paseos:detalle_paseador', id_paseador=id_paseador)

    # Validaciones "amigables" ANTES de intentar el update atomico, para
    # poder darle al dueño un mensaje preciso (cuantos cupos quedaban) en
    # vez del generico "ya no esta disponible" - inscribir_mascotas()
    # sigue siendo la fuente de verdad real (se valida ahi tambien, de
    # forma atomica, por si el cupo cambio justo entre este chequeo y el
    # POST - condicion de carrera).
    if not paseo.get('acepta_inscripciones', True):
        messages.error(request, 'Este horario ya no acepta nuevas inscripciones.')
        return redirect('paseos:detalle_paseador', id_paseador=id_paseador)
    cupos_restantes = MAXIMO_MASCOTAS_POR_PASEO - len(paseo.get('id_mascotas', []))
    if len(ids_mascota) > cupos_restantes:
        messages.error(
            request,
            f'Solo quedan {cupos_restantes} cupo{"s" if cupos_restantes != 1 else ""} '
            f'libre{"s" if cupos_restantes != 1 else ""} en este horario - elige como máximo esa cantidad.',
        )
        return redirect('paseos:detalle_paseador', id_paseador=id_paseador)

    asignado = repository.inscribir_mascotas(
        id_paseo=id_paseo,
        id_dueno=request.session['id_usuario'],
        ids_mascota=ids_mascota,
    )
    if not asignado:
        messages.error(request, 'Este horario ya no está disponible.')
        return redirect('paseos:detalle_paseador', id_paseador=id_paseador)

    paseador = usuarios_repository.obtener_por_id(id_paseador)
    nombres = mascotas_repository.nombres_unidos(mascotas_elegidas)
    messages.success(
        request,
        f'Inscribiste a {nombres} con {paseador["nombre"] if paseador else "el paseador"}.',
    )
    return redirect('paseos:mis_paseos')


@requiere_dueno
def mis_paseos(request):
    id_dueno = request.session['id_usuario']
    paseos = repository.listar_por_dueno(id_dueno)
    paseadores_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_paseador'] for p in paseos]
    )
    # SOLO las mascotas propias de este dueño (nunca obtener_varias_por_id
    # con id_mascotas completo) - un paseo puede tener mascotas de OTROS
    # dueños tambien (hasta 8, Ley Kiara). resolver_lista() ya se encarga
    # de quedarse solo con los ids presentes en este mapa, en el orden
    # original - ver CLAUDE.md, "Corrección de alcance 2026-09-25".
    mis_mascotas_por_id = {m['_id']: m for m in mascotas_repository.listar_por_dueno(id_dueno)}
    # Igual con las calificaciones: un paseo compartido puede tener una
    # calificacion de OTRO dueño sin que este haya calificado todavia -
    # "calificado" es siempre relativo a ESTE dueño, nunca "algun dueño".
    oid_dueno = ObjectId(id_dueno)
    ids_calificados = {
        c['id_paseo'] for c in calificaciones_repository.listar_por_paseos([p['_id'] for p in paseos])
        if c['id_dueno'] == oid_dueno
    }
    items = [
        {
            'id_paseo': str(p['_id']),
            'paseo': p,
            'paseador': paseadores_por_id.get(p['id_paseador']),
            'mascotas_nombres': mascotas_repository.nombres_unidos(
                mascotas_repository.resolver_lista(p.get('id_mascotas'), mis_mascotas_por_id)
            ),
            'calificado': p['_id'] in ids_calificados,
        }
        for p in paseos
    ]
    return render(request, 'paseos/mis_paseos.html', {'items': items})


@requiere_dueno
def historial(request):
    """
    Historial de paseos COMPLETADOS (solo estado='historico'), con el
    patron de tarjetas del dashboard. Distinto de mis_paseos (que
    muestra cualquier estado y sirve para rastrear un paseo agendado o
    en curso - se deja intacta esa vista, esta es nueva).
    """
    id_dueno = request.session['id_usuario']
    paseos = [p for p in repository.listar_por_dueno(id_dueno) if p['estado'] == 'historico']
    paseadores_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_paseador'] for p in paseos if p.get('id_paseador')]
    )
    # SOLO las mascotas propias de este dueño - mismo motivo que mis_paseos().
    mis_mascotas_por_id = {m['_id']: m for m in mascotas_repository.listar_por_dueno(id_dueno)}
    # Idem la calificacion: la de ESTE dueño, no la de cualquiera que haya
    # calificado el mismo paseo compartido.
    oid_dueno = ObjectId(id_dueno)
    calificaciones_por_paseo = {
        c['id_paseo']: c
        for c in calificaciones_repository.listar_por_paseos([p['_id'] for p in paseos])
        if c['id_dueno'] == oid_dueno
    }

    items = []
    for p in paseos:
        duracion_min = None
        if p.get('hora_inicio') and p.get('hora_fin'):
            duracion_min = int((p['hora_fin'] - p['hora_inicio']).total_seconds() // 60)
        calificacion = calificaciones_por_paseo.get(p['_id'])
        mascotas_paseo = mascotas_repository.resolver_lista(p.get('id_mascotas'), mis_mascotas_por_id)
        items.append({
            'id_paseo': str(p['_id']),
            'paseo': p,
            'paseador': paseadores_por_id.get(p.get('id_paseador')),
            'mascota_avatar': mascotas_paseo[0] if mascotas_paseo else None,
            'mascotas_nombres': mascotas_repository.nombres_unidos(mascotas_paseo),
            'duracion_min': duracion_min,
            'puntuacion': calificacion['puntuacion'] if calificacion else None,
        })

    return render(request, 'paseos/historial.html', {'items': items})


@require_POST
@requiere_paseador
def publicar_disponibilidad(request):
    """
    Modal "Publicar horario" del dashboard del paseador. Ya no hay limite
    de uno solo a la vez - un paseador puede tener varios horarios
    'disponible' simultaneos (ver CLAUDE.md). Publicar un horario nuevo
    tampoco se bloquea si el paseador esta en_vivo ahora mismo: es un
    compromiso a futuro, no una accion inmediata, asi que no hay conflicto
    fisico real con estar caminando otro perro en este momento.
    """
    id_paseador = ObjectId(request.session['id_usuario'])
    form = PublicarHorarioForm(request.POST)
    if not form.is_valid():
        primer_error = next(iter(form.errors.values()))[0]
        messages.error(request, f'No se pudo publicar el horario: {primer_error}')
        return redirect('usuarios:bienvenida_paseador')

    horario_desde, horario_hasta = _horario_a_utc(form.cleaned_data['desde'], form.cleaned_data['hasta'])
    repository.crear_disponibilidad(
        id_paseador=id_paseador,
        horario_desde=horario_desde,
        horario_hasta=horario_hasta,
    )
    messages.success(request, 'Horario publicado correctamente.')
    return redirect('usuarios:bienvenida_paseador')


@require_POST
@requiere_paseador
def cancelar_disponibilidad(request, id_paseo):
    """
    Boton "Despublicar"/"Cerrar a nuevas inscripciones" de UN horario
    especifico de la lista del dashboard. Funciona en cualquier momento,
    tenga o no mascotas inscritas ya (ver repository.cancelar_disponibilidad
    para el detalle de los dos comportamientos - se borra si esta vacio,
    o se cierra a nuevas inscripciones sin tocar lo ya inscrito si no).
    """
    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = repository.cancelar_disponibilidad(id_paseo=id_paseo, id_paseador=id_paseador)
    if not paseo:
        messages.error(request, 'No se pudo despublicar: este horario ya no está disponible.')
    elif paseo.get('id_mascotas'):
        messages.success(request, 'Este horario ya no acepta nuevas inscripciones.')
    else:
        messages.success(request, 'Horario despublicado correctamente.')
    return redirect('usuarios:bienvenida_paseador')


@require_POST
@requiere_paseador
def iniciar_paseo(request, id_paseo):
    """Pasa un paseo propio de 'disponible' a 'en_vivo' y notifica al dueño."""
    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = repository.iniciar_paseo(id_paseo=id_paseo, id_paseador=id_paseador)
    if not paseo:
        messages.error(
            request,
            'No se pudo iniciar el paseo: ya no está disponible, no tiene mascota inscrita, '
            'o ya tienes otro paseo en curso.',
        )
    else:
        # Un paseo por notificacion, uno POR CADA dueño involucrado (hasta
        # 8 mascotas, posiblemente de varios dueños - ver CLAUDE.md,
        # "Corrección de alcance 2026-09-25"), no solo al primero.
        for id_dueno in paseo.get('id_duenos', []):
            notificaciones_repository.crear(
                id_usuario=id_dueno,
                tipo='inicio_paseo',
                mensaje=f'{request.session.get("nombre")} inició el paseo de tu mascota.',
            )
    return redirect('usuarios:bienvenida_paseador')


@require_POST
@requiere_paseador
def finalizar_paseo(request, id_paseo):
    """Pasa un paseo propio de 'en_vivo' a 'historico' y notifica al dueño."""
    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = repository.finalizar_paseo(id_paseo=id_paseo, id_paseador=id_paseador)
    if not paseo:
        messages.error(request, 'No se pudo finalizar el paseo: ya no estaba en curso.')
    else:
        for id_dueno in paseo.get('id_duenos', []):
            notificaciones_repository.crear(
                id_usuario=id_dueno,
                tipo='fin_paseo',
                mensaje=f'{request.session.get("nombre")} finalizó el paseo de tu mascota.',
            )
    return redirect('usuarios:bienvenida_paseador')


@require_POST
@requiere_paseador
def subir_foto(request, id_paseo, momento):
    """
    Registro fotografico del paseo (RF15) - distinto de la evidencia de
    incidentes: son las 3 fotos normales de inicio/mitad/fin, guardadas
    en paseos.fotos. Un boton explicito por momento (ver
    bienvenida_paseador.html) en vez de adivinar el momento
    automaticamente, para que el paseador siempre sepa exactamente que
    esta subiendo.
    """
    if momento not in repository.MOMENTOS_FOTO_VALIDOS:
        messages.error(request, 'Momento de foto inválido.')
        return redirect('usuarios:bienvenida_paseador')

    form = SubirFotoPaseoForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, 'No se pudo subir la foto: selecciona un archivo de imagen válido.')
        return redirect('usuarios:bienvenida_paseador')

    try:
        url = subir_imagen(form.cleaned_data['foto'], carpeta='paseos')
    except ErrorSubidaImagen as exc:
        messages.error(request, f'No se pudo subir la foto: {exc}')
        return redirect('usuarios:bienvenida_paseador')

    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = repository.agregar_foto(id_paseo=id_paseo, id_paseador=id_paseador, momento=momento, url=url)
    if not paseo:
        messages.error(
            request,
            'No se pudo registrar la foto: el paseo ya no está activo o ya subiste una foto de ese momento.',
        )
    else:
        messages.success(request, f'Foto de {momento} guardada correctamente.')
    return redirect('usuarios:bienvenida_paseador')


@requiere_paseador
def historial_paseador(request):
    """
    "Mis paseos" del paseador - reemplaza la pantalla vieja "Historial de
    paseos" (misma vista/URL, rediseñada; no hay una pantalla duplicada
    conviviendo). Solo paseos 'historico', mismo criterio que ya usa
    historial() del lado del dueño (con foto/duracion/calificacion no
    tiene sentido mostrar horarios 'disponible'/'en_vivo' aca - esos ya
    se ven en el propio dashboard del paseador).

    El paseador SI puede ver todas las mascotas y todos los dueños de
    cada paseo propio (a diferencia del lado del dueño, no hay nada que
    filtrar por privacidad aca - el paseador ya los llevo a todos juntos
    en el mismo paseo).
    """
    id_paseador = ObjectId(request.session['id_usuario'])
    paseos = [p for p in repository.listar_por_paseador(id_paseador) if p['estado'] == 'historico']

    duenos_por_id = usuarios_repository.obtener_varios_por_id(
        [did for p in paseos for did in p.get('id_duenos', [])]
    )
    mascotas_por_id = mascotas_repository.obtener_varias_por_id(
        [mid for p in paseos for mid in p.get('id_mascotas', [])]
    )
    # Con multi-dueño (ver CLAUDE.md, "Corrección de alcance 2026-09-25"),
    # un mismo paseo puede tener VARIAS calificaciones independientes (una
    # por dueño) - se agrupan por id_paseo para promediarlas por tarjeta,
    # en vez de asumir "a lo sumo una" como antes del cambio.
    calificaciones_por_paseo = {}
    for c in calificaciones_repository.listar_por_paseos([p['_id'] for p in paseos]):
        calificaciones_por_paseo.setdefault(c['id_paseo'], []).append(c)

    ahora = datetime.now(dt_timezone.utc).replace(tzinfo=None)
    items = []
    for p in paseos:
        duracion_min = None
        if p.get('hora_inicio') and p.get('hora_fin'):
            duracion_min = int((p['hora_fin'] - p['hora_inicio']).total_seconds() // 60)
        mascotas_paseo = mascotas_repository.resolver_lista(p.get('id_mascotas'), mascotas_por_id)
        duenos_paseo = usuarios_repository.resolver_lista(p.get('id_duenos'), duenos_por_id)
        calificaciones_paseo = calificaciones_por_paseo.get(p['_id'], [])
        puntuacion_promedio = (
            round(sum(c['puntuacion'] for c in calificaciones_paseo) / len(calificaciones_paseo), 1)
            if calificaciones_paseo else None
        )
        items.append({
            'id_paseo': str(p['_id']),
            'paseo': p,
            # pymongo devuelve hora_inicio naive (UTC) - se marca
            # explicitamente antes de pasarlo al filtro `|date` de Django
            # (mismo bug ya resuelto varias veces en este proyecto, ver
            # CLAUDE.md).
            'hora_inicio_utc': p['hora_inicio'].replace(tzinfo=dt_timezone.utc) if p.get('hora_inicio') else None,
            'mascota_avatar': mascotas_paseo[0] if mascotas_paseo else None,
            'mascotas_nombres': mascotas_repository.nombres_unidos(mascotas_paseo),
            'duenos_nombres': usuarios_repository.nombres_unidos(duenos_paseo),
            'duracion_min': duracion_min,
            'puntuacion_promedio': puntuacion_promedio,
            # None si el paseo tiene menos de 2 puntos GPS - ver
            # coordenadas.repository.distancia_recorrida_km().
            'distancia_km': coordenadas_repository.distancia_recorrida_km(p['_id']),
        })

    # --- estadisticas del encabezado (totales "de siempre", a diferencia
    # de las del dashboard - ver bienvenida_paseador()) ---
    paseos_completados = repository.contar_completados_por_paseador(id_paseador)
    paseos_este_mes = sum(
        1 for p in paseos
        if p.get('hora_fin') and p['hora_fin'].year == ahora.year and p['hora_fin'].month == ahora.month
    )
    usuario = usuarios_repository.obtener_por_id(id_paseador)

    return render(request, 'paseos/historial_paseador.html', {
        'items': items,
        'paseos_completados': paseos_completados,
        'paseos_este_mes': paseos_este_mes,
        'calificacion_promedio': usuario.get('calificacion_promedio'),
    })
