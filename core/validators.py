"""Validadores de formulario compartidos por varias apps del proyecto."""

import re

from django import forms

# Celular colombiano: 10 digitos, empieza en 3 (operadores moviles) - ver
# CLAUDE.md, telefono es obligatorio para los dos roles. Movido aca desde
# usuarios/forms.py (Incremento 4 fase 3, punto A1) - paseos/forms.py
# tambien necesita validar un telefono de contacto (datos de recogida),
# asi que esto deja de ser exclusivo de un solo formulario/app.
_PATRON_TELEFONO_COLOMBIANO = re.compile(r'^3\d{9}$')


def limpiar_telefono(telefono):
    """Quita espacios y guiones antes de validar - '300 123 4567' y
    '300-123-4567' son formas comunes de escribir el mismo numero."""
    return re.sub(r'[\s-]', '', telefono or '')


def validar_telefono_colombiano(telefono):
    telefono = limpiar_telefono(telefono)
    if not _PATRON_TELEFONO_COLOMBIANO.match(telefono):
        raise forms.ValidationError(
            'Ingresa un celular colombiano válido: 10 dígitos que empiecen en 3 (ej. 3001234567).'
        )
    return telefono
