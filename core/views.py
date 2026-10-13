from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from pymongo.errors import PyMongoError

from core.mongo import get_db
from usuarios.decorators import requiere_admin

_ROOT_FILES_DIR = Path(__file__).resolve().parent / 'root_files'
# Leidos UNA sola vez al cargar el modulo (son estaticos, nunca cambian
# en tiempo de ejecucion) - evita un read de disco en cada request.
_MANIFEST_CONTENIDO = (_ROOT_FILES_DIR / 'manifest.webmanifest').read_bytes()
_SERVICE_WORKER_CONTENIDO = (_ROOT_FILES_DIR / 'sw.js').read_bytes()


def manifest(request):
    """
    `manifest.webmanifest` (Incremento 4, fase 2, punto E) - servido
    desde la RAIZ del sitio (/manifest.webmanifest), no bajo /static/,
    para que quede junto al `start_url`/`scope` ("/") que declara - ver
    core/root_files/manifest.webmanifest. WhiteNoise sirve /static/, no
    la raiz, de ahi esta vista en vez de un archivo estatico a secas.
    """
    return HttpResponse(_MANIFEST_CONTENIDO, content_type='application/manifest+json')


def service_worker(request):
    """
    `sw.js` (Incremento 4, fase 2, punto E) - servido desde la RAIZ
    (/sw.js, no /static/sw.js): el alcance (scope) por defecto de un
    service worker es su propio directorio - si viviera bajo /static/,
    solo podria controlar esa carpeta, no el sitio entero (push,
    notificationclick). Ver core/root_files/sw.js.

    `Cache-Control: no-cache` explícito (revisión de fase 2, punto 2):
    antes esta vista no mandaba ningún header de caché, así que un
    cambio futuro a sw.js podía tardar en llegarle a un navegador que ya
    tuviera una copia cacheada - "no-cache" NO significa "no guardar
    nada" (eso sería "no-store"): el navegador SÍ puede quedarse con una
    copia, pero está obligado a revalidarla con el servidor (GET
    condicional, que puede devolver 304 sin volver a mandar el archivo)
    antes de usarla, en vez de confiar en ella a ciegas por el tiempo
    que decida su propia heurística.
    """
    return HttpResponse(
        _SERVICE_WORKER_CONTENIDO,
        content_type='application/javascript',
        headers={'Cache-Control': 'no-cache'},
    )


def privacidad(request):
    """
    RNF1/Ley 1581 de 2012 (cierre de auditoría, punto 1) - página pública
    (sin sesión requerida: hay que poder leerla ANTES de aceptarla, tanto
    desde el registro como desde la pantalla intermedia de
    usuarios.views_web.autorizar_datos). El texto vive entero en el
    template (core/templates/core/privacidad.html) - esta vista no agrega
    ni calcula nada, solo lo renderiza.
    """
    return render(request, 'core/privacidad.html')


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
