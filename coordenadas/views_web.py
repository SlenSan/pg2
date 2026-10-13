"""
Vistas web:
- Dueño: pagina del mapa en vivo/historico y el endpoint JSON que
  consume el JavaScript de Leaflet para pintar la ruta.
- Paseador: endpoint que su navegador llama (via navigator.geolocation)
  cada 10s mientras el paseo esta "en_vivo", autenticado por sesion (no
  por token - la app Android ya no existe, ver CLAUDE.md).
"""

import json
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from calificaciones import repository as calificaciones_repository
from coordenadas import repository
from incidentes import repository as incidentes_repository
from mascotas import repository as mascotas_repository
from notificaciones import repository as notificaciones_repository
from paseos import repository as paseos_repository
from usuarios import repository as usuarios_repository
from usuarios.decorators import URL_DASHBOARD_POR_ROL, requiere_autenticacion, requiere_paseador


def _hay_notificaciones_sin_leer(request, id_usuario):
    """
    Mismo mecanismo de "vista hasta" en sesion que usuarios/views_web.py -
    duplicada aca (no importada de ahi) para no crear una dependencia
    cruzada entre esas dos apps por una funcion de 3 lineas; ambas llaman
    al mismo notificaciones_repository.hay_no_leidas().
    """
    ultima_vista_str = request.session.get('notificaciones_vistas_hasta')
    ultima_vista = datetime.fromisoformat(ultima_vista_str) if ultima_vista_str else None
    return notificaciones_repository.hay_no_leidas(id_usuario, ultima_vista)

_TEXTO_INCIDENTE_GENERICO = 'Se reportó un incidente durante este paseo.'


def _info_incidente_reciente(id_paseo, ids_mascota_viewer=None):
    """
    Texto e id del incidente MAS RECIENTE de este paseo que el que mira
    el mapa puede ver, o None si no hay ninguno que mostrar. El resultado
    de esta funcion es la UNICA fuente de verdad de si el banner se
    muestra - antes se llamaba solo cuando paseo.emergencia era truthy,
    pero si por algun motivo ese campo quedaba en True sin un documento
    real en `incidentes` (desincronia de datos), esta funcion igual
    devolvia el texto generico: se veia un banner "fantasma" sin nada
    detras. Ahora, sin incidentes reales, devuelve None sin importar lo
    que diga paseo.emergencia - "existe un documento real" es una
    condicion, no una opcional.

    Muestra a que mascota afecto el incidente MAS RECIENTE de este paseo
    (si tiene una asignada - ver CLAUDE.md, "accidente_paseador" no
    aplica a ningun animal en particular), o el mensaje generico si no.
    Reusado tanto en la carga inicial de la pagina como en el polling
    (coordenadas_de_paseo), para que el texto se actualice solo si llega
    un incidente nuevo mientras el dueño ya esta mirando el mapa. El id
    (Incremento 4, punto C) deja que el banner enlace directamente al
    detalle de ESE incidente (incidentes:detalle_incidente), para los
    dos roles - antes el link de "Ver detalles" solo existia para el
    dueño y llevaba a la lista genérica, no a este incidente puntual.

    `ids_mascota_viewer`: None (paseador, ve todos los incidentes del
    paseo sin restriccion) o una lista de ObjectId (dueño - solo SUS
    propias mascotas). Corrección de privacidad (12 oct): antes mostraba
    el incidente mas reciente del paseo ENTERO sin importar quien lo
    miraba - un dueño en un paseo multi-dueño se enteraba, por el
    nombre en el banner, de un incidente que afectaba a la mascota de
    OTRO dueño. Ahora, para un dueño, se usa el mismo filtro que
    incidentes.repository.listar_visibles_para_dueno() (su mascota, o
    "accidente_paseador" que afecta a todas) - si el incidente mas
    reciente del paseo no es visible para el, el banner no aparece en
    absoluto (ni el texto generico): que ocurrió un incidente ajeno no
    es un dato que deba filtrarse, ni como mensaje vago.
    """
    if ids_mascota_viewer is None:
        incidentes = incidentes_repository.listar_por_paseo(id_paseo)
    else:
        incidentes = incidentes_repository.listar_visibles_para_dueno([id_paseo], ids_mascota_viewer)
    if not incidentes:
        return None
    ultimo = incidentes[0]  # ya viene ordenado por fecha_hora desc
    texto = _TEXTO_INCIDENTE_GENERICO
    if ultimo.get('id_mascota'):
        mascota = mascotas_repository.obtener_varias_por_id([ultimo['id_mascota']]).get(ultimo['id_mascota'])
        if mascota:
            texto = f'Se reportó un incidente que afecta a {mascota["nombre"]}.'
    return {'texto': texto, 'id': str(ultimo['_id'])}


