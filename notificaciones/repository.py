"""Acceso a la coleccion `notificaciones` de MongoDB."""

import json
import logging
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from django.conf import settings
from django.urls import reverse
from pywebpush import WebPushException, webpush

from core.mongo import get_db

logger = logging.getLogger(__name__)

_TITULO_POR_TIPO = {
    'inicio_paseo': 'Paseo iniciado',
    'fin_paseo': 'Paseo finalizado',
    'emergencia': '¡Emergencia reportada!',
    'calificacion': 'Nueva calificación',
    'verificacion': 'Verificación de perfil',
}


def crear(*, id_usuario, tipo, mensaje):
    """
    `tipo` debe ser uno de: "inicio_paseo", "fin_paseo", "emergencia",
    "calificacion" (ver esquema en el documento de grado).

    Incremento 4, fase 2, punto E: ademas de guardar la notificacion
    INTERNA (lo de siempre), dispara un Web Push a los dispositivos
    suscritos de este usuario - un solo punto de entrada para los 7
    lugares del proyecto que crean una notificacion (paseos, incidentes,
    calificaciones, administracion, usuarios), en vez de agregar el
    envio de push a cada uno por separado (mas facil de olvidar en un
    llamador nuevo el dia de mañana). Es una excepcion deliberada al
    "repository.py = solo acceso a Mongo" del resto del proyecto - se
    aceptó el acoplamiento a cambio de que NINGÚN llamador pueda crear
    una notificación sin que también se intente el push.

    Si el push falla (sin suscripciones, VAPID sin configurar, el
    servicio de push no responde), la notificación INTERNA ya quedó
    creada de todas formas - _enviar_push() nunca lanza.
    """
    notificacion = {
        'id_usuario': id_usuario if isinstance(id_usuario, ObjectId) else ObjectId(id_usuario),
        'tipo': tipo,
        'mensaje': mensaje,
        'fecha': datetime.now(timezone.utc),
    }
    resultado = get_db().notificaciones.insert_one(notificacion)
    notificacion['_id'] = resultado.inserted_id
    _enviar_push(notificacion['id_usuario'], tipo, mensaje)
    return notificacion


def listar_por_usuario(id_usuario):
    try:
        oid = ObjectId(id_usuario)
    except (InvalidId, TypeError):
        return []
    return list(get_db().notificaciones.find({'id_usuario': oid}).sort('fecha', -1))


def hay_no_leidas(id_usuario, ultima_vista):
    """
    True si el usuario tiene alguna notificacion mas nueva que
    `ultima_vista` (None = nunca visito la pantalla de notificaciones,
    asi que cualquier notificacion existente cuenta). Mismo mecanismo de
    "vista hasta" en sesion que ya usa notificaciones/views.py, extraido
    aca para que los dashboards (carga completa y polling) puedan
    reutilizarlo sin duplicar la comparacion.
    """
    try:
        oid = ObjectId(id_usuario)
    except (InvalidId, TypeError):
        return False
    query = {'id_usuario': oid}
    if ultima_vista is not None:
        query['fecha'] = {'$gt': ultima_vista}
    return get_db().notificaciones.find_one(query) is not None


# ---- Web Push (Incremento 4, fase 2, punto E) ----
# Coleccion `suscripciones_push`: una suscripcion del navegador por
# dispositivo/instalación (un mismo usuario puede tener varias - celular
# y computador, por ejemplo). `endpoint` identifica la suscripcion de
# forma unica (lo asigna el navegador/servicio de push, nunca se repite
# entre dispositivos) - ver core/management/commands/crear_indices.py
# para el indice unico.

def crear_suscripcion(*, id_usuario, endpoint, keys):
    """
    Guarda o actualiza una suscripcion push. Upsert por `endpoint` (no
    insert_one a secas): si el MISMO navegador ya estaba suscrito (p.ej.
    el usuario cerró sesión y volvió a activar las notificaciones, o el
    navegador rotó sus claves internas), se actualiza el documento en
    vez de chocar con el índice único o duplicar una fila para el mismo
    dispositivo.
    """
    try:
        oid_usuario = ObjectId(id_usuario)
    except (InvalidId, TypeError):
        return None
    get_db().suscripciones_push.update_one(
        {'endpoint': endpoint},
        {'$set': {
            'id_usuario': oid_usuario,
            'endpoint': endpoint,
            'keys': keys,
            'fecha': datetime.now(timezone.utc),
        }},
        upsert=True,
    )


