from django.urls import path

from usuarios import views_web

app_name = 'usuarios'

urlpatterns = [
    path('registro/', views_web.registro_dueno, name='registro'),
    path('login/', views_web.login_dueno, name='login'),
    path('logout/', views_web.logout_dueno, name='logout'),
    path('bienvenida/', views_web.bienvenida, name='bienvenida'),
]
