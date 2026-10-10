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
| `notificaciones` | Notificaciones in-app (inicio/fin de paseo, emergencia, calificación, verificación) y el endpoint que alimenta el punto naranja del navbar | `notificaciones` |
| `administracion` | Panel de verificación de paseadores (RF14). Sin colección propia - todo el acceso pasa por `usuarios.repository` | ninguna propia |

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
  individualmente. También nuevos (RF14, panel de administración, solo
  paseador): `verificacion: {estado, revisado_por, fecha, observacion}`
  (estado actual de la última revisión) y `verificacion_historial:
  [{estado, revisado_por, fecha, observacion}]` (todas las revisiones,
  nunca se borra una entrada vieja) - ver sección 8.
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
- **`horario_desde`/`horario_hasta` se guardan naive en UTC**, igual que
  todo el resto del esquema (nunca hora local sin zona) - se convierten
  UNA vez, al publicar (`paseos.views_web._horario_a_utc`: combina las
  horas elegidas con el día de HOY en hora de Bogotá, hace el datetime
  aware, lo pasa a UTC y le quita el tzinfo). Para comparar contra "el
  momento actual" en una consulta (por ejemplo, "¿ya pasó la hora de
  fin?"), se usa `datetime.now(timezone.utc).replace(tzinfo=None)` -
  mismo formato, comparación directa, sin reconversión de zona.
- **Un horario "disponible" cuya hora de fin ya pasó sin iniciarse debe
  dejar de ofrecerse** (hallazgos del 9 oct, punto 5 - nada lo cambiaba
  de estado antes: se quedaba "disponible" para siempre). Opción (a)
  elegida (filtro por fecha en cada consulta dueño-facing, sin tocar los
  datos ni agregar un estado nuevo como "vencido" - la opción (b) queda
  solo propuesta, no implementada, a la espera de aprobación):
  `paseos.repository.listar_disponibles_con_cupo()` (usada por
  "Paseadores disponibles") filtra `horario_hasta >= ahora_utc`
  directamente en la query de Mongo. `paseos.views_web.detalle_paseador()`
  (perfil público de un paseador que ve el dueño) agrega el MISMO filtro
  pero como condición extra en su propio list comprehension, en vez de
  dentro de `paseos.repository.listar_disponibles_de_paseador()` - esa
  función también la usa el dashboard del PROPIO paseador
  (`bienvenida_paseador`), donde SÍ debe seguir viendo un horario vencido
  (para poder "Despublicarlo") - filtrar ahí habría escondido esa
  tarjeta de su propio dueño. Mismo criterio, filtro en el lugar que
  corresponde a cada caso, no una regla única para toda la colección.
