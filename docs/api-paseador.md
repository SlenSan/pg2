# API del paseador — referencia para la app Android

Esta es la API REST (JSON) que expone el backend Django de Canigo para la
app Android nativa del paseador. El dueño de mascota **no** usa esta API:
tiene su propia plataforma web (Django Templates). Todo lo que aparece
aquí es lo que la app Android debe consumir.

## Convenciones generales

- **Base URL (desarrollo local):** `http://127.0.0.1:8000`
- **Base URL (producción):** _pendiente de completar tras el despliegue en Render_
- **Content-Type:** `application/json` en la mayoría de endpoints. Los dos
  que suben una foto (`incidentes`) usan `multipart/form-data`.
- **Fechas:** siempre ISO 8601 con offset UTC, ej. `"2026-09-13T02:19:37.583884+00:00"`.
- **IDs:** todos los `_id` de Mongo se exponen como string hexadecimal de 24
  caracteres (ej. `"6aa4d261d35a7a8b6452631f"`), nunca como `ObjectId`.
- **Errores:** siempre `{"error": "mensaje en español"}` con un status HTTP
  apropiado (400, 401, 403, 409, etc.). No hay un formato de error distinto
  por endpoint.

## Autenticación

Todos los endpoints excepto **registro** y **login** requieren un token en
el header:

```
Authorization: Bearer <token>
```

El token se obtiene en la respuesta de `/registro/` o `/login/`. Es un
token firmado (no una sesión ni un JWT estándar), válido por **30 días**
desde que se emite. No hay endpoint de refresh: cuando expira, el usuario
debe volver a hacer login. Guárdalo en `cache_perfil_usuario.token_sesion`
(almacenamiento local de la app) y mándalo en cada request autenticado.

Si el token falta, es inválido o expiró:

```json
{ "error": "Token inválido o expirado." }
```
`401 Unauthorized`

Si el token es válido pero pertenece a una cuenta que no es de paseador
(no debería pasar si solo usas los endpoints de esta API, pero por si acaso):

```json
{ "error": "Esta acción es solo para paseadores." }
```
`403 Forbidden`

## Índice de endpoints

| # | Método | URL | Auth | Descripción |
|---|--------|-----|------|-------------|
| 1 | POST | `/api/paseador/registro/` | No | Crear cuenta de paseador |
| 2 | POST | `/api/paseador/login/` | No | Iniciar sesión |
| 3 | GET | `/api/paseador/perfil/` | Sí | Ver mi propio perfil |
| 4 | POST | `/api/paseador/paseos/disponibilidad/` | Sí | Publicar disponibilidad |
| 5 | GET | `/api/paseador/paseos/actual/` | Sí | Ver mi paseo activo |
| 6 | POST | `/api/paseador/paseos/<id_paseo>/iniciar/` | Sí | Iniciar el paseo |
| 7 | POST | `/api/paseador/paseos/<id_paseo>/finalizar/` | Sí | Finalizar el paseo |
| 8 | POST | `/api/paseador/paseos/<id_paseo>/coordenadas/` | Sí | Enviar un punto GPS |
| 9 | POST | `/api/paseador/paseos/<id_paseo>/incidentes/` | Sí | Botón de emergencia |
| 10 | GET | `/api/paseador/incidentes/` | Sí | Mi historial de incidentes |

---

## 1. Registro — `POST /api/paseador/registro/`

Crea una cuenta nueva con `rol: "paseador"`.

**Body (JSON):**

| Campo | Tipo | Requerido | Notas |
|---|---|---|---|
| `nombre` | string | Sí | |
| `correo` | string | Sí | Debe ser único en todo el sistema |
| `contrasena` | string | Sí | Se guarda hasheada (PBKDF2), nunca en texto plano |
| `telefono` | string | Sí | |
| `direccion` | string | No | Por defecto `""` |
| `descripcion` | string | No | Se muestra al dueño en el listado de paseadores |

**Ejemplo de request:**
```json
POST /api/paseador/registro/
Content-Type: application/json

{
  "nombre": "Juan Pérez",
  "correo": "juan.perez@example.com",
  "contrasena": "clave12345",
  "telefono": "3001234567",
  "descripcion": "Amante de los perros, disponible fines de semana"
}
```

**Respuesta exitosa — `201 Created`:**
```json
{
  "usuario": {
    "nombre": "Juan Pérez",
    "correo": "juan.perez@example.com",
    "telefono": "3001234567",
    "rol": "paseador",
    "foto_perfil": "",
    "direccion": "",
    "fecha_registro": "2026-09-13T02:18:13.370746+00:00",
    "calificacion_promedio": null,
    "verificado": false,
    "descripcion": "Amante de los perros, disponible fines de semana",
    "_id": "6aa4d261d35a7a8b6452631f"
  },
  "token": "eyJpZF91c3VhcmlvIjoiNmFhNGQyNjFkMzVhN2E4YjY0NTI2MzFmIn0:1x5FBJ:CE-Alzo2Mm8sIGGWmD_WRj_M8K6-eH9OYnLohNPVyQE"
}
```

