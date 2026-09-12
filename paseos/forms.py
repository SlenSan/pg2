from django import forms


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
