from django import forms

_INPUT_CLASS = 'form-control'

_OPCIONES_TIPO = [
    ('fuga_animal', 'Fuga del animal'),
    ('mordedura_agresion', 'Mordedura o agresión'),
    ('accidente_animal', 'Accidente del animal'),
    ('accidente_paseador', 'Accidente del paseador'),
    ('otro', 'Otro'),
]


class ReportarIncidenteForm(forms.Form):
    tipo = forms.ChoiceField(
        choices=_OPCIONES_TIPO,
        label='Tipo de incidente',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    descripcion = forms.CharField(
        label='Descripción breve',
        widget=forms.Textarea(attrs={'class': _INPUT_CLASS, 'rows': 3}),
    )
    foto = forms.ImageField(
        label='Foto de evidencia',
        widget=forms.ClearableFileInput(attrs={'class': _INPUT_CLASS}),
    )
