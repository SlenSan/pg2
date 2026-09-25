"""
Crea/asegura los indices de MongoDB que el proyecto necesita. Es
idempotente (correrlo varias veces no duplica ni rompe nada), asi que se
puede ejecutar a mano cuando haga falta: `python manage.py crear_indices`.
"""

from django.core.management.base import BaseCommand

from core.mongo import get_db

_NOVENTA_DIAS_EN_SEGUNDOS = 90 * 24 * 60 * 60


class Command(BaseCommand):
    help = 'Crea los indices de MongoDB del proyecto (usuarios, paseos, coordenadas_detalle).'

    def handle(self, *args, **options):
        db = get_db()

        db.usuarios.create_index('correo', unique=True)
        self.stdout.write(self.style.SUCCESS('usuarios.correo: indice unico OK'))

        db.paseos.create_index([('id_paseador', 1), ('estado', 1)])
        db.paseos.create_index([('id_dueno', 1)])
        self.stdout.write(self.style.SUCCESS('paseos: indices de consulta OK'))

        db.coordenadas_detalle.create_index('id_paseo')
        db.coordenadas_detalle.create_index(
            'fecha_recepcion',
            expireAfterSeconds=_NOVENTA_DIAS_EN_SEGUNDOS,
        )
        self.stdout.write(self.style.SUCCESS(
            'coordenadas_detalle: indice id_paseo + TTL de 90 dias OK'
        ))

        db.calificaciones.create_index('id_paseo', unique=True)
        self.stdout.write(self.style.SUCCESS(
            'calificaciones.id_paseo: indice unico OK (evita calificar el mismo paseo dos veces)'
        ))

        db.notificaciones.create_index([('id_usuario', 1), ('fecha', 1)])
        self.stdout.write(self.style.SUCCESS(
            'notificaciones: indice id_usuario+fecha OK (el punto del navbar la consulta en casi '
            'toda pagina autenticada - ver core/context_processors.py)'
        ))
