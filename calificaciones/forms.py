from django import forms

_OPCIONES_PUNTUACION = [(n, f'{n} estrella{"s" if n != 1 else ""}') for n in range(5, 0, -1)]


class CalificacionForm(forms.Form):
    puntuacion = forms.ChoiceField(
        choices=_OPCIONES_PUNTUACION,
        label='Puntuación',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    comentario = forms.CharField(
        required=False,
        label='Comentario (opcional)',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
