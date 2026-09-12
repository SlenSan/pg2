from django.urls import path

from paseos import views_api

urlpatterns = [
    path('paseador/paseos/disponibilidad/', views_api.publicar_disponibilidad, name='api_publicar_disponibilidad'),
]