def eliminar_suscripcion_por_endpoint(endpoint):
    """
    Borra una suscripción vencida - se llama SOLO cuando el servicio de
    push responde 404/410 (ver _enviar_push), nunca por cualquier otro
    error (uno de red o 5xx es transitorio, no significa que la
    suscripción ya no sirva).
    """
    get_db().suscripciones_push.delete_one({'endpoint': endpoint})


def listar_suscripciones_de_usuario(id_usuario):
    try:
        oid = ObjectId(id_usuario)
    except (InvalidId, TypeError):
        return []
    return list(get_db().suscripciones_push.find({'id_usuario': oid}))


def _url_destino_push(tipo, rol):
    """
    A que pagina lleva tocar un push, segun su tipo y el rol del
    destinatario - version simplificada de
    notificaciones.views._url_destino() (misma idea, pensada para la
    pantalla "Notificaciones"): aca no hace falta ubicar el paseo EXACTO
    en vivo (ese dato ya no esta disponible al momento de armar el push,
    y buscarlo complicaria esta funcion sin necesidad) - alcanza con
    aterrizar en la lista mas relevante; desde ahi el usuario entra al
    paseo puntual con un toque mas.
    """
    if rol == 'dueño':
        if tipo in ('inicio_paseo', 'fin_paseo'):
            return reverse('paseos:mis_paseos')
        if tipo == 'emergencia':
            return reverse('incidentes:lista')
        return reverse('notificaciones:lista')
    # paseador
    if tipo == 'calificacion':
        return reverse('paseos:historial_paseador')
    if tipo == 'verificacion':
        return reverse('usuarios:perfil_paseador')
    return reverse('usuarios:bienvenida_paseador')


def _enviar_push(id_usuario, tipo, mensaje):
    """
    Manda un Web Push a cada dispositivo suscrito de este usuario -
    best effort: NUNCA lanza (un push fallido no debe tumbar la creación
    de la notificación interna, que ya ocurrió antes de llamar a esto -
    ver crear()). Sin VAPID_PRIVATE_KEY configurada, no intenta nada (el
    servidor local/de pruebas puede no tener Web Push configurado -
    mismo criterio de "degradar en silencio" que core/geocoding.py
    cuando falta NOMINATIM_USER_AGENT).

    El texto del push NUNCA lleva datos sensibles (direcciones,
    teléfonos) - es el mismo `mensaje` que ya se guarda en
    `notificaciones.mensaje`, que por diseño del esquema tampoco los
    lleva (ver CLAUDE.md). `url` es a donde abre el navegador al tocar
    el push (ver sw.js, evento "notificationclick").
    """
    if not settings.VAPID_PRIVATE_KEY:
        return

    # Import tardio (no al tope del archivo): usuarios.repository no
    # importa notificaciones, asi que no habria ciclo real, pero se
    # mantiene el import aca para que quede claro que es SOLO para
    # resolver el rol del destinatario antes de armar el link del push.
    from usuarios import repository as usuarios_repository

    suscripciones = listar_suscripciones_de_usuario(id_usuario)
    if not suscripciones:
        return

    usuario = usuarios_repository.obtener_por_id(id_usuario)
    rol = usuario.get('rol') if usuario else None
    payload = json.dumps({
        'titulo': _TITULO_POR_TIPO.get(tipo, 'Canigo'),
        'mensaje': mensaje,
        'url': _url_destino_push(tipo, rol),
    })

    for suscripcion in suscripciones:
        try:
            webpush(
                subscription_info={
                    'endpoint': suscripcion['endpoint'],
                    'keys': suscripcion['keys'],
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={'sub': f'mailto:{settings.VAPID_CLAIMS_EMAIL}'},
            )
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (404, 410):
                # Suscripcion vencida (el usuario desinstaló la app, borró
                # el permiso, o el navegador la rotó) - se borra para no
                # seguir intentando en cada notificación futura.
                eliminar_suscripcion_por_endpoint(suscripcion['endpoint'])
            else:
                logger.warning('Web Push falló (endpoint=%s): %s', suscripcion['endpoint'], exc)
        except Exception as exc:  # noqa: BLE001 - best effort, nunca debe tumbar crear()
            logger.warning('Web Push falló de forma inesperada (endpoint=%s): %s', suscripcion['endpoint'], exc)
