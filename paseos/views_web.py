"""
Vistas web del modulo de paseos.

Dueño: listar paseadores disponibles, ver su perfil, inscribir una
mascota, y ver el estado de "mis paseos".
Paseador: publicar disponibilidad y ver su historial de paseos.
"""

from datetime import datetime, timezone as dt_timezone

from bson import ObjectId
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone as django_timezone
from django.views.decorators.http import require_POST

from calificaciones import repository as calificaciones_repository
from coordenadas import repository as coordenadas_repository
from core.media import ErrorSubidaImagen, ErrorValidacionImagen, subir_imagen
from mascotas import repository as mascotas_repository
from notificaciones import repository as notificaciones_repository
from paseos import repository
from paseos.forms import InscribirMascotaForm, MotivoNoRecogidaForm, PublicarHorarioForm, SubirFotoPaseoForm
from paseos.repository import MAXIMO_MASCOTAS_POR_PASEO, ZONAS_VALIDAS, ZONAS_VALIDAS_CON_NUMERO, etiqueta_zona
from usuarios import repository as usuarios_repository
from usuarios.decorators import requiere_dueno, requiere_paseador
from usuarios.forms import TIPO_PRIMEROS_AUXILIOS


def _distancia_texto_de_paseo(paseo):
    """
    Ajustes del 19 de octubre, punto 1 - texto de distancia ("850 m" /
    "1,2 km") para una tarjeta de historial, usada tanto por historial()
    (dueño) como por historial_paseador(). Si el paseo YA tiene
    `distancia_m` guardado (lo calculó finalizar_paseo() al terminar -
    ver paseos.repository.guardar_distancia()), se usa tal cual, sin
    recalcular; `'distancia_m' in paseo` (no `.get(...)`) distingue ese
    caso de un paseo de ANTES de este punto, que no tiene el campo en
    absoluto y sí necesita el cálculo en vivo.
    """
    if 'distancia_m' in paseo:
        distancia_m = paseo['distancia_m']
    else:
        distancia_m = coordenadas_repository.distancia_recorrida_m(paseo['_id'])
    return coordenadas_repository.formatear_distancia(distancia_m)


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

    Filtro por zona (?zona=...) - Incremento 4, punto G: un paseador con
    VARIOS horarios (algunos en la zona elegida, otros no, o sin zona)
    sigue apareciendo en la lista filtrada - "aparece si tiene al menos
    un horario que califica", confirmado explicitamente antes de
    programar esto. Se valida contra ZONAS_VALIDAS y se ignora (sin
    filtrar, sin error) cualquier valor que no sea una de las 17 comunas
    - una URL manipulada a mano no rompe la pantalla, simplemente no
    filtra nada.

    Una sola consulta sin filtrar (`zona=None`) para TODO: la lista que
    se muestra (filtrada en Python si hay zona_seleccionada) Y el conteo
    de paseadores por comuna del <select> (que necesita el total de las
    17, no solo la seleccionada) - evita repetir la misma consulta dos
    veces contra Mongo.
    """
    zona_seleccionada = request.GET.get('zona') or ''
    if zona_seleccionada not in ZONAS_VALIDAS:
        zona_seleccionada = ''

    todos_vigentes = repository.listar_disponibles_con_cupo(zona=None)

    ids_paseador_por_zona = {}
    for p in todos_vigentes:
        for z in p.get('zonas', []):
            ids_paseador_por_zona.setdefault(z, set()).add(p['id_paseador'])

    opciones_zona = [
        {
            'valor': nombre,
            'etiqueta': etiqueta_zona(nombre),
            'conteo': len(ids_paseador_por_zona.get(nombre, ())),
        }
        for _, nombre in ZONAS_VALIDAS_CON_NUMERO
    ]

    paseos = (
        [p for p in todos_vigentes if zona_seleccionada in p.get('zonas', [])]
        if zona_seleccionada else todos_vigentes
    )
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
            # Si hay un filtro activo, esto cuenta los horarios que
            # califican para esa zona, no el total del paseador - es lo
            # relevante para quien esta filtrando por zona.
            'cantidad_horarios': len(horarios),
            # Zonas de TODOS los horarios vigentes de este paseador (los
            # que estan en `horarios`, no el perfil entero) - union sin
            # duplicados, ordenada por numero de comuna, para mostrar
            # como tags en la tarjeta (punto G).
            'zonas': sorted(
                {z for h in horarios for z in h.get('zonas', [])},
                key=lambda z: repository.numero_de_zona(z) or 0,
            ),
        }
        # El orden de horarios_por_paseador sigue el de `paseos` (mas
        # reciente primero), asi que esto ya queda ordenado por el
        # horario publicado mas recientemente de cada paseador.
        for id_paseador, horarios in horarios_por_paseador.items()
    ]
    return render(request, 'paseos/lista_disponibles.html', {
        'items': items,
        'opciones_zona': opciones_zona,
        'zona_seleccionada': zona_seleccionada,
        'zona_seleccionada_etiqueta': etiqueta_zona(zona_seleccionada) if zona_seleccionada else '',
        'cantidad_resultado': len(items),
    })


@requiere_dueno
def detalle_paseador(request, id_paseador):
    paseador = usuarios_repository.obtener_por_id(id_paseador)
    if not paseador or paseador.get('rol') != 'paseador':
        messages.error(request, 'Este paseador no existe.')
        return redirect('paseos:lista_disponibles')

    oid_paseador = ObjectId(id_paseador)
    # ahora_utc: mismo filtro de fecha que listar_disponibles_con_cupo()
    # (hallazgo del 9 oct) pero aca, no dentro de listar_disponibles_de_paseador() -
    # esa función también la usa el dashboard del PROPIO paseador
    # (bienvenida_paseador), donde SI quiere seguir viendo (para
    # "Despublicar") un horario vencido que nunca inicio; filtrarlo ahi
    # habria escondido esa tarjeta de su propio dueño. Aca, del lado del
    # dueño que esta buscando a quien contratar, un horario vencido nunca
    # debe ofrecerse - mismo criterio, filtro en el lugar que corresponde.
    ahora_utc = datetime.now(dt_timezone.utc).replace(tzinfo=None)
    horarios = [
        _marcar_utc(h)
        for h in repository.listar_disponibles_de_paseador(oid_paseador)
        # "Tiene cupo" (ver CLAUDE.md, "Corrección de alcance 2026-09-25"):
        # ya no es "esta vacio" - un horario con 3/8 mascotas de OTRO dueño
        # sigue apareciendo aca, mientras el paseador no lo haya cerrado y
        # no haya llegado al maximo.
        if h.get('acepta_inscripciones', True) and len(h.get('id_mascotas', [])) < MAXIMO_MASCOTAS_POR_PASEO
        and h.get('horario_hasta') and h['horario_hasta'] >= ahora_utc
        # Incremento 4 fase 3, punto A7 - "si la franja dura menos de 30
        # minutos, no se puede inscribir": sin ninguna duración acordada
        # que ofrecer, no tiene sentido mostrar el horario para inscribir
        # en absoluto (sería pedirle elegir entre cero opciones).
        and repository.duraciones_acordadas_disponibles(h['horario_desde'], h['horario_hasta'])
    ]
    if not horarios:
        messages.error(request, 'Este paseador no tiene horarios disponibles en este momento.')
        return redirect('paseos:lista_disponibles')

    mis_mascotas = mascotas_repository.listar_por_dueno(request.session['id_usuario'])
    tiene_mascotas = bool(mis_mascotas)

    # Incremento 4 fase 3, punto A1 - prellena el formulario de
    # inscripción con la última recogida de este dueño; la primera vez
    # (sin `ultima_recogida` todavía) cae a `direccion`/`telefono` del
    # propio perfil, que ya existen (`direccion` es opcional en el
    # registro del dueño - puede venir vacía).
    usuario_dueno = usuarios_repository.obtener_por_id(request.session['id_usuario'])
    ultima_recogida = usuario_dueno.get('ultima_recogida') if usuario_dueno else None
    if ultima_recogida:
        initial_recogida = ultima_recogida
    else:
        initial_recogida = {
            'direccion': (usuario_dueno or {}).get('direccion', ''),
            'telefono': (usuario_dueno or {}).get('telefono', ''),
        }

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
            'form': InscribirMascotaForm(
                mascotas=mis_mascotas, prefix=id_paseo, initial=initial_recogida,
                # Punto A7 - solo las duraciones que caben en ESTE
                # horario puntual (ya se filtró arriba que hay al menos
                # una, pero se recalcula acá porque el form necesita las
                # choices exactas, no solo saber que existen).
                duraciones_disponibles=repository.duraciones_acordadas_disponibles(
                    h['horario_desde'], h['horario_hasta'],
                ),
            ),
        })

    certificados_paseador = paseador.get('certificados', [])
    # RF14: fecha de la ultima revision (naive UTC desde Mongo - mismo
    # cuidado de siempre antes de pasarla a |date, ver CLAUDE.md).
    fecha_verificacion_cruda = (paseador.get('verificacion') or {}).get('fecha')
    fecha_verificacion = fecha_verificacion_cruda.replace(tzinfo=dt_timezone.utc) if fecha_verificacion_cruda else None
    return render(request, 'paseos/detalle_paseador.html', {
        'id_paseador': id_paseador,
        'paseador': paseador,
        'horarios': items_horario,
        'tiene_mascotas': tiene_mascotas,
        'resenas': resenas,
        'certificados_paseador': certificados_paseador,
        'fecha_verificacion': fecha_verificacion,
        'tiene_primeros_auxilios': any(c['tipo'] == TIPO_PRIMEROS_AUXILIOS for c in certificados_paseador),
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
    # Punto A7 - MISMAS duraciones disponibles que detalle_paseador() le
    # ofreció a este horario puntual; sin esto, el ChoiceField no tendría
    # ninguna choice válida y rechazaría CUALQUIER valor enviado, no solo
    # uno forjado - la validación real (que un POST manual con una
    # duración fuera de la franja se rechace) depende de recalcular esto
    # acá, no solo de confiar en lo que mandó el formulario.
    form = InscribirMascotaForm(
        request.POST, mascotas=mis_mascotas, prefix=id_paseo,
        duraciones_disponibles=repository.duraciones_acordadas_disponibles(
            paseo['horario_desde'], paseo['horario_hasta'],
        ),
    )
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
        direccion=form.cleaned_data['direccion'],
        comuna=form.cleaned_data['comuna'],
        indicaciones=form.cleaned_data['indicaciones'],
        telefono=form.cleaned_data['telefono'],
        duracion_acordada_min=form.cleaned_data['duracion_acordada_min'],
    )
    if not asignado:
        messages.error(request, 'Este horario ya no está disponible.')
        return redirect('paseos:detalle_paseador', id_paseador=id_paseador)

    # Incremento 4 fase 3, punto A1 - prellena la PRÓXIMA inscripción de
    # este dueño con estos mismos datos de recogida.
    usuarios_repository.guardar_ultima_recogida(
        request.session['id_usuario'],
        direccion=form.cleaned_data['direccion'],
        comuna=form.cleaned_data['comuna'],
        indicaciones=form.cleaned_data['indicaciones'],
        telefono=form.cleaned_data['telefono'],
    )

    paseador = usuarios_repository.obtener_por_id(id_paseador)
    nombres = mascotas_repository.nombres_unidos(mascotas_elegidas)
    messages.success(
        request,
        f'Inscribiste a {nombres} con {paseador["nombre"] if paseador else "el paseador"}.',
    )
    return redirect('paseos:mis_paseos')


def _items_mis_paseos(id_dueno):
    """
    Factorizado de mis_paseos() para que estado_mis_paseos() (sondeo cada
    10s desde mis_paseos.html, ver RNF2) calcule exactamente lo mismo que
    la carga completa - mismo patron que _paseo_activo_dueno() o
    _horarios_disponibles_paseador().
    """
    paseos = repository.listar_activos_por_dueno(id_dueno)
    paseadores_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_paseador'] for p in paseos]
    )
    # SOLO las mascotas propias de este dueño (nunca obtener_varias_por_id
    # con id_mascotas completo) - un paseo puede tener mascotas de OTROS
    # dueños tambien (hasta 8, Ley Kiara). resolver_lista() ya se encarga
    # de quedarse solo con los ids presentes en este mapa, en el orden
    # original - ver CLAUDE.md, "Corrección de alcance 2026-09-25".
    mis_mascotas_por_id = {m['_id']: m for m in mascotas_repository.listar_por_dueno(id_dueno)}
    # Sin "calificado"/ids_calificados aca: esta pantalla ya no muestra
    # NUNCA paseos 'historico' (los unicos que se pueden calificar), asi
    # que esa pregunta dejo de aplicar - vive en historial().
    return [
        {
            'id_paseo': str(p['_id']),
            'paseo': p,
            'paseador': paseadores_por_id.get(p['id_paseador']),
            'mascotas_nombres': mascotas_repository.nombres_unidos(
                mascotas_repository.resolver_lista(p.get('id_mascotas'), mis_mascotas_por_id)
            ),
        }
        for p in paseos
    ]


@requiere_dueno
def mis_paseos(request):
    """
    "Paseos activos" (antes "Mis paseos" - ver reporte de hallazgos,
    punto (d)): SOLO 'disponible'/'en_vivo' (repository.
    listar_activos_por_dueno). Lo ya terminado vive en historial() - cada
    paseo aparece en una sola de las dos pantallas, nunca en ambas.
    """
    items = _items_mis_paseos(request.session['id_usuario'])
    return render(request, 'paseos/mis_paseos.html', {'items': items})


@requiere_dueno
def estado_mis_paseos(request):
    """
    Sondeo de "Paseos activos" cada 10s (RNF2: actualizar el estado del
    paseo en intervalos <=10s) - devuelve el fragmento ya renderizado
    (no JSON con los datos sueltos), mismo motivo que
    estado_bienvenida_paseador(): la lista cambia de estructura (badge,
    boton "Ver mapa") según el estado, no solo de texto suelto, asi que
    es mas simple y consistente re-renderizar la misma plantilla que ya
    usa la carga completa.
    """
    items = _items_mis_paseos(request.session['id_usuario'])
    html = render_to_string('paseos/_lista_paseos_activos.html', {'items': items}, request=request)
    return JsonResponse({'html': html})


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
        # Incremento 4 fase 3, puntos A4/A7 - el historial del DUEÑO
        # mostraba la duración y la distancia del PASEO COMPLETO, nunca
        # filtradas por su propio tramo (mismo problema de A3/A9, acá en
        # la lista en vez del mapa). Con una entrada de recogida propia,
        # se usa SOLO ese tramo (hora_recogida/hora_entrega); un paseo
        # sin `recogidas` (de antes de esta fase) sigue mostrando el
        # paseo completo, por compatibilidad.
        entrada_recogida = next(
            (r for r in p.get('recogidas', []) if r['id_dueno'] == oid_dueno), None,
        )
        if entrada_recogida:
            hora_recogida = entrada_recogida.get('hora_recogida')
            hora_entrega = entrada_recogida.get('hora_entrega')
            duracion_min = (
                int((hora_entrega - hora_recogida).total_seconds() // 60)
                if hora_recogida and hora_entrega else None
            )
            distancia_texto = coordenadas_repository.formatear_distancia(
                coordenadas_repository.distancia_recorrida_m(p['_id'], desde=hora_recogida, hasta=hora_entrega)
            ) if hora_recogida else None
            duracion_acordada_etiqueta = repository.etiqueta_duracion_acordada(
                entrada_recogida.get('duracion_acordada_min')
            )
        else:
            duracion_min = None
            if p.get('hora_inicio') and p.get('hora_fin'):
                duracion_min = int((p['hora_fin'] - p['hora_inicio']).total_seconds() // 60)
            distancia_texto = _distancia_texto_de_paseo(p)
            duracion_acordada_etiqueta = None

        calificacion = calificaciones_por_paseo.get(p['_id'])
        mascotas_paseo = mascotas_repository.resolver_lista(p.get('id_mascotas'), mis_mascotas_por_id)
        items.append({
            'id_paseo': str(p['_id']),
            'paseo': p,
            'paseador': paseadores_por_id.get(p.get('id_paseador')),
            'mascota_avatar': mascotas_paseo[0] if mascotas_paseo else None,
            'mascotas_nombres': mascotas_repository.nombres_unidos(mascotas_paseo),
            'duracion_min': duracion_min,
            'duracion_real_texto': repository.formatear_duracion_real(duracion_min),
            'duracion_acordada_etiqueta': duracion_acordada_etiqueta,
            'puntuacion': calificacion['puntuacion'] if calificacion else None,
            'distancia_texto': distancia_texto,
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
        zonas=form.cleaned_data['zonas'],
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
    """
    Pasa un paseo propio de 'disponible' a 'en_vivo'.

    Incremento 4 fase 3, punto A2 - YA NO notifica a los dueños aquí
    (antes mandaba "inició el paseo de tu mascota" a TODOS los dueños
    del paseo al mismo tiempo). Con la recogida por mascota, "empezar el
    paseo" (el paseador sale a buscar a la primera mascota) ya no es lo
    mismo que "tu mascota está siendo paseada" - esa notificación
    (mismo tipo `inicio_paseo`) ahora se manda individualmente, SOLO a
    cada dueño, en el momento real de su propia recogida (ver
    marcar_recogida() más abajo).
    """
    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = repository.iniciar_paseo(id_paseo=id_paseo, id_paseador=id_paseador)
    if not paseo:
        messages.error(
            request,
            'No se pudo iniciar el paseo: ya no está disponible, no tiene mascota inscrita, '
            'o ya tienes otro paseo en curso.',
        )
    else:
        # Incremento 4, fase 2, "pantalla encendida": en iPhone (y en
        # general, cualquier navegador) Safari/las apps de pantalla de
        # inicio suspenden JS cuando la pantalla se bloquea o la app
        # pasa a segundo plano - el envío de GPS se corta ahí, el
        # wakeLock de base.html lo mitiga pero no lo garantiza (el
        # paseador igual puede apagarla a mano, o el SO puede liberar el
        # bloqueo). Aviso UNA vez, al momento de iniciar - no un banner
        # persistente, que ya se probó y se quitó (commit 05af336 lo
        # agregó, D1 lo quitó al volver el envío global - ver
        # MANUAL_DESARROLLADOR.md).
        messages.info(
            request,
            'Mantén Canigo abierto y la pantalla encendida: si bloqueas el celular, '
            'el dueño deja de ver tu ubicación.',
        )
    return redirect('usuarios:bienvenida_paseador')


@require_POST
@requiere_paseador
def finalizar_paseo(request, id_paseo):
    """
    Pasa un paseo propio de 'en_vivo' a 'historico'.

    Incremento 4 fase 3, punto A2, punto 5 - solo si ninguna recogida
    sigue 'pendiente'/'recogida' (repository.finalizar_paseo() lo
    exige de forma atómica, es la defensa real). El chequeo de ACÁ es
    solo para dar un mensaje de error específico en vez del genérico
    "ya no estaba en curso" - sin esto, un paseador que todavía tiene
    una recogida pendiente no entendería por qué el botón no hizo nada.

    Punto A2 tampoco pide notificar aquí - "Entregado" (marcar_entrega)
    ya notifica a cada dueño con `fin_paseo` en su propio momento; antes
    esta vista mandaba esa misma notificación a TODOS los dueños de
    nuevo al finalizar, duplicándola.
    """
    id_paseador = ObjectId(request.session['id_usuario'])
    paseo_actual = repository.obtener_por_id(id_paseo)
    if paseo_actual and str(paseo_actual.get('id_paseador')) == request.session['id_usuario']:
        pendientes = [
            r for r in paseo_actual.get('recogidas', [])
            if r['estado'] in ('pendiente', 'recogida')
        ]
        if pendientes:
            messages.error(
                request,
                'No se puede finalizar: todavía hay recogidas pendientes de entregar.',
            )
            return redirect('usuarios:bienvenida_paseador')

    paseo = repository.finalizar_paseo(id_paseo=id_paseo, id_paseador=id_paseador)
    if not paseo:
        messages.error(request, 'No se pudo finalizar el paseo: ya no estaba en curso.')
    else:
        # Ajustes del 19 de octubre, punto 1 - se calcula y se guarda UNA
        # sola vez aca, para que el historial no tenga que recorrer todo
        # coordenadas_detalle de este paseo cada vez que se consulta.
        distancia_m = coordenadas_repository.distancia_recorrida_m(paseo['_id'])
        repository.guardar_distancia(paseo['_id'], distancia_m)
    return redirect('usuarios:bienvenida_paseador')


def _recogida_de_dueno(paseo, id_dueno):
    """Entrada de `paseo.recogidas` de ese dueño, o None - helper compartido
    por las 3 vistas de abajo para armar el mensaje/la notificación."""
    oid_dueno = ObjectId(id_dueno)
    return next((r for r in paseo.get('recogidas', []) if r['id_dueno'] == oid_dueno), None)


def _nombres_mascotas_de_recogida(paseo, id_dueno):
    """'Dobby, Luna' para la recogida de ESE dueño en este paseo, o
    'tu mascota' si no se pudo resolver ninguna - usado en los mensajes
    de notificación de marcar_recogida()/marcar_no_recogida()/
    marcar_entrega(), que son siempre sobre LAS mascotas de un dueño
    puntual, nunca las 8 del paseo entero."""
    entrada = _recogida_de_dueno(paseo, id_dueno)
    ids = entrada.get('id_mascotas', []) if entrada else []
    mascotas = mascotas_repository.resolver_lista(ids, mascotas_repository.obtener_varias_por_id(ids))
    return mascotas_repository.nombres_unidos(mascotas) or 'tu mascota'


@require_POST
@requiere_paseador
def marcar_recogida(request, id_paseo, id_dueno):
    """
    "Recogido" (Incremento 4 fase 3, punto A2) - notifica SOLO a ese
    dueño, con el tipo YA EXISTENTE `inicio_paseo` (no se crea un tipo
    nuevo - pedido explícito).
    """
    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = repository.marcar_recogida(id_paseo=id_paseo, id_paseador=id_paseador, id_dueno=id_dueno)
    if not paseo:
        messages.error(request, 'No se pudo marcar como recogida: revisa el estado actual.')
        return redirect('usuarios:bienvenida_paseador')

    nombres = _nombres_mascotas_de_recogida(paseo, id_dueno)
    notificaciones_repository.crear(
        id_usuario=id_dueno,
        tipo='inicio_paseo',
        mensaje=f'{request.session.get("nombre")} recogió a {nombres}.',
    )
    messages.success(request, 'Recogida registrada.')
    return redirect('usuarios:bienvenida_paseador')


@require_POST
@requiere_paseador
def marcar_no_recogida(request, id_paseo, id_dueno):
    """"No se pudo recoger" (Incremento 4 fase 3, punto A2) - motivo obligatorio."""
    id_paseador = ObjectId(request.session['id_usuario'])
    form = MotivoNoRecogidaForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Escribe un motivo (máximo 300 caracteres).')
        return redirect('usuarios:bienvenida_paseador')

    paseo = repository.marcar_no_recogida(
        id_paseo=id_paseo, id_paseador=id_paseador, id_dueno=id_dueno,
        motivo=form.cleaned_data['motivo'],
    )
    if not paseo:
        messages.error(request, 'No se pudo registrar: revisa el estado actual.')
        return redirect('usuarios:bienvenida_paseador')

    nombres = _nombres_mascotas_de_recogida(paseo, id_dueno)
    notificaciones_repository.crear(
        id_usuario=id_dueno,
        tipo='emergencia',
        mensaje=f'{request.session.get("nombre")} no pudo recoger a {nombres}: {form.cleaned_data["motivo"]}',
    )
    messages.success(request, 'Registrado - esas mascotas ya no hacen parte de este paseo.')
    return redirect('usuarios:bienvenida_paseador')


@require_POST
@requiere_paseador
def marcar_entrega(request, id_paseo, id_dueno):
    """
    "Entregado" (Incremento 4 fase 3, punto A2) - notifica SOLO a ese
    dueño, con el tipo YA EXISTENTE `fin_paseo`.
    """
    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = repository.marcar_entrega(id_paseo=id_paseo, id_paseador=id_paseador, id_dueno=id_dueno)
    if not paseo:
        messages.error(request, 'No se pudo marcar como entregada: revisa el estado actual.')
        return redirect('usuarios:bienvenida_paseador')

    nombres = _nombres_mascotas_de_recogida(paseo, id_dueno)
    notificaciones_repository.crear(
        id_usuario=id_dueno,
        tipo='fin_paseo',
        mensaje=f'{request.session.get("nombre")} entregó a {nombres}.',
    )
    messages.success(request, 'Entrega registrada.')
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

    Responde SIEMPRE en JSON (Incremento 4, punto D1): antes redirigia a
    "usuarios:bienvenida_paseador" - una recarga completa de pagina
    cortaria el emisor global de GPS (core/templates/base.html) a mitad
    de un POST. El modal "Subir foto" ahora manda por fetch+FormData,
    unico llamador real de esta vista.
    """
    if momento not in repository.MOMENTOS_FOTO_VALIDOS:
        return JsonResponse({'error': 'Momento de foto inválido.'}, status=400)

    form = SubirFotoPaseoForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({'error': 'No se pudo subir la foto: selecciona un archivo de imagen válido.'}, status=400)

    try:
        url = subir_imagen(form.cleaned_data['foto'], carpeta='paseos')
    except ErrorValidacionImagen as exc:
        # El archivo no pasa la validación (tamaño/formato/firma) - error
        # del usuario, no de Cloudinary (punto 3 del reporte de revisión
        # de fase 1).
        return JsonResponse({'error': f'No se pudo subir la foto: {exc}'}, status=400)
    except ErrorSubidaImagen as exc:
        return JsonResponse({'error': f'No se pudo subir la foto: {exc}'}, status=502)

    id_paseador = ObjectId(request.session['id_usuario'])
    paseo = repository.agregar_foto(id_paseo=id_paseo, id_paseador=id_paseador, momento=momento, url=url)
    if not paseo:
        return JsonResponse({
            'error': 'No se pudo registrar la foto: el paseo ya no está activo o ya subiste una foto de ese momento.',
        }, status=409)
    return JsonResponse({'ok': True, 'mensaje': f'Foto de {momento} guardada correctamente.'}, status=200)


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
            # None si el paseo tiene menos de 2 puntos GPS validos - ver
            # coordenadas.repository.distancia_recorrida_m()/
            # formatear_distancia().
            'distancia_texto': _distancia_texto_de_paseo(p),
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
