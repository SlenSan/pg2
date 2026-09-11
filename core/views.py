from django.http import JsonResponse

from pymongo.errors import PyMongoError

from core.mongo import get_db


def db_status(request):
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
