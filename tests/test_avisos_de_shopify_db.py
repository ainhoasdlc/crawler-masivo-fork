"""Avisos de Shopify (analysis/avisos_de_shopify.py), EJECUTADOS contra SQLite
(decision 74) con una tienda de juguete: se detecta por el robots.txt; los
avisos de enlaces van en la pagina que los lleva (o una vez, si son de
plantilla) y los del censo en cada URL afectada.

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


def _id(s, j, ruta):
    return s.execute(select(Url.id).where(Url.job_id == j.id, Url.url == f"https://x.com{ruta}")).scalar()


def test_los_de_enlaces_van_en_la_pagina_que_los_lleva():
    """En la portada solo salia el aviso agrupado y en sus enlaces no estaba
    ninguno: ahora cada pagina lleva el suyo, con sus destinos y a donde
    deberian ir."""
    s, j = _montar()
    u = _tienda(s, j)
    r = _avisar(s, j)
    assert r["productos"] == 2 and r["colecciones"] == 3 and r["colecciones_con_productos"] == 1

    (en_col,) = _issues(s, j, "shopify_enlace_a_producto_en_coleccion")
    assert en_col.severity == "warning" and en_col.url_id == u["camisetas"].id, "en la coleccion que enlaza"
    d = en_col.details
    assert (d["alcance"], d["enlaces"], d["destinos"]) == ("pagina", 3, 2)
    assert d["ejemplos"] == [
        {"url": "https://x.com/collections/camisetas/products/camiseta-azul",
         "enlazar_a": "https://x.com/products/camiseta-azul"},
        {"url": "https://x.com/collections/camisetas/products/camiseta-roja",
         "enlazar_a": "https://x.com/products/camiseta-roja"}]

    (var,) = _issues(s, j, "shopify_enlace_a_variante")
    assert var.url_id == u["home"].id and var.severity == "info"
    assert var.details["enlaces"] == 1, "el nofollow no cuenta"
    assert var.details["ejemplos"][0]["enlazar_a"] == "https://x.com/products/camiseta-azul"
    (p1,) = _issues(s, j, "shopify_enlace_a_pagina_1")
    assert p1.url_id == u["camisetas"].id
    assert p1.details["ejemplos"] == [{"url": "https://x.com/collections/camisetas?page=1",
                                       "enlazar_a": "https://x.com/collections/camisetas"}]
    (apps,) = _issues(s, j, "shopify_parametros_de_apps")
    assert apps.severity == "warning" and apps.url_id == u["home"].id
    assert apps.details["ejemplos"][0]["enlazar_a"] == "https://x.com/products/camiseta-roja"
    (barra,) = _issues(s, j, "shopify_enlace_con_barra_final")
    assert barra.details["ejemplos"] == [{"url": "https://x.com/pages/contacto/",
                                          "enlazar_a": "https://x.com/pages/contacto"}]


def test_los_del_censo_van_en_cada_url_afectada():
    s, j = _montar()
    _tienda(s, j)
    _avisar(s, j)
    (tec,) = _issues(s, j, "shopify_url_tecnica")
    assert tec.url_id == _id(s, j, "/products/camiseta-roja.js.js")
    vacias = _issues(s, j, "shopify_coleccion_vacia")
    assert sorted(v.url_id for v in vacias) == sorted(
        [_id(s, j, "/collections/black-friday-1"), _id(s, j, "/collections/ver-todo-camisetas")])
    (todo,) = _issues(s, j, "shopify_coleccion_ver_todo")
    assert todo.url_id == _id(s, j, "/collections/ver-todo-camisetas")
    (can,) = _issues(s, j, "shopify_canonical_producto_a_coleccion")
    assert can.severity == "error" and can.url_id == _id(s, j, "/products/camiseta-roja")
    assert can.details["canonical"] == "https://x.com/collections/camisetas"

    sh = s.get(Job, j.id).adapters["shopify"]
    assert sh["detectado"] and sh["evidencia"] == ["robots_txt"]
    assert sum(sh["analisis"]["emitidos"].values()) == 10
    assert sh["analisis"]["paginas"] == 6


def test_el_mismo_destino_desde_muchas_paginas_es_de_plantilla():
    """Un bloque fijo del tema (10 paginas o mas al mismo destino) se avisa una
    vez y no en cada pagina; lo que cada pagina enlaza aparte, si."""
    s, j = _montar()
    paginas = [_url(s, j, f"/blogs/noticias/post-{n:02d}") for n in range(10)]
    for p in paginas:
        _enlace(s, j, p, "/collections/camisetas/products/camiseta-azul")
    _enlace(s, j, paginas[3], "/collections/camisetas/products/camiseta-roja")
    s.commit()
    _avisar(s, j)
    avisos = _issues(s, j, "shopify_enlace_a_producto_en_coleccion")
    plantilla = [a for a in avisos if a.details["alcance"] == "plantilla"]
    pagina = [a for a in avisos if a.details["alcance"] == "pagina"]
    assert len(plantilla) == 1 and len(pagina) == 1
    d = plantilla[0].details
    assert plantilla[0].url_id == paginas[0].id, "sin rastrear, en la pagina de URL menor que lo enlaza"
    assert (d["paginas_que_enlazan"], d["enlazar_a"]) == (10, "https://x.com/products/camiseta-azul")
    assert pagina[0].url_id == paginas[3].id
    assert [e["url"] for e in pagina[0].details["ejemplos"]] == [
        "https://x.com/collections/camisetas/products/camiseta-roja"]


ROBOTS_CON_RECOMENDACIONES = ROBOTS_SHOPIFY.replace(
    "Disallow: /checkouts/\n",
    "Disallow: /checkouts/\nDisallow: /recommendations/products\nDisallow: /*/recommendations/products\n")


def _recomendado(handle, rec, ref, prefijo=""):
    """Enlace del carrusel como lo pinta Shopify: `pr_rec_pid` es el producto
    enlazado y `pr_ref_pid` el de la ficha donde se pinto el carrusel."""
    return (f"{prefijo}/products/{handle}?pr_prod_strat=e5_desc&pr_rec_id=a1&pr_rec_pid={rec}"
            f"&pr_ref_pid={ref}&pr_seq=uniform")


def _fichas_con_carrusel(s, j, prefijo=""):
    """Dos fichas que se recomiendan una a otra (ids 111 y 222) y un post que
    pega a mano un enlace copiado del carrusel de la ficha 111."""
    azul = _url(s, j, f"{prefijo}/products/camiseta-azul")
    roja = _url(s, j, f"{prefijo}/products/camiseta-roja")
    post = _url(s, j, "/blogs/noticias/rebajas")
    _enlace(s, j, azul, _recomendado("camiseta-roja", 222, 111, prefijo), veces=2)
    _enlace(s, j, roja, _recomendado("camiseta-azul", 111, 222, prefijo), veces=2)
    _enlace(s, j, post, _recomendado("camiseta-roja", 222, 111))
    s.commit()
    return {"azul": azul, "roja": roja, "post": post}


def _apps(s, j):
    return {a.url_id: a for a in _issues(s, j, "shopify_parametros_de_apps")}


def test_los_del_carrusel_bloqueado_para_googlebot_bajan_a_info_y_dicen_la_regla():
    s, j = _montar(robots=ROBOTS_CON_RECOMENDACIONES)
    u = _fichas_con_carrusel(s, j)
    r = _avisar(s, j)
    apps = _apps(s, j)
    a = apps[u["azul"].id]
    assert a.severity == "info"
    assert {k: a.details[k] for k in ("del_carrusel", "carga_desde", "solo_con_javascript",
                                      "bloqueada_para_googlebot", "regla_robots")} == {
        "del_carrusel": 2, "carga_desde": "/recommendations/products", "solo_con_javascript": True,
        "bloqueada_para_googlebot": True, "regla_robots": "Disallow: /recommendations/products"}
    assert apps[u["roja"].id].severity == "info"
    assert r["carrusel_solo_js"] == 2


def test_un_enlace_del_carrusel_pegado_en_un_post_sigue_siendo_aviso():
    """Su `pr_ref_pid` (111) no es el id de la pagina que lo lleva: esta en el
    HTML del post y Googlebot si lo ve."""
    s, j = _montar(robots=ROBOTS_CON_RECOMENDACIONES)
    u = _fichas_con_carrusel(s, j)
    _avisar(s, j)
    p = _apps(s, j)[u["post"].id]
    assert p.severity == "warning"
    assert "del_carrusel" not in p.details and "bloqueada_para_googlebot" not in p.details


def test_con_prefijo_de_idioma_se_evalua_su_ruta():
    s, j = _montar(robots=ROBOTS_CON_RECOMENDACIONES)
    u = _fichas_con_carrusel(s, j, prefijo="/en-eu")
    _avisar(s, j)
    d = _apps(s, j)[u["azul"].id].details
    assert d["carga_desde"] == "/en-eu/recommendations/products"
    assert d["regla_robots"] == "Disallow: /*/recommendations/products"


def test_si_el_robots_deja_pedir_el_carrusel_sigue_siendo_aviso():
    s, j = _montar()
    u = _fichas_con_carrusel(s, j)
    _avisar(s, j)
    a = _apps(s, j)[u["azul"].id]
    assert a.severity == "warning"
    assert a.details["solo_con_javascript"] is True and a.details["bloqueada_para_googlebot"] is False
    assert "regla_robots" not in a.details


def test_sin_el_id_de_la_ficha_no_se_afirma_que_sea_del_carrusel():
    """Nadie enlaza a la ficha con `pr_rec_pid`: no se sabe su id."""
    s, j = _montar(robots=ROBOTS_CON_RECOMENDACIONES)
    azul = _url(s, j, "/products/camiseta-azul")
    _url(s, j, "/products/camiseta-roja")
    _enlace(s, j, azul, _recomendado("camiseta-roja", 222, 111))
    s.commit()
    _avisar(s, j)
    a = _apps(s, j)[azul.id]
    assert a.severity == "warning" and "del_carrusel" not in a.details


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
