from django import forms


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
    id_mascota = forms.ChoiceField(
        label='Elige tu mascota',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, mascotas=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['id_mascota'].choices = [
            (str(mascota['_id']), mascota['nombre']) for mascota in (mascotas or [])
        ]
