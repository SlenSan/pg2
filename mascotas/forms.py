from django import forms

_INPUT_CLASS = 'form-control'


class MascotaForm(forms.Form):
    nombre = forms.CharField(
        max_length=100,
        label='Nombre',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    raza = forms.CharField(
        max_length=100,
        label='Raza',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    edad = forms.IntegerField(
        min_value=0,
        label='Edad (años)',
        widget=forms.NumberInput(attrs={'class': _INPUT_CLASS}),
    )
    peso = forms.FloatField(
        min_value=0,
        label='Peso (kg)',
        widget=forms.NumberInput(attrs={'class': _INPUT_CLASS, 'step': '0.1'}),
    )
    observaciones = forms.CharField(
        required=False,
        label='Observaciones (alergias, comportamiento, etc.)',
        widget=forms.Textarea(attrs={'class': _INPUT_CLASS, 'rows': 3}),
    )
