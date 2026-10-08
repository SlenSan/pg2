from django.urls import path

from administracion import views_web

app_name = 'administracion'

urlpatterns = [
    path('verificacion/', views_web.verificacion, name='verificacion'),
    path('verificacion/<str:id_paseador>/marcar/', views_web.marcar_verificado, name='marcar_verificado'),
    path('verificacion/<str:id_paseador>/retirar/', views_web.retirar_verificado, name='retirar_verificado'),
]
