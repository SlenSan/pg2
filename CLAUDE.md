# Canigo — Plataforma de gestión de paseos caninos (Bucaramanga)

Proyecto de grado de Ingeniería de Sistemas (UDI). Este archivo resume las decisiones
técnicas YA TOMADAS en el documento de grado. No las cuestiones ni las cambies sin que
te lo pida explícitamente — impleméntalas tal como están descritas aquí.

## Arquitectura

> **Corrección de alcance (2026-09-16):** la versión original del documento de
> grado planteaba una app Android nativa para el paseador. Esa decisión CAMBIÓ
> y ya está corregida en el documento (arquitectura, diagramas, alcance): ya no
> existe app nativa. Dueño y paseador usan la misma plataforma web. La API REST
> con tokens Bearer que existía para esa app (bajo `/api/paseador/...`) ya se
> eliminó del código (2026-09-18) una vez confirmado que ninguna vista web la
> usaba — si ves algo que la referencia, es un resto viejo, no la decisión
> vigente.

Modelo cliente-servidor con un backend único (Python + Django) que sirve una
única plataforma web para los dos actores del sistema:

- **Dueño de mascota y Paseador → Plataforma Web (ambos)**: Django renderiza y
  sirve las páginas directamente (server-side rendering) usando **Django
  Templates + Bootstrap** (vía CDN, sin Node/bundlers). No hay frontend JS
  separado. JavaScript se usa solo puntualmente para el mapa de seguimiento en
  tiempo real (Leaflet.js). Login/logout son comunes a ambos roles; el
  registro usa un formulario distinto según el rol elegido en una pantalla de
  selección previa (`nombre`, `correo`, `contraseña`, `teléfono` para ambos,
  más `descripcion` para paseador).
- **Base de datos**: MongoDB Atlas (NoSQL, orientada a documentos). Se eligió
  NoSQL sobre relacional por la variabilidad de estructura de los datos y el
  volumen/frecuencia de las coordenadas GPS (un punto cada 10-30s durante un
  paseo activo).
- **Mapas**: Leaflet.js + OpenStreetMap (no Google Maps API, por costos).
- **Despliegue**: Render (backend), con MongoDB Atlas como base de datos externa.

No propongas cambiar Django Templates por React/Vue, ni MongoDB por SQL, ni Google
Maps por Leaflet — esas decisiones ya están tomadas y justificadas en el documento
de grado (por recomendación explícita del director, priorizando herramientas
sencillas con bajo consumo de tiempo).

## Actores del sistema

1. **Dueño de mascota**: registra mascotas, busca/selecciona paseador, monitorea
   el paseo en tiempo real, consulta incidentes, califica el servicio.
2. **Paseador**: publica disponibilidad, acepta solicitudes, inicia/finaliza
   paseos, registra evidencia fotográfica, activa botón de emergencia.

## Ciclo de vida del paseo (estado central del sistema)

Un documento en la colección `paseos` transita por exactamente estos 3 estados
(usa estos nombres literales, no sinónimos):

```
(sin documento) → "disponible" → "en_vivo" → "historico"
```

- **disponible**: el paseador publicó el horario; el documento se crea aquí.
- **en_vivo**: el paseador inició el recorrido; se habilita el envío periódico
  de puntos GPS hacia `coordenadas_detalle` (cada 10-30s).
- **historico**: el paseador finalizó el paseo; se registra `hora_fin`.

## Esquema de base de datos (MongoDB — 7 colecciones en servidor)

### `usuarios`
```
{
  _id: ObjectId,
  nombre: String,
  correo: String,              // único, usado para login
  contrasena: String,          // hash, nunca texto plano
  telefono: String,
  rol: String,                 // "dueño" | "paseador"
  foto_perfil: String,
  direccion: String,
  fecha_registro: Date,
  calificacion_promedio: Number,  // solo rol=paseador
  verificado: Boolean,             // solo rol=paseador
  descripcion: String              // solo rol=paseador
}
```

