"""Avisos de Shopify: lo que la plataforma hace de serie y casi nunca se mira.

Sin sonda ni API: Shopify no publica un indice como la REST API de WordPress
(decision 161) y lo que importa ya esta en el censo. Se detecta por el
robots.txt (el de Shopify lo dice en su cabecera, «Shopify storefront» o «we
use Shopify as our ecommerce platform», y lleva sus reglas de `/checkouts/` y
`/cart`) o, si no se leyo, por los recursos servidos desde `cdn.shopify.com`
o `/cdn/shop/`. Sin Shopify, nada.

Los patrones salen de auditorias reales de tiendas Shopify (P1 a P28 del
checklist de SEO tecnico): aqui solo los que se pueden afirmar con lo que el
rastreo ya guarda. Todos **agrupados por host** (decisiones 36, 53, 64 y 73):
son del tema o de la plataforma, no de una pagina suelta.

- ``shopify_enlace_a_producto_en_coleccion`` (warning, P4): enlaces internos a
  `/collections/<c>/products/<p>`. Shopify canonicaliza esa URL a
  `/products/<p>`, pero el listado enlaza a la otra: el enlazado va a una URL
  que no es la canonica. Lo hace `{{ product.url | within: collection }}` en
  la plantilla de coleccion.
- ``shopify_enlace_a_variante`` (info, P5): enlaces internos a `?variant=`.
- ``shopify_enlace_a_pagina_1`` (info, P5): enlaces a `?page=1`, que es la
  coleccion limpia con otra URL. Las paginas 2 y siguientes no se tocan.
- ``shopify_parametros_de_apps`` (warning, P14): enlaces internos con los
  parametros del carrusel de recomendaciones (`pr_prod_strat`, `pr_rec_id`…)
  o de la busqueda predictiva (`_pos`, `_sid`, `_ss`).
- ``shopify_url_tecnica`` (info, P15): URLs tecnicas en el censo o en los
  enlaces: `.js.js`, `customer_authentication`, `/web-pixels`.
- ``shopify_coleccion_vacia`` (warning, P16): colecciones que responden 200 y
  no enlazan a ningun producto. Solo si alguna otra coleccion del censo SI
  enlaza a productos: asi se sabe que el tema pinta la parrilla en el HTML y
  no por JavaScript (sin eso, todas saldrian vacias).
- ``shopify_canonical_producto_a_coleccion`` (error, P26): fichas de producto
  cuyo canonical apunta a una coleccion.
- ``shopify_coleccion_ver_todo`` (info, P27): colecciones «ver todo» o «all»
  indexables, que suelen duplicar la coleccion principal.
- ``shopify_enlace_con_barra_final`` (info, P1): enlaces internos a
  `/products/x/`, `/collections/x/` o `/pages/x/` con barra final.

Se anclan como los avisos de sitemaps (decision 126) y el resumen va a
`jobs.adapters["shopify"]`.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from sqlalchemy import func, or_, select

logger = logging.getLogger(__name__)

ADAPTADOR = "shopify"
TIPOS = ("shopify_enlace_a_producto_en_coleccion", "shopify_enlace_a_variante",
         "shopify_enlace_a_pagina_1", "shopify_parametros_de_apps", "shopify_url_tecnica",
         "shopify_coleccion_vacia", "shopify_canonical_producto_a_coleccion",
         "shopify_coleccion_ver_todo", "shopify_enlace_con_barra_final")
MUESTRA = 10

# Prefijo de idioma o mercado de Shopify Markets: /en, /es-it, /fr-fr.
# Los handles de Shopify son minusculas, cifras y guiones: sin puntos (un
# `.js.js` o `.json` no es una ficha).
_IDIOMA = r"(?:/[a-z]{2}(?:-[a-z]{2})?)?"
PRODUCTO = re.compile(rf"^{_IDIOMA}/products/[^/.]+/?$")
PRODUCTO_EN_COLECCION = re.compile(rf"^{_IDIOMA}/collections/[^/.]+/products/[^/.]+/?$")
COLECCION = re.compile(rf"^{_IDIOMA}/collections/([^/.]+)/?$")
CON_BARRA = re.compile(rf"^{_IDIOMA}/(?:products|collections|pages)/[^/]+(?:/products/[^/]+)?/$")
VER_TODO = re.compile(r"^(?:all|ver-todo.*|.*-ver-todo|ver-todos.*|todos-los-.*|view-all.*|.*-view-all|shop-all.*)$")
PARAMETROS_DE_APPS = ("pr_prod_strat", "pr_rec_id", "pr_rec_pid", "pr_ref_pid", "pr_seq",
                      "_pos", "_sid", "_ss", "cnweblinkclicked")
TECNICAS = (".js.js", "customer_authentication", "/web-pixels")


def _clave(valor: str | None) -> str | None:
    from analysis.analyzer import _clave_de_grupo

    return _clave_de_grupo(valor)


def _partes(url: str) -> tuple[str, str, list[tuple[str, str]]]:
    try:
        p = urlsplit(url or "")
    except ValueError:
        return "", "", []
    return ((p.hostname or "").lower(), unquote(p.path or "/"),
            parse_qsl(p.query, keep_blank_values=True))


def avisar_sin_tumbar(az) -> dict[str, Any] | None:
    """`avisar` en un savepoint y con el try cubriendolo entero (decision 74)."""
    pendientes = list(az._pending_issues)
    try:
        az._flush_issues()
        pendientes = []
        with az.session.begin_nested():
            return avisar(az)
    except Exception:
        az._pending_issues = pendientes
        logger.exception("Shopify del job %s: fallo; el analisis sigue", az.job_id)
        return None


def es_robots_de_shopify(cuerpo: str | None) -> bool:
    c = (cuerpo or "").lower()
    return "shopify" in c and ("/checkouts/" in c or "/cart" in c)


def detectar(az) -> dict[str, Any]:
    """Por el robots.txt y, si no, por los recursos de la CDN de Shopify."""
    from shared.models import Resource, RobotsTxt, Url

    evidencia: list[str] = []
    try:
        with az.session.begin_nested():
            for (cuerpo,) in az.session.execute(
                    select(RobotsTxt.cuerpo).where(RobotsTxt.job_id == az.job_id)):
                if es_robots_de_shopify(cuerpo):
                    evidencia.append("robots_txt")
                    break
    except Exception:  # noqa: BLE001 -- base sin la tabla de robots.txt
        pass
    if not evidencia:
        hit = az.session.execute(
            select(Resource.id).join(Url, Url.id == Resource.url_id)
            .where(Url.job_id == az.job_id,
                   or_(Resource.resource_url.like("%cdn.shopify.com/%"),
                       Resource.resource_url.like("%/cdn/shop/%")))
            .limit(1)).first()
        if hit:
            evidencia.append("cdn_shopify")
    return {"detectado": bool(evidencia), "evidencia": evidencia}


def avisar(az) -> dict[str, Any] | None:
    from analysis.avisos_de_sitemaps import _Anclas
    from shared.models import HtmlMeta, Job, Link, Url

    det = detectar(az)
    if not det["detectado"]:
        return None
    job = az.session.get(Job, az.job_id)

    # El censo: lo que hace falta de cada URL interna.
    censo: dict[int, Any] = {}
    por_url: dict[str, int] = {}
    for fila in az.session.execute(
            select(Url.id, Url.url, Url.status_code, Url.is_html, Url.indexable, Url.in_sitemap)
            .where(Url.job_id == az.job_id, Url.is_internal.is_(True))):
        censo[fila.id] = fila
        por_url[fila.url] = fila.id

    # Los enlaces internos que importan, en streaming y filtrados en SQL por el
    # job (decision 37): cuentas y una muestra, nunca la lista entera.
    grupos: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"enlaces": 0, "origenes": set(), "destinos": set(), "ejemplos": []})
    con_productos: set[int] = set()
    L = Link
    patrones = ["%/products/%", "%/collections/%", "%/pages/%", "%page=1%", "%.js.js%",
                "%customer!_authentication%", "%/web-pixels%", "%pr!_%", "%!_pos=%", "%!_sid=%",
                "%!_ss=%"]
    consulta = (select(L.from_url_id, L.to_url, L.repeticiones)
                .where(L.job_id == az.job_id, L.is_internal.is_(True),
                       or_(L.follow.is_(None), L.follow.is_(True)),
                       or_(*[L.to_url.like(p, escape="!") for p in patrones],
                           func.lower(L.to_url).like("%cnweblinkclicked%"))))

    def anotar(tipo, host, origen, destino, veces):
        g = grupos[(tipo, host)]
        g["enlaces"] += veces
        g["origenes"].add(origen)
        if destino not in g["destinos"] and len(g["ejemplos"]) < MUESTRA:
            g["ejemplos"].append({"url": destino, "desde": origen})
        g["destinos"].add(destino)

    for origen, destino, veces in az.session.execute(
            consulta.execution_options(yield_per=5000)):
        host, ruta, query = _partes(destino)
        veces = int(veces or 1)
        nombres = {k.lower() for k, _ in query}
        if "/products/" in ruta:
            con_productos.add(origen)
        if PRODUCTO_EN_COLECCION.match(ruta):
            anotar("shopify_enlace_a_producto_en_coleccion", host, origen, destino, veces)
        if "variant" in nombres and (PRODUCTO.match(ruta) or PRODUCTO_EN_COLECCION.match(ruta)):
            anotar("shopify_enlace_a_variante", host, origen, destino, veces)
        if ("page", "1") in query and COLECCION.match(ruta):
            anotar("shopify_enlace_a_pagina_1", host, origen, destino, veces)
        if nombres & set(PARAMETROS_DE_APPS):
            anotar("shopify_parametros_de_apps", host, origen, destino, veces)
        if any(t in destino.lower() for t in TECNICAS):
            anotar("shopify_url_tecnica", host, origen, destino, veces)
        if CON_BARRA.match(ruta):
            anotar("shopify_enlace_con_barra_final", host, origen, destino, veces)

    anclas = _Anclas(az)
    resumen: dict[str, Any] = {"emitidos": defaultdict(int)}
    ids_origen = {o for g in grupos.values() for e in g["ejemplos"] for o in [e["desde"]]}
    url_de = {i: censo[i].url for i in ids_origen if i in censo}

    for (tipo, host), g in sorted(grupos.items()):
        ancla = anclas.de_fichero(f"https://{host}/")
        if ancla is None:
            continue
        severidad = "warning" if tipo in ("shopify_enlace_a_producto_en_coleccion",
                                          "shopify_parametros_de_apps") else "info"
        detalle = {"host": host, "enlaces": g["enlaces"], "paginas_origen": len(g["origenes"]),
                   "destinos": len(g["destinos"]), "paginas_afectadas": len(g["destinos"]),
                   "ejemplos": [{"url": e["url"], "desde": url_de.get(e["desde"])} for e in g["ejemplos"]]}
        if tipo == "shopify_enlace_a_producto_en_coleccion":
            detalle["en_el_censo"] = sum(1 for d in g["destinos"] if d in por_url)
        az._add_issue(ancla, tipo, severidad, detalle, group_key=_clave(f"{host}|{tipo}"))
        resumen["emitidos"][tipo] += 1

    # URLs tecnicas que el rastreo SI pidio (ademas de las enlazadas).
    tecnicas_censo: dict[str, list[str]] = defaultdict(list)
    for fila in censo.values():
        if any(t in fila.url.lower() for t in TECNICAS):
            tecnicas_censo[_partes(fila.url)[0]].append(fila.url)
    for host, urls in sorted(tecnicas_censo.items()):
        if ("shopify_url_tecnica", host) in grupos:
            continue
        ancla = anclas.de_fichero(f"https://{host}/")
        if ancla is None:
            continue
        az._add_issue(ancla, "shopify_url_tecnica", "info", {
            "host": host, "paginas_afectadas": len(urls), "en_el_censo": len(urls),
            "ejemplos": sorted(urls)[:MUESTRA]}, group_key=_clave(f"{host}|shopify_url_tecnica"))
        resumen["emitidos"]["shopify_url_tecnica"] += 1

    # Colecciones: vacias y «ver todo».
    colecciones = [(f, COLECCION.match(_partes(f.url)[1])) for f in censo.values()
                   if f.status_code == 200 and f.is_html and not _partes(f.url)[2]]
    colecciones = [(f, m.group(1)) for f, m in colecciones if m]
    resumen["colecciones"] = len(colecciones)
    resumen["colecciones_con_productos"] = sum(1 for f, _ in colecciones if f.id in con_productos)
    vacias: dict[str, list] = defaultdict(list)
    ver_todo: dict[str, list] = defaultdict(list)
    for f, handle in colecciones:
        host = _partes(f.url)[0]
        if f.id not in con_productos and resumen["colecciones_con_productos"]:
            vacias[host].append(f)
        if f.indexable and VER_TODO.match(handle.lower()):
            ver_todo[host].append(f)
    for tipo, porhost, severidad in (("shopify_coleccion_vacia", vacias, "warning"),
                                     ("shopify_coleccion_ver_todo", ver_todo, "info")):
        for host, filas in sorted(porhost.items()):
            filas = sorted(filas, key=lambda f: f.url)
            az._add_issue(filas[0].id, tipo, severidad, {
                "host": host, "paginas_afectadas": len(filas),
                "indexables": sum(1 for f in filas if f.indexable),
                "en_sitemap": sum(1 for f in filas if f.in_sitemap),
                "ejemplos": [f.url for f in filas[:MUESTRA]]}, group_key=_clave(f"{host}|{tipo}"))
            resumen["emitidos"][tipo] += 1

    # Fichas cuyo canonical apunta a una coleccion (P26).
    productos = [f for f in censo.values() if f.status_code == 200 and f.is_html
                 and PRODUCTO.match(_partes(f.url)[1])]
    resumen["productos"] = len(productos)
    malas: dict[str, list] = defaultdict(list)
    ids = [f.id for f in productos]
    for i in range(0, len(ids), 2000):
        for uid, canonical in az.session.execute(
                select(HtmlMeta.url_id, HtmlMeta.canonical_href)
                .where(HtmlMeta.url_id.in_(ids[i:i + 2000]), HtmlMeta.canonical_href.isnot(None))):
            ruta = _partes(canonical)[1]
            if COLECCION.match(ruta):
                malas[_partes(censo[uid].url)[0]].append((censo[uid], canonical))
    for host, filas in sorted(malas.items()):
        filas.sort(key=lambda x: x[0].url)
        az._add_issue(filas[0][0].id, "shopify_canonical_producto_a_coleccion", "error", {
            "host": host, "paginas_afectadas": len(filas),
            "ejemplos": [{"url": f.url, "destino": c} for f, c in filas[:MUESTRA]]},
            group_key=_clave(f"{host}|shopify_canonical_producto_a_coleccion"))
        resumen["emitidos"]["shopify_canonical_producto_a_coleccion"] += 1

    az._flush_issues()
    resumen["emitidos"] = dict(resumen["emitidos"])
    if job is not None:
        adapters = dict(getattr(job, "adapters", None) or {})
        adapters[ADAPTADOR] = {**det, "analisis": resumen}
        job.adapters = adapters
    logger.info("Shopify: %s", resumen)
    return resumen