- **Actualización en vivo sin recargar, con `setInterval` + JSON**: no hay
  WebSockets ni Django Channels (fuera de alcance). El patrón establecido es
  una vista que devuelve JSON con exactamente lo que cambió, consumida por
  un `setInterval` en la plantilla que actualiza el DOM directamente (nunca
  un motor de plantillas en el cliente). Antes de agregar un `setInterval`
  nuevo en una pantalla, revisa si esa pantalla ya tiene uno por otro motivo
  (por ejemplo, el envío de GPS) y aprovecha esa misma petición en vez de
  sumar una nueva — varias pantallas ya comparten una sola petición para
  cubrir dos necesidades a la vez. Intervalo estándar: **10s** (RNF2), no
  12s ni 15s — `usuarios/bienvenida.html` y `paseos/mis_paseos.html` ya lo
  usan; el poller genérico de notificaciones (`core/templates/base.html`,
  `polling_notificaciones`) sigue en 15s a propósito, porque no es
  seguimiento de un paseo. Cuando lo que cambia es la ESTRUCTURA de una
  lista (badges, botones que aparecen/desaparecen según el estado, no solo
  texto suelto), la vista de sondeo devuelve el fragmento ya renderizado
  (`render_to_string` sobre un parcial compartido con la carga completa,
  como `estado_bienvenida_paseador`/`_horarios_paseador.html` o
  `estado_mis_paseos`/`_lista_paseos_activos.html`), no JSON con los datos
  sueltos - más simple y consistente que reconstruir ese HTML a mano en JS.
  **Pausar con la pestaña oculta** (`document.visibilityState`,
  `visibilitychange`): todo sondeo nuevo debe pausarse si la pestaña no
  está visible y refrescar de inmediato al volver a ella - patrón
  establecido en `bienvenida.html` y `mis_paseos.html`, cópialo para
  cualquier sondeo nuevo.
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
- **Registro exitoso YA NO inicia sesión sola** (hallazgos del 9 oct,
  punto 1 - revierte ese detalle de la decisión original de este
  mismo punto): `registro()` crea la cuenta y redirige a
  `login?rol=<mismo rol>&correo=<el que acaba de escribir>` con
  `messages.success('Cuenta creada. Inicia sesión.')`, en vez de llamar
  a `_iniciar_sesion()` y mandar directo al dashboard. `login()` usa ese
  `?correo=` (si viene) como `initial` de `LoginForm` en el GET - nunca
  pisa lo que alguien ya haya escrito en un POST fallido, porque
  `initial` solo aplica a un form sin binding. No se encontró una causa
  de código para el síntoma original ("se queda en el registro") -
  probado ejecutando registro válido (dueño y paseador), correo
  duplicado y contraseñas distintas: en los 3 casos el servidor ya
  respondía correctamente (redirect en éxito, error visible en los
  fallos) antes de este cambio. Se agregó además el campo `direccion`
  a `registro.html` (existía en `RegistroDuenoForm` pero nunca se
  renderizaba - hallazgo incidental, sin relación con el síntoma
  reportado).
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
- **Certificados de mascota (Ley 2480 de 2025, Ley Kiara)**: viven DENTRO
  del mismo `MascotaForm` que usan `mascotas:registro`/`mascotas:editar`
  (campos `certificado_salud`, `fecha_expedicion_salud`,
  `carne_vacunacion`, todos opcionales) - **ya no existe una pantalla
  aparte** (`mascotas:certificados` se eliminó, junto con su vista,
  plantilla y `CertificadosMascotaForm`, en los hallazgos del 9 oct,
  punto 2: la consigna original pedía una pantalla separada, pero se
  revirtió a favor de subirlos directo en el registro/edición, para no
  duplicar formulario). Se puede subir uno, el otro, los dos, o ninguno.
  **Atomicidad** (decisión explícita del punto 2: "no se crea nada" en
  vez de "se crea a medias"): en `registrar_mascota()`/`editar_mascota()`
  (`mascotas/views.py::_subir_certificados_del_form`), los archivos se
  suben ANTES de escribir en Mongo; si cualquier campo del formulario
  falla (incluido un archivo), no se crea/actualiza la mascota, y
  cualquier archivo que SÍ se hubiera llegado a subir en esa misma
  petición se borra de Cloudinary (`eliminar_archivo`) para no dejarlo
  huérfano - verificado ejecutando con un caso mixto real (un archivo
  válido + uno inválido en la misma petición): la mascota no se crea y
  Cloudinary queda sin el archivo que sí se había subido. El estado del
  certificado de salud ("Sin certificado" / "Vigente
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
- **Cloudinary SIEMPRE se configura desde una sola fuente** (confirmado al
  investigar el hallazgo "Invalid api_key \<your_api_key\>" del 9 oct,
  punto 3 - ese texto no aparece en ningún lugar del repositorio ni del
  SDK; es el error que devuelve el SERVIDOR de Cloudinary cuando el
  `api_key` enviado es literalmente esa cadena, lo que apunta a una
  variable de entorno mal copiada - de un ejemplo de la documentación de
  Cloudinary, no de `.env.example` - en el `.env` local o en el
  dashboard de Render, no a un bug de código): los 6 lugares que suben
  algo (`foto_perfil`, foto de mascota, evidencia de incidente, foto de
  paseo, certificados de mascota, certificados de paseador) pasan
  siempre por `core/media.py::subir_imagen()`/`subir_certificado()`,
  que llaman a `_asegurar_configuracion()` antes de cualquier
  `cloudinary.uploader.*` - no hay otro punto del código que llame a
  `cloudinary.config()` ni que lea `CLOUDINARY_*` por su cuenta.
  Verificado ejecutando los 6 tipos de subida con el `CLOUDINARY_URL`
  real del `.env` local: los 6 funcionan igual, sin ningún error -
  descarta una diferencia de código entre tipos de foto.
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
  literal **"Documentos cargados por el paseador y revisados por el
  administrador de Canigo cuando el perfil está verificado. Canigo no
  valida su autenticidad ante la entidad emisora."** (texto actualizado
  cuando se agregó el panel de administración - ver más abajo; antes
  decía "Canigo no verifica su autenticidad", pero ahora un admin SÍ
  revisa el perfil para verificarlo, así que ese texto habría sido
  contradictorio). Si no hay un certificado de tipo "Primeros auxilios
  para perros" (`usuarios.forms.TIPO_PRIMEROS_AUXILIOS`), se muestra
  "Sin certificado de primeros auxilios cargado" - independiente de si
  hay otros certificados cargados.