### `mascotas`
```
{
  _id: ObjectId,
  id_dueno: ObjectId,     // referencia a usuarios
  nombre: String,
  raza: String,
  edad: Number,
  peso: Number,
  foto: String,
  observaciones: String,  // alergias, comportamiento, etc.
  fecha_registro: Date
}
```

### `paseos` (colección central)
```
{
  _id: ObjectId,
  id_paseador: ObjectId,   // referencia a usuarios
  id_mascotas: [ObjectId], // referencia a mascotas - una o varias del mismo dueño, juntas en el mismo paseo
  id_dueno: ObjectId,      // referencia a usuarios
  estado: String,          // "disponible" | "en_vivo" | "historico"
  fecha: Date,
  horario_desde: Date,     // horario PROPUESTO por el paseador (solo mientras estado="disponible")
  horario_hasta: Date,     // idem - distintos de hora_inicio/hora_fin (el momento REAL)
  hora_inicio: Date,
  hora_fin: Date,
  total_puntos: Number,
  emergencia: Boolean,     // true si se activó el botón de emergencia
  fotos: [{ url: String, momento: String }]  // momento: "inicio"|"mitad"|"fin"
}
```

### `coordenadas_detalle`
```
{
  _id: ObjectId,
  id_paseo: ObjectId,      // referencia a paseos
  latitud: Number,
  longitud: Number,
  altitud: Number,
  fecha_captura: Date,     // capturado en el dispositivo
  fecha_recepcion: Date    // recibido por el servidor
}
```
Retención: ~90 días (trazabilidad y validación, no almacenamiento permanente ilimitado).

### `incidentes` (RF12 / RF16 — núcleo diferenciador del proyecto)
```
{
  _id: ObjectId,
  id_paseo: ObjectId,      // referencia a paseos
  id_mascota: ObjectId,    // referencia a mascotas - null solo para "accidente_paseador"
                            // (no involucra a ningun animal en particular); para los
                            // demas tipos, obligatorio si el paseo tiene mas de una mascota
  tipo: String,            // "fuga_animal" | "mordedura_agresion" |
                            // "accidente_animal" | "accidente_paseador" | "otro"
  descripcion: String,
  evidencia_foto: String,
  latitud: Number,
  longitud: Number,
  fecha_hora: Date,
  notificado: Boolean      // si el dueño ya fue notificado
}
```

### `calificaciones`
```
{
  _id: ObjectId,
  id_paseo: ObjectId,      // referencia a paseos
  id_dueno: ObjectId,      // referencia a usuarios
  id_paseador: ObjectId,   // referencia a usuarios
  puntuacion: Number,      // 1 a 5
  comentario: String,
  fecha: Date
}
```

### `notificaciones`
```
{
  _id: ObjectId,
  id_usuario: ObjectId,    // referencia a usuarios (destinatario)
  tipo: String,            // "inicio_paseo"|"fin_paseo"|"emergencia"|"calificacion"
  mensaje: String,
  fecha: Date
}
```

## Requisitos funcionales (resumen — ver documento completo para el detalle)

| Código | Categoría | Resumen |
|---|---|---|
| RF1-RF2 | Gestión de actores | Registro y login (correo + contraseña) |
| RF3-RF4 | Gestión de mascotas | Registrar y listar mascotas |
| RF5-RF6 | Gestión del servicio | Listar paseadores disponibles, ver perfil |
| RF7-RF8 | Monitoreo y geolocalización | Ver ubicación en mapa (cada 10s), trazar ruta |
| RF9-RF10 | Control del servicio | Registrar hora inicio/fin, cerrar paseo |
| RF11 | Notificaciones | Notificar inicio/fin de paseo |
| RF12 | Seguridad | Botón de emergencia: tipo + descripción + foto + GPS, notifica al dueño, queda permanente |
| RF13-RF14 | Confianza y reputación | Calificar (1-5), mostrar estado de verificación |
| RF15 | Funciones complementarias | Foto al inicio, a mitad y al final del paseo |
| RF16 | Gestión de incidentes | Consultar incidentes del historial (dueño y paseador) |

