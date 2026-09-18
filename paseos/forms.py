from django import forms


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
