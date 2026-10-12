"""
Vistas web:
- Dueño: historial de incidentes de sus propios paseos (RF16).
- Paseador: botón de emergencia en su dashboard (RF12).
"""

from bson import ObjectId
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.media import ErrorSubidaImagen, subir_imagen
from coordenadas import repository as coordenadas_repository
from incidentes import repository
from incidentes.forms import ReportarIncidenteForm
from mascotas import repository as mascotas_repository
from notificaciones import repository as notificaciones_repository
from paseos import repository as paseos_repository
from usuarios import repository as usuarios_repository
from usuarios.decorators import requiere_dueno, requiere_paseador


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
        paseo = paseos_por_id.get(incidente['id_paseo'])
        items.append({
            'incidente': incidente,
            'paseador': paseadores_por_id.get(paseo['id_paseador']) if paseo else None,
            'mascota': mascotas_por_id.get(incidente.get('id_mascota')),
        })

    return render(request, 'incidentes/lista.html', {'items': items})


@require_POST
@requiere_paseador
def reportar_incidente(request, id_paseo):
    """
    Boton de emergencia del dashboard del paseador. Mismo flujo que el
    diagrama de secuencia del documento de grado: valida el paseo, sube
    la evidencia, inserta el incidente, notifica al dueño, marca
    paseos.emergencia. El paseo NO se finaliza automaticamente.
    """
    paseo = paseos_repository.obtener_por_id(id_paseo)
    paseo_valido = (
        paseo
        and str(paseo.get('id_paseador')) == request.session.get('id_usuario')
        and paseo['estado'] == 'en_vivo'
    )
    if not paseo_valido:
        messages.error(request, 'No se pudo registrar el incidente: el paseo no está activo.')
        return redirect('usuarios:bienvenida_paseador')

    mascotas_por_id = mascotas_repository.obtener_varias_por_id(paseo.get('id_mascotas', []))
    mascotas_paseo = mascotas_repository.resolver_lista(paseo.get('id_mascotas'), mascotas_por_id)

    form = ReportarIncidenteForm(request.POST, request.FILES, mascotas=mascotas_paseo)
    if not form.is_valid():
        # El boton de emergencia abre un modal simple (ver
        # bienvenida_paseador.html): no hay donde volver a mostrar el
        # formulario con sus errores sin duplicar esa pantalla, asi que el
        # primer error se muestra como mensaje y se vuelve al dashboard.
        primer_error = next(iter(form.errors.values()))[0]
        messages.error(request, f'No se pudo registrar el incidente: {primer_error}')
        return redirect('usuarios:bienvenida_paseador')

    # A cual mascota afecta (ver CLAUDE.md): null solo para
    # "accidente_paseador"; con una sola mascota en el paseo se asigna
    # sola, sin pedirle nada al paseador; con varias, la elige el radio.
    if form.cleaned_data['tipo'] == 'accidente_paseador':
        id_mascota_incidente = None
    elif len(mascotas_paseo) == 1:
        id_mascota_incidente = mascotas_paseo[0]['_id']
    else:
        id_mascota_incidente = ObjectId(form.cleaned_data['id_mascota'])

    try:
        evidencia_url = subir_imagen(form.cleaned_data['foto'], carpeta='incidentes')
    except ErrorSubidaImagen as exc:
        messages.error(request, f'No se pudo subir la foto de evidencia: {exc}')
        return redirect('usuarios:bienvenida_paseador')

    # Ubicacion: la ultima capturada por el tracking del Paso 4. Si el
    # incidente ocurre antes del primer punto GPS (muy al inicio del
    # paseo), se guarda sin coordenadas en vez de bloquear el reporte -
    # que quede registrado importa mas que tener la ubicacion exacta.
    ultimo_punto = coordenadas_repository.obtener_ultimo_punto(paseo['_id'])
    latitud = ultimo_punto['latitud'] if ultimo_punto else None
    longitud = ultimo_punto['longitud'] if ultimo_punto else None

    incidente = repository.crear(
        id_paseo=paseo['_id'],
        tipo=form.cleaned_data['tipo'],
        id_mascota=id_mascota_incidente,
        descripcion=form.cleaned_data['descripcion'],
        evidencia_foto=evidencia_url,
        latitud=latitud,
        longitud=longitud,
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
                f'({form.cleaned_data["tipo"]}) durante el paseo.'
            ),
        )
    if ids_duenos_a_notificar:
        repository.marcar_notificado(incidente['_id'])

    messages.success(request, 'El incidente quedó registrado. El dueño ya fue notificado.')
    return redirect('usuarios:bienvenida_paseador')
