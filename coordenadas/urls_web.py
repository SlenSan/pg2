from django.urls import path

from coordenadas import views_web

app_name = 'coordenadas'

urlpatterns = [
    path('paseos/<str:id_paseo>/mapa/', views_web.mapa_paseo, name='mapa_paseo'),
    path('paseos/<str:id_paseo>/datos/', views_web.coordenadas_de_paseo, name='datos_paseo'),
]