**Errores:**
- `400` — falta algún campo requerido: `{"error": "Campos requeridos faltantes: correo, telefono."}`
- `400` — body no es JSON válido: `{"error": "JSON inválido."}`
- `409` — el correo ya existe: `{"error": "Ya existe un usuario con ese correo."}`

---

## 2. Login — `POST /api/paseador/login/`

**Body (JSON):**

| Campo | Tipo | Requerido |
|---|---|---|
| `correo` | string | Sí |
| `contrasena` | string | Sí |

**Ejemplo de request:**
```json
POST /api/paseador/login/
Content-Type: application/json

{
  "correo": "juan.perez@example.com",
  "contrasena": "clave12345"
}
```

**Respuesta exitosa — `200 OK`:** mismo formato que el registro (`usuario` + `token`).

**Errores:**
- `400` — falta correo o contraseña: `{"error": "correo y contrasena son requeridos."}`
- `401` — credenciales incorrectas: `{"error": "Credenciales inválidas."}`
- `403` — la cuenta es de dueño, no de paseador: `{"error": "Esta cuenta no es de paseador. Usa la plataforma web de Canigo."}`

---

## 3. Mi perfil — `GET /api/paseador/perfil/`

Devuelve el perfil propio, incluyendo `calificacion_promedio` y
`verificado` actualizados.

**Headers:** `Authorization: Bearer <token>`

**Respuesta exitosa — `200 OK`:**
```json
{
  "usuario": {
    "_id": "6aa4d261d35a7a8b6452631f",
    "nombre": "Juan Pérez",
    "correo": "juan.perez@example.com",
    "telefono": "3001234567",
    "rol": "paseador",
    "foto_perfil": "",
    "direccion": "",
    "fecha_registro": "2026-09-13T02:18:13.370000",
    "calificacion_promedio": 4.5,
    "verificado": false,
    "descripcion": "Amante de los perros, disponible fines de semana"
  }
}
```

**Errores:** `401` (token inválido/expirado).

---

## 4. Publicar disponibilidad — `POST /api/paseador/paseos/disponibilidad/`

Crea un paseo en estado `"disponible"` (sin dueño ni mascota asignados
todavía). Es el paso 1 del ciclo de vida del paseo.

**Headers:** `Authorization: Bearer <token>`
**Body:** ninguno.

**Respuesta exitosa — `201 Created`:**
```json
{
  "paseo": {
    "id_paseador": "6aa4d261d35a7a8b6452631f",
    "id_mascota": null,
    "id_dueno": null,
    "estado": "disponible",
    "fecha": "2026-09-13T02:18:14.038909+00:00",
    "hora_inicio": null,
    "hora_fin": null,
    "total_puntos": 0,
    "emergencia": false,
    "fotos": [],
    "_id": "6aa4d262d35a7a8b64526320"
  }
}
```

**Errores:**
- `409` — ya tiene un paseo activo (no puede publicar dos veces sin cerrar el anterior):
```json
{
  "error": "Ya tienes un paseo activo (disponible o en curso).",
  "paseo": { "...": "el paseo activo existente, mismo formato de arriba" }
}
```

---

## 5. Mi paseo actual — `GET /api/paseador/paseos/actual/`

Útil para que la app sepa en qué estado está su paseo sin tener que
recordar el `id_paseo` localmente (por ejemplo, si un dueño ya inscribió
una mascota mientras la app estaba cerrada).

**Headers:** `Authorization: Bearer <token>`

**Respuesta — `200 OK`** (tiene un paseo activo, ya con mascota inscrita):
```json
{
  "paseo": {
    "_id": "6aa4d262d35a7a8b64526320",
    "id_paseador": "6aa4d261d35a7a8b6452631f",
    "id_mascota": "6aa4d277d35a7a8b64526324",
    "id_dueno": "6aa4d277d35a7a8b64526323",
    "estado": "disponible",
    "fecha": "2026-09-13T02:18:14.038000",
    "hora_inicio": null,
    "hora_fin": null,
    "total_puntos": 0,
    "emergencia": false,
    "fotos": []
  }
}
```

**Respuesta — `200 OK`** (no tiene ningún paseo activo):
```json
{ "paseo": null }
```

No tiene respuestas de error propias más allá de la autenticación (`401`).

