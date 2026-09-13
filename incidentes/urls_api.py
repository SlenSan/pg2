from django.urls import path

from incidentes import views_api

urlpatterns = [
    path(
        'paseador/paseos/<str:id_paseo>/incidentes/',
        views_api.reportar_incidente,
        name='api_reportar_incidente',
    ),
    path('paseador/incidentes/', views_api.mis_incidentes, name='api_mis_incidentes'),
]
