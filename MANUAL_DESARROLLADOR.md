# Manual del desarrollador — Canigo

Este manual está dirigido a alguien que nunca ha visto el proyecto y necesita
clonarlo, configurarlo, entenderlo y seguir desarrollando sobre él. Es
complementario a [`CLAUDE.md`](CLAUDE.md), que documenta las decisiones
arquitectónicas ya tomadas en el documento de grado (por qué Django, por qué
MongoDB, por qué Leaflet, etc.) y el esquema de datos con su historial de
cambios. Este manual se enfoca en el "cómo trabajar en el código día a día".

Todo el contenido de este documento fue verificado contra el código del
repositorio al momento de escribirlo, no reconstruido de memoria.

## 1. Descripción general

Canigo es una plataforma web para gestionar el servicio de paseo de mascotas
en Bucaramanga: conecta dueños de mascotas con paseadores, permite publicar y
tomar horarios de paseo, monitorear el paseo en tiempo real sobre un mapa,
reportar incidentes de seguridad, y calificar el servicio al finalizar.

**Estado actual**: todos los requisitos funcionales (RF1–RF16, ver tabla en
`CLAUDE.md`) están implementados y funcionando sobre datos reales en MongoDB
Atlas — no es un prototipo estático. Esto incluye el ciclo de vida completo
del paseo (`disponible` → `en_vivo` → `historico`), el seguimiento GPS en el
mapa, el botón de emergencia, las calificaciones, las notificaciones con
actualización en vivo (sin recargar la página), y una extensión reciente que
permite que un mismo paseo lleve mascotas de **varios dueños distintos** a la
vez (hasta 8, límite real de la Ley Kiara), cada uno con su propia
calificación independiente. El documento de grado, el modelado de datos, los
diagramas UML y el diseño de interfaces ya están aprobados; lo que sigue es
extender/mantener esta implementación.

## 2. Arquitectura

Modelo cliente-servidor con un backend único que sirve una única plataforma
web para los dos actores del sistema (dueño y paseador) — **no existe una
app nativa aparte**. Esa fue la idea original del documento de grado, pero
cambió y ya está corregida: cualquier resto de código o configuración que
haga referencia a una app Android (por ejemplo, entradas viejas en
`.gitignore` para Android Studio/Gradle) es un remanente inofensivo de esa
versión anterior, no la arquitectura vigente.

```
┌─────────────────────────────────────────────────────────┐
│  Navegador (dueño o paseador — misma plataforma web)     │
│  Django Templates renderizados en servidor + Bootstrap   │
│  (CDN) + Leaflet.js (CDN, solo en la pantalla del mapa)  │
└───────────────────────────┬───────────────────────────────┘
                            │ HTTP (sesión con cookie firmada)
┌───────────────────────────▼───────────────────────────────┐
│  Django 5.2 (gunicorn en producción, runserver en local)  │
│  - Vistas por app (views_web.py / views.py)               │
│  - repository.py por app: TODO el acceso a Mongo vía      │
│    pymongo, sin ORM/capa intermedia                        │
│  - core/mongo.py: cliente MongoClient compartido           │
│  - core/media.py: subida de imágenes a Cloudinary          │
└──────────┬───────────────────────────────┬─────────────────┘
           │ pymongo                       │ API de Cloudinary
┌──────────▼───────────────┐   ┌────────────▼─────────────────┐
│  MongoDB Atlas            │   │  Cloudinary                  │
│  7 colecciones de negocio │   │  fotos de perfil/mascota/     │
│  (ver sección 6)          │   │  paseo/evidencia de incidente │
└────────────────────────────┘   └───────────────────────────────┘
```

Notas importantes de esta arquitectura:

- **Django usa SQLite (`db.sqlite3`) solo para su propia maquinaria interna**
  (`django.contrib.admin`, `sessions`, `auth`, `contenttypes`) — ningún dato
  de negocio vive ahí. En Render el disco es efímero (se reinicia en cada
  deploy), así que esa sqlite tampoco sobrevive entre deploys; por eso las
  sesiones de login **no** se guardan ahí, sino en una cookie firmada
  (`SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'`) —
  un dueño o paseador no pierde la sesión en cada redeploy.
- **No hay ORM de Django para el dominio del negocio**: los `models.py` de
  cada app están vacíos (el stub que deja `startapp`, sin tocar). Todo el
  acceso a MongoDB pasa por un archivo `repository.py` por app, que usa
  pymongo directamente.
- **JavaScript solo donde hace falta**: el mapa de seguimiento (Leaflet) y un
  puñado de patrones de actualización en vivo sin recargar la página
  (`setInterval` + un endpoint JSON) — ver sección 8. No hay build step de
  frontend (sin Node, sin bundler); Bootstrap y Leaflet se cargan por CDN.

