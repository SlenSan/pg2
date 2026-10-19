"""Widgets de formulario compartidos por el proyecto."""

from django import forms


class CamaraOArchivoWidget(forms.ClearableFileInput):
    """
    Ajustes del 19 de octubre, punto 2 - para un campo de documento que
    admite imagen O PDF (certificado de salud, carné de vacunación,
    certificados del paseador): un solo `<input type="file">` con
    `accept="image/*,application/pdf"` hace que Safari en iPhone ofrezca
    "Tomar foto O VIDEO" en el panel nativo (cualquier `accept` que
    admita algo más que imágenes activa esa opción) - no hay forma de
    evitarlo con un único control.

    Dos botones en vez de uno (ver la plantilla de este widget), que
    SOLO le cambian `accept`/`capture` al MISMO `<input>` antes de
    abrirlo (una sola función compartida en `core/templates/base.html`,
    no un script por campo):
      - "Tomar foto": `accept="image/*"` + `capture="environment"` -
        abre la cámara, sin ofrecer video ni la galería.
      - "Elegir archivo": vuelve al `accept` original del campo (imagen
        o PDF) sin `capture` - abre el selector nativo normal.

    Mantiene intacto el comportamiento de `ClearableFileInput`
    ("Currently: X / Clear" para un archivo ya subido) - la plantilla
    solo reemplaza la parte final (el propio `<input>`).
    """

    template_name = 'core/widgets/camara_o_archivo.html'

    def __init__(self, attrs=None, *, accept='image/*,application/pdf'):
        attrs = dict(attrs or {})
        attrs.setdefault('accept', accept)
        super().__init__(attrs=attrs)
