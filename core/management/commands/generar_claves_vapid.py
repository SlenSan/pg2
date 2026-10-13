"""
Genera un par de claves VAPID nuevo para Web Push (Incremento 4, fase 2,
punto E) y lo imprime por stdout - NUNCA se guarda en el repositorio.

Uso: `python manage.py generar_claves_vapid`, copiar la salida a .env
(local) y a las variables de entorno de Render (producción) - ver
.env.example para los nombres exactos. Un par de claves sirve para TODO
el despliegue (no una por usuario); generar uno nuevo invalida las
suscripciones push ya guardadas (sus navegadores quedan firmando contra
una clave pública que el servidor ya no reconoce) - no se hace sin
avisar.
"""
from django.core.management.base import BaseCommand
from py_vapid import Vapid02
from py_vapid.utils import b64urlencode


class Command(BaseCommand):
    help = 'Genera un par de claves VAPID nuevo para Web Push (no las guarda en ningún lado).'

    def handle(self, *args, **options):
        vapid = Vapid02()
        vapid.generate_keys()

        # Privada: el ENTERO de 32 bytes en "forma cruda" (RFC8292), no
        # el PEM completo - mas corto, una sola linea, sin encabezados
        # ni saltos de linea, mas comodo para una variable de entorno.
        # pywebpush.webpush(vapid_private_key=...) la reconoce igual
        # (Vapid.from_string prueba RAW primero, DER despues).
        numero_privado = vapid.private_key.private_numbers().private_value
        clave_privada = b64urlencode(numero_privado.to_bytes(32, 'big'))

        # Publica: punto EC sin comprimir (65 bytes) en base64url - es
        # EXACTAMENTE lo que el navegador espera como
        # `applicationServerKey` en pushManager.subscribe().
        from cryptography.hazmat.primitives import serialization
        clave_publica = b64urlencode(vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        ))

        self.stdout.write(self.style.SUCCESS('Par de claves VAPID generado:'))
        self.stdout.write('')
        self.stdout.write(f'VAPID_PRIVATE_KEY={clave_privada}')
        self.stdout.write(f'VAPID_PUBLIC_KEY={clave_publica}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            'Copia estas dos líneas a .env (local) y a las variables de entorno '
            'de Render (producción) - nunca al repositorio. Agrega también '
            'VAPID_CLAIMS_EMAIL con un correo de contacto real (lo exige la '
            'especificación VAPID, igual que NOMINATIM_USER_AGENT).'
        ))
