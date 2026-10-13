"""Middleware compartido del proyecto."""

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


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


class ExigirAutorizacionDatosMiddleware:
    """
    RNF1/Ley 1581 de 2012 (cierre de auditoría, punto 1) - cualquier
    sesión autenticada SIN autorización de tratamiento de datos (ver
    `usuarios.views_web._iniciar_sesion`, que guarda
    `autorizacion_datos_ok` en sesión en cada login, y
    `usuarios.repository.crear_usuario`, que ya la deja en True para
    toda cuenta NUEVA desde que se registra) se redirige a la pantalla
    intermedia `usuarios:autorizar_datos` SIN IMPORTAR a qué ruta
    intentaba entrar - "hasta que la acepten, solo pueden ver esa
    pantalla y cerrar sesión" (pedido explícito de la tarea).

    `_RUTAS_PERMITIDAS` son las únicas excepciones: la propia pantalla de
    autorización (para no entrar en un bucle de redirects), cerrar
    sesión, la política de privacidad (hay que poder leerla ANTES de
    aceptarla, desde el link de esa misma pantalla) y los estáticos/
    manifest/service worker (para no romper la PWA en una cuenta que
    todavía no aceptó).

    Va DESPUÉS de SessionMiddleware (necesita `request.session`) y antes
    de llegar a cualquier vista - por simplicidad se deja al final de
    MIDDLEWARE, junto a NoCacheParaAutenticadosMiddleware.
    """

    _RUTAS_PERMITIDAS = None

    def __init__(self, get_response):
        self.get_response = get_response

    def _rutas_permitidas(self):
        # Resuelto en el primer request, no al importar el modulo: en
        # ese momento el URLconf todavia no esta completamente cargado
        # (mismo motivo por el que reverse() no se usa a nivel de modulo
        # en ningun otro archivo del proyecto).
        if ExigirAutorizacionDatosMiddleware._RUTAS_PERMITIDAS is None:
            ExigirAutorizacionDatosMiddleware._RUTAS_PERMITIDAS = frozenset([
                reverse('usuarios:autorizar_datos'),
                reverse('usuarios:logout'),
                reverse('privacidad'),
                reverse('manifest'),
                reverse('service_worker'),
            ])
        return ExigirAutorizacionDatosMiddleware._RUTAS_PERMITIDAS

    def __call__(self, request):
        es_estatico = request.path.startswith(settings.STATIC_URL)
        if (
            request.session.get('id_usuario')
            and not request.session.get('autorizacion_datos_ok')
            and not es_estatico
            and request.path not in self._rutas_permitidas()
        ):
            return redirect('usuarios:autorizar_datos')
        return self.get_response(request)
