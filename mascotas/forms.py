from datetime import date

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
    foto = forms.ImageField(
        required=False,
        label='Foto (opcional)',
        widget=forms.ClearableFileInput(attrs={'class': _INPUT_CLASS}),
    )


class CertificadosMascotaForm(forms.Form):
    """
    Subida de certificado_salud/carne_vacunacion (Ley 2480 de 2025, Ley
    Kiara) - ambos archivos son independientes y opcionales: se puede
    subir uno, el otro, los dos, o ninguno (aunque la vista exige al
    menos uno). El formato/tamaño del archivo se valida en
    core/media.py::subir_certificado (backend obligatorio); aca solo se
    valida la fecha de expedición, que es dato de formulario, no del
    archivo.
    """

    certificado_salud = forms.FileField(
        required=False,
        label='Certificado de salud (JPG, PNG o PDF, máx. 5MB)',
        widget=forms.ClearableFileInput(attrs={'class': _INPUT_CLASS}),
    )
    fecha_expedicion_salud = forms.DateField(
        required=False,
        label='Fecha de expedición del certificado de salud',
        widget=forms.DateInput(attrs={'class': _INPUT_CLASS, 'type': 'date'}),
    )
    carne_vacunacion = forms.FileField(
        required=False,
        label='Carné de vacunación (JPG, PNG o PDF, máx. 5MB)',
        widget=forms.ClearableFileInput(attrs={'class': _INPUT_CLASS}),
    )

    def clean(self):
        cleaned = super().clean()
        archivo_salud = cleaned.get('certificado_salud')
        fecha = cleaned.get('fecha_expedicion_salud')
        if archivo_salud and not fecha:
            self.add_error(
                'fecha_expedicion_salud',
                'La fecha de expedición es obligatoria para subir el certificado de salud.',
            )
        elif fecha and fecha > date.today():
            self.add_error('fecha_expedicion_salud', 'La fecha de expedición no puede ser futura.')
        if not archivo_salud and not cleaned.get('carne_vacunacion'):
            self.add_error(None, 'Sube al menos un archivo (certificado de salud o carné de vacunación).')
        return cleaned
