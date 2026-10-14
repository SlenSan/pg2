from django import forms


class ObservacionForm(forms.Form):
    """Observacion opcional al marcar/retirar la verificacion de un paseador."""

    observacion = forms.CharField(
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )


class AsignarContrasenaTemporalForm(forms.Form):
    """
    Mejora 2 (hallazgos de la prueba con un usuario final, 14 de
    octubre) - busca la cuenta a la que se le va a asignar una
    contraseña temporal, por su correo. La normalización/el lookup
    case-insensitive los hace `usuarios.repository.obtener_por_correo()`
    (ya los hace para cualquier correo que llegue, sin importar cómo se
    haya escrito) - este form solo valida que sea un correo con formato
    válido.
    """

    correo = forms.EmailField(
        max_length=254,
        label='Correo de la cuenta',
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )
