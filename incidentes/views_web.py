"""
Vistas web:
- Dueño: historial de incidentes de sus propios paseos (RF16).
- Paseador: botón de emergencia en su dashboard (RF12).
"""

from datetime import timezone

from bson import ObjectId
from bson.errors import InvalidId
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.geocoding import direccion_aproximada as geocodificar_direccion
from core.media import ErrorSubidaImagen, ErrorValidacionImagen, subir_imagen
from coordenadas import repository as coordenadas_repository
from incidentes import repository
from incidentes.forms import ReportarIncidenteForm
from mascotas import repository as mascotas_repository
from notificaciones import repository as notificaciones_repository
from paseos import repository as paseos_repository
from usuarios import repository as usuarios_repository
from usuarios.decorators import URL_DASHBOARD_POR_ROL, requiere_autenticacion, requiere_dueno, requiere_paseador


@requiere_dueno
def lista_incidentes(request):
    """
    Corrección de privacidad (12 oct): antes mostraba TODOS los
    incidentes de cualquier paseo donde este dueño tuviera una mascota,
    sin filtrar por cuál mascota afectaba cada uno - en un paseo
    multi-dueño (hasta 8 mascotas, Ley Kiara), el dueño D1 veía también
    el incidente de la mascota del dueño D2. Ahora filtra por
    repository.listar_visibles_para_dueno(): solo lo que afecta a una
    mascota PROPIA, o lo que no afecta a ninguna en particular
    ("accidente_paseador").
    """
    id_dueno = request.session['id_usuario']
    paseos = paseos_repository.listar_por_dueno(id_dueno)
    paseos_por_id = {p['_id']: p for p in paseos}

    ids_mascota_dueno = [m['_id'] for m in mascotas_repository.listar_por_dueno(id_dueno)]
    incidentes = repository.listar_visibles_para_dueno(list(paseos_por_id.keys()), ids_mascota_dueno)

    paseadores_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_paseador'] for p in paseos]
    )
    # La mascota afectada sale del propio incidente (id_mascota), no del
    # paseo (que puede llevar varias) - es None para "accidente_paseador".
    mascotas_por_id = mascotas_repository.obtener_varias_por_id(
        [i['id_mascota'] for i in incidentes if i.get('id_mascota')]
    )

    items = []
    for incidente in incidentes:
        # pymongo devuelve fecha_hora naive en UTC (ver core/mongo.py) -
        # mismo cuidado de siempre (ver CLAUDE.md) que ya aplicaba
        # detalle_incidente() para esta misma fecha, en la pantalla
        # individual - esta vista (el historial GLOBAL del dueño) se
        # había quedado sin marcarla, mostrando la hora 5 horas adelantada
        # (UTC interpretado como si ya fuera hora de Bogotá).
        if incidente.get('fecha_hora'):
            incidente['fecha_hora'] = incidente['fecha_hora'].replace(tzinfo=timezone.utc)
        paseo = paseos_por_id.get(incidente['id_paseo'])
        items.append({
            'incidente': incidente,
            # Stringificado aca (no "incidente._id" en la plantilla): Django
            # no permite acceder a atributos que empiezan con "_" desde un
            # template.
            'id_incidente': str(incidente['_id']),
            'paseador': paseadores_por_id.get(paseo['id_paseador']) if paseo else None,
            'mascota': mascotas_por_id.get(incidente.get('id_mascota')),
        })

    return render(request, 'incidentes/lista.html', {'items': items})


