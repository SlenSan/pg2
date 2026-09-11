from django.urls import path

from usuarios import views_api

urlpatterns = [
    path('paseador/registro/', views_api.registro_paseador, name='api_paseador_registro'),
    path('paseador/login/', views_api.login_paseador, name='api_paseador_login'),
    path('paseador/perfil/', views_api.perfil_paseador, name='api_paseador_perfil'),
]