---

## 6. Iniciar paseo — `POST /api/paseador/paseos/<id_paseo>/iniciar/`

Pasa el paseo de `"disponible"` a `"en_vivo"` y registra `hora_inicio`.
Solo funciona si **ya hay una mascota inscrita** (un dueño lo tomó desde
la web). A partir de aquí la app debe empezar a mandar coordenadas GPS
(endpoint 8) cada 10-30 segundos.

**Headers:** `Authorization: Bearer <token>`
**Body:** ninguno. `id_paseo` va en la URL.

**Ejemplo:** `POST /api/paseador/paseos/6aa4d262d35a7a8b64526320/iniciar/`

**Respuesta exitosa — `200 OK`:**
```json
{
  "paseo": {
    "_id": "6aa4d262d35a7a8b64526320",
    "id_paseador": "6aa4d261d35a7a8b6452631f",
    "id_mascota": "6aa4d277d35a7a8b64526324",
    "id_dueno": "6aa4d277d35a7a8b64526323",
    "estado": "en_vivo",
    "fecha": "2026-09-13T02:18:14.038000",
    "hora_inicio": "2026-09-13T02:19:19.546000",
    "hora_fin": null,
    "total_puntos": 0,
    "emergencia": false,
    "fotos": []
  }
}
```

Al iniciar, el backend automáticamente crea una notificación para el
dueño (visible en su plataforma web) — la app no tiene que hacer nada
más para eso.

**Errores:**
- `409` — el paseo no existe, no es tuyo, ya no está "disponible", o
  todavía no tiene mascota inscrita:
```json
{ "error": "No se pudo iniciar: el paseo no existe, no es tuyo, ya no está \"disponible\" o todavía no tiene una mascota inscrita." }
```

---

## 7. Finalizar paseo — `POST /api/paseador/paseos/<id_paseo>/finalizar/`

Pasa el paseo de `"en_vivo"` a `"historico"` y registra `hora_fin`. A
partir de aquí ya no se aceptan más coordenadas GPS ni incidentes para
este paseo.

**Headers:** `Authorization: Bearer <token>`
**Body:** ninguno.

**Respuesta exitosa — `200 OK`:** mismo formato que "iniciar", con
`"estado": "historico"` y `hora_fin` con la fecha/hora actual.

También crea automáticamente una notificación de fin de paseo para el
dueño.

**Errores:**
- `409`:
```json
{ "error": "No se pudo finalizar: el paseo no existe, no es tuyo o no está \"en_vivo\"." }
```

---

## 8. Enviar coordenada GPS — `POST /api/paseador/paseos/<id_paseo>/coordenadas/`

Se debe llamar **cada 10-30 segundos** mientras el paseo está `"en_vivo"`
(requisito RNF2: el dueño debe ver la ubicación actualizada cada ≤10s en
su mapa). Solo se acepta si el paseo pertenece al paseador autenticado y
está `"en_vivo"`.

**Headers:** `Authorization: Bearer <token>`
**Body (JSON):**

| Campo | Tipo | Requerido | Notas |
|---|---|---|---|
| `latitud` | number | Sí | Rango -90 a 90 |
| `longitud` | number | Sí | Rango -180 a 180 |
| `altitud` | number | No | En metros |
| `fecha_captura` | string (ISO 8601) | No | Momento real de la captura en el dispositivo. Si no se envía, el servidor usa la hora de recepción. |

**Ejemplo de request:**
```json
POST /api/paseador/paseos/6aa4d262d35a7a8b64526320/coordenadas/
Content-Type: application/json

{
  "latitud": 7.1193,
  "longitud": -73.1227,
  "altitud": 950,
  "fecha_captura": "2026-09-13T02:19:37.500Z"
}
```

**Respuesta exitosa — `201 Created`:**
```json
{
  "punto": {
    "latitud": 7.1193,
    "longitud": -73.1227,
    "altitud": 950.0,
    "fecha_captura": "2026-09-13T02:19:37.583884+00:00"
  },
  "total_puntos": 1
}
```
`total_puntos` es el contador acumulado de puntos GPS de todo el paseo
(útil para mostrar progreso en la UI de la app, no hace falta llevarlo
localmente).

**Errores:**
- `400` — falta latitud/longitud o no son numéricos:
  `{"error": "latitud y longitud son requeridos y deben ser numéricos."}`
- `400` — fuera de rango: `{"error": "latitud/longitud fuera de rango."}`
- `409` — el paseo no existe, no es tuyo, o no está "en_vivo":
  `{"error": "Este paseo no existe, no es tuyo, o no está \"en_vivo\"."}`

---

## 9. Botón de emergencia — `POST /api/paseador/paseos/<id_paseo>/incidentes/`

