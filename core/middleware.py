"""Middleware compartido del proyecto."""

from django.conf import settings


class NoCacheParaAutenticadosMiddleware:
    """
    Evita que el navegador guarde en caché (ni en el historial de
    "Atrás") una página vista con sesión activa - corrección del 12 oct:
    sin esto, el botón "Atrás" después de cerrar sesión puede mostrar
    una copia cacheada del dashboard (con datos de la cuenta) sin
    siquiera volver a pedírsela al servidor, donde ya se habría cortado
    el acceso.

    Solo marca `no-store` cuando la petición SE HIZO con sesión activa
    (`request.session['id_usuario']`) - no afecta a los estáticos que
    sirve WhiteNoise (CSS con cache-busting por hash, otra ruta) ni a
    las pantallas públicas (selector de rol, login, registro), que sí
    pueden cachearse sin riesgo.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # request.path.startswith(STATIC_URL): el navegador manda la
        # cookie de sesion en CUALQUIER peticion del mismo sitio,
        # incluida la del CSS - sin este descarte, alguien logueado
        # perdería el cache-busting por hash de WhiteNoise en cada
        # carga de pagina, sin necesidad (el CSS no tiene datos de
        # cuenta que ocultar).
        es_estatico = request.path.startswith(settings.STATIC_URL)
        if request.session.get('id_usuario') and not es_estatico:
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
        return response
