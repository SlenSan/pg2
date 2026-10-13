// Service worker de Canigo (Incremento 4, fase 2, punto E - Web Push).
// Servido desde la RAIZ (/sw.js, no /static/sw.js) para que su alcance
// cubra todo el sitio - el alcance por defecto de un service worker es
// su propio directorio, asi que serville desde /static/ lo hubiera
// dejado controlando solo esa carpeta. No cachea nada (sin soporte
// offline pedido) - su unico trabajo es Web Push.

self.addEventListener('install', function (event) {
  // skipWaiting: activa esta version apenas se instala, sin esperar a
  // que se cierren todas las pestañas viejas - en una PWA de iOS, que
  // rara vez se "cierra" de verdad, esperar dejaria la version nueva
  // sin activarse por mucho tiempo.
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

// CRITICO para iOS (ver MANUAL_DESARROLLADOR.md): si un evento "push"
// no termina en exactamente un showNotification(), Safari/iOS considera
// que la app no esta usando el push correctamente y puede cancelar la
// suscripcion - por eso SIEMPRE se muestra una notificacion, incluso si
// el payload no se pudo leer (mensaje generico de respaldo).
self.addEventListener('push', function (event) {
  var datos = {titulo: 'Canigo', mensaje: 'Tienes una notificación nueva.', url: '/notificaciones/'};
  try {
    if (event.data) {
      var recibido = event.data.json();
      datos.titulo = recibido.titulo || datos.titulo;
      datos.mensaje = recibido.mensaje || datos.mensaje;
      datos.url = recibido.url || datos.url;
    }
  } catch (err) {
    // payload invalido o no-JSON - se usa el mensaje generico de arriba,
    // nunca se deja de mostrar nada (ver el comentario de arriba).
  }

  event.waitUntil(
    self.registration.showNotification(datos.titulo, {
      body: datos.mensaje,
      icon: '/static/img/icono-192.png',
      badge: '/static/img/icono-192.png',
      data: {url: datos.url},
    })
  );
});

// Al tocar el push, abre (o enfoca, si ya esta abierta) la pagina
// correspondiente - nunca una pestaña nueva de mas si Canigo ya esta
// abierto.
self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var urlDestino = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil(
    self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(function (listaClientes) {
      for (var i = 0; i < listaClientes.length; i++) {
        var cliente = listaClientes[i];
        if (cliente.url.indexOf(self.location.origin) === 0 && 'focus' in cliente) {
          cliente.navigate(urlDestino);
          return cliente.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(urlDestino);
      }
    })
  );
});
