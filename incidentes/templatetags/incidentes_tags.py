"""
Filtro de plantilla para mostrar el tipo de un incidente con su etiqueta
legible en vez de su valor interno (INC-06, 13 oct) - mismo patrón que
paseos/templatetags/paseos_tags.py::etiqueta_zona.
"""
from django import template

from incidentes import repository

register = template.Library()


@register.filter
def etiqueta_tipo_incidente(tipo):
    return repository.etiqueta_tipo_incidente(tipo)
