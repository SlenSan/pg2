"""
Geocodificación inversa (coordenadas -> dirección aproximada) via Nominatim
(OpenStreetMap) - Incremento 4, punto C (RF12/RF16, incidentes).

Política de uso de Nominatim (leída antes de implementar esto - resumen
también en el reporte del punto C):
  https://operations.osmfoundation.org/policies/nominatim/
- Máximo 1 request/segundo, nunca "bulk" ni consultas sistemáticas (p.ej.
  geocodificar una grilla, o cada punto GPS). Este módulo se usa SOLO al
  reportar un incidente (RF12) - un evento disparado por una persona, no
  un lote - nunca se llama desde el envío periódico de GPS.
- Requiere un User-Agent genuino que identifique la aplicación (el
  default de una librería HTTP no alcanza - responde 403). Ver
  `NOMINATIM_USER_AGENT` en settings.py / .env.example.
- Pide cachear resultados cuando sea posible: el resultado se guarda para
  siempre en `incidentes.direccion_aproximada` (nunca se vuelve a pedir
  la misma dirección).
- Pide mostrar atribución a OpenStreetMap - ya se muestra en cualquier
  pantalla con el mapa de Leaflet (ver coordenadas/templates/coordenadas/
  mapa.html e incidentes/templates/incidentes/detalle.html), que usan el
  mismo mapa de fondo de OSM.

Limitación conocida y documentada (no hay Redis/cache compartido en este
proyecto): el límite de 1 req/s de abajo se aplica POR PROCESO de
gunicorn, no globalmente entre varios workers. Para la escala de este
proyecto de grado (RF12 es un boton de emergencia, disparado por una
persona a la vez, no un proceso en lote) esto es aceptable - server-side
geocoding de alto volumen correspondería a un proveedor comercial o una
instancia propia de Nominatim, fuera de alcance aquí.
"""
import threading
import time

import requests
from django.conf import settings

_URL_REVERSE = 'https://nominatim.openstreetmap.org/reverse'

# 1 req/s es el maximo absoluto de la politica - 1.1s deja margen.
_INTERVALO_MINIMO_SEGUNDOS = 1.1

# "Si el servicio falla o tarda mas de 5s, el incidente se guarda igual,
# sin dirección" (pedido explícito de la tarea) - este es el presupuesto
# TOTAL (espera de ritmo + la llamada HTTP misma), no solo el timeout de
# la request.
_TIEMPO_MAXIMO_TOTAL_SEGUNDOS = 5

_bloqueo = threading.Lock()
_ultima_llamada = 0.0


def direccion_aproximada(latitud, longitud):
    """
    Dirección legible en texto corto para (latitud, longitud), o None si
    Nominatim falla, no responde a tiempo, o no se pudo respetar el
    límite de ritmo sin exceder el presupuesto total de 5s. NUNCA lanza
    una excepción - un incidente debe poder guardarse sin dirección.
    """
    inicio = time.monotonic()
    with _bloqueo:
        global _ultima_llamada
        espera = _INTERVALO_MINIMO_SEGUNDOS - (time.monotonic() - _ultima_llamada)
        if espera > 0:
            if (time.monotonic() - inicio) + espera > _TIEMPO_MAXIMO_TOTAL_SEGUNDOS:
                return None
            time.sleep(espera)
        _ultima_llamada = time.monotonic()

    tiempo_restante = _TIEMPO_MAXIMO_TOTAL_SEGUNDOS - (time.monotonic() - inicio)
    if tiempo_restante <= 0:
        return None

    try:
        resp = requests.get(
            _URL_REVERSE,
            params={
                'format': 'jsonv2',
                'lat': latitud,
                'lon': longitud,
                'zoom': 18,
                'addressdetails': 1,
            },
            headers={'User-Agent': settings.NOMINATIM_USER_AGENT},
            timeout=min(tiempo_restante, 4),
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    return _formatear(data)


def _formatear(data):
    direccion = data.get('address') or {}
    partes = [
        direccion.get('road'),
        direccion.get('suburb') or direccion.get('neighbourhood'),
        direccion.get('city') or direccion.get('town') or direccion.get('village'),
    ]
    texto = ', '.join(p for p in partes if p)
    return texto or data.get('display_name') or None
