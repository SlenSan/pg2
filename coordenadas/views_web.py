"""
Vistas web (dueño): pagina del mapa en vivo/historico y el endpoint JSON
que consume el JavaScript de Leaflet para pintar la ruta.
"""

from django.http import JsonResponse
from django.shortcuts import redirect, render

from coordenadas import repository
from paseos import repository as paseos_repository
from usuarios.decorators import requiere_dueno


def _paseo_del_dueno_o_none(request, id_paseo):
    paseo = paseos_repository.obtener_por_id(id_paseo)
    if not paseo or str(paseo.get('id_dueno')) != request.session.get('id_usuario'):
        return None
    return paseo


@requiere_dueno
def mapa_paseo(request, id_paseo):
    paseo = _paseo_del_dueno_o_none(request, id_paseo)
    if not paseo:
        return redirect('paseos:mis_paseos')
    return render(request, 'coordenadas/mapa.html', {
        'paseo': paseo,
        'id_paseo': str(paseo['_id']),
    })


@requiere_dueno
def coordenadas_de_paseo(request, id_paseo):
    paseo = _paseo_del_dueno_o_none(request, id_paseo)
    if not paseo:
        return JsonResponse({'error': 'No autorizado.'}, status=403)

    puntos = repository.listar_por_paseo(id_paseo)
    return JsonResponse({
        'estado': paseo['estado'],
        'puntos': [repository.a_json(p) for p in puntos],
    })
