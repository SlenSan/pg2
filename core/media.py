"""
Subida de imagenes a Cloudinary, compartida por todo el proyecto.

Se usa Cloudinary (capa gratuita) en vez del filesystem de Render porque
este ultimo es efimero: cualquier archivo guardado localmente se pierde en
el proximo redeploy o reinicio del dyno. Cloudinary persiste el archivo y
devuelve una URL publica (https) que es justo lo que el esquema de Mongo
espera guardar en los campos de tipo foto/foto_perfil/evidencia_foto
(siempre String, nunca un binario).

Uso:
    from core.media import subir_imagen
    url = subir_imagen(request.FILES['foto'], carpeta='mascotas')
    # url -> "https://res.cloudinary.com/.../canigo/mascotas/xxxx.jpg"

`carpeta` agrupa los archivos dentro de Cloudinary por modulo:
"usuarios" (foto_perfil), "mascotas" (foto), "paseos" (fotos de
inicio/mitad/fin) e "incidentes" (evidencia_foto).
"""

import re
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader
from cloudinary.exceptions import Error as CloudinaryError
from django.conf import settings

_configurado = False


class ErrorSubidaImagen(Exception):
    """Error al configurar Cloudinary o al subir una imagen."""


def _asegurar_configuracion():
    global _configurado
    if _configurado:
        return
    if not settings.CLOUDINARY_URL:
        raise ErrorSubidaImagen(
            'CLOUDINARY_URL no está configurado. Define la variable de entorno '
            'CLOUDINARY_URL (ver .env.example).'
        )
    parsed = urlparse(settings.CLOUDINARY_URL)
    if parsed.scheme != 'cloudinary' or not all([parsed.hostname, parsed.username, parsed.password]):
        raise ErrorSubidaImagen(
            'CLOUDINARY_URL tiene un formato invalido. Debe ser '
            'cloudinary://<api_key>:<api_secret>@<cloud_name>.'
        )
    cloudinary.config(
        cloud_name=parsed.hostname,
        api_key=parsed.username,
        api_secret=parsed.password,
        secure=True,
    )
    _configurado = True


def subir_imagen(archivo, carpeta):
    """
    Sube `archivo` (un UploadedFile de Django, p.ej. request.FILES['foto'])
    a Cloudinary y devuelve su URL segura (https) como string.

    Lanza ErrorSubidaImagen si Cloudinary no esta configurado o si la
    subida falla (red, credenciales, archivo invalido, etc.).
    """
    _asegurar_configuracion()
    try:
        resultado = cloudinary.uploader.upload(archivo, folder=f'canigo/{carpeta}')
    except CloudinaryError as exc:
        raise ErrorSubidaImagen(f'No se pudo subir la imagen a Cloudinary: {exc}') from exc
    return resultado['secure_url']


def _public_id_desde_url(url):
    """
    El esquema de Mongo solo guarda la URL de la imagen (nunca su
    public_id - ver CLAUDE.md, `foto: String`), asi que para borrarla de
    Cloudinary al reemplazarla hay que reconstruir el public_id a partir
    de la URL misma: todo lo que sigue a "/upload/", sin el segmento de
    version ("v1234567/") si esta presente, y sin la extension final.
    None si la URL no tiene la forma esperada (por ejemplo, quedo vacia o
    es de otro origen) - en ese caso no se intenta borrar nada.
    """
    try:
        despues_de_upload = url.split('/upload/', 1)[1]
    except (IndexError, AttributeError):
        return None
    despues_de_upload = re.sub(r'^v\d+/', '', despues_de_upload)
    return despues_de_upload.rsplit('.', 1)[0] or None


def eliminar_imagen(url):
    """
    Borra de Cloudinary la imagen en `url`, si se le pudo determinar un
    public_id (ver _public_id_desde_url). Es "mejor esfuerzo": si no se
    puede (URL con forma inesperada, Cloudinary no configurado, fallo de
    red), no lanza - el llamador ya guardo el reemplazo en Mongo, esto es
    solo limpieza del archivo viejo, no debe tumbar el flujo principal.
    """
    public_id = _public_id_desde_url(url)
    if not public_id:
        return
    try:
        _asegurar_configuracion()
        cloudinary.uploader.destroy(public_id)
    except (CloudinaryError, ErrorSubidaImagen):
        pass
