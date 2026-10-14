from django import forms

from paseos.repository import ZONAS_VALIDAS, etiqueta_zona


class PublicarHorarioForm(forms.Form):
    """
    Publicar un horario nuevo (RF5): solo hora, sin selector de fecha -
    el horario se entiende siempre para HOY. Mas simple de implementar
    bien que un datetime-local (evita una tercera superficie del mismo
    bug de zona horaria ya encontrado en el mapa y en notificaciones), y
    coherente con que la plataforma ya funciona en tiempo real ("paseadores
    disponibles AHORA").
    """
    desde = forms.TimeField(
        label='Desde',
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
    )
    hasta = forms.TimeField(
        label='Hasta',
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
    )
    # MultipleChoiceField: selección múltiple, de 1 a N zonas -
    # INC-09 (hallazgos de la prueba con un usuario final, 14 de
    # octubre): antes era required=False (0 a N, "[] significa 'no
    # especificó zona'" - ver CLAUDE.md), pero eso permitía publicar un
    # horario sin ninguna comuna, invisible para cualquier filtro por
    # zona ("Paseadores disponibles" lo mostraba solo sin filtrar -
    # confuso para el dueño, que no entendía en qué zona atendía ese
    # paseador). Ahora exige al menos una, con el mismo patrón ya
    # establecido en InscribirMascotaForm.ids_mascota (required=True,
    # que ya rechaza una selección vacía sin necesitar un clean()
    # aparte, más un mensaje de error propio). choices=ZONAS_VALIDAS es
    # la validacion de backend "gratis": Django ya rechaza cualquier
    # valor fuera de esa lista fija al llamar is_valid(), sin codigo
    # extra. attrs={'class': 'zona-chip-input'} en el WIDGET (no a mano
    # en la plantilla con {{ casilla.tag }}): asi cualquier plantilla
    # que renderice este campo la trae puesta por construccion. Sin
    # esto, el checkbox se renderizaba sin clase -> la regla CSS
    # ".zona-chip-input { opacity: 0; position: absolute; ... }" nunca
    # aplicaba (confirmado con getComputedStyle: opacity "1", position
    # "static"), dejando la casilla visible y desalineada de su propia
    # etiqueta en el grid - de ahi que se pudiera marcar la zona vecina
    # por error (bug (b) del reporte de hallazgos).
    zonas = forms.MultipleChoiceField(
        label='Zonas de servicio',
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'zona-chip-input'}),
        error_messages={'required': 'Elige al menos una zona de servicio.'},
        # El VALOR sigue siendo el nombre a secas (lo que se guarda en
        # Mongo, sin cambios - Incremento 4, punto G) - solo la ETIQUETA
        # visible cambia a "Comuna N. Nombre", vía la misma
        # etiqueta_zona() que usa cualquier otra pantalla.
        choices=[(z, etiqueta_zona(z)) for z in ZONAS_VALIDAS],
    )

    def clean(self):
        cleaned = super().clean()
        desde = cleaned.get('desde')
        hasta = cleaned.get('hasta')
        if desde and hasta and hasta <= desde:
            self.add_error('hasta', 'La hora de fin debe ser posterior a la de inicio.')
        return cleaned


class SubirFotoPaseoForm(forms.Form):
    foto = forms.ImageField(
        label='Foto',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
    )


class InscribirMascotaForm(forms.Form):
    """
    Checkboxes en vez de un <select>: un paseo puede llevar una o varias
    mascotas del mismo dueño juntas (ver CLAUDE.md). required=True (el
    default de MultipleChoiceField) ya rechaza una seleccion vacia sin
    necesitar un clean() aparte.
    """
    ids_mascota = forms.MultipleChoiceField(
        label='Elige tu(s) mascota(s)',
        widget=forms.CheckboxSelectMultiple,
        error_messages={'required': 'Elige al menos una mascota.'},
    )

    def __init__(self, *args, mascotas=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ids_mascota'].choices = [
            (str(mascota['_id']), mascota['nombre']) for mascota in (mascotas or [])
        ]
