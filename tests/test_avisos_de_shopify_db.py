"""Avisos de Shopify (analysis/avisos_de_shopify.py), EJECUTADOS contra SQLite
(decision 74) con una tienda de juguete: se detecta por el robots.txt, y cada
patron sale una vez por host con sus cuentas y ejemplos.

Sin Shopify no sale nada, y una coleccion sin productos solo se afirma si otra
coleccion del censo si los pinta en el HTML (si no, la parrilla iria por
JavaScript y todas saldrian vacias).
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from analysis import avisos_de_shopify
from analysis.analyzer import SEOAnalyzer
from shared.models import Base, HtmlMeta, Issue, Job, Link, Resource, RobotsTxt, Url

ROBOTS_SHOPIFY = ("# Shopify storefront. Public product, collection, page, blog, policy, cart, and localized HTML is crawlable.\n"
                  "User-agent: *\nDisallow: /admin\nDisallow: /cart/\nDisallow: /checkouts/\n"
                  "Disallow: /collections/*sort_by*\nSitemap: https://x.com/sitemap.xml\n")


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(tipo, compilador, **kw):
    return "INTEGER"


def _montar(robots=ROBOTS_SHOPIFY):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Job.__table__, Url.__table__, Issue.__table__, Link.__table__,
                                             RobotsTxt.__table__, Resource.__table__, HtmlMeta.__table__])
    s = sessionmaker(bind=engine)()
    j = Job(id=uuid.uuid4(), name="t", status="analyzing", seeds=["https://x.com/"], config={},
            started_at=datetime(2026, 11, 3, 9, tzinfo=timezone.utc), adapters={})
    s.add(j)
    s.flush()
    if robots is not None:
        s.add(RobotsTxt(job_id=j.id, host="x.com", url="https://x.com/robots.txt", status_code=200, cuerpo=robots))
    return s, j


def _url(s, j, ruta, *, status=200, indexable=True, canonical=None, sitemap=True):
    u = Url(job_id=j.id, url=f"https://x.com{ruta}", url_hash=f"h:{ruta}", host="x.com", scheme="https",
            path=ruta.split("?")[0], is_internal=True, is_html=True, status_code=status, indexable=indexable,
            in_sitemap=sitemap, crawl_depth=1)
    s.add(u)
    s.flush()
    if canonical:
        s.add(HtmlMeta(url_id=u.id, canonical_href=canonical))
    return u


def _enlace(s, j, desde, a, veces=1, follow=True):
    s.add(Link(job_id=j.id, from_url_id=desde.id, to_url=f"https://x.com{a}", to_url_hash=f"h:{a}",
               is_internal=True, follow=follow, link_type="hyperlink", repeticiones=veces))


def _tienda(s, j):
    home = _url(s, j, "/")
    camisetas = _url(s, j, "/collections/camisetas")
    promo = _url(s, j, "/collections/black-friday-1")
    _url(s, j, "/collections/ver-todo-camisetas")
    _url(s, j, "/products/camiseta-azul", canonical="https://x.com/products/camiseta-azul")
    _url(s, j, "/products/camiseta-roja", canonical="https://x.com/collections/camisetas")
    _url(s, j, "/products/camiseta-roja.js.js", status=200)
    _enlace(s, j, camisetas, "/collections/camisetas/products/camiseta-azul", veces=2)
    _enlace(s, j, camisetas, "/collections/camisetas/products/camiseta-roja")
    _enlace(s, j, camisetas, "/collections/camisetas?page=1")
    _enlace(s, j, camisetas, "/collections/camisetas?page=2")
    _enlace(s, j, home, "/products/camiseta-azul?variant=4411")
    _enlace(s, j, home, "/products/camiseta-roja?pr_prod_strat=e5&pr_rec_id=1&pr_seq=uniform")
    _enlace(s, j, home, "/pages/contacto/")
    _enlace(s, j, home, "/collections/black-friday-1")
    _enlace(s, j, home, "/products/oculta?variant=1", follow=False)
    s.commit()
    return {"home": home, "camisetas": camisetas, "promo": promo}


def _issues(s, j, tipo):
    return s.execute(select(Issue.url_id, Issue.severity, Issue.details, Issue.group_key)
                     .where(Issue.job_id == j.id, Issue.issue_type == tipo)).all()


def _avisar(s, j):
    r = avisos_de_shopify.avisar_sin_tumbar(SEOAnalyzer(s, j.id))
    s.commit()
    return r


def test_cada_patron_sale_una_vez_por_host():
    s, j = _montar()
    u = _tienda(s, j)
    r = _avisar(s, j)
    assert r["productos"] == 2 and r["colecciones"] == 3 and r["colecciones_con_productos"] == 1

    (en_col,) = _issues(s, j, "shopify_enlace_a_producto_en_coleccion")
    assert en_col.severity == "warning" and en_col.url_id == u["home"].id, "anclado en la raiz del host"
    d = en_col.details
    assert (d["enlaces"], d["paginas_origen"], d["destinos"], d["en_el_censo"]) == (3, 1, 2, 0)
    assert d["ejemplos"][0]["desde"] == "https://x.com/collections/camisetas"

    (var,) = _issues(s, j, "shopify_enlace_a_variante")
    assert var.severity == "info" and var.details["enlaces"] == 1, "el nofollow no cuenta"
    (p1,) = _issues(s, j, "shopify_enlace_a_pagina_1")
    assert [e["url"] for e in p1.details["ejemplos"]] == ["https://x.com/collections/camisetas?page=1"]
    (apps,) = _issues(s, j, "shopify_parametros_de_apps")
    assert apps.severity == "warning"
    (barra,) = _issues(s, j, "shopify_enlace_con_barra_final")
    assert barra.details["ejemplos"][0]["url"] == "https://x.com/pages/contacto/"
    (tec,) = _issues(s, j, "shopify_url_tecnica")
    assert tec.details["ejemplos"] == ["https://x.com/products/camiseta-roja.js.js"]

    (vacia,) = _issues(s, j, "shopify_coleccion_vacia")
    assert vacia.details["ejemplos"] == ["https://x.com/collections/black-friday-1",
                                         "https://x.com/collections/ver-todo-camisetas"]
    (todo,) = _issues(s, j, "shopify_coleccion_ver_todo")
    assert todo.details["ejemplos"] == ["https://x.com/collections/ver-todo-camisetas"]
    (can,) = _issues(s, j, "shopify_canonical_producto_a_coleccion")
    assert can.severity == "error"
    assert can.details["ejemplos"] == [{"url": "https://x.com/products/camiseta-roja",
                                        "destino": "https://x.com/collections/camisetas"}]

    sh = s.get(Job, j.id).adapters["shopify"]
    assert sh["detectado"] and sh["evidencia"] == ["robots_txt"]
    assert sum(sh["analisis"]["emitidos"].values()) == 9


def test_sin_shopify_no_sale_nada():
    s, j = _montar(robots="User-agent: *\nDisallow: /wp-admin/\n")
    _tienda(s, j)
    assert _avisar(s, j) is None
    assert not s.execute(select(Issue.id).where(Issue.job_id == j.id)).first()
    assert "shopify" not in (s.get(Job, j.id).adapters or {})


def test_sin_robots_se_detecta_por_la_cdn():
    s, j = _montar(robots=None)
    u = _tienda(s, j)
    s.add(Resource(url_id=u["home"].id, resource_url="https://x.com/cdn/shop/t/3/assets/base.css",
                   resource_type="css"))
    s.commit()
    _avisar(s, j)
    assert s.get(Job, j.id).adapters["shopify"]["evidencia"] == ["cdn_shopify"]


def test_si_ninguna_coleccion_pinta_productos_no_se_afirma_vacia():
    """La parrilla por JavaScript: sin render, ninguna coleccion enlaza a
    productos y no se puede decir cuales estan vacias."""
    s, j = _montar()
    _url(s, j, "/")
    _url(s, j, "/collections/camisetas")
    _url(s, j, "/collections/pantalones")
    s.commit()
    r = _avisar(s, j)
    assert r["colecciones"] == 2 and r["colecciones_con_productos"] == 0
    assert not _issues(s, j, "shopify_coleccion_vacia")


@pytest.mark.parametrize("tipo", avisos_de_shopify.TIPOS)
def test_cada_tipo_tiene_ficha_nombre_y_ambito(tipo):
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    inc = open(os.path.join(raiz, "frontend", "incidencias.js"), encoding="utf-8").read()
    app = open(os.path.join(raiz, "frontend", "app.js"), encoding="utf-8").read()
    fichas = inc[inc.index("const ISSUE_INFO = {"):]
    fichas = fichas[:fichas.index("\n};")]
    nombres = inc[inc.index("const ISSUE_LABEL_EXTRA = {"):]
    nombres = nombres[:nombres.index("\n};")]
    assert f"'{tipo}': {{" in fichas, f"{tipo} sin ficha en ISSUE_INFO"
    assert re.search(rf"['\s]{tipo}'?\s*:", nombres), f"{tipo} sin nombre"
    linea = next(l for l in app.splitlines() if "key: 'a_shopify'" in l)
    assert f"'{tipo}'" in linea, f"{tipo} no esta en la pestana Shopify"
