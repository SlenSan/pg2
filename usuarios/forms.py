import re
from datetime import date

from django import forms

_INPUT_CLASS = 'form-control'

# Lista cerrada (no texto libre) - ver CLAUDE.md/consigna del punto 4.
TIPO_PRIMEROS_AUXILIOS = 'Primeros auxilios para perros'
TIPOS_CERTIFICADO_PASEADOR = (
    (TIPO_PRIMEROS_AUXILIOS, TIPO_PRIMEROS_AUXILIOS),
    ('Capacitación en cuidado o manejo canino', 'Capacitación en cuidado o manejo canino'),
    ('Otro certificado relacionado', 'Otro certificado relacionado'),
)

# Celular colombiano: 10 digitos, empieza en 3 (operadores moviles) - ver
# CLAUDE.md, teléfono es obligatorio para los dos roles y ahora se
# muestra como link "tel:" (Incremento 4, punto B), asi que vale la pena
# que lo que se guarda sea realmente marcable. Antes esto NO se validaba
# (CharField libre) - Incremento 4, punto B lo agrega.
_PATRON_TELEFONO_COLOMBIANO = re.compile(r'^3\d{9}$')


def _limpiar_telefono(telefono):
    """Quita espacios y guiones antes de validar - '300 123 4567' y
    '300-123-4567' son formas comunes de escribir el mismo numero."""
    return re.sub(r'[\s-]', '', telefono or '')


def _validar_telefono_colombiano(telefono):
    telefono = _limpiar_telefono(telefono)
    if not _PATRON_TELEFONO_COLOMBIANO.match(telefono):
        raise forms.ValidationError(
            'Ingresa un celular colombiano válido: 10 dígitos que empiecen en 3 (ej. 3001234567).'
        )
    return telefono


def _normalizar_correo(correo):
    """
    Cierre de auditoría, punto 3 (RF1) - "Test@x.com" y "test@x.com" ya
    no deben poder quedar como dos cuentas distintas. Única función que
    hace esta normalización (reusada por RegistroBaseForm y LoginForm,
    los dos lugares donde un correo escrito a mano entra al sistema) -
    mismo criterio que usuarios.decorators.es_correo_admin(), que ya
    normalizaba así desde antes de este punto.
    """
    return (correo or '').strip().lower()


class _RegistroBaseForm(forms.Form):
    """Campos comunes a los dos roles. dueño y paseador comparten la misma
    plataforma web (ver CLAUDE.md) — solo cambia si se pide `descripcion`."""

    nombre = forms.CharField(
        max_length=80,
        label='Nombre completo',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    correo = forms.EmailField(
        max_length=254,
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'class': _INPUT_CLASS}),
    )
    telefono = forms.CharField(
        max_length=20,
        label='Teléfono',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    contrasena = forms.CharField(
        min_length=8,
        max_length=128,
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': _INPUT_CLASS}),
    )
    confirmar_contrasena = forms.CharField(
        max_length=128,
        label='Confirmar contraseña',
        widget=forms.PasswordInput(attrs={'class': _INPUT_CLASS}),
    )
    # RNF1 / Ley 1581 de 2012 (cierre de auditoría, punto 1) - BooleanField
    # con required=True ya rechaza el envío en el BACKEND si la casilla no
    # viene marcada (no depende del atributo HTML "required", que se puede
    # quitar con las herramientas de desarrollador - Django valida esto del
    # lado del servidor sin importar qué llegó del navegador). El texto
    # real (con el link a /privacidad/) se escribe a mano en el template,
    # no en `label`, porque `label` no permite HTML.
    acepta_tratamiento_datos = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        error_messages={
            'required': 'Debes aceptar la política de tratamiento de datos personales para continuar.',
        },
    )

    def clean_correo(self):
        return _normalizar_correo(self.cleaned_data.get('correo'))

    def clean_telefono(self):
        return _validar_telefono_colombiano(self.cleaned_data.get('telefono', ''))

    def clean(self):
        cleaned = super().clean()
        contrasena = cleaned.get('contrasena')
        confirmar = cleaned.get('confirmar_contrasena')
        if contrasena and confirmar and contrasena != confirmar:
            self.add_error('confirmar_contrasena', 'Las contraseñas no coinciden.')
        return cleaned


class RegistroDuenoForm(_RegistroBaseForm):
    direccion = forms.CharField(
        max_length=150,
        required=False,
        label='Dirección',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )


