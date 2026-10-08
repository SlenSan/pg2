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
from pathlib import Path
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader
from cloudinary.exceptions import Error as CloudinaryError
from django.conf import settings

_configurado = False


class ErrorSubidaImagen(Exception):
    """Error al configurar Cloudinary o al subir una imagen."""


class ErrorArchivoInvalido(Exception):
    """Un certificado (mascota o paseador) no cumple formato/tamaño/contenido esperado."""


# Firmas (primeros bytes) de los formatos permitidos para certificados -
# la extension declarada en el nombre del archivo NO basta (se puede
# renombrar cualquier archivo a .pdf), asi que se confirma tambien el
# contenido real. "jpg" cubre tanto .jpg como .jpeg.
_FIRMAS_POR_TIPO = {
    'jpg': (b'\xff\xd8\xff',),
    'png': (b'\x89PNG\r\n\x1a\n',),
    'pdf': (b'%PDF-',),
}
_EXTENSIONES_POR_TIPO = {
    'jpg': {'.jpg', '.jpeg'},
    'png': {'.png'},
    'pdf': {'.pdf'},
}


def _tipo_por_extension(nombre_archivo):
    extension = Path(nombre_archivo).suffix.lower()
    return next((tipo for tipo, exts in _EXTENSIONES_POR_TIPO.items() if extension in exts), None)


def _tipo_por_contenido(archivo):
    archivo.seek(0)
    inicio = archivo.read(8)
    archivo.seek(0)
    for tipo, firmas in _FIRMAS_POR_TIPO.items():
        if any(inicio.startswith(firma) for firma in firmas):
            return tipo
    return None


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


_TAMANO_MAXIMO_CERTIFICADO_MB = 5


def subir_certificado(archivo, carpeta):
    """
    Sube un certificado (imagen JPG/PNG o PDF - carné de vacunación,
    certificado de salud, certificados del paseador) a Cloudinary.
    `resource_type="auto"` porque, a diferencia de subir_imagen(), este
    archivo puede ser un PDF - con resource_type="image" (el default de
    la API) Cloudinary rechaza los PDF.

    Valida, en este orden: extensión permitida (.jpg/.jpeg/.png/.pdf),
    tamaño (máx. 5MB) y que el CONTENIDO real del archivo (sus primeros
    bytes) coincida con la extensión declarada - no basta con confiar en
    el nombre del archivo. Lanza ErrorArchivoInvalido si no pasa alguna
    de las tres, o si Cloudinary rechaza la subida.

    Devuelve {'url', 'public_id', 'formato'} - a diferencia de
    subir_imagen(), aquí SÍ se guarda el public_id (en el subdocumento
    de certificado, ver mascotas/usuarios.repository), porque estos
    certificados sí se pueden reemplazar/borrar individualmente.
    """
    tipo_declarado = _tipo_por_extension(archivo.name)
    if tipo_declarado is None:
        raise ErrorArchivoInvalido('Formato no permitido. Solo se aceptan JPG, PNG o PDF.')

    if archivo.size > _TAMANO_MAXIMO_CERTIFICADO_MB * 1024 * 1024:
        raise ErrorArchivoInvalido(f'El archivo supera el tamaño máximo permitido ({_TAMANO_MAXIMO_CERTIFICADO_MB} MB).')

    if _tipo_por_contenido(archivo) != tipo_declarado:
        raise ErrorArchivoInvalido(
            'El contenido del archivo no coincide con su extensión. Verifica que no esté dañado o renombrado.'
        )

    _asegurar_configuracion()
    try:
        resultado = cloudinary.uploader.upload(archivo, folder=f'canigo/{carpeta}', resource_type='auto')
    except CloudinaryError as exc:
        raise ErrorArchivoInvalido(f'No se pudo subir el archivo a Cloudinary: {exc}') from exc
    return {
        'url': resultado['secure_url'],
        'public_id': resultado['public_id'],
        'formato': resultado.get('format', tipo_declarado),
    }


def eliminar_archivo(public_id):
    """
    Borra de Cloudinary un certificado por su public_id (a diferencia de
    eliminar_imagen(), aquí no hace falta reconstruirlo desde la URL -
    el subdocumento del certificado ya lo guarda). resource_type="auto"
    al subir no es un valor válido para destroy(); Cloudinary resuelve
    un PDF como "image" normalmente, así que se intenta ahí primero y se
    cae a "raw"/"video" como mejor esfuerzo - de nuevo, sin lanzar si
    falla, es solo limpieza.
    """
    if not public_id:
        return
    try:
        _asegurar_configuracion()
    except ErrorSubidaImagen:
        return
    for tipo_recurso in ('image', 'raw', 'video'):
        try:
            resultado = cloudinary.uploader.destroy(public_id, resource_type=tipo_recurso)
            if resultado.get('result') == 'ok':
                return
        except CloudinaryError:
            continue
