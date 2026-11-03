"""La autoridad desde fuera en el Resumen del rastreo (#31, decision 212),
ejecutando `frontend/app.js` en Chromium. Necesita Chromium: se salta si no
esta."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("playwright")

from test_evolucion_frontend import _evaluar  # noqa: E402

EXTERNO = {"import_id": 3, "fuente": "ahrefs", "fecha_dato": "2026-10-20", "subido": "2026-10-27T20:00:00Z",
           "backlinks": 200, "casados": 150, "parte_casada": 0.75, "paginas_con_backlinks": 42, "beta": 0.5,
           "entra_en": {"indexable": 0.6, "no_indexable": 0.05, "redireccion": 0.1, "error": 0.25,
                        "recurso": 0, "sin_respuesta": 0},
           "no_rastreadas": [{"url": "https://x.com/vieja", "backlinks": 9, "dominios": 4, "aportacion": 12.5}]}


def _bloque(job):
    return _evaluar("() => bloqueBacklinks(" + json.dumps(job) + ")")


def test_sin_backlinks_no_hay_bloque():
    assert _bloque({"pagerank_resumen": {"reparto": {}}}) is None
    assert _bloque({}) is None


def test_lo_que_entra_de_fuera_y_lo_que_se_pierde():
    b = _bloque({"pagerank_resumen": {"externo": EXTERNO}})
    assert b["fuente"] == "Ahrefs" and b["fecha"] == "2026-10-20"
    assert b["frases"][0] == "150 de 200 backlinks (75 %) llegan a 42 páginas de este rastreo."
    assert b["frases"][1].startswith("25 % de la autoridad que entra de fuera cae en páginas con error")
    assert any("redirecciones" in f for f in b["frases"])
    assert b["poco_casado"] is True, "por debajo del 90 % se avisa"
    assert b["no_rastreadas"][0]["url"] == "https://x.com/vieja"
    con_spam = _bloque({"pagerank_resumen": {"externo": {**EXTERNO, "spam": 120}}})
    assert con_spam["frases"][1] == ("120 de 200 (60 %) están marcados como spam por Ahrefs: se cuentan, "
                                     "pero no suman autoridad en el PageRank desde fuera.")
    assert con_spam["spam"] == 120 and b["spam"] == 0
    casi = {**EXTERNO, "parte_casada": 0.95, "entra_en": {"indexable": 1.0}}
    b = _bloque({"pagerank_resumen": {"externo": casi}})
    assert b["poco_casado"] is False and len(b["frases"]) == 1
