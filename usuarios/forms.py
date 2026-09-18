from django import forms

_INPUT_CLASS = 'form-control'


class _RegistroBaseForm(forms.Form):
    """Campos comunes a los dos roles. dueño y paseador comparten la misma
    plataforma web (ver CLAUDE.md) — solo cambia si se pide `descripcion`."""

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


class RegistroDuenoForm(_RegistroBaseForm):
    direccion = forms.CharField(
        max_length=255,
        required=False,
        label='Dirección',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )


class RegistroPaseadorForm(_RegistroBaseForm):
    descripcion = forms.CharField(
        required=False,
        label='Cuéntale a los dueños sobre ti',
        widget=forms.Textarea(attrs={'class': _INPUT_CLASS, 'rows': 3}),
    )


class EditarPerfilPaseadorForm(forms.Form):
    """
    correo/rol/calificacion_promedio/verificado no se editan aqui: correo
    es el identificador de login, y los otros tres los administra el
    sistema (ver CLAUDE.md), no el propio paseador.
    """

    telefono = forms.CharField(
        max_length=30,
        label='Teléfono',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    descripcion = forms.CharField(
        required=False,
        label='Cuéntale a los dueños sobre ti',
        widget=forms.Textarea(attrs={'class': _INPUT_CLASS, 'rows': 3}),
    )
    foto_perfil = forms.ImageField(
        required=False,
        label='Foto de perfil',
        widget=forms.ClearableFileInput(attrs={'class': _INPUT_CLASS}),
    )

    def __init__(self, *args, tenia_descripcion=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._tenia_descripcion = tenia_descripcion

    def clean_descripcion(self):
        descripcion = self.cleaned_data.get('descripcion', '').strip()
        if self._tenia_descripcion and not descripcion:
            raise forms.ValidationError(
                'Ya tenías una descripción escrita: no puedes dejarla vacía, solo cambiarla.'
            )
        return descripcion


class LoginForm(forms.Form):
    """Un solo formulario para ambos roles: el rol lo determina la cuenta
    que ya existe, no lo que el usuario elige al iniciar sesión."""

    correo = forms.EmailField(
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'class': _INPUT_CLASS}),
    )
    contrasena = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': _INPUT_CLASS}),
    )
