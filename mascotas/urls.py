from django.urls import path

from mascotas import views

app_name = 'mascotas'

urlpatterns = [
    path('', views.lista_mascotas, name='lista'),
    path('nueva/', views.registrar_mascota, name='registro'),
    path('<str:id_mascota>/editar/', views.editar_mascota, name='editar'),
    # Punto 4 (ajustes del 20 de octubre) - perfil de solo lectura para
    # el paseador, bajo /mascotas/ pero sin chocar con "editar/" (el
    # dueño) porque el ultimo segmento es distinto.
    path('<str:id_mascota>/perfil-paseador/', views.perfil_mascota_paseador, name='perfil_paseador'),
]