## Requisitos no funcionales clave

- **RNF2**: actualizar ubicación en intervalos ≤10s durante el paseo.
- **RNF3**: responder a acciones del usuario en ≤3s.
- **RNF4-RNF5**: interfaz intuitiva, sin necesidad de asistencia; accesible desde
  navegadores y dispositivos móviles (plataforma Web, para ambos actores).
- **RNF6**: disponibilidad ≥95%.
- **RNF7**: soportar ≥15.000 usuarios concurrentes, respuesta ≤3s en funciones principales.

## Flujo de referencia: reporte de un incidente (el más crítico del sistema)

1. Paseador activa botón de emergencia en la plataforma web.
2. Se solicita tipo de incidente + descripción + foto.
3. Se envía la información al backend (tipo, descripción, foto, GPS, id_paseo).
4. Backend inserta documento en `incidentes`.
5. Backend inserta documento en `notificaciones` (tipo: "emergencia").
6. Dueño ve la alerta en la plataforma Web.
7. Backend confirma que el incidente quedó registrado.

## Flujo de referencia: ciclo de vida completo del paseo

1. Paseador publica disponibilidad → `paseos` se crea con `estado: "disponible"`.
2. Dueño consulta paseadores disponibles, inscribe su mascota.
3. Paseador inicia el paseo → `estado: "en_vivo"`, se registra `hora_inicio`.
4. Mientras `estado = "en_vivo"`: cada 10-30s, el dispositivo del paseador
   envía un punto GPS → se inserta en `coordenadas_detalle`.
5. Paseador finaliza el paseo → `estado: "historico"`, se registra `hora_fin`.
6. Backend notifica al dueño la finalización.

## Módulos del sistema (organización sugerida del código)

1. **Gestión de usuarios** — auth, perfiles (dueño/paseador) → colección `usuarios`
2. **Gestión de mascotas** → colección `mascotas`
3. **Gestión del servicio de paseo** — disponibilidad, solicitud, ciclo de vida → `paseos`
4. **Monitoreo y geolocalización** → `coordenadas_detalle`
5. **Gestión de incidentes** → `incidentes`
6. **Confianza y reputación** — calificaciones, verificación → `calificaciones`
7. **Notificaciones** → `notificaciones`

## Convenciones de nombres

- Nombres de campos en `snake_case` (coinciden con el esquema de arriba: `id_dueno`,
  `hora_inicio`, etc.) — no los traduzcas a camelCase salvo que se indique lo contrario.
- Los valores de `estado` en `paseos` son literalmente `"disponible"`, `"en_vivo"`,
  `"historico"` (con guion bajo en "en_vivo", sin tildes).
- Los valores de `rol` en `usuarios` son `"dueño"` y `"paseador"`.

## Qué NO hace el sistema (alcance definido, no lo agregues por iniciativa propia)

- No determina responsabilidad legal ante un incidente (solo documenta hechos).
- No sustituye autoridades, veterinario, abogado ni aseguradora.
- No garantiza que un incidente no ocurra.
- No emite certificaciones oficiales de idoneidad.
- No integra pasarela de pagos.
- No hay verificación automática/externa de las credenciales que el paseador declara
  (el campo `verificado` lo administra la plataforma, no una fuente externa).

## Estado actual del proyecto de grado

Documento, requisitos, modelado de base de datos, diagramas UML (casos de uso,
clases, secuencia, estados) y diseño de interfaces (Figma) ya están terminados y
aprobados conceptualmente. Lo que sigue es la implementación real (Fase 3 del
proyecto). Cuando generes código, mantenlo consistente con lo descrito arriba —
si algo no está claro o parece contradecir el documento, pregunta antes de asumir.