@requiere_paseador
def lista_incidentes_paseador(request):
    """
    RF16 (cierre de auditoría, punto 5) - equivalente de lista_incidentes()
    para el paseador: antes no existía ninguna pantalla para que el
    paseador consultara sus propios incidentes (ni link en el navbar, ni
    vista - RF16 pide "dueño Y paseador"). Reusa lista.html (mismo
    template, mismo shape de `items`) - a diferencia del dueño, el
    paseador ve TODOS los incidentes de sus paseos sin filtrar por
    mascota (repository.listar_por_paseos(), uso exclusivo del
    paseador - ver su propio docstring), porque se los llevó a todos él
    mismo.
    """
    id_paseador = request.session['id_usuario']
    paseos = paseos_repository.listar_por_paseador(ObjectId(id_paseador))
    paseos_por_id = {p['_id']: p for p in paseos}

    incidentes = repository.listar_por_paseos(list(paseos_por_id.keys()))

    paseador = usuarios_repository.obtener_por_id(id_paseador)
    mascotas_por_id = mascotas_repository.obtener_varias_por_id(
        [i['id_mascota'] for i in incidentes if i.get('id_mascota')]
    )

    # Mismo cuidado que lista_incidentes() (ver ese comentario) - esta
    # vista se escribió reusando esa misma lógica y se le había quedado
    # el mismo descuido.
    for incidente in incidentes:
        if incidente.get('fecha_hora'):
            incidente['fecha_hora'] = incidente['fecha_hora'].replace(tzinfo=timezone.utc)

    items = [
        {
            'incidente': incidente,
            'id_incidente': str(incidente['_id']),
            'paseador': paseador,
            'mascota': mascotas_por_id.get(incidente.get('id_mascota')),
        }
        for incidente in incidentes
    ]

    return render(request, 'incidentes/lista.html', {'items': items})


