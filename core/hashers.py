"""
Hasher de contraseñas propio del proyecto (lentitud en producción, 14
de octubre - decisión de la autora tras medir el costo real de
check_password()).

Django 5.2 trae PBKDF2PasswordHasher con 1.000.000 de iteraciones por
defecto - medido en Render (plan gratuito, CPU compartida y limitada),
el POST de login tardaba 2.4-3.1s por este motivo (confirmado: es el
único paso del flujo cuyo costo es puro CPU, ver MANUAL_DESARROLLADOR.md,
"Lentitud en producción"). 600.000 es el mínimo que recomienda
actualmente el OWASP Password Storage Cheat Sheet para PBKDF2-HMAC-SHA256:
https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
("use PBKDF2 with a work factor of 600,000 or more [...] with an
internal hash function of HMAC-SHA-256") - reduce el costo de CPU sin
bajar de ese mínimo.
"""

from django.contrib.auth.hashers import PBKDF2PasswordHasher


class PBKDF2HasherOWASP600k(PBKDF2PasswordHasher):
    """
    Igual que PBKDF2PasswordHasher de Django, solo con menos
    iteraciones. `algorithm` se hereda sin cambios ('pbkdf2_sha256') a
    propósito: una contraseña YA guardada con 1.000.000 de iteraciones
    (hasheada antes de este cambio) sigue siendo reconocida y validada
    por esta misma clase (Django lee el número real de iteraciones
    DESDE el propio hash guardado al verificar, no desde este
    atributo) - `self.iterations` solo se usa para generar un hash
    NUEVO. Ver `usuarios.views_web.login()` para el re-hash automático
    de una cuenta vieja al iniciar sesión.
    """

    iterations = 600_000