def _pendiente_calificar(paseo, id_dueno):
    """
    True si este paseo ya termino y ESTE dueño (uno de posiblemente
    varios en el mismo paseo - ver CLAUDE.md, "Corrección de alcance
    2026-09-25") TODAVIA no lo califico. Independiente de si otro dueño
    del mismo paseo ya calificó - cada uno tiene su propia calificación
    (indice unico compuesto id_paseo+id_dueno, ver calificaciones/
    repository.py). Sirve tanto para la carga inicial del mapa como para
    el polling, para que el aviso "El paseo finalizó, califícalo ahora"
    aparezca solo cuando corresponde, en los dos casos que pidio el
    dueño (pagina ya abierta cuando el paseador termina, o entrando
    despues a un paseo recien terminado).
    """
    if paseo['estado'] != 'historico':
        return False
    return calificaciones_repository.obtener_por_paseo_y_dueno(paseo['_id'], id_dueno) is None


def _paseo_accesible_o_none(request, id_paseo):
    """
    El paseo, solo si quien esta en sesion tiene un motivo real para
    verlo - el mapa de seguimiento ahora es compartido por los dos roles
    (antes era @requiere_dueno a secas, bloqueando al paseador por
    completo incluso para sus propios paseos - ver el reporte de
    hallazgos, punto (c)):

    - paseador: solo si ES el paseador asignado a este paseo
      (paseo.id_paseador).
    - dueño: solo si es UNO de los (posiblemente varios) dueños que
      tienen mascotas inscritas ahi (paseo.id_duenos) - un paseo puede
      ser multi-dueño, ver CLAUDE.md "Corrección de alcance 2026-09-25".
      Esto YA estaba bien antes de este cambio (se verifica membresia en
      el array, no "cualquier dueño autenticado") - se mantiene igual,
      solo se le agrega la rama del paseador al lado.

    Cualquier otra combinacion (rol desconocido, no pertenece al paseo)
    devuelve None - nunca se muestra el paseo sin un motivo valido.
    """
    paseo = paseos_repository.obtener_por_id(id_paseo)
    if not paseo:
        return None
    try:
        oid_usuario = ObjectId(request.session.get('id_usuario'))
    except (InvalidId, TypeError):
        return None

    rol = request.session.get('rol')
    if rol == 'paseador':
        return paseo if paseo.get('id_paseador') == oid_usuario else None
    if rol == 'dueño':
        return paseo if oid_usuario in paseo.get('id_duenos', []) else None
    return None


def _mascotas_del_dueno_en_paseo(paseo, id_dueno):
    """
    SOLO las mascotas de ESTE dueño dentro del paseo - nunca
    paseo['id_mascotas'] completo, que puede incluir mascotas de OTROS
    dueños (hasta 8 en total, Ley Kiara). Mostrarle a un dueño el nombre
    de una mascota ajena es un problema de privacidad, no solo estetico -
    ver CLAUDE.md, "Corrección de alcance 2026-09-25".
    """
    mascotas = mascotas_repository.obtener_varias_por_id_y_dueno(paseo.get('id_mascotas', []), id_dueno)
    # Se reordenan segun el orden original en id_mascotas (obtener_varias_por_id_y_dueno
    # no garantiza orden) para que se vean siempre en el mismo orden que las inscribio.
    por_id = {m['_id']: m for m in mascotas}
    return [por_id[mid] for mid in paseo.get('id_mascotas', []) if mid in por_id]


