from django.urls import path

from usuarios import views_web

app_name = 'usuarios'

urlpatterns = [
    path('registro/', views_web.registro, name='registro'),
    path('login/', views_web.login, name='login'),
    path('logout/', views_web.logout, name='logout'),
    path('bienvenida/', views_web.bienvenida, name='bienvenida'),
    path('paseador/bienvenida/', views_web.bienvenida_paseador, name='bienvenida_paseador'),
    path('paseador/perfil/', views_web.perfil_paseador, name='perfil_paseador'),
]