@require_POST
@requiere_paseador
def reportar_incidente(request, id_paseo):
    """
    Boton de emergencia del dashboard del paseador. Mismo flujo que el
    diagrama de secuencia del documento de grado: valida el paseo, sube
    la evidencia, inserta el incidente, notifica al dueño, marca
    paseos.emergencia. El paseo NO se finaliza automaticamente.

    Responde SIEMPRE en JSON (Incremento 4, punto D1): antes redirigia a
    "usuarios:bienvenida_paseador" (recarga completa de pagina), pero el
    modal ahora se manda por fetch+FormData para no cortar el emisor
    global de GPS de core/templates/base.html a mitad de un POST - una
    recarga completa reiniciaria ese script. Unico llamador real (el
    modal "Reportar emergencia"), asi que no hace falta una rama aparte
    para un POST tradicional sin JS.
    """
    paseo = paseos_repository.obtener_por_id(id_paseo)
    paseo_valido = (
        paseo
        and str(paseo.get('id_paseador')) == request.session.get('id_usuario')
        and paseo['estado'] == 'en_vivo'
    )
    if not paseo_valido:
        return JsonResponse({'error': 'No se pudo registrar el incidente: el paseo no está activo.'}, status=409)

    mascotas_por_id = mascotas_repository.obtener_varias_por_id(paseo.get('id_mascotas', []))
    mascotas_paseo = mascotas_repository.resolver_lista(paseo.get('id_mascotas'), mascotas_por_id)

    form = ReportarIncidenteForm(request.POST, request.FILES, mascotas=mascotas_paseo)
    if not form.is_valid():
        primer_error = next(iter(form.errors.values()))[0]
        return JsonResponse({'error': f'No se pudo registrar el incidente: {primer_error}'}, status=400)

    # A cual mascota afecta (ver CLAUDE.md): null solo para
    # "accidente_paseador"; con una sola mascota en el paseo se asigna
    # sola, sin pedirle nada al paseador; con varias, la elige el radio.
    if form.cleaned_data['tipo'] == 'accidente_paseador':
        id_mascota_incidente = None
    elif len(mascotas_paseo) == 1:
        id_mascota_incidente = mascotas_paseo[0]['_id']
    else:
        id_mascota_incidente = ObjectId(form.cleaned_data['id_mascota'])

    # Doble toque en "Enviar reporte" (punto 3) - el boton ya se
    # deshabilita del lado del JS mientras se envia, pero esto es la
    # defensa de fondo en el backend: si de todas formas llegan dos POST
    # identicos (red lenta, una segunda pestaña), el segundo NO crea un
    # incidente nuevo ni sube una segunda foto - responde como si hubiera
    # tenido exito, idéntico a lo que ya le respondió al primero, en vez
    # de un error confuso.
    duplicado = repository.obtener_duplicado_reciente(
        id_paseo=paseo['_id'],
        tipo=form.cleaned_data['tipo'],
        id_mascota=id_mascota_incidente,
        descripcion=form.cleaned_data['descripcion'],
    )
    if duplicado:
        return JsonResponse({'ok': True, 'mensaje': 'El incidente quedó registrado. El dueño ya fue notificado.'}, status=201)

    try:
        evidencia_url = subir_imagen(form.cleaned_data['foto'], carpeta='incidentes')
    except ErrorValidacionImagen as exc:
        # El archivo no pasa la validación (tamaño/formato/firma) - error
        # del usuario, no de Cloudinary (punto 3 del reporte de revisión
        # de fase 1).
        return JsonResponse({'error': f'No se pudo subir la foto de evidencia: {exc}'}, status=400)
    except ErrorSubidaImagen as exc:
        return JsonResponse({'error': f'No se pudo subir la foto de evidencia: {exc}'}, status=502)

    # Ubicacion: la ultima capturada por el tracking del Paso 4. Si el
    # incidente ocurre antes del primer punto GPS (muy al inicio del
    # paseo), se guarda sin coordenadas en vez de bloquear el reporte -
    # que quede registrado importa mas que tener la ubicacion exacta.
    ultimo_punto = coordenadas_repository.obtener_ultimo_punto(paseo['_id'])
    latitud = ultimo_punto['latitud'] if ultimo_punto else None
    longitud = ultimo_punto['longitud'] if ultimo_punto else None

    # Direccion aproximada (Incremento 4, punto C) - geocodificacion
    # inversa via Nominatim, SOLO si hay coordenadas. Nunca bloquea el
    # reporte: None si falla, tarda mas de 5s, o no hay ubicacion (ver
    # core/geocoding.py).
    direccion = geocodificar_direccion(latitud, longitud) if latitud is not None and longitud is not None else None

    incidente = repository.crear(
        id_paseo=paseo['_id'],
        tipo=form.cleaned_data['tipo'],
        id_mascota=id_mascota_incidente,
        descripcion=form.cleaned_data['descripcion'],
        evidencia_foto=evidencia_url,
        latitud=latitud,
        longitud=longitud,
        direccion_aproximada=direccion,
    )

    paseos_repository.marcar_emergencia(paseo['_id'])

    # Corrección de privacidad (12 oct): antes se notificaba a TODOS los
    # id_duenos del paseo sin importar a cual mascota afectaba el
    # incidente - en un paseo multi-dueño (hasta 8 mascotas, Ley Kiara),
    # el dueño de una mascota AJENA recibía la alerta de emergencia de
    # otra. Ahora: si el incidente afecta a una mascota concreta
    # (id_mascota_incidente no es None), SOLO se notifica al dueño de
    # ESA mascota. Solo "accidente_paseador" (id_mascota=None, no
    # involucra a ningun animal en particular - ver CLAUDE.md) sigue
    # notificando a TODOS los dueños del paseo, porque los afecta a
    # todos por igual (el paseador tuvo un accidente llevando a todas
    # las mascotas juntas).
    if id_mascota_incidente is None:
        ids_duenos_a_notificar = paseo.get('id_duenos', [])
    else:
        mascota_afectada = mascotas_por_id.get(id_mascota_incidente)
        ids_duenos_a_notificar = [mascota_afectada['id_dueno']] if mascota_afectada else []

    for id_dueno in ids_duenos_a_notificar:
        notificaciones_repository.crear(
            id_usuario=id_dueno,
            tipo='emergencia',
            mensaje=(
                f'{request.session.get("nombre")} reportó un incidente '
                f'({repository.etiqueta_tipo_incidente(form.cleaned_data["tipo"])}) durante el paseo.'
            ),
        )
    if ids_duenos_a_notificar:
        repository.marcar_notificado(incidente['_id'])

    return JsonResponse({'ok': True, 'mensaje': 'El incidente quedó registrado. El dueño ya fue notificado.'}, status=201)


