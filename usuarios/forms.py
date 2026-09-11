from django import forms

_INPUT_CLASS = 'form-control'


class RegistroDuenoForm(forms.Form):
    nombre = forms.CharField(
        max_length=150,
        label='Nombre completo',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    correo = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'class': _INPUT_CLASS}),
    )
    telefono = forms.CharField(
        max_length=30,
        label='Teléfono',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    direccion = forms.CharField(
        max_length=255,
        required=False,
        label='Dirección',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    contrasena = forms.CharField(
        min_length=8,
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': _INPUT_CLASS}),
    )
    confirmar_contrasena = forms.CharField(
        label='Confirmar contraseña',
        widget=forms.PasswordInput(attrs={'class': _INPUT_CLASS}),
    )

    def clean(self):
        cleaned = super().clean()
        contrasena = cleaned.get('contrasena')
        confirmar = cleaned.get('confirmar_contrasena')
        if contrasena and confirmar and contrasena != confirmar:
            self.add_error('confirmar_contrasena', 'Las contraseñas no coinciden.')
        return cleaned


class LoginForm(forms.Form):
    correo = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'class': _INPUT_CLASS}),
    )
    contrasena = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': _INPUT_CLASS}),
    )
