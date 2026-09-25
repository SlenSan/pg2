from django.urls import path

from notificaciones import views

app_name = 'notificaciones'

urlpatterns = [
    path('', views.lista_notificaciones, name='lista'),
    path('estado/', views.estado_no_leidas, name='estado_no_leidas'),
]