**Único endpoint de esta API que usa `multipart/form-data`** en vez de
JSON, porque siempre incluye una foto de evidencia. Solo se acepta sobre
un paseo propio que esté `"en_vivo"`.

**Headers:** `Authorization: Bearer <token>`
**Body (multipart/form-data):**

| Campo | Tipo | Requerido | Notas |
|---|---|---|---|
| `tipo` | string | Sí | Uno de: `fuga_animal`, `mordedura_agresion`, `accidente_animal`, `accidente_paseador`, `otro` |
| `descripcion` | string | Sí | No puede ir vacía |
| `latitud` | number | Sí | Rango -90 a 90 |
| `longitud` | number | Sí | Rango -180 a 180 |
| `foto` | archivo (imagen) | Sí | Se sube a Cloudinary; el backend devuelve la URL pública |

**Ejemplo de request (curl, para referencia de los campos):**
```
POST /api/paseador/paseos/6aa60b59ca15eb6b023963f5/incidentes/
Authorization: Bearer <token>
Content-Type: multipart/form-data

tipo=mordedura_agresion
descripcion=El perro mordió a otro paseante
latitud=7.1193
longitud=-73.1227
foto=<archivo binario>
```

**Respuesta exitosa — `201 Created`:**
```json
{
  "incidente": {
    "id_paseo": "6aa60b59ca15eb6b023963f5",
    "tipo": "mordedura_agresion",
    "descripcion": "El perro mordió a otro paseante",
    "evidencia_foto": "https://res.cloudinary.com/pycl1vev/image/upload/v1789266794/canigo/incidentes/yb9wbu6qwinleiugjoyl.jpg",
    "latitud": 7.1193,
    "longitud": -73.1227,
    "fecha_hora": "2026-09-13T02:33:16.104857+00:00",
    "notificado": true,
    "_id": "6aa60b6cca15eb6b023963f9"
  }
}
```

Al reportarse, el backend automáticamente:
- Marca `paseos.emergencia = true` en el paseo.
- Crea una notificación tipo `"emergencia"` para el dueño (por eso
  `notificado` llega en `true`).

**Errores:**
- `400` — `tipo` inválido: `{"error": "tipo debe ser uno de: fuga_animal, mordedura_agresion, accidente_animal, accidente_paseador, otro."}`
- `400` — sin descripción: `{"error": "descripcion es requerida."}`
- `400` — sin foto: `{"error": "foto (evidencia) es requerida."}`
- `400` — coordenadas inválidas o fuera de rango (mismos mensajes que el endpoint de coordenadas)
- `409` — paseo no existe/no es tuyo/no está "en_vivo": `{"error": "Este paseo no existe, no es tuyo, o no está \"en_vivo\"."}`
- `502` — falló la subida a Cloudinary (problema de red o credenciales del lado del servidor): `{"error": "No se pudo subir la imagen a Cloudinary: <detalle>"}`

---

## 10. Mi historial de incidentes — `GET /api/paseador/incidentes/`

Todos los incidentes que este paseador ha reportado, en cualquiera de
sus paseos, más recientes primero.

**Headers:** `Authorization: Bearer <token>`

**Respuesta exitosa — `200 OK`:**
```json
{
  "incidentes": [
    {
      "_id": "6aa60b6cca15eb6b023963f9",
      "id_paseo": "6aa60b59ca15eb6b023963f5",
      "tipo": "mordedura_agresion",
      "descripcion": "El perro mordió a otro paseante",
      "evidencia_foto": "https://res.cloudinary.com/pycl1vev/image/upload/v1789266794/canigo/incidentes/yb9wbu6qwinleiugjoyl.jpg",
      "latitud": 7.1193,
      "longitud": -73.1227,
      "fecha_hora": "2026-09-13T02:33:16.104000",
      "notificado": true
    }
  ]
}
```

Si no ha reportado ninguno: `{"incidentes": []}`.

---

## Flujo típico completo (para orientar la implementación de la app)

```
1. registro/ o login/           -> guardar token localmente
2. paseos/disponibilidad/       -> guardar id_paseo devuelto
3. (esperar a que un dueño inscriba una mascota — se puede sondear
    paseos/actual/ para saber cuándo id_mascota deja de ser null)
4. paseos/<id>/iniciar/         -> empezar a mandar coordenadas
5. cada 10-30s: paseos/<id>/coordenadas/
   (si ocurre una emergencia en cualquier momento: paseos/<id>/incidentes/)
6. paseos/<id>/finalizar/       -> dejar de mandar coordenadas
7. volver al paso 2 cuando quiera publicar disponibilidad de nuevo
```