def _certificados_de_mascotas_para_paseador(id_paseador, mascotas):
    """
    Mismo criterio que usuarios.views_web._certificados_de_mascotas_para_paseador()
    - duplicada a proposito en vez de importada de esa app (mismo
    criterio que _hay_notificaciones_sin_leer de arriba: evitar una
    dependencia cruzada entre apps por una funcion chica), pero las DOS
    llaman a la misma función de acceso compartida:
    paseos_repository.paseador_tiene_acceso_a_mascota().
    """
    resultado = []
    for m in mascotas:
        if not paseos_repository.paseador_tiene_acceso_a_mascota(id_paseador, m['_id']):
            continue
        resultado.append({
            'nombre': m['nombre'],
            'estado_salud': mascotas_repository.estado_certificado_salud(m.get('certificado_salud')),
            'url_certificado_salud': (m.get('certificado_salud') or {}).get('url'),
            'url_carne_vacunacion': (m.get('carne_vacunacion') or {}).get('url'),
        })
    return resultado


def _fecha_iso_utc(valor):
    """
    Los datetimes que devuelve pymongo son naive (UTC sin tzinfo - ver
    core/mongo.py): hay que marcarlos explicitamente como UTC ("Z") antes
    de mandarlos al navegador, o `new Date(...)` en JS los interpreta como
    hora LOCAL del navegador y el tiempo transcurrido queda mal calculado
    por el desfase horario (Colombia es UTC-5).
    """
    return valor.strftime('%Y-%m-%dT%H:%M:%SZ') if valor else None


@requiere_autenticacion
def mapa_paseo(request, id_paseo):
    """
    Mapa de seguimiento - compartido por los dos roles (antes era
    @requiere_dueno a secas: un paseador nunca podia entrar aca, ni
    siquiera a sus propios paseos - ver el reporte de hallazgos, punto
    (c)). El control real de "a quien le pertenece este paseo" lo hace
    _paseo_accesible_o_none(), no el decorador.
    """
    paseo = _paseo_accesible_o_none(request, id_paseo)
    if not paseo:
        rol_sesion = request.session.get('rol')
        messages.error(request, 'No tienes acceso a ese paseo.')
        return redirect(URL_DASHBOARD_POR_ROL.get(rol_sesion, 'usuarios:login'))

    id_usuario = request.session['id_usuario']
    es_dueno = request.session.get('rol') == 'dueño'
    mascotas_certificados = []
    if es_dueno:
        # SOLO las mascotas de ESTE dueño - ver _mascotas_del_dueno_en_paseo()
        # (puede haber mascotas de OTROS dueños en el mismo paseo).
        mascotas = _mascotas_del_dueno_en_paseo(paseo, id_usuario)
    else:
        # El paseador SI ve todas las mascotas del paseo, sin filtrar -
        # mismo criterio que ya usa su propio dashboard (bienvenida_paseador):
        # se las esta llevando a todas juntas, no hay nada que ocultarle.
        mascotas_por_id = mascotas_repository.obtener_varias_por_id(paseo.get('id_mascotas', []))
        mascotas = mascotas_repository.resolver_lista(paseo.get('id_mascotas'), mascotas_por_id)
        # Certificados (Ley Kiara): el paseador necesita verlos ANTES de
        # empezar, no solo durante el paseo en vivo - este mapa sirve
        # tanto para "en_vivo" como para "historico" (mismo _paseo_accesible_o_none
        # de arriba), asi que cubre el caso "detalle/mapa de un paseo
        # histórico" sin una pantalla aparte.
        mascotas_certificados = _certificados_de_mascotas_para_paseador(id_usuario, mascotas)

    paseador = None
    if paseo.get('id_paseador'):
        paseador = usuarios_repository.obtener_por_id(paseo['id_paseador'])

    return render(request, 'coordenadas/mapa.html', {
        'paseo': paseo,
        'id_paseo': str(paseo['_id']),
        'mascotas': mascotas,
        'mascotas_certificados': mascotas_certificados,
        'paseador': paseador,
        'hora_inicio_iso': _fecha_iso_utc(paseo.get('hora_inicio')),
        'hora_fin_iso': _fecha_iso_utc(paseo.get('hora_fin')),
        # None si no hay un incidente real (ver _info_incidente_reciente)
        # - esto es lo unico que decide si el banner se muestra, no
        # paseo.emergencia por si solo. Con mascotas propias (dueño) o
        # sin restriccion (paseador, None) - ver _info_incidente_reciente().
        'info_incidente_reciente': _info_incidente_reciente(
            paseo['_id'], [m['_id'] for m in mascotas] if es_dueno else None
        ),
        # "Calificar" es una accion EXCLUSIVA del dueño (calificaciones:
        # calificar_paseo ya tiene su propio @requiere_dueno - bloqueado
        # en backend de por si) - se oculta en el template con esta
        # bandera para no mostrarle al paseador un link que lo rebotaria.
        'es_dueno': es_dueno,
        # Aviso "El paseo finalizó, califícalo ahora" - distinto del
        # banner de incidente de arriba (pueden convivir), ver
        # _pendiente_calificar(). False a secas para el paseador: esa
        # pregunta ("¿calificaste TU experiencia?") no aplica a su rol.
        'pendiente_calificar': _pendiente_calificar(paseo, id_usuario) if es_dueno else False,
    })


