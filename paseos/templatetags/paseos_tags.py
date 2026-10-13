"""
Filtros de plantilla para que CUALQUIER template use el mismo formato de
zona sin duplicar la lógica - Incremento 4, punto G. Registrados como
filtro (no tag) para poder usarse tanto sobre un valor suelto
(`{{ zona|etiqueta_zona }}`) como dentro de un `{% for %}`.
"""
from django import template

from paseos import repository

register = template.Library()


@register.filter
def etiqueta_zona(nombre_zona):
    return repository.etiqueta_zona(nombre_zona)
