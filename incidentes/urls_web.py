from django.urls import path

from incidentes import views_web

app_name = 'incidentes'

urlpatterns = [
    path('', views_web.lista_incidentes, name='lista'),
    path(
        'paseador/paseos/<str:id_paseo>/reportar/',
        views_web.reportar_incidente,
        name='reportar_incidente',
    ),
]
