"""Vista web (dueño): historial de incidentes de sus propios paseos (RF16)."""

from django.shortcuts import render

from incidentes import repository
from mascotas import repository as mascotas_repository
from paseos import repository as paseos_repository
from usuarios import repository as usuarios_repository
from usuarios.decorators import requiere_dueno


@requiere_dueno
def lista_incidentes(request):
    paseos = paseos_repository.listar_por_dueno(request.session['id_usuario'])
    paseos_por_id = {p['_id']: p for p in paseos}

    incidentes = repository.listar_por_paseos(list(paseos_por_id.keys()))

    paseadores_por_id = usuarios_repository.obtener_varios_por_id(
        [p['id_paseador'] for p in paseos]
    )
    mascotas_por_id = mascotas_repository.obtener_varias_por_id(
        [p['id_mascota'] for p in paseos if p.get('id_mascota')]
    )

    items = []
    for incidente in incidentes:
        paseo = paseos_por_id.get(incidente['id_paseo'])
        items.append({
            'incidente': incidente,
            'paseador': paseadores_por_id.get(paseo['id_paseador']) if paseo else None,
            'mascota': mascotas_por_id.get(paseo.get('id_mascota')) if paseo else None,
        })

    return render(request, 'incidentes/lista.html', {'items': items})
