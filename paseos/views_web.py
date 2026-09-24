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
from core.media import ErrorSubidaImagen, subir_imagen
from mascotas import repository as mascotas_repository
from notificaciones import repository as notificaciones_repository
from paseos import repository
from paseos.forms import InscribirMascotaForm, PublicarHorarioForm, SubirFotoPaseoForm
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
    paseos = repository.listar_disponibles_sin_asignar()
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
        if not h.get('id_mascota')
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
        # prefix=id_paseo: hay un InscribirMascotaForm por horario en la
        # misma pagina, y sin un prefijo distinto todos terminarian con
        # el mismo id="id_mascota" (HTML invalido, labels rotos).
        items_horario.append({
            'id_paseo': id_paseo,
            'horario': h,
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
        messages.error(request, 'Selecciona una mascota válida.')
        return redirect('paseos:detalle_paseador', id_paseador=id_paseador)

    id_mascota = form.cleaned_data['id_mascota']
    mascota = mascotas_repository.obtener_por_id_y_dueno(id_mascota, request.session['id_usuario'])
    if not mascota:
        messages.error(request, 'Mascota inválida.')
        return redirect('paseos:detalle_paseador', id_paseador=id_paseador)

    asignado = repository.inscribir_mascota(
        id_paseo=id_paseo,
        id_dueno=request.session['id_usuario'],
        id_mascota=id_mascota,
    )
    if not asignado:
        messages.error(request, 'Este horario ya no está disponible.')
        return redirect('paseos:detalle_paseador', id_paseador=id_paseador)

    paseador = usuarios_repository.obtener_por_id(id_paseador)
    messages.success(
        request,
        f'Inscribiste a {mascota["nombre"]} con {paseador["nombre"] if paseador else "el paseador"}.',
    )
    return redirect('paseos:mis_paseos')


@requiere_dueno
def mis_paseos(request):
    paseos = repository.listar_por_dueno(request.session['id_usuario'])
    paseadores_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_paseador'] for p in paseos]
    )
    mascotas_por_id = mascotas_repository.obtener_varias_por_id(
        [p['id_mascota'] for p in paseos if p.get('id_mascota')]
    )
    ids_calificados = {
        c['id_paseo'] for c in calificaciones_repository.listar_por_paseos([p['_id'] for p in paseos])
    }
    items = [
        {
            'id_paseo': str(p['_id']),
            'paseo': p,
            'paseador': paseadores_por_id.get(p['id_paseador']),
            'mascota': mascotas_por_id.get(p['id_mascota']),
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
    paseos = [p for p in repository.listar_por_dueno(request.session['id_usuario']) if p['estado'] == 'historico']
    paseadores_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_paseador'] for p in paseos if p.get('id_paseador')]
    )
    mascotas_por_id = mascotas_repository.obtener_varias_por_id(
        [p['id_mascota'] for p in paseos if p.get('id_mascota')]
    )
    calificaciones_por_paseo = {
        c['id_paseo']: c
        for c in calificaciones_repository.listar_por_paseos([p['_id'] for p in paseos])
    }

    items = []
    for p in paseos:
        duracion_min = None
        if p.get('hora_inicio') and p.get('hora_fin'):
            duracion_min = int((p['hora_fin'] - p['hora_inicio']).total_seconds() // 60)
        calificacion = calificaciones_por_paseo.get(p['_id'])
        items.append({
            'id_paseo': str(p['_id']),
            'paseo': p,
            'paseador': paseadores_por_id.get(p.get('id_paseador')),
            'mascota': mascotas_por_id.get(p.get('id_mascota')),
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
    Boton "Despublicar" de UN horario especifico de la lista del
    dashboard (ya no hay un solo horario/switch - puede haber varios).
    Solo funciona mientras ningun dueño haya inscrito una mascota todavia
    - la interfaz ya no ofrece esta opcion una vez hay una solicitud
    pendiente, pero igual se valida aca por si un dueño alcanzo a
    inscribir justo antes de que este POST llegara (condicion de carrera).
    """
    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = repository.cancelar_disponibilidad(id_paseo=id_paseo, id_paseador=id_paseador)
    if not paseo:
        messages.error(
            request,
            'No se pudo despublicar: un dueño ya inscribió una mascota en este paseo.',
        )
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
        notificaciones_repository.crear(
            id_usuario=paseo['id_dueno'],
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
        notificaciones_repository.crear(
            id_usuario=paseo['id_dueno'],
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
    id_paseador = ObjectId(request.session['id_usuario'])
    paseos = repository.listar_por_paseador(id_paseador)
    duenos_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_dueno'] for p in paseos if p.get('id_dueno')]
    )
    mascotas_por_id = mascotas_repository.obtener_varias_por_id(
        [p['id_mascota'] for p in paseos if p.get('id_mascota')]
    )
    items = [
        {
            'paseo': p,
            'dueno': duenos_por_id.get(p.get('id_dueno')),
            'mascota': mascotas_por_id.get(p.get('id_mascota')),
        }
        for p in paseos
    ]
    return render(request, 'paseos/historial_paseador.html', {'items': items})
