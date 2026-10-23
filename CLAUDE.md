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

## Esquema de base de datos (MongoDB — 8 colecciones en servidor)

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
  autorizacion_datos: {           // RNF1, Ley 1581 de 2012 (cierre de auditoría, punto 1) - una
                                    // cuenta NUEVA lo tiene desde que se registra (casilla
                                    // obligatoria, rechazada en el backend si no viene marcada);
                                    // una cuenta de ANTES de este punto no lo tiene hasta que pasa
                                    // por la pantalla intermedia /cuentas/autorizacion-datos/ (ver
                                    // usuarios.decorators - en realidad core.middleware.
                                    // ExigirAutorizacionDatosMiddleware - que la redirige ahí para
                                    // CUALQUIER ruta mientras falte este campo)
    fecha: Date,                   // UTC, momento en que se aceptó (el de la cuenta nueva o el de
                                    // la pantalla intermedia, lo que haya pasado)
    version: String                // versión del TEXTO de /privacidad/ que se aceptó (ver
                                    // usuarios.repository.VERSION_POLITICA_PRIVACIDAD) - "1.0"
  },
  calificacion_promedio: Number,  // solo rol=paseador
  verificado: Boolean,             // solo rol=paseador
  descripcion: String,             // solo rol=paseador
  requiere_cambio_contrasena: Boolean,  // Mejora 2 (hallazgos de la prueba con un usuario final,
                                          // 14 de octubre) - "¿Olvidaste tu contraseña?" (versión
                                          // provisional, sin envío de correo): true mientras la
                                          // cuenta tenga pendiente cambiar una contraseña TEMPORAL
                                          // que le asignó un admin desde /administracion/contrasenas/
                                          // (core.middleware.ExigirCambioContrasenaMiddleware la
                                          // redirige a /cuentas/cambiar-contrasena/ para CUALQUIER
                                          // ruta mientras esto sea true, igual que
                                          // ExigirAutorizacionDatosMiddleware con autorizacion_datos
                                          // arriba). Ausente/false en una cuenta normal
  contrasena_temporal_historial: [{      // un registro por cada vez que un admin asignó una
                                          // contraseña temporal - NUNCA la contraseña en sí (ni
                                          // aquí ni en ningún log), solo quién y cuándo
    asignado_por: String,                // correo del admin
    fecha: Date                          // UTC
  }],
  ultima_recogida: {              // Incremento 4 fase 3, punto A1 - solo rol=dueño. Se guarda (se
                                    // sobreescribe, no es un historial) cada vez que este dueño
                                    // inscribe una mascota con éxito, para prellenar la PRÓXIMA
                                    // inscripción (paseos.views_web.detalle_paseador()). Ausente en
                                    // una cuenta que nunca inscribió - esa primera vez se prellena
                                    // con `direccion`/`telefono` de arriba en su lugar
    direccion: String,
    comuna: String,                // uno de ZONAS_VALIDAS
    indicaciones: String,
    telefono: String
  }
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
  id_mascotas: [ObjectId], // referencia a mascotas - hasta 8 en total (Ley Kiara, ver Marco
                            // Normativo del documento de grado), de uno o VARIOS dueños distintos
  id_duenos: [ObjectId],   // referencia a usuarios - todos los dueños con al menos una mascota
                            // inscrita en este paseo (no solo uno - ver "Corrección de alcance"
                            // 2026-09-25 mas abajo). Se mantiene junto con id_mascotas en cada
                            // inscripcion (no se deriva de mascotas.id_dueno en cada consulta)
  acepta_inscripciones: Boolean, // true por defecto mientras estado="disponible" - el paseador lo
                                   // pone en false para cerrar el horario a NUEVAS inscripciones
                                   // sin expulsar a las mascotas ya inscritas (ver mas abajo).
                                   // Tambien se cierra solo (implicitamente, sin tocar este campo)
                                   // al llegar a 8 mascotas o al pasar a "en_vivo"/"historico"
  estado: String,          // "disponible" | "en_vivo" | "historico"
  fecha: Date,
  horario_desde: Date,     // horario PROPUESTO por el paseador (solo mientras estado="disponible")
  horario_hasta: Date,     // idem - distintos de hora_inicio/hora_fin (el momento REAL)
  zonas: [String],         // 1 a N valores de ZONAS_VALIDAS (paseos/repository.py) - se elige CADA
                            // VEZ que se publica un horario (no es un dato fijo del perfil del
                            // paseador). Al menos una es obligatoria desde INC-09 (hallazgos de la
                            // prueba con un usuario final, 14 de octubre) - antes [] era válido
                            // ("no especificó zona"); un horario ya existente con [] de ANTES de
                            // ese punto no se migró, sigue así hasta que su paseador lo vuelva a
                            // publicar (ver MANUAL_DESARROLLADOR.md para el conteo)
                            // (Incremento 1, RF5/RF6, ver "Corrección de alcance" 2026-09-29 mas abajo)
  hora_inicio: Date,
  hora_fin: Date,
  total_puntos: Number,
  emergencia: Boolean,     // true si se activó el botón de emergencia
  fotos: [{ url: String, momento: String }],  // momento: "inicio"|"mitad"|"fin" - INC-12 (22 de
                                                // octubre): desde que existe `recogidas[]`, las
                                                // fotos NUEVAS se guardan en `recogidas[ese
                                                // dueño].fotos` (mas abajo), no aca - este campo
                                                // sigue existiendo solo como lo que ya tenia un
                                                // paseo de ANTES de ese punto (legacy, un solo
                                                // dueño en ese entonces, o un paseo que ya estaba
                                                // "en_vivo" al desplegar el fix). No se migra ni
                                                // se borra lo viejo
  distancia_m: Number,     // Ajustes del 19 de octubre, punto 1 - metros recorridos (Haversine
                            // sobre coordenadas_detalle, solo puntos con precision <= 50m o nula -
                            // ver coordenadas/repository.py::distancia_recorrida_m()/
                            // UMBRAL_PRECISION_METROS). Se calcula y se guarda UNA vez, al
                            // finalizar el paseo (paseos/views_web.py::finalizar_paseo) - un paseo
                            // "disponible"/"en_vivo" no lo tiene todavía. Puede ser null (menos de 2
                            // puntos válidos). Un paseo histórico de ANTES de este punto no tiene el
                            // campo en absoluto (no se migró) - se calcula en vivo al consultarse
                            // (paseos/views_web.py::_distancia_texto_de_paseo), sin guardarse
  recogidas: [{            // Incremento 4 fase 3, punto A1 - UNA entrada por dueño con mascotas en
                            // este paseo (no una por inscripción - ver inscribir_mascotas()), creada/
                            // actualizada al inscribir. Un paseo de ANTES de este punto no tiene el
                            // campo en absoluto - tratar como [] (.get('recogidas', [])), nunca asumir
                            // presente
    id_dueno: ObjectId,     // referencia a usuarios
    id_mascotas: [ObjectId], // subconjunto de paseos.id_mascotas que pertenece a ESTE dueño
    direccion: String,
    comuna: String,         // uno de ZONAS_VALIDAS
    indicaciones: String,   // opcional, "" si no se dio ninguna
    telefono: String,       // celular colombiano del dueño, de contacto para ESTE paseo
    duracion_acordada_min: Number, // punto A7 - 30|60|90|120 (maximo bajado de 3h a 2h el 20 de
                                    // octubre: 150|180 ya NO se ofrecen ni se aceptan en una
                                    // inscripcion nueva, pero una inscripcion que ya los tenga
                                    // de antes de ese ajuste se sigue mostrando con su valor -
                                    // paseos/repository.py::_ETIQUETAS_DURACION_DESCONTINUADAS).
                                    // null en paseos de antes de A7
    estado: String,         // "pendiente" | "recogida" | "no_recogida" | "entregada"
    hora_recogida: Date,    // null hasta que el paseador marca "Recogido"
    hora_entrega: Date,     // null hasta que el paseador marca "Entregado"
    motivo_no_recogida: String, // null salvo que estado="no_recogida"
    fotos: [{ url: String, momento: String }] // INC-12 (hallazgos de la prueba de usabilidad,
                                                // 22 de octubre) - las 3 fotos (inicio/mitad/fin,
                                                // RF15) de LAS MASCOTAS DE ESTE DUEÑO, no de todo
                                                // el paseo (antes vivian en paseos.fotos de mas
                                                // abajo, compartidas entre todos los duenos - un
                                                // problema de privacidad ademas del funcional).
                                                // Ausente/[] si el paseador todavia no subio
                                                // ninguna para este dueno. Ver
                                                // paseos.repository.agregar_foto()/
                                                // fotos_visibles_para_dueno()
  }]
}
```

> **Corrección de alcance (2026-09-25):** un paseo YA NO es necesariamente
> de un solo dueño. El paseador puede llevar hasta 8 mascotas juntas en el
> mismo paseo (límite real de la Ley Kiara), de dueños distintos - un
> horario publicado sigue abierto a nuevas inscripciones de OTROS dueños
> hasta llegar a 8 mascotas en total o hasta que el paseador lo cierre
> manualmente (`acepta_inscripciones: false`), lo que pase primero. Por
> eso `id_dueno` (singular) pasó a `id_duenos` (array). Cualquier código o
> documentación vieja que hable de "el dueño de este paseo" en singular es
> un resto de la version anterior, no la decision vigente. Consecuencia
> importante de privacidad: cualquier pantalla que le muestre a un dueño
> "las mascotas de este paseo" debe filtrar `id_mascotas` a SOLO las de
> ESE dueño (`mascotas.obtener_varias_por_id_y_dueno`), nunca las 8 - un
> dueño no debe ver el nombre de una mascota ajena.

> **Corrección de alcance (2026-09-29):** se agregó `zonas` (Incremento 1,
> RF5/RF6) - el paseador elige en qué comunas puede pasear cada vez que
> publica un horario (selección múltiple, opcional). La lista fija son
> las **17 comunas oficiales de Bucaramanga** (división político-urbana
> de la Alcaldía, bucaramanga.gov.co/division-politico-urbana), en este
> orden y con estos nombres exactos - no uses ninguna otra lista de
> zonas/barrios en el proyecto:
> `Norte`, `Nororiental`, `San Francisco`, `Occidental`, `García Rovira`,
> `La Concordia`, `La Ciudadela`, `Sur Occidente`, `La Pedregosa`,
> `Provenza`, `Sur`, `Cabecera del Llano`, `Oriental`, `Morrorico`,
> `Centro`, `Lagos del Cacique`, `Mutis` (constante `ZONAS_VALIDAS` en
> `paseos/repository.py`). Se eligió la división oficial completa (no una
> lista curada de sectores populares) para que ningún sector de la ciudad
> quede sin cobertura posible. El dueño filtra por zona en "Paseadores
> disponibles" (un paseador con horarios mixtos - algunos en la zona
> filtrada, otros no - sigue apareciendo, porque tiene al menos un
> horario que califica) y ve las zonas de cada horario en el perfil del
> paseador.
>
> **Corrección de alcance (2026-10-12, Incremento 4 punto G):** el ORDEN
> de arriba coincide exactamente con el número oficial de cada comuna
> (1=Norte, 2=Nororiental, ..., 17=Mutis - confirmado contra
> bucaramanga.gov.co/el-mapa/division-politico-urbana antes de usarlo).
> `paseos/repository.py` ahora lo hace explícito con
> `ZONAS_VALIDAS_CON_NUMERO` (tuplas `(numero, nombre)`), de la que
> `ZONAS_VALIDAS` se deriva - lo que se GUARDA en `paseos.zonas` sigue
> siendo solo el nombre, sin migración. `etiqueta_zona(valor)` (reusada
> como filtro de plantilla, `paseos/templatetags/paseos_tags.py`) es la
> ÚNICA función que da el formato "Comuna N. Nombre" - ninguna plantilla
> lo arma a mano.

### `coordenadas_detalle`
```
{
  _id: ObjectId,
  id_paseo: ObjectId,      // referencia a paseos
  latitud: Number,
  longitud: Number,
  altitud: Number,
  precision: Number,       // radio de incertidumbre en metros (position.coords.accuracy
                            // del navegador) - null en documentos de antes del Incremento 4
                            // o si el navegador no lo reportó. Desde la revisión de la fase 1
                            // (commit 651bcc7) un punto con mala precisión YA NO se descarta
                            // al guardar - se guarda siempre, con su precision tal cual llegó.
                            // El umbral de 50m solo se aplica del lado del DIBUJO del mapa
                            // (UMBRAL_PRECISION_DIBUJO en coordenadas/templates/coordenadas/
                            // mapa.html), nunca al escribir en esta colección. Por otro lado,
                            // un punto SÍ se descarta al guardar si implica una velocidad
                            // > 30 km/h respecto al ÚLTIMO PUNTO GUARDADO de este paseo
                            // (coordenadas.repository.velocidad_implicita_kmh()/
                            // VELOCIDAD_MAXIMA_RAZONABLE_KMH, aplicado en
                            // coordenadas.views_web.registrar_coordenada()) - un punto GPS
                            // puede reportar precision buena y aun así estar fuera de lugar
                            // (típico de un fix de red/Wi-Fi reemplazando al GPS satelital),
                            // así que precision sola no alcanza para este tipo de error. No
                            // se aplica al PRIMER punto de un paseo (no hay punto anterior con
                            // el que comparar) - ver MANUAL_DESARROLLADOR.md para la propuesta
                            // pendiente de decisión sobre ese caso.
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
  direccion_aproximada: String,  // geocodificación inversa (Nominatim/OSM) al momento de
                                   // guardar - null si no había coordenadas, si el servicio
                                   // falló, o si tardó más de 5s (ver core/geocoding.py).
                                   // "Aproximada" porque viene de un servicio externo, no de
                                   // un dato que el paseador haya escrito.
  fecha_hora: Date,
  notificado: Boolean,     // si el dueño ya fue notificado
  complementos: [{            // Incremento 4 fase 3, punto A8 - tipo, descripcion, evidencia_foto,
                                // latitud, longitud, direccion_aproximada y fecha_hora de ARRIBA
                                // quedan inmutables (ningun codigo los modifica despues de crear() -
                                // ver incidentes/repository.py); esto es lo UNICO que se puede
                                // agregar despues. Ausente/[] en un incidente de antes de A8
    texto: String,              // obligatorio, maximo 500 caracteres
    foto: String,                // opcional, null si no se adjunto
    fecha: Date
  }]
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
Índice único **compuesto** `(id_paseo, id_dueno)`, no solo `id_paseo` - un
paseo con varios dueños (ver `paseos.id_duenos` arriba) permite una
calificación independiente POR dueño, no una sola para todo el paseo.

### `notificaciones`
```
{
  _id: ObjectId,
  id_usuario: ObjectId,    // referencia a usuarios (destinatario)
  tipo: String,            // "inicio_paseo"|"fin_paseo"|"emergencia"|"calificacion"|"verificacion"
  mensaje: String,
  fecha: Date
}
```

### `suscripciones_push`
```
{
  _id: ObjectId,
  id_usuario: ObjectId,    // referencia a usuarios
  endpoint: String,        // único (índice único) - lo asigna el navegador/servicio de push,
                            // identifica un dispositivo/instalación concreto, no al usuario
  keys: {
    p256dh: String,
    auth: String
  },
  fecha: Date              // última vez que se guardó/actualizó esta suscripción
}
```
Incremento 4, fase 2 (Web Push) - un usuario puede tener varias suscripciones (varios
dispositivos). Al crearse una notificación en `notificaciones` (cualquiera de los 7
llamadores existentes), se intenta además un Web Push a cada suscripción de ese
usuario (`notificaciones/repository.py::_enviar_push`) - si falla, la notificación
interna ya quedó creada igual. Una suscripción vencida (404/410 del servicio de push)
se borra sola.

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
