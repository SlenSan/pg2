from django.urls import path

from mascotas import views

app_name = 'mascotas'

urlpatterns = [
    path('', views.lista_mascotas, name='lista'),
    path('nueva/', views.registrar_mascota, name='registro'),
]
