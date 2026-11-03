"""El PageRank con backlinks y sus avisos, contra Postgres de verdad (#31,
decision 212). Reutiliza el blog de `test_pagerank_db.py` (301, 404,
canonicalizada, noindex) con un cliente y un CSV de backlinks.

Se salta sin `PAGERANK_TEST_DATABASE_URL`. NUNCA apuntarlo a la BD de trabajo.
"""

from __future__ import annotations

import os
import uuid

import pytest

URL_BD = os.environ.get("PAGERANK_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL_BD, reason="sin PAGERANK_TEST_DATABASE_URL")

pytest.importorskip("numpy")

from sqlalchemy import select  # noqa: E402

from test_pagerank_db import BASE, job, sesion  # noqa: E402,F401

from shared.models import BacklinkImport, Client, ExternalLink, Issue, Job, Url  # noqa: E402


@pytest.fixture()
def con_backlinks(sesion, job):  # noqa: F811
    j, filas = job
    c = Client(id=uuid.uuid4(), nombre="X", slug=f"x-{uuid.uuid4().hex[:8]}", dominios=["x.com"],
               config_defecto={}, integraciones=[])
    sesion.add(c)
    sesion.flush()
    sesion.get(Job, j.id).cliente_id = c.id
    imp = BacklinkImport(cliente_id=c.id, fuente="ahrefs", filas=6)
    sesion.add(imp)
    sesion.flush()
    bloqueada = Url(job_id=j.id, url=BASE + "/privado", url_hash="privado", is_internal=True, status_code=None,
                    is_html=None, indexable=False, indexability_status="Blocked by robots.txt",
                    blocked_by_robots=True, crawl_depth=2)
    sesion.add(bloqueada)
    sesion.flush()
    filas["/privado"] = bloqueada
    for destino, aporte in (("https://www.x.com/roto", 8.0), ("https://x.com/viejo", 4.0),
                            ("https://x.com/tag/x", 2.0), ("https://x.com/ya-no-existe", 1.0),
                            ("https://x.com/privado", 1.0), ("https://x.com/contacto", 1.0)):
        sesion.add(ExternalLink(import_id=imp.id, url_to=destino, url_from="https://otro.com/p",
                                dominio_from="otro.com", aportacion=aporte))
    sesion.commit()
    yield j, filas, c
    sesion.delete(sesion.get(Client, c.id))
    sesion.commit()


def test_pagerank_externo_y_avisos(sesion, con_backlinks):
    from analysis import avisos_de_backlinks
    from analysis.analyzer import SEOAnalyzer

    j, filas, _ = con_backlinks
    an = SEOAnalyzer(sesion, str(j.id))
    # /contacto como huerfana: su aviso lleva los backlinks, no se cambia por otro
    an._add_issue(filas["/contacto"].id, "orphan_page", "warning", {"x": 1})
    an._flush_issues()
    an.compute_pagerank()
    avisos_de_backlinks.avisar(an)
    an._flush_issues()
    sesion.commit()

    resumen = sesion.get(Job, j.id).pagerank_resumen
    ext = resumen["externo"]
    assert (ext["backlinks"], ext["casados"], ext["parte_casada"]) == (6, 5, round(5 / 6, 4))
    assert ext["no_rastreadas"][0]["url"] == "https://x.com/ya-no-existe"
    assert ext["entra_en"]["error"] == pytest.approx(8 / 16, abs=1e-3)
    # Lo que llega al 404 se pierde: el desperdiciado del externo pasa al del interno
    assert ext["desperdiciado"] > resumen["desperdiciado"]

    def fila(ruta):
        return sesion.execute(select(Url.pagerank_score, Url.pagerank_externo_score, Url.backlinks_externos,
                                     Url.autoridad_externa).where(Url.id == filas[ruta].id)).one()

    assert fila("/roto")[2:] == (1, 8.0)
    assert fila("/blog/a3")[2] == 0

    tipos = {(t, u) for t, u in sesion.execute(
        select(Issue.issue_type, Issue.url_id).where(Issue.job_id == j.id, Issue.issue_type.like("%backlinks%")))}
    assert ("backlinks_a_error", filas["/roto"].id) in tipos
    assert ("backlinks_a_noindex", filas["/tag/x"].id) in tipos
    assert ("backlinks_a_bloqueada_robots", filas["/privado"].id) in tipos, "bloqueada, no «error»"
    assert ("backlinks_a_error", filas["/privado"].id) not in tipos
    assert not any(u == filas["/viejo"].id for _, u in tipos), "una 301 con backlinks no se avisa"
    (det,) = sesion.execute(select(Issue.details).where(Issue.job_id == j.id, Issue.issue_type == "orphan_page",
                                                         Issue.url_id == filas["/contacto"].id)).one()
    assert det["x"] == 1 and det["backlinks"] == 1, "la huerfana lleva sus backlinks en el detalle"


def _con_spam(sesion, con_backlinks):
    """Dos backlinks spam con mucha aportacion: uno al 404 que ya tiene uno
    bueno y otro a un 404 que solo recibe spam. Analiza y avisa."""
    from analysis import avisos_de_backlinks
    from analysis.analyzer import SEOAnalyzer

    j, filas, c = con_backlinks
    solo_spam = Url(job_id=j.id, url=BASE + "/spam-404", url_hash="spam-404", is_internal=True, status_code=404,
                    is_html=True, indexable=False, indexability_status="4xx Client Error", crawl_depth=2)
    sesion.add(solo_spam)
    imp = sesion.query(BacklinkImport).filter(BacklinkImport.cliente_id == c.id).one()
    imp.spam = 2
    for destino in ("https://x.com/roto", "https://x.com/spam-404"):
        sesion.add(ExternalLink(import_id=imp.id, url_to=destino, url_from="https://red.shop/p",
                                dominio_from="red.shop", aportacion=50.0, spam=True))
    sesion.commit()
    an = SEOAnalyzer(sesion, str(j.id))
    an.compute_pagerank()
    avisos_de_backlinks.avisar(an)
    an._flush_issues()
    sesion.commit()
    return j, filas, solo_spam


def test_el_spam_se_cuenta_no_aporta_y_no_avisa(sesion, con_backlinks):
    """Un backlink spam suma en `backlinks_spam` y no en la autoridad; un 404
    al que solo enlaza spam no es «backlinks a error»."""
    j, filas, solo_spam = _con_spam(sesion, con_backlinks)
    ext = sesion.get(Job, j.id).pagerank_resumen["externo"]
    assert (ext["backlinks"], ext["spam"], ext["spam_casados"]) == (8, 2, 2)
    assert ext["entra_en"]["error"] == pytest.approx(8 / 16, abs=1e-3), "los 50 del spam no cuentan"
    roto = sesion.execute(select(Url.backlinks_externos, Url.backlinks_spam, Url.backlinks_spam_pct,
                                 Url.autoridad_externa).where(Url.id == filas["/roto"].id)).one()
    assert tuple(roto) == (2, 1, 50.0, 8.0)
    sin = sesion.execute(select(Url.backlinks_spam_pct).where(Url.job_id == j.id, Url.backlinks_externos == 0)).scalars().all()
    assert sin and set(sin) == {None}, "sin backlinks no es un 0 % de spam"
    tipos = {(t, u) for t, u in sesion.execute(
        select(Issue.issue_type, Issue.url_id).where(Issue.job_id == j.id, Issue.issue_type == "backlinks_a_error"))}
    assert ("backlinks_a_error", filas["/roto"].id) in tipos
    assert ("backlinks_a_error", solo_spam.id) not in tipos, "solo spam: nada que recuperar"


def test_el_informe_cuenta_el_spam(sesion, con_backlinks):
    pytest.importorskip("fastapi")
    from api.routers.results import _backlinks_del_informe

    j, _, _ = _con_spam(sesion, con_backlinks)
    inf = _backlinks_del_informe(sesion, sesion.get(Job, j.id))
    assert (inf["backlinks"], inf["spam"], inf["a_error"]) == (8, 2, 1)
    assert {"url": BASE + "/roto", "backlinks": 2, "spam": 1} in inf["paginas"]


def test_sin_aristas_los_avisos_salen_igual(sesion, con_backlinks):
    """El cruce no depende del grafo: un censo sin enlaces internos tambien
    avisa del 404 con backlinks."""
    from analysis import avisos_de_backlinks
    from analysis.analyzer import SEOAnalyzer
    from shared.models import Link

    j, filas, _ = con_backlinks
    sesion.query(Link).filter(Link.job_id == j.id).delete()
    sesion.commit()
    an = SEOAnalyzer(sesion, str(j.id))
    an.compute_pagerank()
    avisos_de_backlinks.avisar(an)
    an._flush_issues()
    sesion.commit()
    tipos = {t for (t,) in sesion.execute(select(Issue.issue_type).where(Issue.job_id == j.id))}
    assert "backlinks_a_error" in tipos


def test_sin_importacion_las_columnas_quedan_a_null(sesion, con_backlinks):
    from analysis.analyzer import SEOAnalyzer

    j, filas, c = con_backlinks
    SEOAnalyzer(sesion, str(j.id)).compute_pagerank()
    sesion.commit()
    assert sesion.get(Url, filas["/roto"].id).backlinks_externos == 1
    sesion.query(BacklinkImport).filter(BacklinkImport.cliente_id == c.id).delete()
    sesion.commit()
    SEOAnalyzer(sesion, str(j.id)).compute_pagerank()
    sesion.commit()
    sesion.expire_all()
    assert sesion.get(Url, filas["/roto"].id).backlinks_externos is None
    assert "externo" not in (sesion.get(Job, j.id).pagerank_resumen or {})


def test_un_404_con_solo_nofollow_se_avisa_y_no_aporta(sesion, con_backlinks):
    """Un nofollow no trae autoridad, pero si visitas: el 404 que solo lo
    recibe se avisa (inventario de una migracion), y sale en su columna."""
    from analysis import avisos_de_backlinks
    from analysis.analyzer import SEOAnalyzer

    j, filas, c = con_backlinks
    nf = Url(job_id=j.id, url=BASE + "/nf-404", url_hash="nf-404", is_internal=True, status_code=404,
             is_html=True, indexable=False, indexability_status="4xx Client Error", crawl_depth=2)
    sesion.add(nf)
    imp = sesion.query(BacklinkImport).filter(BacklinkImport.cliente_id == c.id).one()
    sesion.add(ExternalLink(import_id=imp.id, url_to=BASE + "/nf-404", url_from="https://foro.com/hilo",
                            dominio_from="foro.com", aportacion=50.0, nofollow=True))
    sesion.commit()
    an = SEOAnalyzer(sesion, str(j.id))
    an.compute_pagerank()
    avisos_de_backlinks.avisar(an)
    an._flush_issues()
    sesion.commit()
    ext = sesion.get(Job, j.id).pagerank_resumen["externo"]
    assert (ext["backlinks"], ext["nofollow"], ext["nofollow_casados"]) == (7, 1, 1)
    assert ext["entra_en"]["error"] == pytest.approx(8 / 16, abs=1e-3), "los 50 del nofollow no cuentan"
    fila = sesion.execute(select(Url.backlinks_externos, Url.backlinks_nofollow, Url.backlinks_spam_pct,
                                 Url.autoridad_externa).where(Url.id == nf.id)).one()
    assert tuple(fila) == (0, 1, 0.0, 0.0)
    (det,) = sesion.execute(select(Issue.details).where(Issue.job_id == j.id, Issue.url_id == nf.id,
                                                         Issue.issue_type == "backlinks_a_error")).one()
    assert (det["backlinks"], det["nofollow"]) == (1, 1)