- **RF14 ("Verificado"): panel de administración** (`administracion/`,
  sin colección propia - todo pasa por `usuarios.repository`). No es un
  rol nuevo: una cuenta (de cualquier rol) es administradora si su
  correo está en `settings.CANIGO_ADMIN_EMAILS` (variable de entorno,
  lista separada por comas - ver `.env.example`). El correo se guarda en
  `request.session['correo']` al iniciar sesión (antes no se guardaba
  nada de eso en sesión) para que `usuarios.decorators.requiere_admin()`
  no necesite una consulta extra a Mongo en cada request; una sesión que
  ya estaba activa ANTES de este cambio no lo tiene hasta el próximo
  login (se trata como "no admin" mientras tanto). `requiere_admin`: sin
  sesión → login (con `?next=`); con sesión pero sin ser admin → `404`
  (no `403` ni un mensaje de "no autorizado" - no se revela que la ruta
  existe a quien no es admin). El link "Verificación" del navbar
  (`core/templates/base.html`) usa el context processor
  `core.context_processors.es_admin` (nuevo) para decidir si se muestra,
  sin que cada vista tenga que calcularlo a mano.

  Panel en `/administracion/verificacion/` (filtro `?filtro=pendientes|
  verificados|todos` por links, mismo patrón que el filtro de zonas en
  `paseos/lista_disponibles.html` - sin JS). Acciones
  `marcar_verificado`/`retirar_verificado` (`@require_POST`): guardan en
  el usuario `verificado: bool` + `verificacion: {estado, revisado_por,
  fecha, observacion}` (estado actual) y además `$push` la misma entrada
  a `verificacion_historial` (array, nunca se borra). `revisado_por` es
  el CORREO del admin, o el literal `"sistema"` para el retiro
  automático (ver abajo). Regla de negocio (NO en el repository, que
  solo escribe - la valida la vista): no se puede verificar a un
  paseador sin al menos un certificado de "Primeros auxilios para
  perros" - rechazado con mensaje aunque se mande el POST directo sin
  pasar por el botón (que además aparece `disabled` en el HTML si no lo
  tiene, como complemento). Si un paseador verificado borra su ÚLTIMO
  certificado de primeros auxilios
  (`usuarios.views_web.eliminar_certificado_paseador`), la verificación
  se retira automáticamente en la misma request
  (`revisado_por='sistema'`) y se notifica al paseador - mismo mecanismo
  de `notificaciones` que ya existía (`tipo='verificacion'`, **nuevo
  valor que no está en la lista cerrada que documenta CLAUDE.md**:
  `"inicio_paseo"|"fin_paseo"|"emergencia"|"calificacion"` - se agregó
  porque la tarea pidió explícitamente reusar ese mecanismo; si hace
  falta, actualizar CLAUDE.md para reflejarlo). `notificaciones/views.py::
  _TIPO_INFO` tiene una entrada para este tipo nuevo (icono/color), igual
  que los demás.

  "Certificados revisados por Canigo el DD/MM/AAAA" se muestra debajo de
  la insignia "Verificado" en el perfil propio del paseador y en el
  perfil público que ve el dueño, tomando `usuario.verificacion.fecha`
  (naive UTC desde Mongo - se marca `tzinfo=utc` explícitamente en la
  vista antes de pasarla al filtro `|date`, mismo cuidado de siempre,
  ver más abajo). La insignia en `paseos/lista_disponibles.html` (listado
  de paseadores) no se tocó - solo se agregó la fecha en el perfil
  completo, no en las tarjetas del listado.

  Confirmado ejecutando: antes de este cambio, nada en el código movía
  `verificado` después de `crear_usuario()` (quedaba en `False` para
  siempre, solo se podía cambiar editando Mongo directamente) - ahora el
  panel es la única forma de cambiarlo desde la aplicación.
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
  `DJANGO_DEBUG` (`False`), `MONGO_URI`, `MONGO_DB_NAME`, `CLOUDINARY_URL`,
  `CANIGO_ADMIN_EMAILS` (correos con acceso a `/administracion/verificacion/`,
  separados por coma - ver sección 8, RF14).
  Render también inyecta automáticamente `RENDER_EXTERNAL_HOSTNAME`, que
  `config/settings.py` usa para completar `ALLOWED_HOSTS`/
  `CSRF_TRUSTED_ORIGINS` (que además siempre incluyen un wildcard
  `.onrender.com`/`https://*.onrender.com` fijo, sin depender de esa
  variable - cubre el caso de que no esté disponible en algún punto,
  p.ej. durante el build).