@requiere_autenticacion
def coordenadas_de_paseo(request, id_paseo):
    paseo = _paseo_accesible_o_none(request, id_paseo)
    if not paseo:
        return JsonResponse({'error': 'No autorizado.'}, status=403)

    id_usuario = request.session['id_usuario']
    es_dueno = request.session.get('rol') == 'dueño'
    # SOLO las mascotas de ESTE dueño (ver _info_incidente_reciente) -
    # mismo criterio que mapa_paseo(), necesario aca tambien porque este
    # endpoint es el que alimenta el banner durante el polling, no solo
    # la carga inicial.
    ids_mascota_viewer = (
        [m['_id'] for m in _mascotas_del_dueno_en_paseo(paseo, id_usuario)] if es_dueno else None
    )
    puntos = repository.listar_por_paseo(id_paseo)
    return JsonResponse({
        'estado': paseo['estado'],
        'emergencia': paseo.get('emergencia', False),
        # None si no hay un incidente real (ver _info_incidente_reciente)
        # - el JS decide si mostrar el banner segun esto, no segun
        # "emergencia".
        'info_incidente_reciente': _info_incidente_reciente(paseo['_id'], ids_mascota_viewer),
        'puntos': [repository.a_json(p) for p in puntos],
        # Esta pantalla ya hace polling cada 10s mientras el paseo esta
        # "en_vivo" - se aprovecha esa misma peticion para el punto de
        # notificaciones del navbar en vez de sumar una aparte (ver
        # mapa.html, que por eso deja vacio el poller generico de
        # base.html solo mientras esta en ese estado). Sirve para los dos
        # roles por igual - cualquier usuario puede tener notificaciones.
        'hay_notificaciones_sin_leer': _hay_notificaciones_sin_leer(request, id_usuario),
        # Misma logica que mapa_paseo() - solo aplica al dueño.
        'pendiente_calificar': _pendiente_calificar(paseo, id_usuario) if es_dueno else False,
    })


def _parsear_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
    except ValueError:
        return None


# INC-03 (13 oct): con varias pestañas del mismo paseador abiertas a la
# vez, cada una manda su propio punto cada 10s de forma independiente,
# sin coordinarse entre ellas - el resultado medido es una rafaga de 2+
# puntos casi simultaneos seguida de un hueco de ~10s, no un punto cada
# 10s real (ver MANUAL_DESARROLLADOR.md, diagnostico INC-03/INC-04). 8s
# (no 10, el intervalo nominal) da margen para la variacion normal de
# red/GPS de una sola pestaña legitima sin arriesgar descartar un punto
# valido que llegue un poco antes de los 10s por latencia - a la vez,
# suficientemente cerca de 10 para cortar las rafagas de verdad.
_SEGUNDOS_MINIMOS_ENTRE_PUNTOS = 8

# Incremento 4, punto D2: "precision" es el radio de incertidumbre en
# metros que reporta el navegador (position.coords.accuracy) - un valor
# ALTO significa una lectura MALA (por ejemplo, GPS sin buena señal de
# satelite, estimada solo por torres de celular/wifi), no una distancia
# recorrida. 50m descarta esas lecturas claramente malas (un punto con
# ese radio de error puede caer en la cuadra equivocada) sin descartar
# una lectura normal de celular al aire libre (tipicamente 5-20m) ni
# siquiera una algo degradada (p.ej. entre edificios altos, ~30-40m).
_PRECISION_MAXIMA_ACEPTABLE_METROS = 50


