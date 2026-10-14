"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from core import views as core_views
from usuarios import views_web as usuarios_views_web

urlpatterns = [
    # Servidos desde la RAIZ a proposito (Incremento 4, fase 2, punto E
    # - Web Push) - ver core/views.py::manifest()/service_worker() para
    # el motivo (alcance del service worker, start_url del manifest).
    path('manifest.webmanifest', core_views.manifest, name='manifest'),
    path('sw.js', core_views.service_worker, name='service_worker'),
    # RNF1/Ley 1581 (cierre de auditoría, punto 1) - en la RAIZ (no bajo
    # /cuentas/ ni ninguna otra app) porque se enlaza desde el pie de
    # pagina de TODAS las pantallas, con y sin sesion.
    path('privacidad/', core_views.privacidad, name='privacidad'),
    path('', usuarios_views_web.seleccionar_rol, name='home'),
    path('cuentas/', include('usuarios.urls_web')),
    path('mascotas/', include('mascotas.urls')),
    path('paseos/', include('paseos.urls_web')),
    path('notificaciones/', include('notificaciones.urls')),
    path('coordenadas/', include('coordenadas.urls_web')),
    path('incidentes/', include('incidentes.urls_web')),
    path('calificaciones/', include('calificaciones.urls_web')),
    path('administracion/', include('administracion.urls_web')),
    path('api/', include('core.urls')),
]

# INC-11 (hallazgos de la prueba con un usuario final, 14 de octubre) -
# el panel de administracion REAL de Canigo es /administracion/
# verificacion/ (RF14, ver administracion/urls_web.py) - el de Django
# (/admin/) nunca tuvo ningun modelo registrado (confirmado: ningun
# admin.py del proyecto llama a admin.site.register, ver
# MANUAL_DESARROLLADOR.md), asi que no sirve para nada real, solo
# expone una pantalla de login y superficie de ataque de mas. Solo se
# agrega la ruta si DEBUG=True (desarrollo local) - en produccion
# (DEBUG=False) la ruta no existe en absoluto, responde 404 como
# cualquier URL que no esta en urlpatterns, no un 403/401 que
# confirmaria que la ruta es real.
if settings.DEBUG:
    urlpatterns.insert(0, path('admin/', admin.site.urls))
