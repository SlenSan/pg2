"""Acceso a la coleccion `coordenadas_detalle` de MongoDB."""

import math
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db

_RADIO_TIERRA_KM = 6371.0

# Ajustes del 19 de octubre, punto 1 - mismo criterio que
# UMBRAL_PRECISION_DIBUJO en coordenadas/templates/coordenadas/mapa.html
# (no se puede compartir literalmente una constante entre Python y JS,
# pero es el MISMO valor a propósito: un punto con mala precisión no
# debería ni dibujarse en el mapa ni contar para la distancia recorrida).
# Si se cambia uno, hay que cambiar el otro a mano.
UMBRAL_PRECISION_METROS = 50


def registrar_punto(*, id_paseo, latitud, longitud, altitud=None, precision=None, fecha_captura=None):
    ahora = datetime.now(timezone.utc)
    punto = {
        'id_paseo': id_paseo if isinstance(id_paseo, ObjectId) else ObjectId(id_paseo),
        'latitud': latitud,
        'longitud': longitud,
        'altitud': altitud,
        # Radio de incertidumbre en metros (position.coords.accuracy del
        # navegador) - Incremento 4, punto D1. None para un documento
        # viejo o un navegador que no lo reporte (.get(...) en cualquier
        # lectura, nunca asumido presente).
        'precision': precision,
        'fecha_captura': fecha_captura or ahora,
        'fecha_recepcion': ahora,
    }
    resultado = get_db().coordenadas_detalle.insert_one(punto)
    punto['_id'] = resultado.inserted_id
    return punto


def obtener_ultimo_punto(id_paseo, *, desde=None, hasta=None):
    """
    El punto GPS mas reciente de un paseo, o None si todavia no hay
    ninguno. `desde`/`hasta` (datetime, opcionales) - Incremento 4 fase
    3, punto A3: el mapa de un DUEÑO solo debe considerar el tramo
    entre la recogida y la entrega de SUS mascotas (nunca el paseo
    completo) para decidir cosas como "hay puntos" o "hay un punto
    reciente" - mismos parametros que listar_por_paseo() mas abajo.
    """
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None
    query = {'id_paseo': oid}
    rango_fecha = {}
    if desde is not None:
        rango_fecha['$gte'] = desde
    if hasta is not None:
        rango_fecha['$lte'] = hasta
    if rango_fecha:
        query['fecha_captura'] = rango_fecha
    return get_db().coordenadas_detalle.find_one(
        query,
        sort=[('fecha_captura', -1)],
    )


def obtener_ultima_recepcion(id_paseo):
    """
    `fecha_recepcion` (hora del SERVIDOR, no la del dispositivo) del
    punto GPS mas reciente de este paseo, o None si todavia no hay
    ninguno - usada para descartar duplicados por ventana de tiempo
    (INC-03, ver coordenadas/views_web.py::registrar_coordenada).
    Ordena por `fecha_recepcion`, no por `fecha_captura` (que viene del
    dispositivo del paseador - no es confiable para esta comparacion,
    ya que dos pestañas podrian reportar relojes de cliente distintos).
    """
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None
    punto = get_db().coordenadas_detalle.find_one(
        {'id_paseo': oid},
        sort=[('fecha_recepcion', -1)],
    )
    return punto['fecha_recepcion'] if punto else None


def listar_por_paseo(id_paseo, desde=None, hasta=None):
    """
    `desde` (datetime, opcional, exclusivo - `$gt`) - lentitud en
    producción, 14 de octubre, punto 3: antes el polling del mapa en
    vivo (cada 8s, mientras dura el paseo) llamaba a esto SIN `desde`,
    así que cada vuelta volvía a traer y volvía a serializar TODOS los
    puntos desde el inicio del paseo, no solo los nuevos - en un paseo
    de 30 minutos (~225 puntos a 8s cada uno) el volumen total
    transferido a lo largo del paseo crece proporcional al CUADRADO de
    su duración, no a su duración (confirmado leyendo
    coordenadas/views_web.py::coordenadas_de_paseo(), que ya recibía el
    array entero y lo volvía a mandar completo en cada respuesta JSON).
    Con `desde`, cada petición de polling solo pide (y Mongo solo
    escanea) los puntos posteriores al último que el navegador ya
    tiene - ver mapa.html. Mismo parametro reusado (Incremento 4 fase
    3, punto A3) como límite inferior de privacidad: el mapa de un
    dueño nunca debe pedir puntos de ANTES de la recogida de su propia
    mascota - el `$gt` de un solo punto de margen (la recepción del GPS
    es cada 6-8s) es insignificante frente a eso.

    `hasta` (datetime, opcional, inclusivo - `$lte`) - punto A3: límite
    superior de privacidad, la hora de entrega de ese dueño (si ya se
    entregó). `None` significa "sin límite superior todavía" (la
    mascota sigue con el paseador).
    """
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return []
    query = {'id_paseo': oid}
    rango_fecha = {}
    if desde is not None:
        rango_fecha['$gt'] = desde
    if hasta is not None:
        rango_fecha['$lte'] = hasta
    if rango_fecha:
        query['fecha_captura'] = rango_fecha
    return list(get_db().coordenadas_detalle.find(query).sort('fecha_captura', 1))


