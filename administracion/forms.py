from django import forms


class ObservacionForm(forms.Form):
    """Observacion opcional al marcar/retirar la verificacion de un paseador."""

    observacion = forms.CharField(
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )
