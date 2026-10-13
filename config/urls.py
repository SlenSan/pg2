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
from django.contrib import admin
from django.urls import include, path

from core import views as core_views
from usuarios import views_web as usuarios_views_web

urlpatterns = [
    path('admin/', admin.site.urls),
    # Servidos desde la RAIZ a proposito (Incremento 4, fase 2, punto E
    # - Web Push) - ver core/views.py::manifest()/service_worker() para
    # el motivo (alcance del service worker, start_url del manifest).
    path('manifest.webmanifest', core_views.manifest, name='manifest'),
    path('sw.js', core_views.service_worker, name='service_worker'),
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