def _distancia_haversine_m(lat1, lon1, lat2, lon2):
    """
    Distancia en linea recta entre dos puntos GPS, formula de Haversine -
    tiene en cuenta la curvatura de la Tierra (una resta simple de
    latitud/longitud no serviria para una distancia real). En METROS
    (no km): es la unidad que usa formatear_distancia() y en la que se
    guarda paseos.distancia_m.
    """
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    return _RADIO_TIERRA_KM * 1000 * 2 * math.asin(math.sqrt(a))


def distancia_recorrida_m(id_paseo, *, desde=None, hasta=None):
    """
    Suma la distancia entre cada PAR de puntos GPS consecutivos de este
    paseo (Haversine, en metros) - Ajustes del 19 de octubre, punto 1.
    No es un campo guardado en `paseos` mientras el paseo sigue en curso
    (se calcula al consultarlo); para un paseo YA finalizado, el
    llamador debería preferir el `distancia_m` ya guardado (ver
    paseos.repository.guardar_distancia()) en vez de llamar a esto de
    nuevo. None con menos de 2 puntos VALIDOS (paseo recien iniciado, o
    sin señal GPS en todo el trayecto).

    Mismo criterio que el dibujo del mapa (UMBRAL_PRECISION_METROS,
    igual que UMBRAL_PRECISION_DIBUJO en mapa.html): se descartan los
    puntos con `precision` peor a ese umbral ANTES de medir - un punto
    con mala señal no debería contar como desplazamiento real. Un punto
    sin `precision` (None, de antes del Incremento 4 o si el navegador
    no la reportó) SI se usa - no hay forma de saber si es bueno o malo,
    así que se trata como aceptable (nunca se asume "malo" por ausencia
    de dato).

    `desde`/`hasta` (datetime, opcionales, comparados contra
    `fecha_captura`): preparada en los ajustes del 19 de octubre para
    esto - Incremento 4 fase 3, punto A9: cada dueño ve SOLO la
    distancia de su propio tramo (entre su `hora_recogida` y
    `hora_entrega`), nunca el paseo completo - ver
    coordenadas.views_web._rango_visible_para_dueno().

    Se decidió NO agregar un filtro de "jitter" (ignorar un tramo si es
    más corto que la suma de las precisiones de sus dos puntos) a pesar
    de que la tarea lo sugería - ver MANUAL_DESARROLLADOR.md para los
    números reales de un paseo de producción que muestran por qué ese
    filtro, tal como estaba planteado, sería CONTRAPRODUCENTE (descarta
    casi todo el recorrido real, no solo el ruido).
    """
    puntos = listar_por_paseo(id_paseo, desde=desde)
    if hasta is not None:
        puntos = [p for p in puntos if p['fecha_captura'] <= hasta]
    puntos_validos = [
        p for p in puntos
        if p.get('precision') is None or p['precision'] <= UMBRAL_PRECISION_METROS
    ]
    if len(puntos_validos) < 2:
        return None
    total_m = sum(
        _distancia_haversine_m(
            anterior['latitud'], anterior['longitud'],
            actual['latitud'], actual['longitud'],
        )
        for anterior, actual in zip(puntos_validos, puntos_validos[1:])
    )
    return round(total_m)


def formatear_distancia(metros):
    """
    ÚNICA función que da el texto de distancia a mostrar ("850 m" /
    "1,2 km") - Ajustes del 19 de octubre, punto 1. None si `metros` es
    None (paseo sin suficientes puntos para medir - el llamador decide
    qué mostrar en ese caso, p.ej. "Sin datos de GPS").

    Coma decimal a propósito (no es un bug tipo INC-05): esto arma un
    STRING en el servidor para mostrar en HTML/texto, nunca un número
    crudo que vaya a un <script>/JSON a ser interpretado por JS - por
    eso no hace falta (ni corresponde) el filtro |unlocalize de INC-05
    aquí. Quien necesite el número crudo en JSON debe usar
    distancia_recorrida_m()/el campo `distancia_m` directamente, nunca
    parsear este texto.
    """
    if metros is None:
        return None
    if metros < 1000:
        return f'{round(metros)} m'
    km = metros / 1000
    return f'{km:.1f} km'.replace('.', ',')


def a_json(punto):
    fecha_captura = punto.get('fecha_captura')
    return {
        'latitud': punto['latitud'],
        'longitud': punto['longitud'],
        'altitud': punto.get('altitud'),
        'precision': punto.get('precision'),
        'fecha_captura': fecha_captura.isoformat() if isinstance(fecha_captura, datetime) else fecha_captura,
    }
