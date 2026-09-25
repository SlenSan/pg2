"""Acceso a la coleccion `coordenadas_detalle` de MongoDB."""

import math
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from core.mongo import get_db

_RADIO_TIERRA_KM = 6371.0


def registrar_punto(*, id_paseo, latitud, longitud, altitud=None, fecha_captura=None):
    ahora = datetime.now(timezone.utc)
    punto = {
        'id_paseo': id_paseo if isinstance(id_paseo, ObjectId) else ObjectId(id_paseo),
        'latitud': latitud,
        'longitud': longitud,
        'altitud': altitud,
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


def listar_por_paseo(id_paseo):
    try:
        oid = ObjectId(id_paseo)
    except (InvalidId, TypeError):
        return []
    return list(get_db().coordenadas_detalle.find({'id_paseo': oid}).sort('fecha_captura', 1))


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
        'fecha_captura': fecha_captura.isoformat() if isinstance(fecha_captura, datetime) else fecha_captura,
    }
