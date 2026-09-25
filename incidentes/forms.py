from django import forms

_INPUT_CLASS = 'form-control'

_OPCIONES_TIPO = [
    ('fuga_animal', 'Fuga del animal'),
    ('mordedura_agresion', 'Mordedura o agresión'),
    ('accidente_animal', 'Accidente del animal'),
    ('accidente_paseador', 'Accidente del paseador'),
    ('otro', 'Otro'),
]


_TIPO_SIN_MASCOTA = 'accidente_paseador'


class ReportarIncidenteForm(forms.Form):
    """
    id_mascota: a cual de las mascotas del paseo afecta el incidente (ver
    CLAUDE.md - null solo para "accidente_paseador", que no involucra a
    ningun animal). Se agrega dinamicamente en __init__ SOLO si el paseo
    lleva mas de una mascota - con una sola, no tiene sentido preguntar
    (se asigna sola en la vista) y no se le agrega friccion al caso mas
    comun.
    """
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

    def __init__(self, *args, mascotas=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.mascotas = mascotas or []
        if len(self.mascotas) > 1:
            self.fields['id_mascota'] = forms.ChoiceField(
                label='¿A cuál mascota afecta?',
                required=False,
                choices=[(str(m['_id']), m['nombre']) for m in self.mascotas],
                widget=forms.RadioSelect,
            )

    def clean(self):
        cleaned = super().clean()
        if 'id_mascota' in self.fields:
            if cleaned.get('tipo') != _TIPO_SIN_MASCOTA and not cleaned.get('id_mascota'):
                self.add_error('id_mascota', 'Selecciona a cuál mascota afecta este incidente.')
        return cleaned
