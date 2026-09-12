from django.urls import path

from paseos import views_web

app_name = 'paseos'

urlpatterns = [
    path('', views_web.lista_disponibles, name='lista_disponibles'),
    path('mios/', views_web.mis_paseos, name='mis_paseos'),
    path('paseadores/<str:id_paseo>/', views_web.detalle_paseador, name='detalle_paseador'),
]