## 3. Requisitos previos

- **Python 3.13** (la versión exacta usada en desarrollo y en producción —
  `render.yaml` fija `PYTHON_VERSION: 3.13.13`).
- Un entorno virtual (`venv`) — el proyecto no usa Poetry/pipenv, solo
  `requirements.txt` + `pip`.
- **Una cuenta y cluster de MongoDB Atlas** (capa gratuita alcanza): necesitas
  la cadena de conexión de un usuario de base de datos (no tu cuenta de
  Atlas), desde Atlas → Connect → Drivers.
- **Una cuenta de Cloudinary** (capa gratuita alcanza): necesitas la URL de
  credenciales desde el dashboard → Product Environment Credentials.

Variables de entorno que hacen falta (ver `.env.example` en la raíz del
repo, que ya trae esta misma lista con comentarios — solo nombres, ningún
valor real):

| Variable | Para qué |
|---|---|
| `DJANGO_SECRET_KEY` | Clave secreta de Django (firma de sesiones/CSRF). En local puede quedar con el valor de ejemplo; en producción Render la genera sola. |
| `DJANGO_DEBUG` | `True` en local, `False` en producción. |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos, separados por coma (`localhost,127.0.0.1` alcanza en local). |
| `MONGO_URI` | Cadena de conexión de MongoDB Atlas. |
| `MONGO_DB_NAME` | Nombre de la base de datos dentro del cluster (`canigo`). |
| `CLOUDINARY_URL` | Credenciales de Cloudinary en formato `cloudinary://<api_key>:<api_secret>@<cloud_name>`. |

## 4. Instalación y ejecución local

Comandos reales, verificados contra este repositorio (ejemplo en Windows con
Git Bash; en macOS/Linux el único cambio es cómo se activa el entorno
virtual):

```bash
git clone <url-del-repositorio>
cd Canigo

# Entorno virtual
python -m venv venv
source venv/Scripts/activate      # Windows (Git Bash)
# venv\Scripts\activate.bat       # Windows (cmd)
# source venv/bin/activate        # macOS/Linux

pip install -r requirements.txt

# Variables de entorno
cp .env.example .env
# Edita .env y completa MONGO_URI y CLOUDINARY_URL con tus propias
# credenciales (ver sección 3). .env nunca se sube al repo (está en
# .gitignore).

# Maquinaria interna de Django (admin/sessions/auth) - no toca MongoDB
python manage.py migrate

# Índices de MongoDB (únicos, TTL de coordenadas, etc. - ver sección 6)
python manage.py crear_indices

# Levantar el servidor
python manage.py runserver
```