@require_POST
@requiere_paseador
def registrar_coordenada(request, id_paseo):
    """
    Recibe un punto GPS desde el navegador del propio paseador mientras
    su paseo esta "en_vivo" (autenticado por sesion).
    """
    paseo = paseos_repository.obtener_por_id(id_paseo)
    if not paseo or str(paseo.get('id_paseador')) != request.session.get('id_usuario') or paseo['estado'] != 'en_vivo':
        return JsonResponse({
            'error': 'Este paseo no existe, no es tuyo, o no está "en_vivo".',
        }, status=409)

    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido.'}, status=400)

    try:
        latitud = float(data['latitud'])
        longitud = float(data['longitud'])
    except (KeyError, TypeError, ValueError):
        return JsonResponse(
            {'error': 'latitud y longitud son requeridos y deben ser numéricos.'},
            status=400,
        )
    if not (-90 <= latitud <= 90) or not (-180 <= longitud <= 180):
        return JsonResponse({'error': 'latitud/longitud fuera de rango.'}, status=400)

    altitud = data.get('altitud')
    try:
        altitud = float(altitud) if altitud is not None else None
    except (TypeError, ValueError):
        altitud = None

    precision = data.get('precision')
    try:
        precision = float(precision) if precision is not None else None
    except (TypeError, ValueError):
        precision = None

    # Descarta en silencio una lectura de mala precision (D2, ver
    # _PRECISION_MAXIMA_ACEPTABLE_METROS mas arriba) - MISMA respuesta
    # que si se hubiera guardado, mismo criterio que el descarte de
    # INC-03 de abajo: no es un error del paseador, es una lectura mala
    # que no vale la pena guardar ni dibujar en el mapa.
    if precision is not None and precision > _PRECISION_MAXIMA_ACEPTABLE_METROS:
        return JsonResponse({
            'total_puntos': paseo.get('total_puntos', 0),
            'hay_notificaciones_sin_leer': _hay_notificaciones_sin_leer(request, paseo['id_paseador']),
        }, status=201)

    # Descarta en silencio un punto que llega demasiado pronto despues
    # del ultimo (INC-03, ver _SEGUNDOS_MINIMOS_ENTRE_PUNTOS mas arriba)
    # - MISMA respuesta que si se hubiera guardado (201, mismo cuerpo),
    # para que el JS no reintente ni muestre un error: no es una falla,
    # es trabajo redundante de otra pestaña del mismo paseador.
    ultima_recepcion = repository.obtener_ultima_recepcion(paseo['_id'])
    ahora = datetime.now(timezone.utc)
    if ultima_recepcion:
        ultima_recepcion_aware = ultima_recepcion.replace(tzinfo=timezone.utc)
        if (ahora - ultima_recepcion_aware).total_seconds() < _SEGUNDOS_MINIMOS_ENTRE_PUNTOS:
            return JsonResponse({
                'total_puntos': paseo.get('total_puntos', 0),
                'hay_notificaciones_sin_leer': _hay_notificaciones_sin_leer(request, paseo['id_paseador']),
            }, status=201)

    repository.registrar_punto(
        id_paseo=paseo['_id'],
        latitud=latitud,
        longitud=longitud,
        altitud=altitud,
        precision=precision,
        fecha_captura=_parsear_fecha(data.get('fecha_captura')),
    )
    total_puntos = paseos_repository.incrementar_total_puntos(paseo['_id'])
    return JsonResponse({
        'total_puntos': total_puntos,
        # El dashboard del paseador no hace su propio polling de
        # notificaciones mientras esta "en_vivo" (no hay "nueva solicitud"
        # que mostrar ahi - ver estado_bienvenida_paseador()) - se
        # aprovecha este mismo POST de GPS, que ya se manda cada 10s, para
        # el punto del navbar en vez de sumar una peticion aparte.
        'hay_notificaciones_sin_leer': _hay_notificaciones_sin_leer(request, paseo['id_paseador']),
    }, status=201)
