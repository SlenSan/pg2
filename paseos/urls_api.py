from django.urls import path

from paseos import views_api

urlpatterns = [
    path('paseador/paseos/disponibilidad/', views_api.publicar_disponibilidad, name='api_publicar_disponibilidad'),
    path('paseador/paseos/actual/', views_api.paseo_actual, name='api_paseo_actual'),
    path('paseador/paseos/<str:id_paseo>/iniciar/', views_api.iniciar_paseo, name='api_iniciar_paseo'),
    path('paseador/paseos/<str:id_paseo>/finalizar/', views_api.finalizar_paseo, name='api_finalizar_paseo'),
]