- **`DEBUG` es `False` por defecto** (no `True`) si `DJANGO_DEBUG` no está
  definida en el entorno - fallo seguro: un despliegue nuevo sin esa
  variable configurada todavía no debe mostrar tracebacks con detalles
  internos. En local no cambia nada (`.env.example`/`.env` ya la definen
  explícitamente en `True`).
- **`SECURE_SSL_REDIRECT = True`** (solo cuando `DEBUG=False`, junto a
  `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`): Render ya redirige
  http→https en su propio proxy, esto es una segunda capa dentro de la
  app (recomendación básica de `manage.py check --deploy`, warning
  `W008`). **No se activó HSTS** (warning `W004`) a propósito - el
  propio warning de Django explica que mal configurado puede causar
  problemas difíciles de revertir (queda "pegado" en el navegador por el
  tiempo que se le indique) y no se pidió explícitamente; queda
  reportado, no corregido.
- **Gunicorn no corre en Windows nativo** (`import fcntl` falla - es un
  módulo exclusivo de POSIX): para probar "modo producción" en una
  máquina de desarrollo Windows, se usa `manage.py runserver` con
  `DJANGO_DEBUG=False` en su lugar (mismo `DEBUG`/`SECURE_*`/WhiteNoise
  real, vía `collectstatic` previo) - gunicorn en sí solo se ejecuta en
  el contenedor Linux de Render, donde sí funciona sin problema.
- **Probar cookies `Secure` (sesión/CSRF) en local, sin TLS real**: con
  `DEBUG=False`, el cookie `csrftoken`/la sesión se emiten con el
  atributo `Secure` - un cliente HTTP real (navegador, `requests`) los
  descarta sobre `http://` aunque se simule el header
  `X-Forwarded-Proto: https` (ese header solo cambia lo que Django CREE
  del lado del servidor, no el comportamiento del cliente). Además, con
  ese header puesto, el chequeo de CSRF para "requests que Django ve
  como https" exige un `Referer` que haga match con el host de la
  petición (o con `CSRF_TRUSTED_ORIGINS`) - sin un `Referer` así, un
  POST autenticado da `403` aunque el token sea correcto. Para probar
  esto desde un script (no un navegador real), hace falta mandar el
  valor de la cookie a mano en el header `Cookie` de la siguiente
  petición (en vez de depender del cookie-jar del cliente) Y un
  `Referer` que coincida con el propio host de la prueba
  (`https://127.0.0.1:<puerto>/`). La verificación real, con HTTPS
  genuino, es la de después del despliegue (ver "pruebas de humo").
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
