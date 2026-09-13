from django.urls import path

from coordenadas import views_api

urlpatterns = [
    path(
        'paseador/paseos/<str:id_paseo>/coordenadas/',
        views_api.registrar_coordenada,
        name='api_registrar_coordenada',
    ),
]
