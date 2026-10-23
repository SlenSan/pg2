from django.urls import path

from paseos import views_web

app_name = 'paseos'

urlpatterns = [
    path('', views_web.lista_disponibles, name='lista_disponibles'),
    path('mios/', views_web.mis_paseos, name='mis_paseos'),
    path('mios/estado/', views_web.estado_mis_paseos, name='estado_mis_paseos'),
    path('historial/', views_web.historial, name='historial'),
    path('paseadores/<str:id_paseador>/', views_web.detalle_paseador, name='detalle_paseador'),
    path(
        'paseadores/<str:id_paseador>/horarios/<str:id_paseo>/inscribir/',
        views_web.inscribir_en_horario,
        name='inscribir_en_horario',
    ),
    path('paseador/publicar-disponibilidad/', views_web.publicar_disponibilidad, name='publicar_disponibilidad'),
    path('paseador/paseos/<str:id_paseo>/cancelar-disponibilidad/', views_web.cancelar_disponibilidad, name='cancelar_disponibilidad'),
    path('paseador/historial/', views_web.historial_paseador, name='historial_paseador'),
    path('paseador/paseos/<str:id_paseo>/iniciar/', views_web.iniciar_paseo, name='iniciar_paseo'),
    path('paseador/paseos/<str:id_paseo>/finalizar/', views_web.finalizar_paseo, name='finalizar_paseo'),
    path(
        'paseador/paseos/<str:id_paseo>/recogidas/<str:id_dueno>/fotos/<str:momento>/',
        views_web.subir_foto,
        name='subir_foto',
    ),
    # INC-12 - antes de las recogidas por dueño, un paseo legacy (sin
    # `recogidas`) sigue subiendo al arreglo viejo compartido; no tiene
    # un dueño que elegir, de ahi esta segunda ruta sin id_dueno.
    path('paseador/paseos/<str:id_paseo>/fotos/<str:momento>/', views_web.subir_foto, name='subir_foto_legacy'),
    # Incremento 4 fase 3, punto A2 - una recogida por dueño dentro del paseo.
    path(
        'paseador/paseos/<str:id_paseo>/recogidas/<str:id_dueno>/recoger/',
        views_web.marcar_recogida,
        name='marcar_recogida',
    ),
    path(
        'paseador/paseos/<str:id_paseo>/recogidas/<str:id_dueno>/no-recogida/',
        views_web.marcar_no_recogida,
        name='marcar_no_recogida',
    ),
    path(
        'paseador/paseos/<str:id_paseo>/recogidas/<str:id_dueno>/entregar/',
        views_web.marcar_entrega,
        name='marcar_entrega',
    ),
]
