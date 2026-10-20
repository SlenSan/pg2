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
| `NOMINATIM_USER_AGENT` | User-Agent con un contacto real, exigido por la política de uso de Nominatim (dirección aproximada de un incidente - ver sección 7/9). |

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
requisitos funcionales. El reparto por incremento es el de la **tabla 3.3
del documento de grado** (no una agrupación por rango consecutivo de RF -
ver la tabla completa de RF en `CLAUDE.md`):

- Incremento 1 = RF1–RF6 **y RF9**
- Incremento 2 = RF7, RF8 **y RF15**
- Incremento 3 = RF10–RF14 **y RF16**

**Incremento 1 — Núcleo funcional (RF1–RF6, RF9)**: registro y login de ambos
roles (`usuarios/views_web.py`: `registro`, `login`, `logout`,
`seleccionar_rol`), gestión de mascotas (`mascotas/views.py`), el ciclo de
publicar/buscar/inscribir un horario de paseo (`paseos/views_web.py`:
`publicar_disponibilidad`, `lista_disponibles`, `detalle_paseador`,
`inscribir_en_horario`), incluida la selección de zonas de servicio y el
filtro por zona del lado del dueño, y **registrar la hora de inicio del
paseo** (RF9, `paseos/views_web.py::iniciar_paseo`).

**Incremento 2 — Monitoreo y seguimiento (RF7, RF8, RF15)**: el envío
periódico de coordenadas GPS desde el navegador del paseador y el mapa de
seguimiento (`coordenadas/views_web.py`: `registrar_coordenada`,
`mapa_paseo`, `coordenadas_de_paseo`, con Leaflet.js en
`coordenadas/templates/coordenadas/mapa.html`), y el **registro fotográfico
del paseo** al inicio, a mitad y al final (RF15, `paseos/views_web.py::
subir_foto`).

**INC-03/INC-04 (13 oct) — ráfagas de GPS y envío interrumpido**:
diagnóstico completo en el reporte del 12 oct, resumen aquí porque ya
hay una corrección aplicada:
- **INC-03 (corregido)**: con varias pestañas del mismo paseador
  abiertas a la vez, cada una manda su propio punto GPS cada 10s de
  forma independiente - sin coordinarse entre sí, el resultado medido
  era una ráfaga de 2+ puntos casi simultáneos seguida de un hueco de
  ~10s (mediana de 1.08s en una prueba de 2 pestañas, contra un
  promedio de 10.00s). `coordenadas/views_web.py::registrar_coordenada`
  ahora descarta en silencio (misma respuesta 201 que un guardado
  real - el JS nunca ve un error ni reintenta) un punto si el último
  del mismo paseo llegó hace menos de
  `_SEGUNDOS_MINIMOS_ENTRE_PUNTOS = 8` segundos, comparado contra
  `fecha_recepcion` (hora del SERVIDOR - `coordenadas.repository.
  obtener_ultima_recepcion()`), nunca `fecha_captura` (viene del
  dispositivo del paseador, no es confiable para esto).
- **INC-04 (corregido de fondo, Incremento 4 punto D1)**: el envío de GPS
  solo funcionaba mientras el paseador estaba en
  `bienvenida_paseador.html` - navegar a cualquier otra pantalla, o
  enviar los formularios modales de emergencia/foto (eran POST normales,
  recargaban la página), lo detenía por completo hasta volver.
  Corrección de fondo: ver sección 8, "Emisor de GPS global" - el envío
  ahora vive en `core/templates/base.html`, gated por
  `id_paseo_en_vivo_del_paseador` (nuevo context processor), así que
  sigue funcionando sin importar en qué pantalla esté el paseador. Los
  formularios modales de emergencia/foto se convirtieron a
  `fetch`+`FormData` (ver sección 8) precisamente para que YA NO
  recarguen la página a mitad de un paseo. Con esto corregido, el aviso
  "Mantén esta página abierta..." (mitigación temporal del 13 oct) se
  quitó - ya no aplica, el envío sobrevive a cualquier navegación.

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

**Incremento 3 — Seguridad y evaluación (RF10–RF14, RF16)**: **finalizar el
paseo** (RF10, `paseos/views_web.py::finalizar_paseo`) y las
**notificaciones de inicio/fin de paseo** con actualización en vivo en el
navbar (RF11, `notificaciones/`, `core/context_processors.py`), el botón de
emergencia del paseador y el registro de incidentes
(`incidentes/views_web.py`: `reportar_incidente`, `lista_incidentes`), y las
calificaciones al finalizar un paseo (`calificaciones/views_web.py`:
`calificar_paseo`), incluidas las reseñas con comentario que se muestran
tanto en el perfil público de un paseador (`paseos/views_web.py::
detalle_paseador`) como en su propio "Mi perfil"
(`usuarios/views_web.py::perfil_paseador`).

**Privacidad de incidentes en paseos multi-dueño (corrección del 12 oct)**:
un incidente sobre una mascota concreta (`id_mascota` no nulo) solo
notifica y se muestra al dueño de ESA mascota, nunca a los demás dueños
del mismo paseo (hasta 8 mascotas, Ley Kiara). Solo `"accidente_paseador"`
(`id_mascota` nulo — el único tipo sin mascota asignada, ver
`incidentes/forms.py::_TIPO_SIN_MASCOTA`) notifica y se muestra a TODOS
los dueños del paseo, porque los afecta a todos por igual. Antes,
`reportar_incidente()` notificaba a todos los `id_duenos` sin excepción, y
`lista_incidentes()`/el banner del mapa (`_texto_incidente()`) mostraban
el incidente más reciente del paseo entero sin filtrar — ver sección 8
para el patrón de la corrección.

**Cerrar sesión lleva al selector de rol, no a un login** (corrección del
12 oct): `usuarios/views_web.py::logout()` sigue limpiando la sesión por
completo con `request.session.flush()` (rol recordado, correo prellenado
del punto 3 de la sección 8, todo), pero ahora redirige a `home`
(`seleccionar_rol`) en vez de a `usuarios:login` — el pedido explícito es
que cerrar sesión, desde cualquier rol, lleve siempre a "Eres... Paseador
/ Cliente", nunca al formulario de login de un rol específico.

**Incremento 4, fase 1 (GPS continuo y ruta por puntos) — punto D**:
- **D1 (envío)**: el emisor de GPS pasó de vivir solo en
  `bienvenida_paseador.html` a ser global — ver "Emisor de GPS global"
  en la sección 8. Se agregó `position.coords.accuracy` como el nuevo
  campo `precision` de `coordenadas_detalle` (ver sección 6 y
  `CLAUDE.md`), con `enableHighAccuracy: true`, un `timeout` menor al
  intervalo de envío (valores exactos ajustados en la revisión de
  fase 1, ver más abajo) y un guard `enviandoAhora` contra lecturas
  superpuestas si el GPS tarda más de un ciclo en responder.
- **D2 (dibujo)**: `coordenadas/templates/coordenadas/mapa.html` ya no
  llama `linea.setLatLngs(puntos)` con el array completo en cada vuelta
  del polling (eso redibujaba toda la ruta cada 10s) — ahora recuerda
  cuántos puntos ya procesó (`puntosProcesados`) y solo evalúa los
  nuevos con `linea.addLatLng(...)`, más un `L.circleMarker` chico por
  cada punto nuevo de buena precisión (capa `capaPuntos`). Marcador
  verde fijo en el primer punto BUENO del paseo (`marcadorInicio`,
  nunca se mueve); marcador de pin en la posición actual
  (`marcadorActual`). El historial usa el mismo código (sin polling:
  todos los puntos llegan de una sola vez, `puntosProcesados` arranca
  en 0 igual).

**Incremento 4, fase 1 — revisión (puntos 1 y 2 del reporte de
revisión, 2026-10-12)**: tres ajustes sobre el punto D original, antes
de seguir con la fase 2.

- **Punto 1 — ya NO se descarta por precisión al guardar**: la versión
  original descartaba en el backend un punto con `precision` > 50m, con
  una constante que en ese entonces vivía en `coordenadas/views_web.py`
  (esa constante ya no existe ahí - ver más abajo dónde quedó el
  equivalente actual). Problema real: una precisión de PRUEBA fija
  (p.ej. 11m en el emulador/CDP) no representa un celular real en la
  calle, y descartar
  en silencio podía perder puntos válidos sin que nadie se enterara —
  el mapa del dueño se quedaba quieto sin ningún aviso. Ahora
  `registrar_coordenada` guarda TODOS los puntos con lat/lon válidos,
  con su `precision` tal cual (incluida `None`); el filtro se movió
  ENTERO al dibujo, en `mapa.html`:
  - la polilínea y los `circleMarker` de la ruta (más el marcador de
    inicio, que también es un `circleMarker`) usan solo los puntos con
    `precision <= UMBRAL_PRECISION_DIBUJO` (50m, constante en el JS) o
    `precision == null` (puntos antiguos, de antes de este campo);
  - la posición actual (`marcadorActual`) usa SIEMPRE el último punto,
    sin importar su precisión — ocultarla por mala precisión dejaría al
    dueño sin saber dónde está el paseador AHORA mismo, que es
    justamente para lo que existe ese marcador. Un `L.circle` (radio en
    METROS, no en píxeles como `circleMarker`) dibuja el margen de error
    real sobre el mapa; si la precisión supera el umbral, el tooltip
    pasa a "Ubicación aproximada (±N m)" en vez de "Posición actual"/
    "Fin del paseo";
  - nuevo campo `hay_punto_reciente` en la respuesta de
    `mapa_paseo`/`coordenadas_de_paseo` (`_hay_punto_reciente()`,
    constante `_SEGUNDOS_PUNTO_RECIENTE = 30`, calculado con la hora del
    SERVIDOR vía `fecha_recepcion`, no el reloj del navegador del
    dueño): si el último punto tiene más de 30s y el paseo sigue
    `en_vivo`, se muestra «Esperando la ubicación del paseador…»
    (`#esperando-ubicacion`) — correcto tanto en la carga inicial como
    en el polling de 8s.
- **Punto 2 — intervalos con más margen para RNF2**: con el periodo
  nominal de 10s, la latencia normal dejaba la mayoría de los
  intervalos reales en 10,0xs o más, y un cambio de pantalla los subía
  a 13-14s. Ajustes, todos con constante nombrada:
  - emisor de GPS (`core/templates/base.html`): `INTERVALO_ENVIO_MS =
    8000` (antes 10000);
  - descarte de duplicados (`coordenadas/views_web.py`):
    `_SEGUNDOS_MINIMOS_ENTRE_PUNTOS = 6` (antes 8) - mismo margen de
    ~2s que la versión anterior (10000/8000 → 8000/6000), proporcional
    al nuevo intervalo;
  - polling del mapa del dueño (`mapa.html`): cada 8s (antes 10s), para
    no quedar sistemáticamente un ciclo entero atrás del envío real.
  - **Revisión del `timeout` de geolocalización**: con el intervalo
    también en 8000ms, un `timeout` IGUAL a 8000ms podía coincidir con
    el siguiente tick del `setInterval` mientras `enviandoAhora` seguía
    `true` — ese tick se saltaba ENTERO por el guard, y dos ciclos
    perdidos seguidos dejaban un hueco de ~16s. Se confirmó el riesgo
    (es exactamente el mecanismo: el guard existe para evitar lecturas
    superpuestas, pero con intervalo == timeout el peor caso de latencia
    agota el ciclo completo antes de liberar el guard). Se bajó
    `TIMEOUT_GEOLOCALIZACION_MS` a 6000 — mismo margen de ~2s de antes.
  - **Medición real, 3 minutos, una sola pestaña** (bienvenida_paseador
    → perfil_paseador → bienvenida_paseador → reportar una emergencia →
    subir una foto): 22 puntos, intervalos entre 7.75s y 12.68s, **90%
    de los intervalos ≤10s** (19/21), sin ningún hueco de 16s — ver el
    reporte de revisión para la tabla completa.

**Incremento 4, fase 1 — punto C (dirección e incidente en el mapa)**:
al reportar un incidente (`incidentes.views_web.reportar_incidente`), si
hay coordenadas (la última capturada por el tracking), se geocodifican
de forma inversa con **Nominatim** (OpenStreetMap) vía
`core/geocoding.py::direccion_aproximada()`, y el resultado se guarda en
el nuevo campo `incidentes.direccion_aproximada`. Política de uso de
Nominatim (leída antes de implementar, resumen completo en el reporte
del punto C): máximo 1 solicitud/segundo, nunca "bulk"/sistemático (acá
se respeta porque solo se llama una vez por incidente reportado, un
evento humano, nunca por cada punto GPS), User-Agent genuino con
contacto (`NOMINATIM_USER_AGENT`, ver sección 9 y `.env.example`), y
atribución a OpenStreetMap (ya presente en cualquier mapa de Leaflet del
proyecto). Si el servicio falla, no responde, o el presupuesto total
(espera de ritmo + la llamada) supera **5 segundos**, se guarda el
incidente igual, con `direccion_aproximada: null` - geocodificar nunca
bloquea ni hace fallar el reporte. Limitación documentada: el límite de
1 req/s se aplica por proceso (no hay Redis/cache compartido entre
workers de gunicorn) - aceptable a la escala de este proyecto, donde
RF12 es un botón de emergencia disparado por una persona, no un proceso
en lote.

Nueva vista `incidentes.views_web.detalle_incidente` (`incidentes:
detalle_incidente`, URL `/incidentes/<id>/`): tipo, descripción, foto,
fecha/hora, dirección aproximada (o coordenadas si no hay ninguna),
mapa de Leaflet con un solo marcador fijo (sin polling - un incidente ya
ocurrido no cambia), y el teléfono del paseador como link `tel:` SOLO
si el paseo sigue `disponible`/`en_vivo` (mismo criterio del punto B,
oculto en `historico`). Control de acceso en
`_incidente_accesible_o_none()`: el paseador del paseo (sin
restricción), o un dueño de ese paseo cuando el incidente afecta a UNA
DE SUS mascotas o no afecta a ninguna en particular
(`accidente_paseador`) - EXACTAMENTE el mismo criterio de
`incidentes.repository.listar_visibles_para_dueno()` (corrección de
privacidad del 12 oct), reutilizado acá para que el detalle de un
incidente nunca se le muestre a quien no debería verlo. El banner de
emergencia del mapa (`coordenadas/templates/coordenadas/mapa.html`,
antes `_texto_incidente()`, ahora `_info_incidente_reciente()` porque
devuelve también el id) enlaza "Ver detalles" directamente a ESE
incidente para los dos roles - antes ese link solo existía para el
dueño y llevaba a la lista genérica (`incidentes:lista`, que ni
siquiera existe para el paseador).

**Incremento 4, fase 1 — punto B (teléfono del paseador)**:
`usuarios.telefono` ya existía y era obligatorio para los dos roles -
antes NO se validaba su formato (`forms.CharField` libre) ni se mostraba
en ningún lado. Ahora: `usuarios/forms.py::_validar_telefono_colombiano()`
(celular colombiano = 10 dígitos que empiezan en 3, ignorando espacios o
guiones) se aplica en `clean_telefono()` de `_RegistroBaseForm`
(registro de los dos roles) y de `EditarPerfilPaseadorForm` (editar
perfil) - rechazado en el backend, no solo sugerido por el `<input>`.
Se muestra como link `tel:` en dos lugares, los dos ya con el objeto
`paseador` en su contexto:
`paseos/templates/paseos/_lista_paseos_activos.html` ("Paseos activos"
del dueño - esta pantalla YA filtra a solo `disponible`/`en_vivo`, ver
`paseos.repository.listar_activos_por_dueno`, así que no hace falta un
chequeo de estado aparte) y
`coordenadas/templates/coordenadas/mapa.html` (mapa de seguimiento,
SOLO para `es_dueno` - el paseador no necesita ver su propio número),
con un `id="telefono-paseador"` que el polling de 10s oculta
dinámicamente si el estado pasa a `historico` MIENTRAS esa pantalla ya
está abierta (no solo al cargar la página). También incluido en el
detalle de un incidente (punto C) con el mismo criterio. Nunca se
muestra en `historial.html` (paseos ya `historico`) ni en el perfil
público de un paseador (`detalle_paseador` - ahí el dueño todavía no
tiene ninguna mascota inscrita con él, mostrar el teléfono ahí sería
exponerlo sin que exista una relación real todavía).

