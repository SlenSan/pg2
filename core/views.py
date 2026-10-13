from django.conf import settings
from django.http import JsonResponse

from pymongo.errors import PyMongoError

from core.mongo import get_db
from usuarios.decorators import requiere_admin


def _db_status(request):
    """Endpoint de prueba: confirma que la conexión a MongoDB Atlas funciona."""
    try:
        db = get_db()
    except RuntimeError as exc:
        return JsonResponse({
            'status': 'error',
            'detalle': str(exc),
        }, status=500)

    try:
        db.command('ping')
        collections = db.list_collection_names()
        return JsonResponse({
            'status': 'conectado',
            'database': db.name,
            'colecciones': collections,
        })
    except PyMongoError as exc:
        return JsonResponse({
            'status': 'error',
            'detalle': str(exc),
        }, status=503)


# Incremento 4, punto F: este endpoint expone el nombre de la base de
# datos y la lista de colecciones - util como humo de diagnostico en
# desarrollo, pero no algo que deba quedar abierto a cualquiera en
# produccion. En DEBUG (local) queda sin restriccion, igual que siempre;
# fuera de DEBUG se exige la MISMA cuenta admin que protege
# /administracion/verificacion/ (usuarios.decorators.requiere_admin) -
# 404 para cualquiera que no sea admin, sin revelar que la ruta existe.
# Evaluado una sola vez al cargar el modulo (mismo momento en que
# settings.py arma SECURE_SSL_REDIRECT y el resto segun DEBUG) - este
# proyecto no cambia DEBUG en caliente.
db_status = _db_status if settings.DEBUG else requiere_admin(_db_status)
