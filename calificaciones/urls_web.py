from django.urls import path

from calificaciones import views_web

app_name = 'calificaciones'

urlpatterns = [
    path('paseos/<str:id_paseo>/nueva/', views_web.calificar_paseo, name='calificar_paseo'),
]