**Incremento 4, fase 1 — punto G (filtro de zonas en "Paseadores
disponibles")**: diagnóstico antes de cambiar nada - el filtro YA
existía desde el Incremento 1 (`?zona=`, validado contra `ZONAS_VALIDAS`
en el backend, ignorado sin error si no es una de las 17 comunas), pero
como una fila de chips-link (`<a href="?zona=X">`), sin conteo de
paseadores, sin número de comuna, y sin tags de zona en las tarjetas de
resultado. Cambios:
- `paseos/repository.py::ZONAS_VALIDAS_CON_NUMERO` (nueva, ver sección 6
  y `CLAUDE.md`) y `etiqueta_zona(valor)` - formato único "Comuna N.
  Nombre" reusado en CUATRO plantillas (filtro, tarjetas de "Paseadores
  disponibles", perfil público del paseador, modal "Publicar horario"),
  vía `paseos/templatetags/paseos_tags.py` (`{{ zona|etiqueta_zona }}`)
  para las que no arman el choices de un form.
- El filtro pasó de chips a un `<select>` real (sin JavaScript - un
  `<form method="get">` con un botón "Filtrar"), con el conteo de
  paseadores con horario VIGENTE por comuna entre paréntesis - mismo
  criterio de "vigente" que `c4d119c` (horario_hasta todavía no pasó).
  Una comuna sin paseadores aparece `disabled` en el `<select>` (nunca
  oculta). Arriba de los resultados: "N paseadores en Comuna X. Nombre"
  + botón "Quitar filtro".
- Cada tarjeta de paseador muestra sus zonas (de sus horarios vigentes,
  no de todo su historial) como tags ordenadas por número, con la
  comuna filtrada resaltada (`.zona-chip-activa`).
- **Hallazgo del diagnóstico, corregido aparte**: el perfil público de
  un paseador (`detalle_paseador.html`) mostraba su teléfono SIN
  ninguna condición, desde antes de este incremento - contradice la
  regla explícita del punto B ("dueños CON mascotas EN ESE paseo lo
  ven"), porque en esta pantalla el dueño todavía no inscribió nada. Se
  quitó esa línea - el teléfono ahora solo aparece donde el punto B lo
  define (ver más arriba).

**Incremento 4, fase 1 — punto F (endpoint de diagnóstico)**:
`/api/db-status/` (`core/views.py::db_status`) quedaba completamente
abierto, en cualquier entorno, y exponía el nombre de la base de datos y
la lista de colecciones a cualquiera. Ahora: en `DEBUG=True` (local)
sigue sin restricción, como herramienta de humo; fuera de `DEBUG`
(producción) exige la MISMA cuenta admin que protege
`/administracion/verificacion/` (`usuarios.decorators.requiere_admin`,
reusado tal cual, no una copia) - 404 para cualquier cuenta que no sea
admin, redirección a login sin sesión. La condición se evalúa una sola
vez al cargar el módulo (`db_status = _db_status if settings.DEBUG
else requiere_admin(_db_status)`), mismo momento en que `settings.py`
ya arma `SECURE_SSL_REDIRECT` según `DEBUG` - este proyecto no cambia
`DEBUG` en caliente.

**Incremento 4, fase 2 — punto E (notificaciones en el dispositivo, Web
Push)**: diagnóstico antes de empezar - el proyecto no tenía NADA de
esto (sin manifest, sin service worker, sin colección de
suscripciones); las notificaciones solo existían como documentos en
`notificaciones` + el punto del navbar, visibles solo si el usuario
tenía la pestaña abierta.

- **Infraestructura**: `core/root_files/manifest.webmanifest` y
  `core/root_files/sw.js`, servidos desde la RAÍZ del sitio
  (`/manifest.webmanifest`, `/sw.js` - `core/views.py::manifest()`/
  `service_worker()`, rutas en `config/urls.py`, NO bajo `/static/`
  que sirve WhiteNoise) - el alcance (scope) por defecto de un service
  worker es su propio directorio, así que servirlo bajo `/static/` lo
  hubiera dejado controlando solo esa carpeta, no el sitio entero.
  Íconos nuevos `core/static/img/icono-192.png`/`icono-512.png`
  (cuadrados, fondo naranja de marca `#D9703A`, pata blanca - no existía
  ningún ícono cuadrado utilizable como ícono de app; `canigo-logo.png`
  es rectangular y de líneas muy claras, pensado para un fondo oscuro).
- **Claves VAPID**: par nuevo por despliegue (no por usuario), generado
  con `python manage.py generar_claves_vapid` (comando nuevo, nunca
  guarda nada - solo imprime por stdout para copiar a mano). Se
  almacena la clave privada en su forma "raw" de 32 bytes en base64url
  (no el PEM completo) - una sola línea, sin saltos, más cómoda para
  una variable de entorno; `pywebpush`/`py_vapid` la reconocen igual
  (`Vapid.from_string` prueba RAW antes que DER). Ver
  `VAPID_PRIVATE_KEY`/`VAPID_PUBLIC_KEY`/`VAPID_CLAIMS_EMAIL` en
  `.env.example` y `config/settings.py`.
- **Colección `suscripciones_push`** (ver `CLAUDE.md`): índice único
  por `endpoint` (`core/management/commands/crear_indices.py`).
  `notificaciones/repository.py::crear_suscripcion()` hace upsert por
  `endpoint` (no insert a secas) - el mismo navegador puede volver a
  suscribirse (reinstaló, cerró/abrió sesión) sin chocar contra el
  índice único.
- **Envío automático, un solo punto de entrada**: `notificaciones.
  repository.crear()` es el ÚNICO lugar que inserta en `notificaciones`
  en todo el proyecto - confirmado buscando los 7 llamadores
  (`paseos`, `incidentes`, `calificaciones`, `administracion`,
  `usuarios`) antes de tocar nada. En vez de agregar el envío de push a
  cada uno de los 7 por separado (fácil de olvidar en un llamador
  nuevo el día de mañana), `crear()` ahora también llama a
  `_enviar_push()` al final - una excepción deliberada a "repository.py
  = solo acceso a Mongo" del resto del proyecto, aceptada a cambio de
  que ningún llamador pueda crear una notificación sin intentar
  también el push. `_enviar_push()` NUNCA lanza (ver sección 8,
  "Best effort") - si no hay `VAPID_PRIVATE_KEY` configurada, si el
  usuario no tiene suscripciones, o si `pywebpush` falla, la
  notificación INTERNA ya se creó de todas formas.
- **Sin datos sensibles en el payload**: el push manda exactamente el
  mismo `mensaje` que ya se guarda en `notificaciones.mensaje` - por
  diseño del esquema (ver CLAUDE.md) ese campo nunca lleva direcciones
  ni teléfonos, así que no hizo falta un mensaje "genérico" aparte.
- **Suscripciones vencidas**: un 404/410 del servicio de push borra la
  suscripción (`eliminar_suscripcion_por_endpoint`); cualquier otro
  error (red, 5xx) se registra en el log pero NO borra nada - es
  transitorio, no significa que la suscripción ya no sirva.
- **Verificado con un Chrome real (headless) contra el servicio de
  push real de Google (FCM)**: suscripción con la clave VAPID pública
  del proyecto aceptada por Chrome, guardada en el backend, y
  `pywebpush` entregó el push sin excepción - confirma que el formato
  de las claves y el payload son compatibles de punta a punta. La
  confirmación VISUAL (que el dispositivo MUESTRE la notificación) sólo
  se puede hacer con un dispositivo real - ver la sección de
  verificación del reporte.

**Incremento 4, fase 2 — punto E, continuación (permiso y UI de
activación)**: nuevo parcial compartido
`notificaciones/templates/notificaciones/_activar_push.html`, incluido
una sola vez en cada dashboard (`bienvenida.html`,
`bienvenida_paseador.html`) - "en el panel" de cada rol, sin mantener
dos copias. Oculto por completo si el servidor no tiene
`VAPID_PUBLIC_KEY` configurada (chequeo en Django, no en JS). El JS
decide cuál de 5 estados mostrar: no soportado, instrucciones iOS,
bloqueado, activo, o el botón - detección de iOS
(`/iPad|iPhone|iPod/.test(navigator.userAgent)`) y de modo standalone
(`navigator.standalone` + `matchMedia('(display-mode: standalone)')`,
los dos, por si alguno falta). El permiso se pide con
`Notification.requestPermission()` LLAMADO DIRECTO dentro del
listener de clic, sin ningún `await`/`.then()` previo - Safari exige
el gesto del usuario de forma estricta, cualquier espera previa (aunque
sea de una promesa ya resuelta) hace que lo rechace sin preguntar nada.
Con el permiso ya concedido de antes, se revisa
`pushManager.getSubscription()` y se vuelve a suscribir en silencio si
hace falta (pedido explícito: "las suscripciones pueden perderse con
el tiempo").

**Bug real encontrado probando con un Chrome real (no solo leyendo el
código)**: el primer intento de `guardarSuscripcion()` no revisaba
`resp.ok` del POST al backend - un fallo (403 por falta de la cookie
`csrftoken`, que en la primera visita al dashboard tras iniciar sesión
todavía no existía, al no haber pasado antes por ninguna página con un
`<form>`) dejaba la suscripción SIN guardar en el servidor, pero la UI
igual mostraba "Notificaciones activadas" - confirmado con un push real
que nunca llegaba a guardarse en `suscripciones_push` pese a que la
pantalla decía lo contrario. Corregido en dos frentes: (1) el token
CSRF ahora se incrusta directo del contexto de Django
(`{{ csrf_token }}`) en vez de leerse de la cookie, eliminando la
condición de carrera; (2) `guardarSuscripcion()` ahora lanza si
`!resp.ok`, así que un fallo del backend SÍ se refleja como error en la
UI en vez de mostrar éxito falso.

**Sesión independiente en iOS standalone**: `base_auth.html` (login/
registro/seleccionar_rol) muestra un aviso con
`window.navigator.standalone === true` explicando que iniciar sesión
ahí es independiente de Safari - la app instalada en la pantalla de
inicio en iOS NO comparte cookies con Safari normal (son contextos de
navegación separados a propósito de Apple), así que SIEMPRE pide
sesión de nuevo la primera vez que se abre desde ese ícono, aunque ya
hubiera una sesión iniciada en Safari.

**Incremento 4, fase 2 — "pantalla encendida durante el paseo"**: en
iPhone (y en general), Safari y las apps de pantalla de inicio
suspenden JavaScript cuando la pantalla se bloquea o la app pasa a
segundo plano - el envío de GPS se corta ahí sin importar qué tan bien
esté hecho el emisor, es una decisión del sistema operativo, no algo
que JS pueda evitar del todo. Mitigación: `navigator.wakeLock.request
('screen')` en `core/templates/base.html`, en un bloque TOTALMENTE
APARTE del emisor de GPS (pedido explícito de la tarea: no tocar ese
bloque) - mismo gate `id_paseo_en_vivo_del_paseador`. Se vuelve a pedir
en cada `visibilitychange` que deje la página visible, porque el lock
se libera solo al ocultarla. `if ('wakeLock' in navigator)` - sin
soporte, no hace nada, nunca lanza. Es una MITIGACIÓN, no una garantía
- el paseador puede apagar la pantalla a mano con el botón físico, o el
sistema operativo puede liberar el lock bajo poca batería; por eso
sigue existiendo el aviso de abajo.

**Aviso al iniciar el paseo**: `paseos.views_web.iniciar_paseo()` ahora
agrega un `messages.info()` ("Mantén Canigo abierto y la pantalla
encendida...") - UNA vez, al momento de iniciar, no un banner
persistente. Distinto del aviso "Mantén esta página abierta..." que
existió brevemente (commit `05af336`, 13 oct) y se quitó al volver
global el emisor de GPS (Incremento 4, punto D1): ESE era sobre no
CAMBIAR DE PÁGINA (ya no aplica, el emisor es global); ESTE es sobre no
BLOQUEAR LA PANTALLA (limitación de plataforma distinta, no relacionada
con D1).

**Verificado que el cambio en `base.html` no rompió el emisor de GPS**
(pedido explícito de la tarea, por tocar ese archivo): medido con un
Chrome real después de agregar el bloque de wake lock - intervalos de
7.89s/8.04s/7.96s, sin ningún hueco - igual que antes de este cambio.
`wakeLock.request('screen')` confirmado tanto al cargar la pantalla
como al simular un ciclo de `visibilitychange` (oculta → visible).

**Incremento 4, fase 2, revisión (puntos 1 y 2, 2026-10-13)**:

- **Punto 1 — timeout por suscripción de Web Push**: diagnóstico -
  `notificaciones/repository.py::_enviar_push()` llamaba a
  `pywebpush.webpush(...)` sin pasarle `timeout`, así que la llamada
  HTTP interna (vía `requests`) no tenía NINGÚN límite de tiempo propio
  - una suscripción con un endpoint que no responde podía colgar la
    petición completa que disparó la notificación (p.ej. reportar una
    emergencia) hasta que el sistema operativo cortara la conexión por
  su cuenta, que puede tardar minutos. Se agregó
  `_TIMEOUT_PUSH_SEGUNDOS = 4` (constante nombrada, con el motivo en el
  comentario) pasado como `timeout=_TIMEOUT_PUSH_SEGUNDOS` en la
  llamada a `webpush()`. Un timeout de `requests` (`ReadTimeout`/
  `ConnectTimeout`) no es un `WebPushException` - lo captura igual el
  `except Exception` genérico ya existente (best effort, nunca lanza).

  **Medido con un paseo multi-dueño real** (D1 y D2, una suscripción
  cada uno - la de D1 apuntando a un servidor TCP que acepta la
  conexión y nunca responde, la de D2 a un puerto cerrado que falla
  rápido) y reportando una emergencia (`accidente_paseador`, notifica a
  los dos): **6.78s en total** (antes del fix, sin límite, hubiera
  tardado lo que tardara el sistema operativo en cortar la conexión
  colgada - minutos, no segundos). La mayor parte de esos 6.78s es la
  suma de la subida real a Cloudinary (~2s) más el tope de 4s de la
  suscripción colgada - el reporte ya NO puede colgarse indefinidamente,
  pero sigue agregando varios segundos reales por cada suscripción
  problemática, porque `_enviar_push()` se llama de forma SÍNCRONA
  dentro de la misma petición HTTP que crea el incidente. Quedó
  documentado como una limitación conocida, no corregida en esta
  revisión (mover el envío de push a algo asíncrono - un hilo aparte o
  una cola - no se pidió explícitamente y cambiaría la arquitectura
  síncrona que usa el resto del proyecto).

- **Punto 2 — `sw.js` sin caché de páginas ni respuestas autenticadas**:
  confirmado por lectura completa del archivo - `core/root_files/sw.js`
  solo tiene `install`, `activate`, `push` y `notificationclick`; NUNCA
  tuvo un handler de `fetch` (no hay nada que quitar, el archivo ya
  cumplía esto desde que se creó). Lo que SÍ faltaba: ningún
  `Cache-Control` explícito en la respuesta de `/sw.js`
  (`core/views.py::service_worker()`) - ahora manda
  `Cache-Control: no-cache` (confirmado con `curl -I`) - el navegador
  puede guardar una copia, pero tiene que revalidarla con el servidor
  antes de usarla, para que una actualización futura del service worker
  no tarde en propagarse por culpa de una caché vieja.

**Revisión de fase 1, puntos pendientes (a)/(b)/(c), 2026-10-13**:

- **Punto (a) — incidente sin foto**: diagnóstico - `ReportarIncidenteForm.foto`
  ya era un `forms.ImageField()` (obligatorio por defecto), así que el
  backend ya rechazaba correctamente un POST sin el campo `foto` antes
  de esta revisión. **Verificado, sin cambios de código**: un POST
  directo a `reportar_incidente()` sin el campo `foto` (simulando quitar
  el atributo `required` del `<input>` con las herramientas de
  desarrollador) responde 400 y NO crea el incidente.
- **Punto (b)**: ver más arriba (commit aparte).
- **Punto (c) — link "Verificación de paseadores" en el navbar**:
  diagnóstico - el link YA estaba en `core/templates/base.html`
  (`{% if es_admin %}`, en las dos ramas de rol) desde antes de esta
  revisión. Lo que SÍ estaba duplicado: `core.context_processors.
  es_admin()` y `usuarios.decorators.requiere_admin()` tenían cada uno
  su PROPIA copia de la misma comparación (`correo.strip().lower() in
  CANIGO_ADMIN_EMAILS`) - dos lugares decidiendo "es admin" por
  separado, que podían desincronizarse sin que nada lo avisara si se
  cambiaba la regla en uno y no en el otro. Se extrajo
  `usuarios.decorators.es_correo_admin(correo)` como ÚNICA fuente de
  verdad, reusada por los dos.

**Hallazgos de la caminata real del 13 de octubre (iPhone como paseadora)**:

- **INC-05 — mapa gris en el detalle de un incidente**: diagnóstico -
  `incidentes/templates/incidentes/detalle.html` interpola
  `{{ incidente.latitud }}`/`{{ incidente.longitud }}` directo dentro de
  un `<script>` para armar `var punto = [lat, lon];`. Con
  `LANGUAGE_CODE = 'es-co'` y `USE_I18N = True` (`config/settings.py`),
  Django renderiza un decimal con **coma**, no punto (`7.1201` sale como
  `7,1201`) - confirmado aislado con
  `Template('{{ v }}').render(Context({'v': 7.1201}))` antes de tocar
  ningún archivo del proyecto. Eso deja la línea como `var punto =
  [7,1201, -73,1235];`: un array de **4** números, no de 2 -
  `L.map().setView()` arma una vista inválida que nunca llega a pedir
  tiles reales, de ahí el mapa gris con la atribución por defecto de
  Leaflet sola (sin "© OpenStreetMap", porque el `tileLayer` nunca
  terminó de agregarse bien). `coordenadas/templates/coordenadas/
  mapa.html` NO tiene este bug porque sus coordenadas llegan por un
  `fetch` a JSON (`coordenadas_de_paseo`), que nunca pasa por el
  localizador de plantillas de Django - `detalle.html` es el único
  archivo del proyecto que interpola un número crudo directo dentro de
  un `<script>`. Fix: `{% load l10n %}` + el filtro `|unlocalize` en las
  dos coordenadas de esa línea (y en el texto de respaldo "Dirección
  aproximada" cuando no hay geocodificación, por consistencia, aunque
  ese caso no rompía nada por no estar dentro de un `<script>`). Si se
  interpola cualquier número de Mongo directo dentro de un `<script>` en
  cualquier plantilla nueva, necesita el mismo cuidado - mismo tipo de
  bug que el de zonas horarias (ver más abajo), otra forma en la que
  Django "ayuda" de más y rompe algo que no era texto para humanos.

  **Verificado ejecutando**: antes del fix (reproducido con `git stash`
  sobre el archivo, re-probado y revertido) - 0 tiles cargados
  (`leaflet-tile-loaded`), atribución solo `"Leaflet"` (sin
  OpenStreetMap), 0 marcadores. Después del fix - 6 tiles cargados,
  atribución `"Leaflet | © OpenStreetMap contributors"`, 1 marcador.
  Confirmado también contra el incidente real de producción
  `6ace7d2ae08c8c415ba12dc1` en modo lectura (sin escribir nada), una
  vez desplegado el fix.

- **INC-06 — el tipo de incidente se mostraba con su valor interno**
  (`mordedura_agresion` en vez de "Mordedura o agresión"): diagnóstico -
  `incidentes/repository.py` ya tenía una constante `TIPOS_VALIDOS`,
  pero una búsqueda en todo el proyecto confirmó que **nunca se usaba en
  ningún lado** - la lista real de opciones vivía duplicada, sin
  documentar, dentro de `incidentes/forms.py` (`_OPCIONES_TIPO`, con las
  etiquetas legibles). Se consolidó en una sola fuente de verdad,
  siguiendo el mismo patrón que `paseos.repository.
  ZONAS_VALIDAS_CON_NUMERO`/`etiqueta_zona()` y
  `usuarios.decorators.es_correo_admin()`:
  `incidentes.repository.TIPOS_VALIDOS_CON_ETIQUETA` (tuplas
  `(valor, etiqueta)`) + `etiqueta_tipo_incidente(tipo)`, expuesta a las
  plantillas vía el filtro `incidentes.templatetags.incidentes_tags.
  etiqueta_tipo_incidente` (nuevo). `incidentes/forms.py` ahora importa
  `TIPOS_VALIDOS_CON_ETIQUETA` en vez de duplicar la lista. Se aplicó el
  filtro en el detalle del incidente, el listado y el mensaje de
  notificación (`incidentes/views_web.py`) - las tres pantallas que
  mostraban el tipo. El "aviso del mapa" (banner de emergencia en
  `coordenadas/templates/coordenadas/mapa.html`,
  `_info_incidente_reciente()`) se revisó también por pedido de la
  tarea, pero NO mostraba el tipo crudo (solo el nombre de la mascota o
  un mensaje genérico) - no había nada que corregir ahí, se deja
  documentado para que quede claro que se revisó.

  **Verificado ejecutando**: `ReportarIncidenteForm().fields['tipo']
  .choices` sigue devolviendo los mismos 5 pares `(valor, etiqueta)` de
  antes. Carga real de `/incidentes/<id>/` y `/incidentes/` muestran la
  etiqueta legible ("Otro", "Accidente del paseador", etc.), no el valor
  crudo.

- **Punto 3 — pantalla apagada a los ~5s durante la caminata (iPhone,
  Modo de Bajo Consumo activo)**: diagnóstico solicitado explícitamente
  SIN cambiar comportamiento todavía, solo instrumentación de
  diagnóstico. El wake lock (`navigator.wakeLock.request('screen')`,
  ver más arriba) ya se pedía en esa pantalla - lo que faltaba era
  cualquier forma de que la autora viera, desde su propio iPhone, si la
  petición tuvo éxito o no. Se agregó: `console.log`/`console.warn` con
  `error.name`/`error.message` en cada rama (éxito, sin soporte, rechazo
  del navegador, liberación por el sistema vía el evento `release`), y
  un indicador visible SOLO para el paseador en
  `usuarios/templates/usuarios/bienvenida_paseador.html`
  (`#estado-wakelock`, mismo patrón "buscar por id y actualizar si
  existe" que ya usa `#estado-gps`): "Pantalla activa: sí" / "no
  disponible (navegador sin soporte)" / "no (NombreDelError)" / "no (el
  sistema lo liberó)".

  **El Modo de Bajo Consumo de iOS puede hacer que el sistema operativo
  NO honre un Wake Lock ya concedido** (lo libere por su cuenta, sin que
  la página haga nada) - esto es una limitación de la plataforma, no
  algo que este código pueda forzar; el indicador existe precisamente
  para que la autora pueda comprobar en su propio teléfono, CON y SIN
  Modo de Bajo Consumo activado, qué rama ocurre en la práctica.

  **Verificado ejecutando**: en Chrome (headless, con soporte de Wake
  Lock API), el indicador muestra correctamente "Pantalla activa: sí"
  al conceder el lock. **Solo leído en código / pendiente de la propia
  autora**: qué pasa específicamente en Safari de iOS con Modo de Bajo
  Consumo activo - ningún entorno de prueba automatizado disponible
  reproduce esa combinación exacta de plataforma + modo de energía; la
  autora debe revisar el indicador en su iPhone con y sin ese modo
  activado y reportar qué rama aparece.

- **Punto 4 — demasiados puntos dibujados cuando el paseador está
  detenido**: con un punto GPS cada 8s, media hora detenido (ej.
  esperando en un parque) deja ~225 lecturas casi en el mismo lugar - no
  es un problema de los DATOS (todos son válidos y se guardan igual,
  sirven para el punto 5 de abajo y cualquier análisis futuro), es un
  problema de DIBUJO: tantos `circleMarker` superpuestos no aportan
  nada, solo tapan el mapa. Cambio solo en
  `coordenadas/templates/coordenadas/mapa.html`, capa de dibujo: la
  polilínea sigue recibiendo TODOS los puntos válidos sin excepción
  (`linea.addLatLng(latlng)`, sin tocar); un `circleMarker` nuevo solo
  se agrega si quedó a `UMBRAL_DISTANCIA_DIBUJO_M` (10m, constante
  nombrada) o más del ÚLTIMO punto que SÍ se dibujó (no del último
  punto recibido - si el paseador está parado, todos los puntos nuevos
  se comparan contra ese mismo punto ancla hasta que alguno se aleje lo
  suficiente). Además, la capa completa de puntos (`capaPuntos`, un
  `L.layerGroup`) se oculta del mapa por debajo de
  `ZOOM_MINIMO_CIRCULOS` (16, constante nombrada) mediante el evento
  `zoomend` de Leaflet - a ese nivel de zoom o menos, los puntos
  quedarían tan juntos en pantalla que no aportan nada, solo ruido
  visual; vuelve a mostrarse en cuanto se hace zoom a 16 o más. El
  marcador de inicio (`marcadorInicio`) y el círculo de incertidumbre de
  la posición actual NO se tocaron - no son parte del problema reportado
  (no se acumulan, cada uno existe una sola vez o se reposiciona).

  **Verificado ejecutando**: sembrados 9 puntos de prueba en
  `canigo_dev` (6 agrupados en un radio de ~3m simulando una parada, un
  salto real de ~16.7m, y 3 más agrupados ~1m entre sí en el nuevo
  punto) contra un paseo de prueba `en_vivo`. Con `L.circleMarker`
  interceptado para contar llamadas y conteo directo de elementos
  `<path>` en el mapa: con zoom inicial (ajustado automáticamente a 16
  por lo pequeño del área), solo 2 de los 9 puntos generaron un
  `circleMarker` nuevo (los otros 7 cayeron dentro del umbral de 10m del
  último punto dibujado) - 5 paths totales en el DOM (línea + 2 puntos +
  marcador de inicio + círculo de incertidumbre), igual a lo esperado
  por el cálculo manual de distancias. Al bajar el zoom 6 niveles (por
  debajo de 16), los paths se redujeron a 3 (línea + marcador de inicio
  + círculo de incertidumbre) - la capa de puntos quedó completamente
  oculta, confirmando el `zoomend`. Puntos de prueba borrados de
  `canigo_dev` al terminar.

**Cierre de auditoría antes del enlace a usuarios (14 de octubre)**:

- **Punto 1 — autorización de tratamiento de datos (RNF1, Ley 1581 de
  2012)**: diagnóstico - la auditoría anterior confirmó 0 resultados
  para "1581"/"tratamiento de datos"/"política de privacidad" en todo el
  proyecto; el único texto relacionado era una frase decorativa sin
  casilla ni validación real en `registro.html` ("aceptas los Términos
  de servicio..."). Se reemplazó por una casilla real:
  `usuarios.forms._RegistroBaseForm.acepta_tratamiento_datos`
  (`BooleanField(required=True)`) - Django rechaza el `POST` en el
  BACKEND si no viene marcada, sin importar el atributo `required` del
  HTML (que se puede quitar con las herramientas de desarrollador). El
  texto con el link a `/privacidad/` se escribe a mano en el template
  (no en `label`, que no admite HTML).

  `usuarios.repository.crear_usuario()` guarda
  `autorizacion_datos: {fecha, version}` en TODA cuenta nueva (la
  casilla ya es obligatoria, así que esto nunca queda sin valor para un
  registro nuevo). `VERSION_POLITICA_PRIVACIDAD = '1.0'` vive en
  `usuarios/repository.py` - si el texto de `/privacidad/` cambia de
  forma sustancial en el futuro, subir ese número (y el mismo número en
  el `<h1>` de `core/templates/core/privacidad.html`) hace que las
  cuentas que ya aceptaron la versión anterior vuelvan a pasar por la
  pantalla de autorización.

  **Cuentas que ya existían de antes de este punto** (sin
  `autorizacion_datos`): `core.middleware.ExigirAutorizacionDatosMiddleware`
  (nuevo, al final de `MIDDLEWARE`, junto a
  `NoCacheParaAutenticadosMiddleware`) redirige CUALQUIER request
  autenticado sin `request.session['autorizacion_datos_ok']` a
  `usuarios:autorizar_datos`, sin importar qué ruta pedía - lista blanca
  de solo 5 rutas (la propia pantalla, logout, `/privacidad/`, manifest
  y service worker). `autorizacion_datos_ok` se guarda en sesión en
  `_iniciar_sesion()` (mismo patrón que `correo` para
  `requiere_admin()`) para no consultar Mongo en cada request - se
  actualiza a `True` en el momento en que la cuenta acepta, sin esperar
  al próximo login. La vista `usuarios.views_web.autorizar_datos()` NO
  borra ni modifica ningún otro dato de la cuenta, solo agrega el campo.

  **`/privacidad/`** (`core.views.privacidad`, pública, sin sesión
  requerida - hay que poder leerla antes de aceptar): usa el texto
  EXACTO de la tarea, sin agregar afirmaciones legales propias.
  Discrepancias encontradas y reportadas, sin cambiar el texto pedido:
  (a) "contraseña (guardada cifrada)" - técnicamente el sistema la
  guarda con **hash** (PBKDF2-SHA256, irreversible), no con cifrado
  reversible; es una imprecisión del texto dado, no del código. (b) el
  placeholder `[FECHA DE ELIMINACIÓN QUE DEFINA LA AUTORA]` se dejó
  **literal**, tal como pidió la tarea - falta que la autora defina esa
  fecha. El resto del texto (datos recogidos, finalidades, 90 días de
  retención de `coordenadas_detalle` - confirmado que el índice TTL real
  de `crear_indices.py` usa exactamente ese valor -, terceros
  MongoDB/Cloudinary/Render, derechos, edad) coincide con el sistema
  real.

  Link a `/privacidad/` agregado al pie de página de `base.html`, FUERA
  de `{% block body %}` (mismo lugar que el resto del footer) - aparece
  en toda pantalla, con y sin sesión, sin tocar cada plantilla por
  separado.

  **Verificado ejecutando** (`canigo_dev`, cuentas `@canigo.test`
  creadas y borradas en la misma prueba): registro sin marcar la casilla
  → 400 renderizado de nuevo con el mensaje de error, cuenta NO creada;
  registro marcándola → cuenta creada con `autorizacion_datos` guardado
  en Mongo. Cuenta sembrada manualmente SIN `autorizacion_datos`
  (simulando una cuenta de antes de este punto): login → redirige a
  `/cuentas/autorizacion-datos/`; intento de ir directo a
  `/cuentas/bienvenida/` → rebotado de vuelta a la misma pantalla;
  "Cerrar sesión" → funciona (302); tras aceptar la casilla →
  `autorizacion_datos` queda guardado y `/cuentas/bienvenida/` ya
  responde 200.

- **Punto 2 — concurrencia del servidor (RNF3/RNF7)**: diagnóstico -
  `render.yaml` arrancaba `gunicorn config.wsgi:application` sin
  `--workers`/`--threads`, es decir con el default de gunicorn (**1
  worker sync**): procesa una sola petición a la vez. Mientras esa
  única petición espera los hasta 5s de Nominatim o 4s de cada
  suscripción de push (ver la auditoría RF/RNF anterior), el proceso
  completo queda bloqueado para TODOS los demás usuarios, sin importar
  cuántos haya.

  **Antes de fijar los valores** (pedido explícito de la tarea):
  - **`core/mongo.py` es seguro para hilos**: confirmado leyendo
    directamente el docstring de `pymongo.synchronous.mongo_client.
    MongoClient.__init__` instalado en este proyecto - *"The client
    object is thread-safe and has connection-pooling built in."* El
    cliente ya es un singleton a nivel de módulo (`get_client()`,
    `_client` global) - nunca se crea uno nuevo por petición en ningún
    archivo del proyecto (confirmado con una búsqueda de `MongoClient(`
    en todo el código: una sola aparición, en `core/mongo.py`). Con
    varios hilos compartiendo el mismo proceso, el pool de conexiones
    de pymongo ya resuelve la concurrencia sin configuración adicional.
  - **Memoria por worker**: no se pudo medir con `gunicorn` real (ver
    más abajo), así que se midió un proxy realista - un proceso Python
    que hace `django.setup()` completo (misma carga de apps/dependencias
    que haría un worker de gunicorn: pymongo, cloudinary, pywebpush,
    whitenoise, etc.) y atiende una petición, medido con `Get-Process`
    de PowerShell (`WorkingSetSize`): **~77-87 MB** por proceso
    (reproducido 3 veces con el mismo rango). Los *threads* de un mismo
    worker NO multiplican esta memoria (comparten el mismo proceso); los
    *workers* sí. Con `--workers 2`: ~2×85 MB + el proceso maestro de
    gunicorn (unos pocos MB) ≈ **180-190 MB**, dentro del límite de
    **512 MB** del plan gratuito de Render con margen (~320 MB) para el
    resto del sistema operativo y picos de uso. `--threads 4` no suma a
    esta cuenta.

  **Valores elegidos**: `--workers 2 --threads 4 --worker-class gthread
  --timeout 60`. 2 workers (no 1, no 4+) por el margen de memoria de
  arriba - un tercer worker ya dejaría menos margen del que parece
  prudente para un plan gratuito compartido con el resto del proceso.
  4 threads por worker (gthread) para que una petición lenta (Nominatim/
  push/Cloudinary) no bloquee a las demás DENTRO del mismo worker - el
  cuello de botella real es de I/O esperando una red externa, no de CPU,
  así que hilos (no más workers) es la herramienta correcta. `--timeout
  60` (gunicorn mata y reinicia un worker si una petición tarda más de
  esto) da margen de sobra sobre el peor caso conocido de este proyecto
  (~9-10s con geocoding + push, medido más abajo), sin dejarlo
  indefinido.

  **Verificación en local - limitación encontrada**: `gunicorn` **no
  puede correr en este Windows** - confirmado intentando ejecutar
  literalmente el comando de la tarea (`gunicorn config.wsgi:application
  --workers 2 --threads 4 --worker-class gthread --timeout 60`):
  `ModuleNotFoundError: No module named 'fcntl'` (gunicorn importa
  módulos exclusivos de Unix al arrancar, antes de leer un solo
  argumento - es un servidor "WSGI HTTP Server for UNIX", según su
  propio `pip show gunicorn`). No hay WSL ni Docker instalados en esta
  máquina para correrlo en un Linux real.

  Como alternativa LOCAL que sí se pudo ejecutar: se usó el
  `runserver` de Django (que por defecto ya sirve con
  `ThreadingMixIn` - hilos reales de Python, el mismo mecanismo de
  fondo que `--worker-class gthread`), con
  `incidentes.views_web.geocodificar_direccion` parcheado EN MEMORIA
  (sin tocar el archivo) para tardar 5s siempre, simulando el peor caso
  de Nominatim sin depender de la red real. Se dispararon dos peticiones
  en paralelo contra un paseo de prueba `en_vivo`:

  | Petición | Resultado | Tiempo |
  |---|---|---|
  | `POST .../incidentes/.../reportar/` (geocoding parcheado a 5s + subida real a Cloudinary + Web Push real al dueño) | 201 (incidente creado) | **9.84 s** |
  | `GET /cuentas/login/`, disparada 0.3s después de la anterior | 200 | **0.008 s** |

  La petición rápida NO esperó a la lenta (0.008s, no ~9-10s) - confirma
  que los hilos resuelven el problema de fondo (una petición de I/O
  lenta no bloquea a las demás), aunque esto prueba el mecanismo de
  **hilos**, no literalmente `gunicorn --worker-class gthread` (que no
  pudo ejecutarse en esta máquina). La verificación de que gunicorn en
  sí se comporta igual queda pendiente de confirmar en Render (Linux
  real) tras el despliegue de este cambio.

- **Punto 3 — correo sin distinguir mayúsculas (RF1)**: diagnóstico -
  la auditoría anterior ya había confirmado que `obtener_por_correo()`
  hacía un match exacto (sensible a mayúsculas) y que el índice único
  `correo_1` no tiene collation (comparación binaria de Mongo, también
  sensible a mayúsculas). `usuarios.decorators.es_correo_admin()` y
  `settings.CANIGO_ADMIN_EMAILS` **ya normalizaban** con
  `.strip().lower()` desde antes de este punto - no necesitaron cambio.

  Se agregó `usuarios.forms._normalizar_correo()` (única función que
  hace `.strip().lower()`, reusada por los dos formularios donde un
  correo escrito a mano entra al sistema) y `clean_correo()` en
  `_RegistroBaseForm` (cubre registro Y el "prellenado" de
  `request.session['correo_prellenado']`, que sale de
  `form.cleaned_data['correo']` ya normalizado) y en `LoginForm`.

  **Cuentas existentes guardadas con mayúsculas**: la tarea pidió
  **solo lectura** - reportar sin modificar. Resultado contra
  `canigo` (producción, `find`/`count_documents` únicamente, ninguna
  escritura): de **8 usuarios totales**, **0 correos con alguna
  mayúscula** y **0 grupos de correos duplicados que solo difieran en
  mayúsculas**. No hace falta ningún `update_many` en la práctica - la
  base de producción ya está limpia en este aspecto. Si en el futuro
  apareciera alguno, el `update_many` propuesto (NO ejecutado) sería:
  ```python
  for doc in db.usuarios.find({'correo': {'$regex': '[A-Z]'}}):
      db.usuarios.update_one(
          {'_id': doc['_id']},
          {'$set': {'correo': doc['correo'].strip().lower()}},
      )
  ```
  uno por uno (no un `update_many` con pipeline a secas) porque primero
  habría que resolver a mano cualquier grupo que quedara duplicado al
  normalizar (dos cuentas reales con el mismo correo en distinta
  mayúscula) - el índice único `correo_1` rechazaría el segundo
  `update_one` de un grupo así, lo cual es la señal correcta de que esa
  cuenta necesita revisión manual antes de normalizarla.

  Como la base de datos actual no tiene ningún caso, **y** el login ya
  funciona para una cuenta vieja con mayúsculas gracias al fallback de
  `obtener_por_correo()` (ver abajo), no hay urgencia de ejecutar esto -
  queda documentado para el día en que sí aparezca alguno.

  **`obtener_por_correo()` ahora intenta primero un match exacto sobre
  el correo normalizado** (usa el índice, cubre toda cuenta nueva y
  cualquier cuenta vieja que ya esté en minúscula) **y, solo si ese
  falla, un `$regex` case-insensitive** (`^correo_escapado$`, con
  `re.escape()` para evitar inyección de regex) - cubre una cuenta vieja
  guardada con mayúsculas sin necesitar la migración de arriba. El
  segundo intento no usa el índice, pero solo corre cuando el primero no
  encontró nada - no afecta el camino común (cuenta ya en minúscula).

  **Verificado ejecutando** (`canigo_dev`, cuentas `@canigo.test`
  creadas y borradas en la misma prueba): registro con el correo en
  MAYÚSCULAS → se guarda en minúscula; un segundo registro con OTRA
  variante de mayúsculas del mismo correo → rechazado como duplicado;
  una cuenta sembrada manualmente con el correo en mayúsculas
  (simulando una cuenta vieja, sin pasar por el formulario) → el login
  escribiendo el correo en minúscula la encuentra y entra
  correctamente.

- **Punto 4 — timeout de la subida a Cloudinary (RNF3)**: diagnóstico -
  `core/media.py::subir_imagen()`/`subir_certificado()` llamaban a
  `cloudinary.uploader.upload()` sin pasarle `timeout`, igual que el
  caso de Web Push de la revisión anterior (`_enviar_push()`, ya
  corregido) - dependían del default interno de la librería (urllib3),
  sin ningún límite propio del proyecto. Se agregó
  `_TIEMPO_MAXIMO_SUBIDA_SEGUNDOS = 15` (una foto de celular puede pesar
  varios MB, más que la carga de una petición normal) pasado como
  `timeout=` en las dos llamadas a `cloudinary.uploader.upload()`.

  No hizo falta agregar ningún `except` nuevo: confirmado leyendo
  `cloudinary/uploader.py` (instalado en el proyecto) que
  `call_api()` ya envuelve `urllib3.exceptions.HTTPError` (del que
  `MaxRetryError`/`ReadTimeoutError`/`ConnectTimeoutError` SON
  subclases, confirmado con `issubclass()`) en su propio
  `cloudinary.exceptions.Error` - el `except CloudinaryError` que ya
  existía en las dos funciones atrapa un timeout exactamente igual que
  cualquier otro fallo de red, y lo convierte en `ErrorSubidaImagen`/
  `ErrorArchivoInvalido` con un mensaje claro, sin dejar nada a medias
  (ningún archivo llega a subirse si el timeout corta la conexión antes
  de que la subida termine). La atomicidad de `a7dd1fb` (si sube un
  certificado y falla el otro, el primero se borra de Cloudinary y la
  mascota no se crea) sigue aplicando sin cambios - está hecha por tipo
  de excepción, no le importa SI el fallo fue un timeout u otra cosa.

  **Verificado ejecutando** (contra el Cloudinary REAL del proyecto, sin
  simular nada): con `_TIEMPO_MAXIMO_SUBIDA_SEGUNDOS` forzado a `0.001`
  (1 milisegundo, imposible de cumplir en una red real), `subir_imagen()`
  lanzó `ErrorSubidaImagen` en 0.47s con el mensaje esperado
  (`MaxRetryError` envuelto); con el valor normal de 15s, una subida real
  de prueba terminó en 1.34s sin problema (y se borró de Cloudinary al
  terminar la prueba).

- **Punto 5 — incidentes en el detalle del historial del paseo, para
  ambos roles (RF16)**: diagnóstico - la auditoría anterior ya había
  confirmado que el dueño SÍ tenía un historial completo
  (`incidentes:lista`, `@requiere_dueno`), pero el paseador no tenía
  NADA equivalente (ni vista, ni link en el navbar) - su único camino
  incidental era el banner del mapa (`_info_incidente_reciente`, solo el
  incidente MÁS RECIENTE de ese paseo, no una lista). También se había
  confirmado que `incidentes.repository.listar_por_paseos()` existía
  pero nunca se usaba en ningún lado.

  **Sección "Incidentes de este paseo"** (`coordenadas/templates/
  coordenadas/mapa.html`, debajo de "Fotos del paseo"): nueva, visible
  tanto en vivo como histórico (mismo `_paseo_accesible_o_none()` que ya
  cubre los dos estados). `coordenadas.views_web.mapa_paseo()` calcula
  `items_incidentes` con el mismo criterio de privacidad que
  `incidentes.views_web.lista_incidentes()`: paseador → `repository.
  listar_por_paseos([paseo['_id']])` (sin filtrar, ve todos los de ESE
  paseo); dueño → `repository.listar_visibles_para_dueno([paseo['_id']],
  ids_mascota_dueno)`, donde `ids_mascota_dueno` sale de las mascotas
  que ya estaban resueltas para ESE dueño más arriba en la misma función
  (`_mascotas_del_dueno_en_paseo()` - nunca las 8 posibles del paseo).
  `fecha_hora` se marca `tzinfo=utc` antes de pasarla a la plantilla
  (mismo cuidado de siempre - ver CLAUDE.md), igual que ya hacía
  `incidentes.views_web.detalle_incidente()` para esta misma fecha, en
  la pantalla individual.

  **Hallazgo aparte, no corregido (fuera de alcance de este punto)**:
  `incidentes.views_web.lista_incidentes()` (el historial GLOBAL del
  dueño, no esta sección nueva) NO marca `tzinfo=utc` sobre `fecha_hora`
  antes de pasarla a `lista.html` - a diferencia de `detalle_incidente()`
  y de la sección nueva de este punto, que sí lo hacen. Es el mismo bug
  de zona horaria documentado en CLAUDE.md/sección 8 (naive UTC
  interpretado como hora local, 5 horas de desfase), pero en un lugar
  que esta tarea no pidió tocar - se reporta para una corrección
  aparte.

  **Lista propia del paseador** (`/incidentes/paseador/`, vista nueva
  `incidentes.views_web.lista_incidentes_paseador()`, reutiliza
  `lista.html` tal cual - mismo shape de `items` que ya usaba
  `lista_incidentes()`): todos los incidentes de TODOS los paseos del
  paseador (`paseos_repository.listar_por_paseador()` +
  `repository.listar_por_paseos()`), sin filtrar - se los llevó él
  mismo. Nuevo link "Incidentes" en la rama del paseador del navbar
  (`core/templates/base.html`) - antes esa rama no tenía ninguno.

  **Verificado ejecutando** (`canigo_dev`, incidentes de prueba creados
  y borrados en la misma prueba, sobre el paseo multi-dueño existente
  de pruebas anteriores): sembrados 3 incidentes marcados (uno afecta a
  la mascota de D1, otro a la de D2, otro "accidente_paseador") -
  **paseador**: ve los 3; **D1**: ve el suyo + el de "accidente_
  paseador", **nunca** el de D2; **D2**: ve el suyo + el de "accidente_
  paseador", **nunca** el de D1 - confirma que el filtro de privacidad
  de `listar_visibles_para_dueno()` se respeta igual en esta sección
  nueva. `/incidentes/paseador/` muestra los incidentes del paseador sin
  filtrar. Capturas de pantalla (vista de celular, 390px) tomadas contra
  estos datos de prueba antes de borrarlos. De paso, se encontraron y
  limpiaron 4 incidentes de prueba de tareas ANTERIORES de este mismo
  cierre de auditoría que habían quedado sin borrar en `canigo_dev`
  (`"Medicion de timeout de push..."`, de la revisión de fase 2).

- **Punto 5, corrección posterior (14 de octubre) — `fecha_hora` sin
  marcar como UTC en los dos historiales de incidentes**: el hallazgo
  aparte reportado junto con el punto 5 (`lista_incidentes()`, el
  historial global del dueño, mostraba la hora cruda de Mongo sin
  convertir - 5 horas adelantada respecto a Bogotá) se corrigió:
  `incidente['fecha_hora'] = incidente['fecha_hora'].replace(tzinfo=
  timezone.utc)` antes de armar cada `item`, igual que ya hacía
  `detalle_incidente()`. Se aplicó el MISMO fix en
  `lista_incidentes_paseador()` (la vista nueva de ese mismo punto 5,
  agregada reusando `lista_incidentes()` como base - heredó el mismo
  descuido sin que se hubiera notado hasta ahora, porque las dos
  comparten plantilla pero no código).

  **Verificado ejecutando** (`canigo_dev`, con `git stash` para
  reproducir el antes/después sobre el mismo incidente de prueba,
  sembrado con `fecha_hora = 2026-10-14 01:00:00` UTC = 2026-10-13
  20:00 Bogotá): ANTES del fix, `/incidentes/` mostraba "14 de Octubre
  de 2026 a las 01" (la hora UTC cruda, sin convertir); DESPUÉS,
  "13 de Octubre de 2026 a las 20" (correcto). Confirmado también en
  `/incidentes/paseador/` con el mismo incidente de prueba. Incidente
  de prueba borrado al terminar.

- **INC-07 — en iPhone (Safari o Chrome normal, sin agregar Canigo a
  inicio), `_activar_push.html` mostraba "Tu dispositivo o navegador no
  admite notificaciones" en vez de las instrucciones de iOS**:
  diagnóstico - el comentario de la línea ya decía *"por eso esta
  condición va ANTES de mirar el permiso"*, pero el `if/else` real tenía
  `!soportaPush` como PRIMERA condición, antes de `esIOS && !esStandalone`.
  `soportaPush` exige `'PushManager' in window`, que en iOS Safari/Chrome
  FUERA de modo standalone es `false` (no es que falle o esté incompleto:
  directamente no existe en absoluto hasta iOS 16.4+ **y** solo dentro de
  una PWA instalada) - así que `!soportaPush` ya daba `true` y disparaba
  la rama genérica de "no soportado" antes de que el código llegara a
  revisar si era iOS. Fix: se invirtió el orden - `esIOS && !esStandalone`
  ahora va primero, igual que ya decía el comentario (corregido para que
  diga lo que el código realmente hace).

  **Verificado ejecutando** (`canigo_dev`, Chrome headless con
  `Network.setUserAgentOverride` a un iPhone real y `delete
  window.PushManager` inyectado ANTES de que cargara la página - vía
  `Page.addScriptToEvaluateOnNewDocument`, que necesita `Page.enable`
  primero para que el script realmente se ejecute, detalle encontrado
  recién al armar esta prueba) con `git stash` para el antes/después:
  ANTES del fix, con `PushManager` genuinamente ausente (`'PushManager'
  in window` → `false`, igual que un iPhone real fuera de standalone),
  se mostraba "no admite notificaciones" y las instrucciones de iOS
  quedaban ocultas; DESPUÉS, exactamente al revés (instrucciones
  visibles, "no admite notificaciones" oculto). Dos casos de regresión
  confirmados sin cambios: navegador de escritorio sin `PushManager`
  (no iOS) sigue mostrando "no admite notificaciones"; iPhone en modo
  **standalone** (`navigator.standalone = true`, `PushManager` presente)
  sigue mostrando el botón normal de activar, no las instrucciones.

  **Cómo probarlo en un iPhone real** (pendiente de la autora, ningún
  entorno de prueba automatizado reemplaza esto): entrar a Canigo desde
  Safari (o Chrome, que en iOS usa el mismo motor WebKit) **sin**
  haberlo agregado a la pantalla de inicio, iniciar sesión, y mirar la
  tarjeta de notificaciones en el panel (`bienvenida.html`/
  `bienvenida_paseador.html`) - debería decir "Para recibir
  notificaciones: toca Compartir → Agregar a inicio..." en vez de "no
  admite notificaciones". Para confirmar que el flujo normal sigue
  intacto: agregar Canigo a inicio desde ese mismo botón Compartir,
  abrirlo desde el ícono nuevo (no desde Safari), volver a esa misma
  tarjeta - ahí debería aparecer el botón "Activar notificaciones" de
  siempre.

**Lentitud en producción (14 de octubre)**:

- **Causa raíz confirmada del login lento**: `check_password()` con el
  hasher por defecto de Django (`PBKDF2PasswordHasher`, 1.000.000 de
  iteraciones) mide **~1.0-1.3s en esta máquina de desarrollo** (Ryzen 7
  7730U) - medido en producción (Render, plan gratuito, CPU compartida y
  limitada a una fracción de un core), el `POST /cuentas/login/` real
  tardó **2.4-3.1s** (3 mediciones por rol, cuenta `@canigo.test`,
  servicio ya despierto). Es el único paso de todo el flujo de login
  cuyo costo es intrínsecamente de CPU (no de red ni de Mongo) y escala
  con la potencia de cómputo disponible - en un plan con CPU limitada,
  tarda proporcionalmente más que en cualquier máquina de desarrollo
  normal. **No se cambió el hasher ni las iteraciones** (decisión de
  seguridad, pendiente de la autora) - ver las opciones medidas más
  abajo.

- **Opciones de hasher/iteraciones** (medidas en esta máquina,
  *no aplicadas* - la autora decide): PBKDF2 escala linealmente con las
  iteraciones -
  600.000 → ~600ms (40% más rápido), 390.000 → ~370ms (~3x más rápido),
  260.000 → ~250ms (~4x más rápido), 100.000 → ~100ms (~10x más rápido,
  cerca del viejo default de Django ~2019). Bajar iteraciones no usa
  memoria adicional (PBKDF2 es CPU-only, a diferencia de Argon2/bcrypt,
  que exigen varios MB de RAM por verificación - un costo real en un
  plan de 512MB con varias verificaciones concurrentes). Argon2
  (`argon2-cffi`) y bcrypt (`bcrypt`) no están instalados en el
  proyecto - usarlos exigiría agregar una dependencia nueva, no es un
  cambio de una sola línea de `settings.py`. Más iteraciones = más
  resistente a un ataque de fuerza bruta offline si la base de datos se
  filtrara algún día; menos iteraciones = login más rápido. Es un
  trade-off de seguridad explícito, no algo que se decida por
  rendimiento solo.

- **Inventario de peticiones periódicas** (ver tabla completa en el
  reporte entregado a la autora) - resumen: 4 `setInterval` reales que
  llaman al servidor (notificaciones genérico 15s, mapa en vivo 8s,
  "Mis paseos" 10s, dashboard del dueño 10s) + 1 que NO llamaba al
  servidor hasta este punto en segundo plano por descuido (dashboard
  del paseador, 12s - corregido, ver más abajo) + el emisor de GPS (8s,
  nunca se pausa, por diseño - RNF2). Los pollers "genéricos" y los de
  dashboard YA comparten una sola petición con el punto de notificaciones
  del navbar (patrón establecido, sin duplicación entre ellos).

- **Punto 3 — `coordenadas_de_paseo()` reenviaba TODO el historial de
  puntos en cada vuelta del polling del mapa en vivo**: diagnóstico -
  el polling de `mapa.html` (cada 8s mientras el paseo está "en_vivo")
  llamaba a `repository.listar_por_paseo(id_paseo)` SIN ningún filtro,
  así que cada respuesta traía (y volvía a serializar a JSON) todos los
  puntos GPS desde el inicio del paseo, no solo los nuevos - el
  volumen total transferido y el costo de Mongo a lo largo de UN paseo
  crecían con el **cuadrado** de su duración, no linealmente (confirmado
  leyendo el código: el filtro de "ya procesados" vivía solo del lado
  del cliente, `puntos.slice(puntosProcesados)` en `mapa.html`, después
  de que el servidor ya había hecho el trabajo completo). Para un paseo
  de 30 minutos (~225 puntos a 8s), esto significa que el servidor
  termina transfiriendo del orden de **~25.000 valores de punto** a lo
  largo del paseo (suma 1+2+...+225), en vez de los 225 que realmente
  importan.

  Fix: `coordenadas_de_paseo()` ahora acepta `?desde=<ISO>` (opcional,
  reusa `_parsear_fecha()` que ya existía para
  `registrar_coordenada()`) y `repository.listar_por_paseo()` filtra
  por `fecha_captura > desde` cuando se le pasa. `mapa.html` guarda la
  `fecha_captura` del último punto ya recibido (`ultimaFechaCapturaConocida`,
  reemplaza al contador `puntosProcesados`) y la manda en cada vuelta -
  la respuesta ya viene incremental, sin recortar nada del lado del
  cliente. Se agregó `hay_puntos_historicos` (independiente de
  `puntos`, vía `obtener_ultimo_punto()` - ya existía, consulta barata
  con índice) porque con el polling incremental una respuesta puede
  traer 0 puntos NUEVOS aunque el paseo sí tenga historial (simplemente
  no hubo una lectura GPS nueva en esos 8s) - sin este campo aparte,
  "Todavía no hay puntos..." habría parpadeado en cada vuelta sin
  novedades.

  **Verificado ejecutando** (`canigo_dev`): sin `desde`, trae todos los
  puntos sembrados; con `desde` = el último conocido y SIN puntos
  nuevos, trae 0 puntos pero `hay_puntos_historicos` sigue `true`; con
  un punto nuevo agregado, trae exactamente ese 1 punto. Confirmado
  también de punta a punta en un navegador real (Chrome headless): el
  mapa cargó con 1 punto sembrado, se agregó un 2º punto a más de 10m
  del primero, y tras un ciclo de polling (8-9s) el número de `<path>`
  en el mapa subió de 4 a 5 (línea extendida + nuevo circleMarker) sin
  ningún error - el polling incremental se integra sin romper el dibujo
  existente (ver "Hallazgos de la caminata real del 13 de octubre,
  punto 4").

  **Confirmado después en producción real** con un paseo en vivo de
  ~12 minutos (89 ciclos de GPS + mapa cada 8s, cuentas `@canigo.test`,
  respaldadas y borradas al terminar): cada respuesta del mapa trajo
  **exactamente 1 punto nuevo** (nunca el historial acumulado) durante
  TODO el paseo - confirma que el fix funciona igual en producción que
  en local. Tiempos estables (GPS mediana 0.74s, mapa mediana 0.95s),
  sin tendencia a empeorar con la duración - pero con picos aislados
  (GPS hasta 14.3s, mapa hasta 3.1s en un solo ciclo cada uno, de 89):
  consistentes con contención de CPU compartida del plan gratuito de
  Render bajo uso concurrente, no con una fuga progresiva - ver más
  abajo, "Lentitud en producción".

- **Punto 4 — el dashboard del paseador (`bienvenida_paseador.html`,
  sondeo de 12s cuando NO está caminando) era el único de los 4 sondeos
  periódicos del proyecto sin pausa en segundo plano**: diagnóstico -
  `usuarios/bienvenida.html` y `paseos/mis_paseos.html` ya tenían el
  patrón `iniciarSondeo()`/`detenerSondeo()` + `visibilitychange`
  (ver sección 8 más abajo); este archivo nunca lo tuvo, seguía
  llamando al servidor cada 12s aunque el navegador estuviera en
  segundo plano o la pantalla bloqueada. Fix: mismo patrón exacto,
  copiado de `bienvenida.html` - sin cambiar el intervalo de 12s (eso
  es una inconsistencia aparte frente a los 10s de los otros dos, no
  parte de esta corrección - reportado, no corregido, para no mezclar
  dos cambios en un commit).

  **Verificado ejecutando** (`canigo_dev`, Chrome headless, `fetch`
  interceptado para contar llamadas reales a `.../bienvenida/estado/`):
  con la pestaña oculta (`document.visibilityState = 'hidden'`
  simulado) durante 13s (más de un ciclo de 12s), 0 peticiones nuevas;
  al volver a "visible", 1 petición inmediata (el refresco explícito al
  recuperar foco, igual que `bienvenida.html`).

- **Conclusión tras los dos puntos corregidos + ~12 minutos de uso
  continuo real en producción**: no se observó una tendencia de
  degradación progresiva ("se pone más lento mientras más se usa") en
  esa ventana - los tiempos de respuesta se mantuvieron estables de
  principio a fin. Sí aparecieron picos aislados de latencia bajo la
  CPU compartida/limitada del plan gratuito (hasta 14.3s en un único
  ciclo de 89) - coherente con "a veces los botones tardan en
  responder" como síntoma de contención de CPU puntual, no como fuga
  de memoria. La causa dominante y más reproducible de lentitud sigue
  siendo el costo fijo de `check_password()` en cada login (ver más
  arriba) - eso no cambia con estos dos puntos, porque ninguno de los
  dos lo toca.

- **Decisión de la autora sobre el hasher (14 de octubre)**: PBKDF2-SHA256
  con **600.000 iteraciones** (antes 1.000.000, el default de Django) -
  es el mínimo que recomienda hoy el [OWASP Password Storage Cheat
  Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
  para PBKDF2-HMAC-SHA256 ("use PBKDF2 with a work factor of 600,000 or
  more [...] with an internal hash function of HMAC-SHA-256") - no se
  bajó más allá de ese piso por seguridad, aunque mediciones anteriores
  mostraban que iteraciones más bajas (260k, 100k) serían aún más
  rápidas.

  `core/hashers.py::PBKDF2HasherOWASP600k` hereda de
  `PBKDF2PasswordHasher` de Django, solo cambia `iterations`. `settings.
  PASSWORD_HASHERS` lo pone PRIMERO (es el que usa `make_password()`
  para cualquier contraseña nueva) y deja el `PBKDF2PasswordHasher` de
  Django DESPUÉS (pedido explícito, defensa adicional explícita, aunque
  con el `algorithm` igual en los dos - `'pbkdf2_sha256'` heredado sin
  cambios - el primero de la lista ya es en la práctica el único que
  Django usa para verificar CUALQUIER hash pbkdf2_sha256, viejo o
  nuevo: las iteraciones reales se leen del propio hash guardado al
  verificar, nunca de `self.iterations` - ver el docstring de la
  clase).

  **Actualización automática al iniciar sesión**: como este proyecto no
  usa el modelo `User` de Django (pymongo directo, sin ORM - ver
  CLAUDE.md), el re-hash automático que Django normalmente hace solo
  vía `AbstractBaseUser.check_password()` hubo que armarlo a mano en
  `usuarios.views_web.login()`: se le pasa un `setter` a la función
  `check_password()` de Django (acepta uno desde siempre, parámetro que
  este proyecto nunca había usado) - si la contraseña es correcta Y el
  hash guardado no coincide con los parámetros del hasher "default"
  actual (`hasher.must_update(encoded)`, interno de Django), el
  `setter` genera un hash nuevo con `make_password()` (600k) y lo
  guarda (`usuarios.repository.actualizar_contrasena()`, sin tocar
  ningún otro campo). Una cuenta vieja con 1.000.000 de iteraciones
  queda en 600.000 la PRIMERA vez que su dueño inicia sesión después de
  este cambio, sin que nadie tenga que hacer nada - las que nunca
  vuelvan a iniciar sesión se quedan en 1.000.000 para siempre (más
  lentas de verificar, pero igual de válidas).

  **Verificado ejecutando** (`canigo_dev`): una cuenta de prueba
  sembrada con un hash simulando 1.000.000 de iteraciones (el formato
  real de una cuenta anterior a este cambio) inició sesión
  correctamente por la vista real (`/cuentas/login/`), y quedó guardada
  con `600000` iteraciones inmediatamente después - confirmado leyendo
  el documento en Mongo tras el login, no solo la respuesta HTTP.

**Hallazgos de la prueba con un usuario final (14 de octubre)**:

- **INC-08 — error al guardar cambios al editar**: diagnóstico -
  reproducidas las ediciones de perfil del paseador (con y sin cambiar
  cada campo), mascota (con y sin certificados nuevos) y confirmado que
  no existe pantalla de "editar datos del dueño" (nada que probar ahí).
  Causa raíz encontrada: `EditarPerfilPaseadorForm.clean_telefono()`
  (agregado en `437334f`, Incremento 4 punto B) revalida el teléfono en
  **cada** "Guardar cambios", incluso si el paseador no tocó ese campo -
  una cuenta creada ANTES de esa validación (con un teléfono en
  cualquier formato viejo, ej. un fijo de 7 dígitos) queda bloqueada
  para guardar CUALQUIER cambio de perfil (descripción, foto) hasta que
  también arregle un teléfono que ni siquiera estaba intentando tocar.
  Los otros 3 sospechosos (middleware de autorización de datos,
  normalización de correo, timeout de Cloudinary) se descartaron:
  `EditarPerfilPaseadorForm` no tiene campo `correo`; una cuenta
  reciente (post cce89d8) siempre tiene `autorizacion_datos_ok` en
  sesión; y una subida normal de foto termina muy por debajo de los 15s
  del timeout (ya medido en la tarea de lentitud).

  Fix: `EditarPerfilPaseadorForm` recibe ahora `telefono_actual` (el
  valor YA guardado) - `clean_telefono()` solo exige el patrón nuevo
  **si el valor cambió** respecto al guardado; si el paseador deja el
  mismo teléfono viejo tal cual, se acepta sin volver a validarlo (dato
  viejo, no uno que esté intentando guardar ahora). Cambiarlo a
  cualquier OTRO valor sigue exigiendo el formato correcto - doble capa
  intacta, el backend sigue siendo quien decide.

  **Verificado ejecutando** (`canigo_dev`): cuenta de prueba con
  teléfono `"6301234"` (formato viejo) - ANTES del fix, "Guardar
  cambios" sin tocar nada fallaba con "Ingresa un celular colombiano
  válido..."; DESPUÉS, guarda sin error. Cambiar a un teléfono NUEVO
  pero inválido (`"12345"`) sigue rechazándose igual que antes (sin
  regresión). Edición de mascota sin archivos nuevos, confirmada sin
  error (no afectada por este bug).

- **INC-09 — horario publicado sin comuna**: diagnóstico -
  `paseos.forms.PublicarHorarioForm.zonas` era `required=False` a
  propósito (decisión original: "0 a N zonas, nunca 'todas' por
  defecto" - ver CLAUDE.md), permitiendo publicar un horario sin
  ninguna comuna - invisible para cualquier dueño que filtrara por
  zona en "Paseadores disponibles", sin ninguna pista de en qué parte
  de la ciudad atiende ese paseador. La autora decidió que al menos
  una zona pase a ser obligatoria. Fix: `zonas` ahora es
  `required=True` (el default) con `error_messages={'required': ...}`,
  mismo patrón que `InscribirMascotaForm.ids_mascota`. No hizo falta
  tocar la vista (`publicar_disponibilidad()`) ni el template: esa
  vista ya arma el mensaje de error con el primer campo que falle
  (`messages.error(..., f'No se pudo publicar el horario: {primer_error}')`),
  así que "Elige al menos una zona de servicio." sale gratis por ese
  mismo mecanismo genérico.

  **Horarios ya existentes sin zona** (solo lectura, sin modificar):
  de 8 paseos en `canigo` (producción), **1** no tiene ninguna zona
  (`zonas: []`) - ya está en estado `historico` (un paseo ya
  finalizado, no una oferta activa que un dueño pudiera estar
  buscando por zona ahora mismo).

  **Verificado ejecutando** (`canigo_dev`): publicar sin zonas →
  rechazado, mensaje "Elige al menos una zona de servicio." visible,
  cero paseos creados; publicar con 1 zona → aceptado, "Horario
  publicado correctamente.", paseo creado normalmente.

- **INC-10 — sin límite de caracteres**: diagnóstico - se listaron
  programáticamente TODOS los `CharField`/`EmailField` de todos los
  `forms.py` del proyecto (28 campos en 11 formularios) para confirmar
  cuáles tenían `max_length` y cuáles no, en vez de revisarlos a
  mano uno por uno. `max_length` en un `CharField`/`EmailField` ya
  agrega el atributo HTML `maxlength` automáticamente (comportamiento
  de Django, confirmado renderizando el widget) - no hizo falta
  tocar ningún template para la parte visual.

  **Antes de reducir cualquier límite ya existente o agregar uno
  nuevo**, se revisó `canigo` (producción) por campo para confirmar que
  ningún dato real ya guardado quedara más largo que el nuevo límite
  (mismo cuidado que INC-08: una validación nueva no debe bloquear la
  edición de un dato viejo que no se está tocando). Se encontró **una
  mascota de prueba real** (cuenta `@gmail.com`, registrada el mismo 14
  de octubre - coincide con la sesión de prueba del usuario final) con
  `nombre`/`raza` de 100 caracteres (texto de relleno, "2000...") y
  **`observaciones` de ~1.9 MILLONES de caracteres** - claramente datos
  de prueba/estrés, no una mascota real. Se decidió **mantener**
  `nombre`/`raza` de mascota en 100 (no bajar a los 40/50 sugeridos)
  justamente por este caso real ya guardado con esa longitud; para
  `observaciones` sí se aplicó el límite sugerido de 500 porque ninguna
  OTRA mascota real se acerca a eso - esta única mascota de prueba
  queda reportada aparte (ver el reporte entregado a la autora) en vez
  de truncarla sin permiso.

  No existe ningún campo "Indicaciones" en el proyecto (sugerido en la
  tarea) - ninguna pantalla real lo tiene, así que no se agregó nada
  para un campo que no existe.

  Tabla final de límites (los marcados con * ya tenían ese valor, sin
  cambios):

  | Campo | Máximo | Dónde |
  |---|---|---|
  | Nombre de persona | 80 | registro (dueño/paseador) |
  | Correo | 254 | registro, login |
  | Teléfono | 20 (ya validado a 10 dígitos por regex) | registro, editar perfil |
  | Contraseña | 128 | registro, login |
  | Nombre de mascota | 100* | registrar/editar mascota (dato real ya en 100) |
  | Raza | 100* | registrar/editar mascota (dato real ya en 100) |
  | Observaciones de mascota | 500 | registrar/editar mascota |
  | Descripción del paseador | 500 | registro, editar perfil |
  | Descripción del incidente | 500 | reportar incidente |
  | Comentario de calificación | 300 | calificar paseo |
  | Observación de verificación (admin) | 300* | panel de administración |
  | Dirección | 150 | registro de dueño |
  | Nombre/entidad de certificado | 150* | certificados del paseador |

  **Verificado ejecutando** (`canigo_dev`): un `nombre` de registro de
  90 caracteres (más de 80) se rechaza con el mensaje estándar de
  Django ("Asegúrese de que este valor tenga como máximo 80
  caracteres..."); un registro normal, dentro de todos los límites,
  sigue funcionando igual que antes. Confirmado con
  `str(form['campo'])` que el HTML ya trae `maxlength` para los campos
  revisados (nombre, teléfono, correo).

- **INC-11 — panel de administración de Django expuesto**: diagnóstico
  - confirmado que ningún `admin.py` del proyecto llama a
  `admin.site.register()` (son los archivos vacíos que deja
  `startapp` por defecto) - `/admin/` de Django nunca tuvo ningún
  modelo que administrar, solo expone una pantalla de login y
  superficie de ataque sin ningún beneficio real. El panel de
  administración REAL del proyecto (RF14, verificación de paseadores)
  es `/administracion/verificacion/`, una app propia sin relación con
  `django.contrib.admin`.

  Fix: `path('admin/', admin.site.urls)` ahora se agrega a
  `urlpatterns` SOLO si `settings.DEBUG` es `True` - en producción
  (`DEBUG=False`), la ruta no existe en absoluto (no es un
  403/401, que confirmaría que la URL es real - es un 404 igual que
  cualquier URL que nunca estuvo en `urlpatterns`). `django.contrib.
  admin` se queda en `INSTALLED_APPS` sin cambios (lo siguen
  necesitando `auth`/`contenttypes`/`sessions` internamente) - solo se
  quitó la RUTA en producción.

  **Verificado ejecutando**: con `DEBUG=True` (local, como siempre) -
  `/admin/` responde `302` (redirige al login de Django, sigue
  disponible). Simulando `DEBUG=False` (vía `Client(secure=True)`, para
  evitar el ruido del redirect a HTTPS de `SecurityMiddleware` que
  tapaba el resultado real la primera vez que lo probé) - `/admin/`
  responde **404**; `/administracion/verificacion/` (el panel real)
  sigue respondiendo `302` (redirige a login, sin tocar), confirmando
  que solo se quitó la ruta de Django, no la administración real del
  proyecto.

- **Mejora 1 — foto desde cámara o galería, y aviso de carga**:
  diagnóstico - el compañero que probó la plataforma reportó que, en su
  celular, el selector de foto abría directo la cámara (sin opción de
  elegir una ya tomada) y que al enviar un formulario con archivo
  (registrar mascota, certificados, emergencia, foto del paseo) no había
  ninguna señal de que la página estuviera procesando el envío, lo que
  invitaba a tocar "enviar" dos veces.

  Fix (dos partes independientes):
  1. **Selector de foto**: se agregó `accept="image/*"` a los 4
     `ImageField`/`FileField` de foto que ya existían
     (`mascotas.MascotaForm.foto`, `incidentes.ReportarIncidenteForm.foto`,
     `usuarios.EditarPerfilPaseadorForm.foto_perfil`,
     `paseos.SubirFotoPaseoForm.foto`) - **sin** el atributo `capture`
     (que sí fuerza la cámara). `accept` por sí solo le dice al navegador
     qué tipo de archivo se espera, pero dejando que él ofrezca cámara Y
     galería como opciones, no una sola a la fuerza.
  2. **Aviso de carga**: un solo par de funciones compartidas,
     `canigoMarcarCargando(boton)`/`canigoQuitarCargando(boton)`, definidas
     una vez en `core/templates/base.html`, más un único
     `document.addEventListener('submit', ...)` a nivel de documento que
     las aplica automáticamente a CUALQUIER formulario tradicional del
     sitio (deshabilita el botón y le pone un spinner + «Cargando…»,
     evitando el doble envío). Los dos formularios que ya usaban
     `fetch`/`FormData` en vez de un POST tradicional (emergencia y subir
     foto del paseo, en `bienvenida_paseador.html` - ver Incremento 4,
     punto D1) manejan su propio ciclo de vida de envío, así que se
     marcaron con el atributo `data-canigo-carga-manual` (que el listener
     genérico respeta y no toca) y se migraron para llamar a las MISMAS
     dos funciones compartidas en vez de repetir su propia lógica de
     deshabilitar/rehabilitar el botón.

  **Verificado ejecutando** (navegador headless a 390×844, sesión real de
  dueño/paseador en `canigo_dev`):
  - `/mascotas/nueva/`: el input de foto renderiza con
    `accept="image/*"` y sin `capture` (confirmado leyendo los atributos
    del DOM ya renderizado, no solo el código fuente).
  - Un formulario tradicional (login) sometido con
    `requestSubmit()`: el botón pasa de "Ingresar" a un spinner +
    "Cargando…" y queda `disabled`, sin tocar el HTML de
    `login.html` para lograrlo (confirma que el listener genérico de
    `base.html` sí alcanza formularios que nunca se tocaron a mano).
  - El formulario de emergencia (`fetch`, con
    `data-canigo-carga-manual`): sometido con una mascota, tipo y foto
    reales contra el servidor de desarrollo - el botón muestra
    "Cargando…"/`disabled` mientras la petición está en curso y vuelve a
    "Enviar reporte"/habilitado al terminar; se confirmó en
    `canigo_dev` que el incidente quedó realmente creado (con su foto en
    Cloudinary) y la notificación al dueño se generó - luego se
    eliminaron ambos documentos de prueba (y se vació `paseos.fotos` del
    paseo de prueba usado) para no dejar basura en la base de datos de
    desarrollo.
  - El formulario de subir foto del paseo (`fetch`, con
    `data-canigo-carga-manual`): mismo patrón - "Cargando…" durante el
    envío, restaurado al terminar, foto subida de verdad a Cloudinary
    para los 3 momentos (`inicio`/`mitad`/`fin`); un primer intento
    pareció quedarse "pegado" en "Cargando…" más de lo esperado — se
    confirmó con captura de errores globales
    (`window.onerror`/`unhandledrejection`) que no hubo ninguna excepción
    de JavaScript y que el backend sí respondió `200 OK`: fue una
    petición más lenta de lo esperado hacia Cloudinary (primera subida
    "fría" del proceso), no un error del código - repitiendo la prueba
    con más margen de espera, el botón se restauró correctamente.

- **Mejora 2 — «¿Olvidaste tu contraseña?» (versión provisional)**:
  diseño - la recuperación automática por correo necesita un servicio de
  envío que queda para después (fuera del alcance de este punto), así
  que se implementó una versión manual con dos partes:
  1. **Para cualquier usuario**: el link «¿Olvidaste tu contraseña?» del
     login (antes `href="#"`, placeholder muerto) ahora lleva a
     `usuarios:recuperar_contrasena` (`/cuentas/recuperar-contrasena/`),
     una pantalla pública (sin sesión, igual que `/privacidad/`) con el
     texto fijo pedido: escribir a srojas13@udi.edu.co desde el correo
     con el que se registró.
  2. **Para un admin** (`/administracion/contrasenas/`, protegida por
     `requiere_admin` igual que `/administracion/verificacion/` - 404
     para quien no sea admin): busca una cuenta por correo
     (`usuarios_repository.obtener_por_correo()`, que ya hace el
     lookup case-insensitive) y le asigna una contraseña temporal
     **generada por el servidor** (`secrets.choice()`, 12 caracteres,
     sin `0/O/1/l/I` para que no se confundan al copiarla de un correo o
     dictarla) - nunca una que el admin escriba a mano. Se hashea con
     `make_password()` (usa el hasher "default" actual,
     `core.hashers.PBKDF2HasherOWASP600k`, 600.000 iteraciones - mismo
     hasher que cualquier contraseña nueva del sitio). La contraseña en
     texto plano **nunca se guarda ni se registra en ningún log**: solo
     se muestra una vez, en la respuesta de esa misma petición (vía
     `messages.success`), y no reaparece si se recarga la página. La
     acción queda registrada en `usuarios.contrasena_temporal_historial`
     (`$push`, mismo patrón que `verificacion_historial` de RF14) con
     quién la asignó y cuándo - nunca la contraseña.

  **Forzar el cambio en el siguiente login**: `requiere_cambio_
  contrasena: True` se guarda en el usuario al asignar la temporal, se
  copia a la sesión en `_iniciar_sesion()` (mismo patrón que
  `autorizacion_datos_ok`) y
  `core.middleware.ExigirCambioContrasenaMiddleware` redirige a
  `/cuentas/cambiar-contrasena/` para CUALQUIER otra ruta mientras siga
  en `True` - calco exacto de `ExigirAutorizacionDatosMiddleware`
  (RNF1/Ley 1581). Al elegir la contraseña nueva,
  `usuarios_repository.completar_cambio_contrasena_forzado()` la
  hashea y apaga la bandera, sin esperar al próximo login.

  **Bug real encontrado probando el flujo de punta a punta**: una
  cuenta que necesitara las DOS pantallas intermedias a la vez
  (autorización de datos pendiente Y contraseña temporal pendiente -
  caso de borde, ya que una temporal solo se asigna a una cuenta que ya
  existía) entraba en un bucle infinito de redirects: el middleware de
  autorización la mandaba a `/cuentas/autorizacion-datos/`, pero el de
  contraseña no tenía esa ruta en su lista de permitidas y la rebotaba
  de inmediato hacia `/cuentas/cambiar-contrasena/`, que el primer
  middleware volvía a rebotar hacia `/cuentas/autorizacion-datos/` -
  Chrome terminaba mostrando "Esta página no funciona"
  (`ERR_TOO_MANY_REDIRECTS`). Fix: se agregó
  `usuarios:autorizar_datos` a las rutas permitidas de
  `ExigirCambioContrasenaMiddleware`, para que esa pantalla termine de
  mostrarse primero sin que el segundo middleware interfiera - solo
  DESPUÉS de aceptarla (`autorizacion_datos_ok=True`), el primer
  middleware deja de interceptar y el segundo puede llevar al cambio de
  contraseña.

  **Verificado ejecutando** (contra `canigo_dev`, con una cuenta de
  prueba real que tenía las dos pantallas pendientes a la vez, para
  probar el caso que encontró el bug):
  - El link del login lleva a la página pública correcta, con el texto
    exacto pedido.
  - Un admin asigna una contraseña temporal por correo: el mensaje de
    éxito la muestra una sola vez y desaparece al recargar la página;
    `usuarios.contrasena_temporal_historial` queda con `asignado_por`/
    `fecha`, sin la contraseña.
  - Login con la contraseña temporal: redirige primero a
    autorización de datos (sin bucle, tras el fix) y, al aceptarla, a
    `/cuentas/cambiar-contrasena/`; cualquier otra ruta (se probó el
    dashboard directamente) redirige de vuelta ahí mientras no se
    cambie.
  - Tras cambiar la contraseña: `requiere_cambio_contrasena` queda en
    `False` en Mongo, el hash nuevo usa el hasher de 600.000
    iteraciones, y un login posterior con la contraseña NUEVA entra
    directo al dashboard (sin volver a pedir el cambio); la contraseña
    TEMPORAL ya no funciona para iniciar sesión.
  - Un admin busca un correo que no existe: mensaje de error claro, sin
    revelar si la cuenta existe con otro dato.
  - Una sesión sin `correo` en `CANIGO_ADMIN_EMAILS` que intenta entrar
    a `/administracion/contrasenas/` directamente: `404` (mismo
    criterio que el resto del panel de administración, no confirma que
    la ruta existe).

**Ajustes del 19 de octubre, punto 1 — distancia recorrida del paseo**:
diagnóstico - el cálculo YA existía (`coordenadas/repository.py::
distancia_recorrida_km()`, Haversine sobre todos los puntos de
`coordenadas_detalle` en orden de `fecha_captura`), pero con tres
problemas: (1) no filtraba por `precision` en absoluto - un punto con
mala señal contaba igual que uno bueno; (2) no estaba formateado según
el criterio pedido (devolvía un float en km sin redondear a un patrón
fijo); (3) solo se mostraba en **un solo lugar**, `historial_paseador.
html` (historial del paseador) - nunca en el mapa en vivo, ni en el
panel del paseador durante el paseo, ni en el historial del dueño.

Fix:
- `coordenadas/repository.py::distancia_recorrida_m()` (reemplaza a
  `distancia_recorrida_km()`) ahora filtra los puntos con
  `UMBRAL_PRECISION_METROS = 50` (mismo criterio que
  `UMBRAL_PRECISION_DIBUJO` del JS de `mapa.html` - no se puede
  compartir una constante literal entre Python y JS, pero es el MISMO
  valor a propósito) antes de sumar los tramos; un punto sin
  `precision` (`None`) se acepta igual (no se asume "malo" por falta de
  dato). Trabaja en METROS, no km.
- `formatear_distancia(metros)`: única función que arma el texto ("850
  m" bajo 1000m, "1,2 km" con coma decimal desde ahí) - ya es un STRING
  armado en el servidor, nunca un número crudo en JSON (no aplica el
  cuidado de INC-05 aquí porque no hay ningún número yendo a un
  `<script>`/JSON para que JS lo interprete).
- Se guarda en `paseos.distancia_m` al finalizar el paseo
  (`paseos.repository.guardar_distancia()`, llamado desde
  `finalizar_paseo()`) - el historial de un paseo YA finalizado no
  recalcula; un paseo histórico de ANTES de este punto (sin el campo)
  se calcula en vivo (`paseos/views_web.py::_distancia_texto_de_paseo()`,
  compartida por `historial()` del dueño e `historial_paseador()`).
- Se muestra en 3 lugares: el mapa en vivo (`coordenadas_de_paseo()`,
  mismo sondeo de 8s, sin petición nueva), el panel del paseador durante
  el paseo (reusa el mismo POST de GPS de `base.html`, también cada
  8s), y el historial de ambos roles (`historial.html`/
  `historial_paseador.html`).
- `distancia_recorrida_m()` acepta `desde`/`hasta` (datetime,
  opcionales, sin usar todavía por ningún llamador real) - preparación
  explícita para la Fase 3 (RF de "recogida por dueño"), donde cada
  dueño necesitará la distancia de solo su propio tramo.

**Filtro de "jitter" — NO implementado, con los datos que lo explican**:
la tarea pedía evaluar un filtro que ignorara un tramo más corto que la
suma de las precisiones de sus dos puntos, antes de implementarlo.
`canigo_dev` no tenía ningún paseo con movimiento real (todos sus
paseos de prueba usan una sola coordenada GPS fija, de pruebas CDP
anteriores) - se probó en su lugar, en **solo lectura**, contra un
paseo REAL de producción (`canigo`, 32 minutos, 79 puntos, el mismo
conservado en la limpieza de cuentas de prueba del 9 de octubre). El
resultado: **928.4 m sin ningún filtro de jitter**, contra **145.6 m
con el filtro propuesto** (77 de 78 tramos quedaban "ignorados"). La
precisión típica del GPS real de un celular en ese paseo era de 15 a
40m - muy por encima de los ~11m que camina una persona en 8s a paso
normal, así que el umbral "tramo < suma de precisiones" descarta casi
TODO el recorrido real, no solo el ruido: el filtro tal como estaba
planteado sería contraproducente (subcuenta la distancia real en más
del 80%). **Decisión: no se implementó.** Si en el futuro se quiere un
filtro de jitter, necesitaría un diseño distinto (por ejemplo, un
mínimo fijo de unos pocos metros por tramo, no basado en sumar
precisiones típicas de 15-40m).

**Verificado ejecutando** (`canigo_dev`, paseo de prueba desechable con
4 puntos GPS reales variando ~100m entre sí, uno de ellos con
`precision` > 50m a propósito): `distancia_recorrida_m()` excluye
correctamente el punto de mala precisión (confirmado con un caso de
prueba aislado: 2 puntos con `precision=None` SÍ se miden, sin
excluirse); `formatear_distancia()` confirmado en los bordes exactos
(850→"850 m", 999→"999 m", 1000→"1,0 km", 1200→"1,2 km", None→None);
el mapa en vivo (`/coordenadas/paseos/<id>/mapa/`) y su polling
(`/datos/`) muestran "300 m" consistentemente; el panel del paseador
(`/cuentas/paseador/bienvenida/`) lo muestra igual, y
`registrar_coordenada()` lo actualiza a "400 m" tras un punto GPS
nuevo; al finalizar el paseo, `distancia_m: 400` queda guardado en
Mongo y el historial del paseador lo muestra sin recalcular; un paseo
histórico SIN el campo (simulado) lo calcula en vivo correctamente, y
uno que YA tiene `distancia_m: None` guardado NO lo recalcula (se
respeta el valor ya guardado, aunque sea `None`).

**Corrección del 20 de octubre — distancia poco visible**: tras
desplegar el punto 1, un paseo real de producción (`@gmail.com`
paseador, 45 puntos, ~9 horas "en_vivo" antes de finalizarse) confirmó
que el cálculo y el guardado funcionan bien - el reporte inicial de "no
aparece la distancia" resultó ser de tiempo (se revisó mientras el
paseo seguía en curso; el panel del paseador solo muestra la distancia
DURANTE el paseo, no en el historial, y el historial no lista paseos
que siguen `en_vivo`). Una vez revisado con el paseo ya finalizado, la
autora pidió que la distancia se distinga mejor de la duración (antes
las dos usaban `text-muted small`, se veían igual de apagadas, y la
distancia quedaba "perdida" debajo). Fix: `id="distancia-paseo"` ahora
usa `fw-bold` (sin `text-muted`/`small`) en `mapa.html`
(`coordenadas/templates/coordenadas/mapa.html`) y `fw-bold text-dark`
en el panel del paseador (`bienvenida_paseador.html`) - el historial
(`historial.html`/`historial_paseador.html`) no se tocó, es un resumen
compacto de una sola línea donde el mismo problema no aplicaba.
**Verificado ejecutando** (`canigo_dev`, capturas móviles): "596 m" en
negrita, claramente diferenciado de "15 min transcurridos" en el mapa y
de "Distancia recorrida:" en el panel del paseador.

**Tercera corrección del 20 de octubre — etiqueta en el mapa**: el
panel del paseador ya decía "Distancia recorrida: X" (con etiqueta); el
mapa de seguimiento (`mapa.html`) mostraba el número SOLO, sin ninguna
etiqueta - pedido explícito de la autora para que no quede ambiguo qué
representa. Fix: mismo texto "Distancia recorrida: " delante del
`<span id="distancia-paseo">` (el `id` se movió al `<span>` del valor,
no al contenedor, porque el polling de 8s solo debe reemplazar el
número, nunca la etiqueta). **Verificado ejecutando** (`canigo_dev`,
captura móvil): "Distancia recorrida: 596 m" en el mapa, mismo texto
que ya usaba el panel del paseador.

**Ajustes del 19 de octubre, puntos 2 y 3 — fotos/documentos sin la
opción de grabar video, y cámara + galería donde falte**: diagnóstico -
inventario completo de los 7 campos de archivo del proyecto:

| Campo | Pantalla | `accept` antes | `capture` antes |
|---|---|---|---|
| `foto_perfil` | Editar perfil del paseador | `image/*` | (ninguno) |
| `foto` (mascota) | Registrar/editar mascota | `image/*` | (ninguno) |
| `certificado_salud` | Registrar/editar mascota | **(ninguno - cualquier archivo)** | (ninguno) |
| `carne_vacunacion` | Registrar/editar mascota | **(ninguno - cualquier archivo)** | (ninguno) |
| `archivo` (certificado paseador) | Mis certificados | **(ninguno - cualquier archivo)** | (ninguno) |
| `foto` (evidencia incidente) | Reportar emergencia (modal) | `image/*` | (ninguno) |
| `foto` (paseo inicio/mitad/fin) | Subir foto del paseo (modal) | `image/*` (escrito a mano en el HTML del modal, NO via el widget de `SubirFotoPaseoForm` - ese formulario nunca se renderiza con `{{ form.foto }}`, es un hallazgo aparte, sin impacto porque el HTML a mano ya tenía el valor correcto) | (ninguno) |

**Por qué aparece la opción de video en iPhone**: Safari ofrece "Tomar
foto o video" cuando el `accept` del `<input>` admite algo más que
imágenes puras (o no restringe nada) - los 3 campos de certificados
(salud, vacunación, del paseador) no tenían NINGÚN `accept` (aceptaban
cualquier archivo, para poder subir también un PDF), así que activaban
esa opción. Los 4 campos que ya eran `accept="image/*"` (desde Mejora
1, 14 de octubre) no deberían ofrecerla - no se pudo confirmar en un
iPhone físico (no se dispone de uno), queda pendiente que la autora lo
confirme en su propio dispositivo.

Fix:
- Los 4 campos solo-foto se dejan **sin cambios** (`accept="image/*"`,
  sin `capture` - ya cumplían lo pedido desde Mejora 1).
- Los 3 campos de documento (imagen o PDF) ahora usan
  `core.widgets.CamaraOArchivoWidget` (nuevo, extiende
  `ClearableFileInput` - mantiene intacto el "Currently: X / Clear" de
  Django para un archivo ya subido, solo cambia la parte final): un
  único `<input type="file">` real **oculto**, con DOS botones que le
  cambian `accept`/`capture` antes de abrirlo:
  - "Tomar foto": `accept="image/*"` + `capture="environment"` (cámara,
    sin video ni galería);
  - "Elegir archivo": vuelve a `accept="image/*,application/pdf"` sin
    `capture` (selector nativo normal, imagen o PDF).
  Una sola función JS delegada en `base.html`
  (`data-canigo-modo-captura`/`data-canigo-camara-o-archivo`), reusada
  por los 3 campos - no un script por campo. El mismo backend
  (`core/media.py::subir_certificado`) sigue validando formato/tamaño/
  contenido exactamente igual que antes - el widget es puramente de
  interfaz, no cambia qué se acepta en el servidor.

**Tabla final** (campo | pantalla | `accept`/`capture` antes | `accept`/
`capture` después | qué ofrece en iPhone/Android):

| Campo | Pantalla | Antes | Después | iPhone | Android |
|---|---|---|---|---|---|
| `foto_perfil` | Editar perfil paseador | `image/*` / — | sin cambios | Cámara o galería, sin video | Cámara o galería |
| `foto` (mascota) | Registrar/editar mascota | `image/*` / — | sin cambios | Cámara o galería, sin video | Cámara o galería |
| `certificado_salud` | Registrar/editar mascota | — / — | dos botones: `image/*`+`environment` / `image/*,application/pdf` | "Tomar foto" sin video; "Elegir archivo" abre Fotos/Archivos (puede incluir PDF) | Cámara (solo foto) o selector de archivos |
| `carne_vacunacion` | Registrar/editar mascota | — / — | ídem anterior | ídem anterior | ídem anterior |
| `archivo` (certificado paseador) | Mis certificados | — / — | ídem anterior | ídem anterior | ídem anterior |
| `foto` (evidencia incidente) | Reportar emergencia | `image/*` / — | sin cambios | Cámara o galería, sin video | Cámara o galería |
| `foto` (paseo) | Subir foto del paseo | `image/*` / — (hardcoded en el HTML) | sin cambios | Cámara o galería, sin video | Cámara o galería |

**Backend - video rechazado por contenido real, no por extensión**:
confirmado con una prueba real (no solo lectura de código) - un archivo
con la firma real de un `.mp4` (`ftypmp42...`), renombrado a `.jpg`, se
mandó a `core.media.subir_certificado()` y fue **rechazado**
("El contenido del archivo no coincide con su extensión..."), porque
`_FIRMAS_POR_TIPO` solo reconoce `jpg`/`png`/`pdf` por sus primeros
bytes - cualquier otra firma (incluida la de un video) no coincide con
NINGUNA extensión permitida. `subir_imagen()` (campos solo-foto) tiene
la misma protección de forma independiente (rechaza cualquier
contenido que no sea `jpg`/`png`, sin importar qué diga la extensión).

**HEIC - reportado, no modificado**: `_FIRMAS_POR_TIPO`/
`_EXTENSIONES_POR_TIPO` NO incluyen HEIC - un archivo HEIC real sería
rechazado por ambas funciones (`subir_imagen()`: firma no es jpg/png;
`subir_certificado()`: `.heic` no está en las extensiones permitidas).
En la práctica, Safari en iOS suele convertir la foto a JPEG antes de
subirla desde un `<input type="file">` (comportamiento estándar de
WebKit desde iOS 11), así que esto normalmente no debería pasar - pero
no se pudo confirmar sin un iPhone real, y existe al menos un caso
conocido donde SÍ podría llegar HEIC real: si el usuario tiene
"Mantener original" activado en Ajustes > Cámara > Formatos Y elige una
foto YA existente de la galería (en vez de tomarla en el momento) vía
"Elegir archivo". Se reporta esta incertidumbre tal cual pide la tarea,
sin tocar la validación de contenido para no aceptar de más sin
confirmar primero que hace falta.

**Verificado ejecutando** (`canigo_dev`, navegador headless): el
widget renderiza correctamente en `/mascotas/nueva/`, `/mascotas/<id>/
editar/` (confirmado que no rompe nada - esos dos campos NUNCA pasaban
`initial=` con un valor con `.url`, así que el bloque "Currently/Clear"
de `ClearableFileInput` no se usaba ahí ni antes ni después de este
cambio) y `/cuentas/paseador/certificados/`; clic en "Tomar foto" deja
el `<input>` oculto con `accept="image/*"` y `capture="environment"`;
clic en "Elegir archivo" lo vuelve a `accept="image/*,application/pdf"`
sin `capture`; al asignarle un archivo real (vía CDP
`DOM.setFileInputFiles`), el nombre se muestra correctamente junto a
los botones. Prueba de contenido real: un `.mp4` renombrado a `.jpg`
rechazado por `subir_certificado()`.

**Solo leído en código** (sin dispositivo real para confirmarlo):
que `accept="image/*"` efectivamente no ofrezca la opción de video en
Safari de iPhone, y el comportamiento exacto de HEIC al tomar/elegir
una foto.

**Ajustes del 19 de octubre, punto 4 — botones bloqueados mientras se
procesa una petición**: diagnóstico - inventario completo de toda
acción que manda una petición:

| Acción | Tipo | ¿Ya bloqueaba? |
|---|---|---|
| Login, registro, autorización de datos, cambiar contraseña | form POST | Sí (listener genérico, Mejora 1) |
| Registrar/editar mascota, editar perfil del paseador | form POST | Sí |
| Publicar horario, despublicar, inscribir | form POST | Sí |
| Iniciar paseo, finalizar paseo | form POST | Sí |
| Fotos del paseo, emergencia | `fetch` | Sí (manual, Mejora 1) |
| Calificar | form POST | Sí |
| Marcar notificaciones como leídas | — | No es una acción con botón: se marca sola, como efecto de visitar `/notificaciones/` (`notificaciones/views.py`) - nada que bloquear |
| Activar notificaciones | `fetch` | **No** (gap real, corregido aquí) |
| Verificar paseador (marcar/retirar), asignar contraseña temporal | form POST | Sí |
| Quitar filtros | enlace `<a>`, no un formulario | No aplica (solo navega, no envía nada) |
| Filtro de "Paseadores disponibles" | form **GET** | Bloqueado por error - el listener genérico no distinguía GET de POST (gap real, corregido aquí) |

Fix:
- El listener genérico de `base.html` ahora ignora cualquier
  `<form method="get">` (se confirmó que SÍ bloqueaba el filtro de
  zonas antes de este punto - no estaba en el alcance original de
  Mejora 1, que solo pensó en formularios que suben archivos).
- Nuevo manejador `window.addEventListener('pageshow', ...)`: si
  `event.persisted` (la página se restauró desde la caché de "Atrás"),
  reactiva cualquier botón que haya quedado en estado "Cargando…" -
  antes no existía ningún manejo de este caso.
- El botón "Activar notificaciones en este dispositivo”
  (`notificaciones/_activar_push.html`) no tenía ningún bloqueo (es un
  `fetch`, el listener genérico de formularios no lo alcanza) - ahora
  usa las mismas `canigoMarcarCargando()`/`canigoQuitarCargando()` que
  el resto del sitio.

**Respaldo en el backend - qué ya estaba cubierto y qué se agregó**:

| Acción crítica | ¿Ya estaba cubierta? |
|---|---|
| Iniciar/finalizar (control de estado) | Sí - `find_one_and_update` con `estado` como parte del filtro atómico; un segundo POST no encuentra el documento y no hace nada (`paseos/repository.py::iniciar_paseo()`/`finalizar_paseo()`) |
| Inscribir dos veces la misma mascota | Sí - `$addToSet` (no `$push`) en `id_mascotas`/`id_duenos`, ya documentado en el propio código (`paseos/repository.py::inscribir_mascotas()`) |
| Calificar | Sí - índice único compuesto `(id_paseo, id_dueno)` |
| Emergencia | Sí - `incidentes.repository.obtener_duplicado_reciente()`, descarta un incidente idéntico creado hace menos de 10s (`_SEGUNDOS_DUPLICADO_INCIDENTE`) |
| **Publicar dos veces el mismo horario** | **No estaba cubierta - se agregó.** `paseos/repository.py::crear_disponibilidad()` no tenía ninguna protección: un doble POST creaba dos documentos `'disponible'` idénticos. Se agregó el mismo patrón que `obtener_duplicado_reciente()` (`_SEGUNDOS_DUPLICADO_HORARIO = 10`): si el mismo paseador ya publicó un horario con el mismo `horario_desde`/`horario_hasta` hace menos de 10s, se devuelve ESE documento en vez de crear uno nuevo. No compara `zonas` (publicar el mismo horario con otras zonas tan rápido no tiene un caso de uso real) |

**Verificado ejecutando** (`canigo_dev`): el formulario GET de filtro de
zonas ya NO deshabilita su botón tras un submit (antes sí lo hacía);
simulando `pageshow` con `persisted: true` sobre un botón ya
deshabilitado, se reactiva y recupera su texto original; `crear_
disponibilidad()` llamado dos veces con el mismo horario devuelve el
MISMO documento (`_id` igual, un solo documento en Mongo), y llamado con
horarios genuinamente distintos sigue creando documentos separados (sin
sobre-bloquear).

**Solo leído en código**: que los formularios POST ya listados
("inicio de sesión", "registrar mascota", etc.) de verdad no tenían
`data-canigo-carga-manual` (confirmado por inspección, no se probó
cada uno manualmente en el navegador).

## 8. Convenciones del proyecto

- **"Best effort" para una integración externa opcional, cuando ya hay
  un resultado principal que no depende de ella**: `core/geocoding.py`
  (dirección aproximada de un incidente) y `notificaciones/
  repository.py::_enviar_push()` (Web Push) siguen el mismo patrón -
  intentan la llamada externa (Nominatim, el servicio de push), nunca
  lanzan si falla, y el dato/acción PRINCIPAL (el incidente, la
  notificación interna) ya quedó guardado de todas formas. Si se agrega
  una integración externa nueva en esta misma situación (el resultado
  principal no depende de ella), seguir este mismo criterio - nunca
  dejar que un servicio de terceros caído rompa una operación que de
  otra forma habría funcionado.
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
  cualquier sondeo nuevo. **Excepción deliberada: el emisor de GPS** (ver
  más abajo) nunca se pausa por pestaña oculta - a diferencia de un
  sondeo de notificaciones, el GPS es la razón de ser de RNF2 (actualizar
  la ubicación cada ≤10s MIENTRAS el paseo está en curso); un paseador
  con la pantalla bloqueada en el bolsillo sigue caminando, y es
  justamente cuando más importa no perder la traza. Si el navegador
  suspende el `setInterval` de todas formas por estar en segundo plano,
  es una limitación de la plataforma, no algo que el código deba
  reforzar a propósito.
- **Emisor de GPS global, no atado a una pantalla** (Incremento 4, punto
  D1 — corrige INC-04, ver sección 7): el envío periódico de coordenadas
  vive en `core/templates/base.html`, no en `bienvenida_paseador.html`.
  Se habilita con `core.context_processors.id_paseo_en_vivo_del_paseador`
  (nuevo context processor, registrado en `settings.py`): disponibiliza
  `id_paseo_en_vivo_del_paseador` en CUALQUIER render, con una sola
  consulta extra por página (filtrada por `id_paseador`+`estado`, mismo
  índice compuesto que ya existía) — `{}` para cualquier caso que no sea
  un paseador autenticado con un paseo `en_vivo` ahora mismo (la inmensa
  mayoría de las páginas vistas), así que el costo real es insignificante.
  El poller genérico de notificaciones de `base.html`
  (`polling_notificaciones`) se auto-suprime cuando ese valor está
  presente (`and not id_paseo_en_vivo_del_paseador`), porque el propio
  POST de GPS ya devuelve `hay_notificaciones_sin_leer` en cada vuelta -
  sumar los dos sería una petición redundante. Si una pantalla necesita
  seguir usando su PROPIO polling en vez del genérico (p.ej. el mapa
  mientras está `en_vivo`), sigue sobreescribiendo
  `{% block polling_notificaciones %}` como ya hacía.
- **Formularios que no deben interrumpir un paseo en vivo, por `fetch` +
  `FormData`** (Incremento 4, punto D1): los modales de "Reportar
  emergencia" y "Subir foto" en `bienvenida_paseador.html` eran POST
  normales con recarga de página - una recarga reinicia cualquier script
  en memoria, incluido el emisor de GPS global de arriba. Se convirtieron
  a `fetch(form.action, {method: 'POST', headers: {'X-CSRFToken': ...},
  body: new FormData(form)})`, con el token CSRF leído de la cookie
  `csrftoken` y mandado en un header (no en el body, que aquí es
  binario). Las vistas detrás (`incidentes.views_web.reportar_incidente`,
  `paseos.views_web.subir_foto`) responden SIEMPRE `JsonResponse` en vez
  de `redirect()` + `django.contrib.messages` — son los ÚNICOS llamadores
  reales de esas vistas, así que no hace falta mantener una rama para un
  POST tradicional sin JS. La confirmación de éxito se inserta en el DOM
  sin recargar (`#avisos-paseo` en la plantilla); un error se muestra
  dentro del propio modal. Si se agrega un formulario nuevo que el
  paseador pueda abrir durante un paseo `en_vivo`, seguir este mismo
  patrón — un POST con recarga ahí rompe el envío de GPS.
  **Robustez (revisión de fase 1, punto 3, 2026-10-12)**: el botón
  `submit` se deshabilita de forma SÍNCRONA al entrar al listener (con
  un guard `if (boton.disabled) return;` antes de deshabilitarlo de
  nuevo) y se re-habilita en un único `.finally()` — así queda
  protegido sin importar si termina en éxito, error de validación o
  error de red, y un segundo toque mientras el primero sigue en vuelo
  no dispara un segundo `fetch`. Como defensa de fondo en el backend
  (por si de todas formas llegan dos POST, p.ej. con red muy lenta o
  dos pestañas), `incidentes.repository.obtener_duplicado_reciente()`
  evita crear dos incidentes IDÉNTICOS (mismo paseo, tipo, mascota y
  descripción) en menos de 10s — el segundo responde como si hubiera
  tenido éxito, en vez de un error confuso o un documento duplicado.
  `core/media.py::subir_imagen()` ahora también valida tamaño (máx.
  5MB) y que el CONTENIDO real sea una imagen JPG o PNG (nueva excepción
  `ErrorValidacionImagen` para distinguir "archivo inválido" de "falló
  Cloudinary" y responder 400 en vez de 502) - antes solo dependía de
  `forms.ImageField` (Pillow), que valida que el contenido sea una
  imagen cargable pero NO limita el tamaño.
  **Corrección de la revisión de fase 2, punto (b)**: la primera versión
  de este cambio además comparaba el contenido CONTRA la extensión
  declarada y rechazaba cualquier diferencia - eso rechazaba de más: un
  PNG real guardado como `.jpg` es un archivo perfectamente válido (lo
  abre cualquier visor, Cloudinary lo sirve bien), no había motivo real
  para rechazarlo. Ahora la decisión es SOLO por la firma real del
  archivo (sus primeros bytes) - se acepta si el contenido es JPG o PNG,
  sin importar la extensión del nombre; se sigue rechazando cualquier
  contenido que NO sea ninguno de los dos (p.ej. un `.txt` renombrado a
  `.jpg`) y cualquier archivo de más de 5MB. `_tipo_por_extension()`
  sigue existiendo y se sigue usando en `subir_certificado()` (que sí
  necesita saber si es PDF vs imagen para pasarle el `resource_type`
  correcto a Cloudinary) - el cambio es solo en `subir_imagen()`.
- **Privacidad en paseos con varios dueños**: cualquier pantalla que le
  muestre a un dueño específico "las mascotas de este paseo" debe filtrar a
  las de ESE dueño (`mascotas.repository.obtener_varias_por_id_y_dueno`),
  nunca la lista completa del paseo — un paseo compartido puede tener
  mascotas de otros dueños. **Mismo criterio para incidentes** (corrección
  del 12 oct, privacidad crítica — ver sección 7): un incidente con
  `id_mascota` concreto solo es visible/notificable al dueño de ESA
  mascota, nunca a los demás `id_duenos` del mismo paseo — ni la
  notificación (`incidentes.views_web.reportar_incidente`), ni el
  historial (`incidentes.repository.listar_visibles_para_dueno()`, que
  reemplaza a `listar_por_paseos()` del lado del dueño — esa función
  vieja sigue existiendo, pero solo para el paseador, que SÍ ve todos los
  incidentes de sus propios paseos sin filtrar), ni el banner de
  emergencia del mapa compartido (`coordenadas.views_web._texto_incidente()`,
  que ahora recibe `ids_mascota_viewer` — `None` sin restricción para el
  paseador, la lista de sus propias mascotas para un dueño). El filtro
  siempre va en el backend (repository o vista), nunca solo ocultando un
  link en la plantilla — ver el hallazgo de privacidad del 12 oct como
  el ejemplo de por qué: ocultar el link no evita notificar por error, ni
  evita que alguien entre por la URL directa.
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
  a `_iniciar_sesion()` y mandar directo al dashboard. El correo
  prellenado viaja en `request.session['correo_prellenado']`, **no en
  la URL** (`login?correo=...` quedaba en el historial del navegador en
  texto plano - corregido después de la primera versión de este mismo
  punto) - `login()` lo lee con `session.pop()` (lo borra apenas lo
  lee, no sobrevive ni una recarga de la misma página) y lo usa como
  `initial` de `LoginForm` en el GET - nunca pisa lo que alguien ya
  haya escrito en un POST fallido, porque `initial` solo aplica a un
  form sin binding. No se encontró una causa
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
- **`core/middleware.py::NoCacheParaAutenticadosMiddleware`** (agregado el
  12 oct): marca `Cache-Control: no-store` en cualquier respuesta servida
  con sesión activa — sin esto, el botón "Atrás" del navegador después de
  cerrar sesión podía mostrar una copia cacheada de una pantalla con datos
  de la cuenta, sin siquiera volver a pedírsela al servidor. Excluye
  explícitamente las rutas bajo `STATIC_URL` (el CSS de WhiteNoise ya tiene
  su propio cache-busting por hash en el nombre del archivo — no hace
  falta, y rompería ese cache para cualquiera que esté logueado). Va al
  final de `MIDDLEWARE` en `settings.py`, después de los demás.

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
  separados por coma - ver sección 8, RF14), `NOMINATIM_USER_AGENT`
  (identifica la app ante Nominatim con un contacto real - ver sección 7,
  punto C del Incremento 4; sin configurar, cae a un valor genérico sin
  contacto, que cumple la forma pero no lo que la política de Nominatim
  en realidad pide).
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
