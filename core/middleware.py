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


class ExigirCambioContrasenaMiddleware:
    """
    Mejora 2 (hallazgos de la prueba con un usuario final, 14 de
    octubre) - mismo patrón que ExigirAutorizacionDatosMiddleware de
    arriba, para la contraseña temporal: cualquier sesión autenticada
    con `requiere_cambio_contrasena` (ver `usuarios.views_web.
    _iniciar_sesion`, que lo guarda en sesión en cada login, y
    `administracion.views_web.asignar_contrasena_temporal`, que lo deja
    en `True` al asignar la temporal) se redirige a
    `usuarios:cambiar_contrasena_forzado` sin importar a qué ruta
    intentaba entrar, hasta que elija una contraseña nueva.

    Va DESPUÉS de ExigirAutorizacionDatosMiddleware (si una cuenta
    necesitara las dos pantallas a la vez - caso excepcional, ya que
    una contraseña temporal solo se asigna a una cuenta que ya existía -
    primero se le pide la autorización de datos, y solo después el
    cambio de contraseña). Por eso `usuarios:autorizar_datos` también
    está en las rutas permitidas de ESTA clase: si no lo estuviera, una
    cuenta con las dos pendientes a la vez quedaría en un bucle de
    redirects entre las dos pantallas (la primera la manda a
    autorizar_datos, pero esta clase la rebotaría de ahí mismo hacia
    cambiar_contrasena_forzado, que a su vez la primera clase rebota de
    vuelta - bug real, encontrado probando este flujo de punta a punta).
    """

    _RUTAS_PERMITIDAS = None

    def __init__(self, get_response):
        self.get_response = get_response

    def _rutas_permitidas(self):
        # Mismo motivo que en ExigirAutorizacionDatosMiddleware - resuelto
        # en el primer request, no al importar el módulo.
        if ExigirCambioContrasenaMiddleware._RUTAS_PERMITIDAS is None:
            ExigirCambioContrasenaMiddleware._RUTAS_PERMITIDAS = frozenset([
                reverse('usuarios:cambiar_contrasena_forzado'),
                reverse('usuarios:autorizar_datos'),
                reverse('usuarios:logout'),
                reverse('privacidad'),
                reverse('manifest'),
                reverse('service_worker'),
            ])
        return ExigirCambioContrasenaMiddleware._RUTAS_PERMITIDAS

    def __call__(self, request):
        es_estatico = request.path.startswith(settings.STATIC_URL)
        if (
            request.session.get('id_usuario')
            and request.session.get('requiere_cambio_contrasena')
            and not es_estatico
            and request.path not in self._rutas_permitidas()
        ):
            return redirect('usuarios:cambiar_contrasena_forzado')
        return self.get_response(request)
