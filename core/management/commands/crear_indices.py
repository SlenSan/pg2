"""
Crea/asegura los indices de MongoDB que el proyecto necesita. Es
idempotente (correrlo varias veces no duplica ni rompe nada), asi que se
puede ejecutar a mano cuando haga falta: `python manage.py crear_indices`.
"""

from django.core.management.base import BaseCommand
from pymongo.errors import OperationFailure

from core.mongo import get_db

_NOVENTA_DIAS_EN_SEGUNDOS = 90 * 24 * 60 * 60


class Command(BaseCommand):
    help = 'Crea los indices de MongoDB del proyecto (usuarios, paseos, coordenadas_detalle).'

    def handle(self, *args, **options):
        db = get_db()

        db.usuarios.create_index('correo', unique=True)
        self.stdout.write(self.style.SUCCESS('usuarios.correo: indice unico OK'))

        db.paseos.create_index([('id_paseador', 1), ('estado', 1)])
        # El campo viejo era 'id_dueno' (un solo dueño); paso a
        # 'id_duenos' (array - ver CLAUDE.md, "Corrección de alcance
        # 2026-09-25"). Se tira el indice viejo, que ya no aporta nada
        # (nada nuevo escribe ese campo).
        try:
            db.paseos.drop_index('id_dueno_1')
        except OperationFailure:
            pass
        db.paseos.create_index([('id_duenos', 1)])
        self.stdout.write(self.style.SUCCESS('paseos: indices de consulta OK'))

        db.coordenadas_detalle.create_index('id_paseo')
        db.coordenadas_detalle.create_index(
            'fecha_recepcion',
            expireAfterSeconds=_NOVENTA_DIAS_EN_SEGUNDOS,
        )
        self.stdout.write(self.style.SUCCESS(
            'coordenadas_detalle: indice id_paseo + TTL de 90 dias OK'
        ))

        # El indice viejo era 'id_paseo' unico a secas (un paseo = una
        # calificacion, total). Con paseos de varios dueños (ver
        # CLAUDE.md, "Corrección de alcance 2026-09-25"), cada dueño
        # califica su propia experiencia por separado - hay que
        # reemplazarlo por uno compuesto (id_paseo+id_dueno), o el
        # indice viejo seguiria bloqueando la segunda calificacion de un
        # mismo paseo. drop_index ignora silenciosamente si ya no existe
        # (cluster nuevo, o ya se corrio esta migracion antes).
        try:
            db.calificaciones.drop_index('id_paseo_1')
        except OperationFailure:
            pass
        db.calificaciones.create_index([('id_paseo', 1), ('id_dueno', 1)], unique=True)
        self.stdout.write(self.style.SUCCESS(
            'calificaciones: indice unico compuesto id_paseo+id_dueno OK '
            '(un paseo con varios dueños permite una calificación por cada uno)'
        ))

        db.notificaciones.create_index([('id_usuario', 1), ('fecha', 1)])
        self.stdout.write(self.style.SUCCESS(
            'notificaciones: indice id_usuario+fecha OK (el punto del navbar la consulta en casi '
            'toda pagina autenticada - ver core/context_processors.py)'
        ))