El sitio queda en `http://127.0.0.1:8000/`. La pantalla de entrada
(`seleccionar_rol`, vista `home`) pregunta si sos "Paseador" o "Cliente"; el
rol elegido ahí se conserva en `?rol=` mientras se salta entre login y
registro (no solo para crear cuenta — ver sección 8, "El rol se elige una
sola vez").

Para confirmar que la conexión a MongoDB Atlas quedó bien configurada, hay
un endpoint de diagnóstico: `http://127.0.0.1:8000/api/db-status/` (devuelve
JSON con el estado de la conexión y las colecciones existentes).

## 5. Estructura del proyecto

```
Canigo/
├── config/          # Paquete de configuración de Django (settings, urls raíz, wsgi)
├── core/            # Infraestructura compartida (ver detalle abajo)
├── usuarios/        # Autenticación y dashboards de ambos roles
├── mascotas/        # Gestión de mascotas del dueño
├── paseos/          # Disponibilidad, inscripción y ciclo de vida del paseo
├── coordenadas/      # Seguimiento GPS y mapa en vivo
├── incidentes/       # Botón de emergencia y consulta de incidentes
├── calificaciones/   # Calificar un paseo finalizado
├── notificaciones/    # Notificaciones in-app y el punto del navbar
├── docs/            # (vacía por ahora)
├── requirements.txt
├── render.yaml       # Configuración de despliegue en Render
├── .env.example
├── CLAUDE.md         # Decisiones arquitectónicas + esquema de datos (fuente de verdad)
└── MANUAL_DESARROLLADOR.md   # Este documento
```

Cada app de Django (excepto `core`) sigue, con distinto grado de estrictez,
el mismo patrón:

- **`repository.py`**: CRUD puro contra una colección de MongoDB vía
  pymongo. No sabe nada de HTTP ni de formularios — solo recibe/devuelve
  datos. Es la única capa que ejecuta consultas.
- **`views_web.py`** (o `views.py` si no hay `views_web.py` — ver nota
  abajo): la lógica de negocio real y el render de plantillas. Llama a uno o
  varios `repository.py`, nunca accede a Mongo directamente.
- **`forms.py`**: validación de formularios (cuando la vista recibe datos de
  un `<form>`).
- **`urls_web.py`** (o `urls.py`): rutas de esa app.
- **`templates/<app>/`**: las plantillas HTML de esa app.

> **Nota real encontrada al verificar el código** (no es un patrón
> deliberado, es una inconsistencia histórica menor): `usuarios`, `paseos`,
> `coordenadas`, `incidentes` y `calificaciones` tienen **ambos**
> `views.py` y `views_web.py` — el `views.py` de esas cinco apps es el stub
> vacío que deja `python manage.py startapp` (3 líneas, nunca se tocó); toda
> la lógica real está en `views_web.py`. `mascotas` y `notificaciones`, en
> cambio, **no tienen** `views_web.py` — su lógica real vive directamente en
> `views.py`. Si vas a agregar una vista nueva, revisa primero cuál de los
> dos archivos tiene contenido real en esa app específica antes de asumir el
> nombre.

Responsabilidad de cada app:

| App | Responsabilidad | Colección(es) principal(es) |
|---|---|---|
| `core` | Infraestructura compartida: cliente de MongoDB (`mongo.py`), subida de imágenes a Cloudinary (`media.py`), tema visual (`static/css/canigo-theme.css`), layout base (`templates/base.html`), context processor del punto de notificaciones, comando `crear_indices`, y un endpoint de diagnóstico (`/api/db-status/`). | ninguna propia |
| `usuarios` | Registro/login/logout (comunes a los dos roles), dashboards de dueño y paseador, perfil editable del paseador (incl. certificados), decoradores de autenticación (`decorators.py`) | `usuarios` |
| `mascotas` | Registrar, listar y editar las mascotas de un dueño | `mascotas` |
| `paseos` | Publicar/despublicar disponibilidad (con zonas de servicio), listar paseadores e inscribir mascotas, iniciar/finalizar el paseo, "Paseos activos"/historial del dueño y "Mis paseos" del paseador | `paseos` (colección central) |
| `coordenadas` | Recepción de puntos GPS del paseador, mapa en vivo/histórico del dueño, cálculo de distancia recorrida | `coordenadas_detalle` |
| `incidentes` | Botón de emergencia del paseador, historial de incidentes del dueño | `incidentes` |
| `calificaciones` | Calificar un paseo finalizado (1–5 + comentario opcional) | `calificaciones` |
| `notificaciones` | Notificaciones in-app (inicio/fin de paseo, emergencia, calificación) y el endpoint que alimenta el punto naranja del navbar | `notificaciones` |

## 6. Modelo de datos

La fuente de verdad completa (todos los campos, tipos e índices) es
[`CLAUDE.md`](CLAUDE.md#esquema-de-base-de-datos-mongodb--7-colecciones-en-servidor) —
no se duplica aquí campo por campo para no terminar con dos versiones del
mismo esquema desincronizándose con el tiempo. Resumen de las 7 colecciones
y cómo se relacionan:

- **`usuarios`** — dueños y paseadores en la misma colección, distinguidos
  por `rol` (`"dueño"` | `"paseador"`). Campos como `calificacion_promedio`,
  `verificado` y `descripcion` solo aplican a paseadores. Nuevo array
  opcional (solo paseador): `certificados: [{id, tipo, nombre, entidad,
  fecha_expedicion, url, public_id, formato, subido_en}]` - `tipo` es una
  lista cerrada (`usuarios.forms.TIPOS_CERTIFICADO_PASEADOR`), no texto
  libre. Cada certificado tiene su propio `id` (un `ObjectId` generado al
  agregarlo, distinto del `_id` del usuario) para poder borrarlo
  individualmente.
- **`mascotas`** — cada una referencia a su dueño (`id_dueno`). Dos
  subdocumentos opcionales añadidos para la Ley 2480 de 2025 (Ley Kiara):
  `certificado_salud: {url, public_id, formato, fecha_expedicion,
  subido_en}` y `carne_vacunacion: {url, public_id, formato, subido_en}`.
  A diferencia de `foto` (solo URL), estos SÍ guardan `public_id` —
  permite borrarlos de Cloudinary al reemplazarlos sin tener que
  reconstruirlo desde la URL (ver sección 8).
- **`paseos`** — la colección central. Un documento nace cuando el paseador
  publica un horario (`estado: "disponible"`) y transita a `"en_vivo"` y
  luego `"historico"`. Desde la extensión de multi-dueño, **un mismo paseo
  puede tener mascotas de varios dueños distintos** (hasta 8, `id_mascotas`
  + `id_duenos` como arrays), y desde la extensión de zonas de servicio,
  cada horario publicado puede llevar 0 o más zonas (`zonas: [String]`,
  lista fija de las 17 comunas de Bucaramanga — ver constante
  `ZONAS_VALIDAS` en `paseos/repository.py`).
- **`coordenadas_detalle`** — un punto GPS por documento, referenciando el
  paseo (`id_paseo`). Con retención de ~90 días vía índice TTL.
- **`incidentes`** — referencia el paseo y, opcionalmente, una mascota
  específica afectada (`id_mascota`, `null` solo para `"accidente_paseador"`).
- **`calificaciones`** — referencia el paseo, el dueño que calificó y el
  paseador calificado. Índice único **compuesto** `(id_paseo, id_dueno)`:
  con multi-dueño, cada dueño de un paseo compartido califica su propia
  experiencia por separado.
- **`notificaciones`** — un documento por notificación, con su destinatario
  (`id_usuario`) y tipo.

No hay migraciones de esquema al estilo Django (no hay ORM sobre estas
colecciones) — un campo nuevo simplemente empieza a escribirse desde el
código que lo necesita; los documentos viejos que no lo tienen se tratan
como si tuvieran el valor por defecto (por ejemplo, `paseo.get('zonas', [])`
en vez de `paseo['zonas']`).

## 7. Flujos principales

El proyecto se construyó en 3 incrementos, cada uno agregando un conjunto de
requisitos funcionales (ver la tabla completa en `CLAUDE.md`):

**Incremento 1 — Núcleo funcional (RF1–RF6)**: registro y login de ambos
roles (`usuarios/views_web.py`: `registro`, `login`, `logout`,
`seleccionar_rol`), gestión de mascotas (`mascotas/views.py`), y el ciclo de
publicar/buscar/inscribir un horario de paseo (`paseos/views_web.py`:
`publicar_disponibilidad`, `lista_disponibles`, `detalle_paseador`,
`inscribir_en_horario`), incluida la selección de zonas de servicio y el
filtro por zona del lado del dueño.

**Incremento 2 — Monitoreo y seguimiento (RF7–RF11)**: iniciar/finalizar el
paseo (`paseos/views_web.py`: `iniciar_paseo`, `finalizar_paseo`), el envío
periódico de coordenadas GPS desde el navegador del paseador y el mapa de
seguimiento (`coordenadas/views_web.py`: `registrar_coordenada`,
`mapa_paseo`, `coordenadas_de_paseo`, con Leaflet.js en
`coordenadas/templates/coordenadas/mapa.html`), y las notificaciones de
inicio/fin de paseo con actualización en vivo en el navbar
(`notificaciones/`, `core/context_processors.py`).

`mapa_paseo`/`coordenadas_de_paseo` son compartidas por los dos roles
(`@requiere_autenticacion`, no `@requiere_dueno` — corregido en la
corrección de hallazgos de octubre 2026: antes un paseador no podía ver
ni sus propios paseos ahí). El control de a quién le pertenece el paseo
lo hace `_paseo_accesible_o_none()` dentro de la vista, no el decorador:
un paseador solo entra si es el paseador asignado; un dueño solo si es
uno de los `id_duenos` del paseo (puede haber varios, ver sección 6). Las
acciones exclusivas del dueño en esa pantalla (calificar, ver detalle de
un incidente) se ocultan en la plantilla con la bandera `es_dueno` del
contexto — nunca se renderiza el link para el paseador, aunque de todas
formas esas vistas de destino también tienen su propio decorador de rol.

**Incremento 3 — Seguridad y evaluación (RF12–RF16)**: el botón de
emergencia del paseador y el registro de incidentes
(`incidentes/views_web.py`: `reportar_incidente`, `lista_incidentes`), y las
calificaciones al finalizar un paseo (`calificaciones/views_web.py`:
`calificar_paseo`), incluidas las reseñas con comentario que se muestran
tanto en el perfil público de un paseador (`paseos/views_web.py::
detalle_paseador`) como en su propio "Mi perfil"
(`usuarios/views_web.py::perfil_paseador`).

## 8. Convenciones del proyecto

- **snake_case en todo**: nombres de campos de Mongo (`id_dueno`,
  `hora_inicio`, etc.) y de variables/funciones en Python — no se traducen a
  camelCase.
- **Los valores de `estado` en `paseos` son literales exactos**:
  `"disponible"`, `"en_vivo"`, `"historico"` (con guion bajo, sin tildes) —
  nunca sinónimos ni abreviaciones.
- **Repository pattern estricto**: ninguna vista ejecuta una consulta de
  pymongo directamente; siempre pasa por el `repository.py` de esa app. Esto
  mantiene las consultas centralizadas y fáciles de encontrar/probar.
- **Validación en dos capas cuando hay una lista fija de opciones**: el
  backend es la capa obligatoria (por ejemplo, `PublicarHorarioForm.zonas`
  es un `MultipleChoiceField` con `choices` fijas — Django rechaza
  automáticamente cualquier valor fuera de la lista); el frontend limita la
  selección por diseño, pero nunca reemplaza la validación del servidor.
- **Selección múltiple sin JavaScript**: cuando la interfaz necesita chips o
  botones tipo "toggle" para elegir varias opciones (mascotas a inscribir,
  zonas de servicio), el patrón es un `forms.MultipleChoiceField` con
  `CheckboxSelectMultiple`, renderizado como checkboxes reales pero
  visualmente ocultos, con su `<label>` inmediato estilado como el chip
  visible (alternando color vía el selector CSS `:checked + label`, ver
  `canigo-theme.css`). Un formulario HTML normal, cero JavaScript para el
  toggle.
- **Manejo de zonas horarias**: pymongo siempre devuelve `datetime` *naive*
  en UTC (sin `tzinfo`). Antes de pasar cualquier fecha a un filtro de
  plantilla (`|date`, `|time`) hay que marcarla explícitamente como UTC
  (`fecha.replace(tzinfo=timezone.utc)`) — si no, Django la trata como si ya
  estuviera en hora local (`America/Bogotá`) y el resultado queda
  desfasado 5 horas. Este bug ya se cometió y se corrigió varias veces en
  distintas pantallas; cualquier fecha nueva que se muestre en una plantilla
  necesita este mismo cuidado.
- **Actualización en vivo sin recargar, con `setInterval` + JSON**: no hay
  WebSockets ni Django Channels (fuera de alcance). El patrón establecido es
  una vista que devuelve JSON con exactamente lo que cambió, consumida por
  un `setInterval` en la plantilla que actualiza el DOM directamente (nunca
  un motor de plantillas en el cliente). Antes de agregar un `setInterval`
  nuevo en una pantalla, revisa si esa pantalla ya tiene uno por otro motivo
  (por ejemplo, el envío de GPS) y aprovecha esa misma petición en vez de
  sumar una nueva — varias pantallas ya comparten una sola petición para
  cubrir dos necesidades a la vez.
- **Privacidad en paseos con varios dueños**: cualquier pantalla que le
  muestre a un dueño específico "las mascotas de este paseo" debe filtrar a
  las de ESE dueño (`mascotas.repository.obtener_varias_por_id_y_dueno`),
  nunca la lista completa del paseo — un paseo compartido puede tener
  mascotas de otros dueños.
- **`requiere_dueno`/`requiere_paseador` ante un rol equivocado**: si hay
  sesión activa pero del rol que no es (p. ej. un paseador entrando a una
  vista `@requiere_dueno`), el decorador NO manda a login — redirige al
  panel propio de ese rol (`usuarios.decorators.URL_DASHBOARD_POR_ROL`) con
  `messages.warning(...)`. Solo sin sesión del todo se sigue yendo a login.
  Para una vista que de verdad deba aceptar los dos roles con reglas de
  pertenencia distintas por rol (como `coordenadas:mapa_paseo`), no se usa
  ninguno de los dos — se usa `@requiere_autenticacion` y la vista decide el
  acceso ella misma según `request.session['rol']`.
- **El rol se elige una sola vez, en el selector, y se conserva entre login
  y registro**: `seleccionar_rol.html` ("Eres...", tarjetas "Paseador"/
  "Cliente") enlaza a `login?rol=paseador|dueno`, no a registro. Desde login,
  el toggle "Crear cuenta" lleva a `registro?rol=<mismo rol>`; desde registro,
  "Iniciar sesión" lleva a `login?rol=<mismo rol>`. El `rol` viaja en un campo
  oculto del formulario de login y se valida en el backend contra
  `{"paseador", "dueno"}` — cualquier otro valor se trata como "sin rol"
  (mismo comportamiento que el login de siempre, sin comparar rol). En
  `login()`, el rol elegido **nunca filtra qué cuenta puede entrar**: las
  credenciales se validan primero, igual que siempre; solo si son correctas
  se compara el rol de la cuenta contra el elegido, y un mismatch no crea
  sesión (mensaje: `Esta cuenta está registrada como cliente/paseador...`,
  sin revelar si el correo existe con el otro rol). Login sin `?rol=` (el
  caso de un decorador redirigiendo por falta de sesión) sigue sin comparar
  rol. Ese redirect ahora incluye `?next=` (`usuarios.decorators.
  _redirigir_a_login`) — **no existía antes de este cambio**; se agregó
  porque, sin él, no había nada que "respetar" después de iniciar sesión.
  `login()` valida `next` con `url_has_allowed_host_and_scheme` antes de
  redirigir ahí (mismo mecanismo que usa `django.contrib.auth`), para
  que no sea un open redirect.
- **Editar mascota reusa el mismo formulario que registrarla**:
  `mascotas:editar` (`mascotas/views.py::editar_mascota`) usa el mismo
  `MascotaForm` que `registrar_mascota` - no hay un form de edición
  separado. El HTML de los campos tambien esta factorizado una sola vez
  (`mascotas/templates/mascotas/_formulario.html`, incluido por
  `registro.html` y `editar.html`), para no duplicar el markup. `foto`
  ya era opcional en `MascotaForm` desde antes (registro tambien la
  permite vacía), así que "no reemplazar la foto si no se sube una
  nueva" no necesitó un campo nuevo: `repository.actualizar_mascota()`
  distingue `foto=None` ("no tocar la que ya había") de `foto=''`
  ("borrarla"), y la vista solo pasa una URL cuando sí se subió un
  archivo. El dueño no es editable (no está en el form) - ver CLAUDE.md.
  Ownership: `repository.obtener_por_id_y_dueno()`; si la mascota no
  existe o es de otro dueño, mismo mensaje en ambos casos (no revela
  cuál fue el motivo) y redirige al listado.
- **Borrado de la foto anterior en Cloudinary al reemplazarla**: el
  esquema de Mongo solo guarda la URL (`mascotas.foto: String`, ver
  CLAUDE.md) - no el `public_id` de Cloudinary. `core/media.py::
  eliminar_imagen()` reconstruye el `public_id` a partir de la URL
  (todo lo que sigue a `/upload/`, sin el segmento de versión ni la
  extensión) y llama a `cloudinary.uploader.destroy()`. Es mejor
  esfuerzo: si no puede, no lanza - el reemplazo en Mongo ya quedó bien,
  esto es solo limpieza del archivo viejo. Verificado ejecutando: tras
  reemplazar la foto de una mascota, el `public_id` de la foto anterior
  ya no existe en Cloudinary (`cloudinary.api.resource()` devuelve 404).
- **Certificados de mascota (Ley 2480 de 2025, Ley Kiara)**:
  `mascotas:certificados` (`mascotas/views.py::certificados_mascota`,
  dueño-only, mismo ownership check que editar) sube
  `certificado_salud`/`carne_vacunacion` de forma independiente - se
  puede subir uno, el otro, los dos, o ninguno (la vista exige al menos
  uno). El estado del certificado de salud ("Sin certificado" / "Vigente
  (vence el DD/MM/AAAA)" / "Vencido", 6 MESES CALENDARIO desde
  `fecha_expedicion`, no días) se calcula **siempre al leer, nunca se
  guarda** - una sola función (`mascotas.repository.
  estado_certificado_salud()`) reusada en el listado, la edición de
  mascotas y la vista del paseador sobre su paseo en vivo, para que
  "vencido" signifique lo mismo en los tres lugares. `carne_vacunacion`
  no tiene ese concepto de vigencia (el esquema no le pide
  `fecha_expedicion` - ver CLAUDE.md), así que solo se muestra
  "Cargado"/"Sin carné cargado".
  Visibilidad: el dueño de la mascota (las vistas de arriba) y el
  paseador que la tiene asignada en **cualquier paseo suyo, en
  cualquier estado** (Ley Kiara: el paseo se planea según el
  certificado, así que el paseador lo necesita ANTES de empezar, no
  solo mientras camina - ajuste posterior a la primera versión de este
  punto, que solo lo mostraba en el paseo en vivo). Una mascota queda
  asociada a un paseo en el momento en que el dueño la inscribe en un
  horario `disponible` (`paseos_repository.inscribir_mascotas`,
  `paseos:inscribir_en_horario`) - ese `id_mascotas` ya NUNCA se
  modifica después (ni al pasar a `en_vivo` ni a `historico`), así que
  "cualquier estado" no necesita revisar cada uno por separado.
  `paseos_repository.paseador_tiene_acceso_a_mascota(id_paseador,
  id_mascota)` es la única función que decide esto - cuenta si existe al
  menos un documento de `paseos` con ese `id_paseador` y esa mascota en
  `id_mascotas`, sin filtrar por `estado`. El badge se muestra en 3
  lugares, los 3 llamando a esa misma función antes de incluir el dato
  (nunca solo ocultando el link en la plantilla):
  `usuarios.views_web._horarios_disponibles_paseador` (horarios
  "disponible" con mascota ya asignada, dashboard del paseador),
  `usuarios.views_web.bienvenida_paseador` (paseo "en_vivo", mismo
  dashboard) y `coordenadas.views_web.mapa_paseo` (sirve tanto "en_vivo"
  como "historico" con la misma plantilla - cubre "detalle/mapa de un
  paseo histórico" sin necesitar una pantalla aparte). La función de
  construcción del badge (`_certificados_de_mascotas_para_paseador`)
  está duplicada entre `usuarios/views_web.py` y
  `coordenadas/views_web.py` a propósito (mismo criterio que
  `_hay_notificaciones_sin_leer`, para evitar una dependencia cruzada
  entre esas dos apps) - lo que NO está duplicado es la función de
  acceso en sí, que vive una sola vez en `paseos/repository.py`.
- **Validación de archivo por contenido real, no solo por extensión**:
  `core/media.py::subir_certificado()` (usada por certificados de
  mascota y, en un commit aparte, del paseador) rechaza un archivo si
  sus primeros bytes no coinciden con la extensión declarada (firma
  JPEG `\xff\xd8\xff`, PNG `\x89PNG\r\n\x1a\n`, PDF `%PDF-`) - un archivo
  de texto renombrado a `.pdf` no pasa. También valida tamaño (máx. 5MB)
  antes de intentar subir nada. Usa `resource_type="auto"` en la subida
  a Cloudinary (a diferencia de `subir_imagen()`, que asume imagen) -
  necesario para que Cloudinary acepte un PDF.
- **Limitación conocida y DELIBERADA de Cloudinary (capa gratuita): los
  PDF se suben bien pero su URL devuelve 401 al intentar verla** (las
  imágenes SÍ se ven con normalidad). Confirmado ejecutando: se subió un
  certificado_salud en PDF real (no simulado) y su `secure_url` responde
  401 (`image/gif` de 0 bytes) al pedirla directamente, mientras que un
  carné de vacunación en JPG subido de la misma forma responde 200. La
  causa es una configuración de la cuenta de Cloudinary, no del código:
  **Cloudinary → Settings → Security → "Allow delivery of PDF and ZIP
  files"** (desactivado por defecto en cuentas gratuitas). No se
  implementó ningún workaround (como convertir el PDF a imagen) - decisión
  explícita de la consigna de este cambio. Hasta que se active esa
  opción, un certificado/carné subido como PDF se guarda bien en Mongo y
  Cloudinary, pero el link "Ver" de alguien que lo abra devolverá error.
- **Limitación conocida: las URLs de Cloudinary son públicas para
  cualquiera que tenga el link exacto** - no hay control de acceso de
  Cloudinary en sí (a diferencia de la vista de Canigo, que sí exige
  sesión y ownership antes de MOSTRAR el link). Alguien que consiga la
  URL de un certificado (por ejemplo, compartiéndola fuera de la
  plataforma) puede verla sin autenticarse. No se cambió este
  comportamiento.
- **Certificados del paseador**: `usuarios:certificados_paseador`
  (`usuarios/views_web.py`, `@requiere_paseador`) agrega certificados a
  `usuarios.certificados` (cada envío del formulario AGREGA uno nuevo, no
  edita uno existente - para "editar", se borra y se sube de nuevo).
  `usuarios:eliminar_certificado_paseador` (`@require_POST`,
  `@requiere_paseador`) borra uno por su `id` de subdocumento - el
  `$pull` en Mongo ya está acotado al `_id` del usuario en sesión, así
  que un paseador nunca puede borrar un certificado ajeno aunque
  manipule el id en la URL. Mismas validaciones de archivo que los
  certificados de mascota (`core/media.py::subir_certificado`, carpeta
  `canigo/certificados_paseadores`). Visible en "Mi perfil" (el propio
  paseador, con botón "Eliminar") y en el perfil público que ve el dueño
  (`paseos:detalle_paseador`, solo lectura) - en ambos lugares, el texto
  literal **"Documentos cargados por el paseador. Canigo no verifica su
  autenticidad."** (nunca la palabra "verificado" para estos documentos,
  para no confundirlos con el campo `verificado` de RF14, que es un
  mecanismo totalmente distinto - ver mas abajo). Si no hay un
  certificado de tipo "Primeros auxilios para perros"
  (`usuarios.forms.TIPO_PRIMEROS_AUXILIOS`), se muestra "Sin certificado
  de primeros auxilios cargado" - independiente de si hay otros
  certificados cargados.
- **RF14 ("Verificado") es un mecanismo DISTINTO a los certificados, y
  no se tocó**: `usuarios.verificado` (Boolean, solo paseador) se
  inicializa en `False` al registrarse (`usuarios/repository.py::
  crear_usuario`) y se muestra como insignia verde "Verificado" en 3
  plantillas (`perfil_paseador.html`, `paseos/detalle_paseador.html`,
  `paseos/lista_disponibles.html`). **Nada en el código actual lo
  cambia después de la creación de la cuenta** - no hay vista, botón,
  comando de gestión ni integración con Django admin (las colecciones
  de Mongo no son modelos de Django, así que `/admin/` no puede tocarlo
  aunque se registrara: `usuarios/admin.py` está vacío). Confirmado
  revisando todo el repositorio (`grep verificado`): la única forma hoy
  de poner `verificado=True` es editando el documento directamente en
  MongoDB Atlas (o un script aparte), fuera de la aplicación. Esta tarea
  NO conecta los certificados con `verificado` ni agrega una forma de
  cambiarlo - esa decisión queda pendiente, a criterio del usuario.
- **No existe una pantalla de "detalle" de mascota** (solo listado y
  formulario) - el link "Editar" se agregó en el listado
  (`mascotas/templates/mascotas/lista.html`); si en el futuro se agrega
  una pantalla de detalle, debería llevar el mismo link.
- **Nunca pongas `{% %}` de Django dentro de un comentario de JavaScript**
  (`// ...` o `/* ... */` en un `<script>`): el motor de plantillas de
  Django no sabe qué es un comentario de JS, parsea `{% %}` en todo el
  archivo por igual — un `{% if %}` sin su `{% endif %}` ahí dentro (aunque
  sea solo para "mencionar" la condición en prosa) rompe la compilación de
  toda la plantilla con un `TemplateSyntaxError` nada obvio de ubicar. Si
  hace falta explicar una condición de Django en un comentario de JS,
  describila en prosa plana, sin la sintaxis de la etiqueta.

## 9. Despliegue

Desplegado en **Render** como un único servicio web (`render.yaml` en la
raíz define todo el servicio, no hace falta configurarlo a mano en el
dashboard):

- **Build**: `pip install -r requirements.txt`, `python manage.py
  collectstatic --noinput`, `python manage.py migrate`, `python manage.py
  crear_indices` (en ese orden, en cada deploy).
- **Start**: `gunicorn config.wsgi:application`.
- **Archivos estáticos**: servidos por WhiteNoise directamente desde el
  proceso de Django (comprimidos, con cache-busting) — no hace falta Nginx
  ni un bucket aparte. Lo único que Django sirve como estático es el CSS
  propio del proyecto (Bootstrap y Leaflet se cargan por CDN).
- **Variables de entorno de producción** (mismos nombres que en local, ver
  sección 3, valores reales configurados en el dashboard de Render, nunca en
  el repositorio): `DJANGO_SECRET_KEY` (Render la genera sola),
  `DJANGO_DEBUG` (`False`), `MONGO_URI`, `MONGO_DB_NAME`, `CLOUDINARY_URL`.
  Render también inyecta automáticamente `RENDER_EXTERNAL_HOSTNAME`, que
  `config/settings.py` usa para completar `ALLOWED_HOSTS`/
  `CSRF_TRUSTED_ORIGINS` sin configuración manual adicional.
- **Base de datos de negocio**: MongoDB Atlas, externa al servicio de
  Render (no se despliega junto con la app).

## 10. Cómo correr las pruebas

**Hallazgo al verificar esto contra el repositorio** (ver el mensaje que
acompaña este manual): el proyecto **no tiene un suite de pruebas
automatizadas dentro del repositorio**. Los archivos `tests.py` que trae
cada app son el stub vacío de `startapp` (3 líneas, nunca se les agregó
contenido) — confirmado en las 8 apps. Las verificaciones exhaustivas
hechas durante el desarrollo (registro/login, ciclo de vida del paseo,
multi-dueño, notificaciones en vivo, zonas de servicio, etc.) se hicieron
con scripts sueltos de `requests.Session()` contra un servidor local
corriendo, pero esos scripts vivieron en un directorio de trabajo temporal
fuera del control de versiones — nunca se comitearon al repositorio.

Lo único que existe hoy como verificación automatizada dentro del repo es
el chequeo de sistema de Django:

```bash
python manage.py check
```

Esto valida configuración e imports (URLs, modelos, templates), pero no
prueba ningún flujo de negocio real contra datos. Si se quiere evidencia
formal de pruebas para el jurado, hace falta decidir un siguiente paso
concreto — por ejemplo, migrar algunos de esos scripts de verificación a
un módulo `tests.py` real por app (con `django.test.TestCase` o
`pytest-django`), o documentar los escenarios probados manualmente como un
plan de pruebas aparte. Este manual no asume ninguna de las dos opciones
por decisión propia — es una decisión pendiente de tomar.