class RegistroPaseadorForm(_RegistroBaseForm):
    descripcion = forms.CharField(
        max_length=500,
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
        max_length=20,
        label='Teléfono',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    descripcion = forms.CharField(
        max_length=500,
        required=False,
        label='Cuéntale a los dueños sobre ti',
        widget=forms.Textarea(attrs={'class': _INPUT_CLASS, 'rows': 3}),
    )
    # Mejora 1 (hallazgos de la prueba con un usuario final, 14 de
    # octubre) - accept="image/*" SIN "capture": ofrece tomar una foto
    # nueva o elegir una ya tomada, en vez de forzar la cámara.
    foto_perfil = forms.ImageField(
        required=False,
        label='Foto de perfil',
        widget=forms.ClearableFileInput(attrs={'class': _INPUT_CLASS, 'accept': 'image/*'}),
    )

    def __init__(self, *args, tenia_descripcion=False, telefono_actual=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._tenia_descripcion = tenia_descripcion
        # INC-08 (hallazgos de la prueba con un usuario final, 14 de
        # octubre) - una cuenta creada ANTES del Incremento 4 punto B
        # (437334f) puede tener un teléfono guardado que no pasa el
        # patrón actual (celular colombiano estricto, 10 dígitos que
        # empiezan en 3). Sin esto, "Guardar cambios" fallaba con un
        # error de teléfono aunque el paseador no hubiera tocado ESE
        # campo para nada - solo quería cambiar su descripción o su
        # foto. Se guarda ya limpio (sin espacios/guiones) para
        # comparar manzanas con manzanas en clean_telefono().
        self._telefono_actual_limpio = _limpiar_telefono(telefono_actual) if telefono_actual else None

    def clean_telefono(self):
        telefono = self.cleaned_data.get('telefono', '')
        telefono_limpio = _limpiar_telefono(telefono)
        if self._telefono_actual_limpio is not None and telefono_limpio == self._telefono_actual_limpio:
            # No cambió respecto al valor ya guardado - se deja pasar
            # tal cual, aunque no cumpla el patrón nuevo (dato viejo,
            # no uno que el paseador esté intentando guardar ahora).
            return telefono_limpio
        return _validar_telefono_colombiano(telefono)

    def clean_descripcion(self):
        descripcion = self.cleaned_data.get('descripcion', '').strip()
        if self._tenia_descripcion and not descripcion:
            raise forms.ValidationError(
                'Ya tenías una descripción escrita: no puedes dejarla vacía, solo cambiarla.'
            )
        return descripcion


class CertificadoPaseadorForm(forms.Form):
    """Agregar un certificado nuevo a la lista del paseador (ver
    usuarios.repository.agregar_certificado_paseador) - cada envío crea un
    certificado nuevo, no edita uno existente (para editar uno, se borra
    y se sube de nuevo)."""

    tipo = forms.ChoiceField(
        choices=TIPOS_CERTIFICADO_PASEADOR,
        label='Tipo de certificado',
        widget=forms.Select(attrs={'class': _INPUT_CLASS}),
    )
    nombre = forms.CharField(
        max_length=150,
        label='Nombre del certificado',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    entidad = forms.CharField(
        max_length=150,
        label='Entidad que lo expidió',
        widget=forms.TextInput(attrs={'class': _INPUT_CLASS}),
    )
    fecha_expedicion = forms.DateField(
        label='Fecha de expedición',
        widget=forms.DateInput(attrs={'class': _INPUT_CLASS, 'type': 'date'}),
    )
    archivo = forms.FileField(
        label='Archivo (JPG, PNG o PDF, máx. 5MB)',
        widget=forms.ClearableFileInput(attrs={'class': _INPUT_CLASS}),
    )

    def clean_fecha_expedicion(self):
        fecha = self.cleaned_data['fecha_expedicion']
        if fecha > date.today():
            raise forms.ValidationError('La fecha de expedición no puede ser futura.')
        return fecha


class LoginForm(forms.Form):
    """Un solo formulario para ambos roles: el rol lo determina la cuenta
    que ya existe, no lo que el usuario elige al iniciar sesión."""

    correo = forms.EmailField(
        max_length=254,
        label='Correo electrónico',
        widget=forms.EmailInput(attrs={'class': _INPUT_CLASS}),
    )
    contrasena = forms.CharField(
        max_length=128,
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': _INPUT_CLASS}),
    )

    def clean_correo(self):
        return _normalizar_correo(self.cleaned_data.get('correo'))


class CambiarContrasenaForzadoForm(forms.Form):
    """
    Mejora 2 (hallazgos de la prueba con un usuario final, 14 de
    octubre) - pantalla intermedia obligatoria cuando un admin le asignó
    una contraseña temporal a la cuenta (ver
    `usuarios.views_web.cambiar_contrasena_forzado`,
    `core.middleware.ExigirCambioContrasenaMiddleware`). Mismos límites
    que `_RegistroBaseForm.contrasena`/`.confirmar_contrasena`.
    """

    nueva_contrasena = forms.CharField(
        min_length=8,
        max_length=128,
        label='Nueva contraseña',
        widget=forms.PasswordInput(attrs={'class': _INPUT_CLASS}),
    )
    confirmar_contrasena = forms.CharField(
        max_length=128,
        label='Confirmar nueva contraseña',
        widget=forms.PasswordInput(attrs={'class': _INPUT_CLASS}),
    )

    def clean(self):
        cleaned = super().clean()
        nueva = cleaned.get('nueva_contrasena')
        confirmar = cleaned.get('confirmar_contrasena')
        if nueva and confirmar and nueva != confirmar:
            self.add_error('confirmar_contrasena', 'Las contraseñas no coinciden.')
        return cleaned


class AutorizacionDatosForm(forms.Form):
    """
    Pantalla intermedia para cuentas que ya existían antes de este punto
    (cierre de auditoría, punto 1 - RNF1/Ley 1581) y que todavía no tienen
    `usuarios.autorizacion_datos`. Mismo campo y mismo mensaje de error que
    `_RegistroBaseForm.acepta_tratamiento_datos`, pero como formulario
    propio: esta pantalla no vuelve a pedir nombre/correo/contraseña, solo
    la autorización.
    """

    acepta_tratamiento_datos = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        error_messages={
            'required': 'Debes aceptar la política de tratamiento de datos personales para continuar.',
        },
    )