def _incidente_accesible_o_none(request, id_incidente):
    """
    El incidente y su paseo, solo si quien esta en sesion tiene un
    motivo real para verlo (Incremento 4, punto C) - MISMO criterio de
    privacidad que listar_visibles_para_dueno()/_texto_incidente()
    (corrección del 12 oct, ver CLAUDE.md):

    - paseador: solo si ES el paseador asignado al paseo de ese
      incidente - ve cualquier incidente de sus propios paseos, sin
      restricción por mascota (se los está llevando a todos juntos).
    - dueño: solo si es uno de los id_duenos del paseo Y, ademas, el
      incidente afecta a UNA DE SUS PROPIAS mascotas - o no afecta a
      ninguna mascota en particular ("accidente_paseador", visible para
      todos los dueños del paseo por igual).

    (None, None) para cualquier otro caso - nunca se revela que el
    incidente existe.
    """
    incidente = repository.obtener_por_id(id_incidente)
    if not incidente:
        return None, None
    paseo = paseos_repository.obtener_por_id(incidente['id_paseo'])
    if not paseo:
        return None, None
    try:
        oid_usuario = ObjectId(request.session.get('id_usuario'))
    except (InvalidId, TypeError):
        return None, None

    rol = request.session.get('rol')
    if rol == 'paseador':
        return (incidente, paseo) if paseo.get('id_paseador') == oid_usuario else (None, None)
    if rol == 'dueño':
        if oid_usuario not in paseo.get('id_duenos', []):
            return None, None
        if incidente.get('id_mascota') is None:
            return incidente, paseo
        mascota_propia = mascotas_repository.obtener_varias_por_id_y_dueno(
            [incidente['id_mascota']], oid_usuario
        )
        return (incidente, paseo) if mascota_propia else (None, None)
    return None, None


@requiere_autenticacion
def detalle_incidente(request, id_incidente):
    """
    Detalle de un incidente puntual (Incremento 4, punto C): tipo,
    descripción, foto, fecha y hora, dirección aproximada (o
    coordenadas si no hay), mapa de Leaflet con un marcador en el punto,
    y el teléfono del paseador SOLO mientras el paseo sigue activo
    (mismo criterio del punto B - oculto en historial).
    """
    incidente, paseo = _incidente_accesible_o_none(request, id_incidente)
    if not incidente:
        messages.error(request, 'No tienes acceso a ese incidente.')
        rol_sesion = request.session.get('rol')
        return redirect(URL_DASHBOARD_POR_ROL.get(rol_sesion, 'usuarios:login'))

    mascota = None
    if incidente.get('id_mascota'):
        mascota = mascotas_repository.obtener_varias_por_id([incidente['id_mascota']]).get(incidente['id_mascota'])

    paseador = usuarios_repository.obtener_por_id(paseo['id_paseador']) if paseo.get('id_paseador') else None

    # pymongo devuelve datetimes naive en UTC - hay que marcarlos antes
    # de que la plantilla use "|date"/"|time" (que asumen un datetime
    # "aware" para convertir a la zona local, America/Bogota) - mismo
    # patrón que notificaciones/views.py y usuarios/views_web.py.
    if incidente.get('fecha_hora'):
        incidente['fecha_hora'] = incidente['fecha_hora'].replace(tzinfo=timezone.utc)

    return render(request, 'incidentes/detalle.html', {
        'incidente': incidente,
        'id_incidente': str(incidente['_id']),
        'mascota': mascota,
        'paseador': paseador,
        # Teléfono visible solo mientras el paseo está activo (punto B,
        # mismo criterio que el resto de la plataforma) - oculto si ya
        # es "historico".
        'mostrar_telefono_paseador': paseo['estado'] in ('disponible', 'en_vivo'),
    })
