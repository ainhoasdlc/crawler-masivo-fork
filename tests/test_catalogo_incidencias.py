"""Ningun tipo que emite el analizador se queda sin ficha en `incidencias.js`.

Es el criterio de la ola 1 del plan (`grep` del analyzer contra el catalogo):
la vista agrupada de Problemas enseña la ficha —que es, que decide Google,
como se arregla— y un tipo sin ella sale con su nombre tecnico en la reunion
con el cliente. Lee el fuente a proposito: lo que se comprueba es que dos
ficheros digan lo mismo, no un comportamiento (decision 74).

Los tipos se sacan con `ast` y no con una regex: la primera version, con
regex, no veia `hreflang_idioma_repetido` ni `hreflang_sin_x_default` porque
su primer argumento lleva parentesis (`ancla(pags)`), y el test seguia verde.
Las llamadas cuyo tipo no es un literal estan enumeradas abajo: una nueva hace
fallar el test hasta que alguien diga que tipos produce.
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Expresion del tipo (tal cual la escribe `ast.unparse`) -> tipos que produce.
_NO_LITERALES = {
    "f'structured_data_{status}'": {"structured_data_error",
                                    "structured_data_warning"},
    "tipo": {"missing_hsts", "missing_csp", "missing_x_content_type_options",
             "missing_x_frame_options"},
    # avisos_de_render.py (decision 140)
    "tipo_render": {"noindex_solo_en_crudo", "noindex_solo_al_renderizar",
                    "canonical_cambia_al_renderizar", "nofollow_cambia_al_renderizar",
                    "contenido_solo_con_js", "cambia_al_renderizar",
                    "respuesta_cambia_al_renderizar"},
    # avisos_de_accesibilidad.py (decision 174)
    "tipo_axe": {"accesibilidad_grave", "accesibilidad_menor"},
    "tipo_de_serie": {"paginacion_canonical_a_la_primera", "paginacion_noindex",
                      "solo_enlazada_desde_paginacion_profunda", "paginacion_sin_enlace",
                      "paginacion_siguiente_rota", "paginacion_rel_incorrecto"},
}

# Los modulos que emiten con `az._add_issue` ademas del analizador. Estaban
# fuera y sus tipos se escapaban del test (decisiones 106 y 122).
FUENTES = ("analyzer.py", "avisos_de_enlaces.py", "avisos_de_paginacion.py",
           "avisos_de_html.py", "avisos_de_servidor.py", "avisos_de_sondas.py",
           "avisos_de_sitemaps.py", "avisos_de_render.py", "avisos_de_gsc.py",
           "oportunidades_gsc.py", "avisos_de_medios.py", "avisos_de_wordpress.py",
           "avisos_de_nosnippet.py", "avisos_de_accesibilidad.py", "avisos_de_nofollow.py",
           "soft404.py", "avisos_de_backlinks.py", "avisos_de_logs.py", "avisos_de_trampas.py",
           "avisos_de_shopify.py")


def _llamadas() -> list[ast.expr]:
    tipos = []
    for fuente in FUENTES:
        tipos.extend(_llamadas_de(RAIZ / "analysis" / fuente))
    return tipos


def _llamadas_de(ruta: Path) -> list[ast.expr]:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    tipos = []
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "_add_issue"):
            if len(nodo.args) > 1:
                tipos.append(nodo.args[1])
            else:
                tipos.append(next(k.value for k in nodo.keywords
                                  if k.arg == "issue_type"))
    return tipos


def _tipos_emitidos() -> set[str]:
    tipos: set[str] = set()
    for expr in _llamadas():
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            tipos.add(expr.value)
        else:
            texto = ast.unparse(expr)
            assert texto in _NO_LITERALES, (
                f"_add_issue con un tipo no literal ({texto}): anadelo a "
                "_NO_LITERALES con los tipos que produce")
            tipos |= _NO_LITERALES[texto]
    return tipos


def test_el_patron_encuentra_los_tipos():
    tipos = _tipos_emitidos()
    # Si la extraccion se rompe, el test de abajo pasaria sin mirar nada.
    # Van los cinco de la decision 99, incluidos los dos que la regex perdia.
    assert {"4xx_error", "hreflang_missing_return",
            "hreflang_destino_no_indexable", "hreflang_idioma_repetido",
            "hreflang_sin_x_default", "hreflang_sin_autorreferencia",
            "hreflang_retorno_incoherente", "structured_data_error",
            "missing_csp", "enlace_interno_a_error", "enlace_externo_roto",
            "dominio_externo_muerto", "broken_resource"} <= tipos
    assert len(tipos) > 40


def test_cada_tipo_emitido_tiene_ficha():
    catalogo = (RAIZ / "frontend" / "incidencias.js").read_text(encoding="utf-8")
    sin_ficha = sorted(t for t in _tipos_emitidos() if f"'{t}': {{" not in catalogo)
    assert not sin_ficha, f"tipos sin entrada en ISSUE_INFO: {sin_ficha}"
