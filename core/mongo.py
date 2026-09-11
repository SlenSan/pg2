"""
Cliente de MongoDB Atlas compartido para todo el proyecto.

Django (sqlite) solo maneja su propia maquinaria interna (admin, sessions,
auth). Las colecciones de negocio de Canigo (usuarios, mascotas, paseos,
coordenadas_detalle, incidentes, calificaciones, notificaciones) viven en
MongoDB Atlas y se acceden aquí directamente vía pymongo.

Uso:
    from core.mongo import get_db
    db = get_db()
    db.usuarios.find_one(...)
"""

from django.conf import settings
from pymongo import MongoClient
from pymongo.server_api import ServerApi

_client = None


def get_client() -> MongoClient:
    """Devuelve un MongoClient singleton (reutiliza el pool de conexiones)."""
    global _client
    if _client is None:
        if not settings.MONGO_URI:
            raise RuntimeError(
                'MONGO_URI no está configurado. Define la variable de entorno '
                'MONGO_URI (ver .env.example).'
            )
        _client = MongoClient(settings.MONGO_URI, server_api=ServerApi('1'))
    return _client


def get_db():
    """Devuelve la base de datos de Canigo configurada en MONGO_DB_NAME."""
    return get_client()[settings.MONGO_DB_NAME]
