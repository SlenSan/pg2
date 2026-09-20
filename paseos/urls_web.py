from django.urls import path

from paseos import views_web

app_name = 'paseos'

urlpatterns = [
    path('', views_web.lista_disponibles, name='lista_disponibles'),
    path('mios/', views_web.mis_paseos, name='mis_paseos'),
    path('historial/', views_web.historial, name='historial'),
    path('paseadores/<str:id_paseo>/', views_web.detalle_paseador, name='detalle_paseador'),
    path('paseador/publicar-disponibilidad/', views_web.publicar_disponibilidad, name='publicar_disponibilidad'),
    path('paseador/paseos/<str:id_paseo>/cancelar-disponibilidad/', views_web.cancelar_disponibilidad, name='cancelar_disponibilidad'),
    path('paseador/historial/', views_web.historial_paseador, name='historial_paseador'),
    path('paseador/paseos/<str:id_paseo>/iniciar/', views_web.iniciar_paseo, name='iniciar_paseo'),
    path('paseador/paseos/<str:id_paseo>/finalizar/', views_web.finalizar_paseo, name='finalizar_paseo'),
    path('paseador/paseos/<str:id_paseo>/fotos/<str:momento>/', views_web.subir_foto, name='subir_foto'),
]
