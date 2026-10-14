"""Acceso a la coleccion `coordenadas_detalle` de MongoDB."""

import math
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db

_RADIO_TIERRA_KM = 6371.0


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


def obtener_ultimo_punto(id_paseo):
    """El punto GPS mas reciente de un paseo, o None si todavia no hay ninguno."""
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return None
    return get_db().coordenadas_detalle.find_one(
        {'id_paseo': oid},
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


def listar_por_paseo(id_paseo, desde=None):
    """
    `desde` (datetime, opcional) - lentitud en producción, 14 de
    octubre, punto 3: antes el polling del mapa en vivo (cada 8s,
    mientras dura el paseo) llamaba a esto SIN `desde`, así que cada
    vuelta volvía a traer y volvía a serializar TODOS los puntos desde
    el inicio del paseo, no solo los nuevos - en un paseo de 30 minutos
    (~225 puntos a 8s cada uno) el volumen total transferido a lo largo
    del paseo crece proporcional al CUADRADO de su duración, no a su
    duración (confirmado leyendo coordenadas/views_web.py::
    coordenadas_de_paseo(), que ya recibía el array entero y lo volvía
    a mandar completo en cada respuesta JSON). Con `desde`, cada
    petición de polling solo pide (y Mongo solo escanea) los puntos
    posteriores al último que el navegador ya tiene - ver mapa.html.
    """
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return []
    query = {'id_paseo': oid}
    if desde is not None:
        query['fecha_captura'] = {'$gt': desde}
    return list(get_db().coordenadas_detalle.find(query).sort('fecha_captura', 1))


def _distancia_haversine_km(lat1, lon1, lat2, lon2):
    """
    Distancia en linea recta entre dos puntos GPS, formula de Haversine -
    tiene en cuenta la curvatura de la Tierra (una resta simple de
    latitud/longitud no serviria para una distancia real en km).
    """
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    return _RADIO_TIERRA_KM * 2 * math.asin(math.sqrt(a))


def distancia_recorrida_km(id_paseo):
    """
    Suma la distancia entre cada PAR de puntos GPS consecutivos de este
    paseo (Haversine). No es un campo guardado en `paseos` - se calcula
    al momento de consultarlo (ver "Mis paseos" del paseador). listar_por_paseo()
    ya viene ordenado por fecha_captura ascendente, asi que los pares
    consecutivos representan el recorrido real en orden. None con menos
    de 2 puntos (no hay ningun tramo que medir - paseo recien iniciado,
    o sin señal GPS en todo el trayecto).
    """
    puntos = listar_por_paseo(id_paseo)
    if len(puntos) < 2:
        return None
    total_km = sum(
        _distancia_haversine_km(
            anterior['latitud'], anterior['longitud'],
            actual['latitud'], actual['longitud'],
        )
        for anterior, actual in zip(puntos, puntos[1:])
    )
    return round(total_km, 1)


def a_json(punto):
    fecha_captura = punto.get('fecha_captura')
    return {
        'latitud': punto['latitud'],
        'longitud': punto['longitud'],
        'altitud': punto.get('altitud'),
        'precision': punto.get('precision'),
        'fecha_captura': fecha_captura.isoformat() if isinstance(fecha_captura, datetime) else fecha_captura,
    }
