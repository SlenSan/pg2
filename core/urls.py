from django.urls import path

from core import views

urlpatterns = [
    path('db-status/', views.db_status, name='db_status'),
]
