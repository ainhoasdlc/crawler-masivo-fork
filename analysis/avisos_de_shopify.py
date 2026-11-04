"""Avisos de Shopify: lo que la plataforma hace de serie y casi nunca se mira.

Sin sonda ni API: Shopify no publica un indice como la REST API de WordPress
(decision 161) y lo que importa ya esta en el censo. Se detecta por el
robots.txt (el de Shopify lo dice en su cabecera, «Shopify storefront» o «we
use Shopify as our ecommerce platform», y lleva sus reglas de `/checkouts/` y
`/cart`) o, si no se leyo, por los recursos servidos desde `cdn.shopify.com`
o `/cdn/shop/`. Sin Shopify, nada.

Los patrones salen de auditorias reales de tiendas Shopify (P1 a P28 del
checklist de SEO tecnico): aqui solo los que se pueden afirmar con lo que el
rastreo ya guarda.

**Donde se cuelga cada aviso.** Antes todos iban agrupados por host y anclados
en la portada: en el Explorador solo salia la home, y en sus enlaces no estaba
ninguno de los que se avisaban (venian de posts del blog o de fichas). Ahora,
como los avisos de enlaces (decision 106):

- los de **enlaces**, en la pagina que los lleva: es donde hay que editar. Uno
  por pagina y tipo, con cuantos enlaces, sus destinos y a que URL deberian ir
  (`enlazar_a`). Si el MISMO destino lo enlazan `enlaces_plantilla_min_paginas`
  paginas o mas, es del tema (menu, pie, un bloque fijo): un solo aviso con
  ``alcance: plantilla`` en el destino si se rastreo o, si no, en la pagina de
  URL menor que lo enlaza (decision 88), y esas paginas no lo repiten;
- los del **censo** (colecciones vacias o «ver todo», canonical de ficha a
  coleccion, URLs tecnicas rastreadas), en cada URL afectada, no solo en la
  primera.

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
  o de la busqueda predictiva (`_pos`, `_sid`, `_ss`, `_atid`).
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

El resumen (avisos por tipo y paginas con alguno) va a
`jobs.adapters["shopify"]`.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

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
                      "_pos", "_sid", "_ss", "_atid", "cnweblinkclicked")
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


def _enlazar_a(tipo: str, url: str) -> str | None:
    """La URL a la que deberia ir ese enlace: la que Shopify da por canonica.
    None si no hay ninguna (una URL tecnica no se enlaza)."""
    try:
        p = urlsplit(url)
    except ValueError:
        return None
    ruta = p.path or "/"
    query = parse_qsl(p.query, keep_blank_values=True)
    if tipo == "shopify_enlace_a_producto_en_coleccion":
        ruta, query = re.sub(r"/collections/[^/]+(?=/products/)", "", ruta).rstrip("/"), []
    elif tipo == "shopify_enlace_a_variante":
        query = []
    elif tipo == "shopify_enlace_a_pagina_1":
        query = [(k, v) for k, v in query if (k, v) != ("page", "1")]
    elif tipo == "shopify_parametros_de_apps":
        query = [(k, v) for k, v in query if k.lower() not in PARAMETROS_DE_APPS]
    elif tipo == "shopify_enlace_con_barra_final":
        ruta = ruta.rstrip("/") or "/"
    else:
        return None
    return urlunsplit((p.scheme, p.netloc, ruta, urlencode(query), ""))


def _tipos_de_enlace(destino: str) -> list[str]:
    _, ruta, query = _partes(destino)
    nombres = {k.lower() for k, _ in query}
    tipos = []
    if PRODUCTO_EN_COLECCION.match(ruta):
        tipos.append("shopify_enlace_a_producto_en_coleccion")
    if "variant" in nombres and (PRODUCTO.match(ruta) or PRODUCTO_EN_COLECCION.match(ruta)):
        tipos.append("shopify_enlace_a_variante")
    if ("page", "1") in query and COLECCION.match(ruta):
        tipos.append("shopify_enlace_a_pagina_1")
    if nombres & set(PARAMETROS_DE_APPS):
        tipos.append("shopify_parametros_de_apps")
    if any(t in destino.lower() for t in TECNICAS):
        tipos.append("shopify_url_tecnica")
    if CON_BARRA.match(ruta):
        tipos.append("shopify_enlace_con_barra_final")
    return tipos


def _severidad(tipo: str) -> str:
    if tipo == "shopify_canonical_producto_a_coleccion":
        return "error"
    if tipo in ("shopify_enlace_a_producto_en_coleccion", "shopify_parametros_de_apps",
                "shopify_coleccion_vacia"):
        return "warning"
    return "info"


def avisar(az) -> dict[str, Any] | None:
    from shared.models import HtmlMeta, Job, Link, Url

    det = detectar(az)
    if not det["detectado"]:
        return None
    job = az.session.get(Job, az.job_id)
    umbral = int(getattr(az, "enlaces_plantilla_min_paginas", 10) or 10)

    # El censo: lo que hace falta de cada URL interna.
    censo: dict[int, Any] = {}
    por_url: dict[str, int] = {}
    for fila in az.session.execute(
            select(Url.id, Url.url, Url.status_code, Url.is_html, Url.indexable, Url.in_sitemap)
            .where(Url.job_id == az.job_id, Url.is_internal.is_(True))):
        censo[fila.id] = fila
        por_url[fila.url] = fila.id

    # Los enlaces internos que importan, en streaming y filtrados en SQL por el
    # job (decision 37). Se acumulan por destino (para saber si es de
    # plantilla) y por pagina de origen (donde va el aviso).
    por_destino: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"origenes": set(), "enlaces": 0})
    por_origen: dict[tuple[str, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    con_productos: set[int] = set()
    L = Link
    patrones = ["%/products/%", "%/collections/%", "%/pages/%", "%page=1%", "%.js.js%",
                "%customer!_authentication%", "%/web-pixels%", "%pr!_%", "%!_pos=%", "%!_sid=%",
                "%!_ss=%", "%!_atid=%"]
    consulta = (select(L.from_url_id, L.to_url, L.repeticiones)
                .where(L.job_id == az.job_id, L.is_internal.is_(True),
                       or_(L.follow.is_(None), L.follow.is_(True)),
                       or_(*[L.to_url.like(p, escape="!") for p in patrones],
                           func.lower(L.to_url).like("%cnweblinkclicked%"))))
    for origen, destino, veces in az.session.execute(
            consulta.execution_options(yield_per=5000)):
        if origen not in censo:
            continue
        if "/products/" in _partes(destino)[1]:
            con_productos.add(origen)
        veces = int(veces or 1)
        for tipo in _tipos_de_enlace(destino):
            if tipo == "shopify_url_tecnica" and any(t in censo[origen].url.lower() for t in TECNICAS):
                continue  # una URL tecnica que enlaza a otra: ya sale en el censo
            d = por_destino[(tipo, destino)]
            d["origenes"].add(origen)
            d["enlaces"] += veces
            por_origen[(tipo, origen)][destino] += veces

    resumen: dict[str, Any] = {"emitidos": defaultdict(int), "paginas": set()}

    def emitir(url_id, tipo, detalle, group_key=None):
        az._add_issue(url_id, tipo, _severidad(tipo), detalle, group_key=group_key)
        resumen["emitidos"][tipo] += 1
        resumen["paginas"].add(url_id)

    # De plantilla: el mismo destino desde `umbral` paginas o mas. Un aviso, en
    # el destino si se rastreo o en la pagina de URL menor que lo enlaza.
    de_plantilla = {k for k, d in por_destino.items() if len(d["origenes"]) >= umbral}
    for tipo, destino in sorted(de_plantilla):
        d = por_destino[(tipo, destino)]
        origenes = sorted(censo[o].url for o in d["origenes"])
        ancla = por_url.get(destino) or por_url[origenes[0]]
        emitir(ancla, tipo, {
            "alcance": "plantilla", "host": _partes(destino)[0], "destino": destino,
            "enlazar_a": _enlazar_a(tipo, destino), "paginas_que_enlazan": len(origenes),
            "enlaces": d["enlaces"], "paginas_ejemplo": origenes[:MUESTRA]},
            group_key=_clave(f"plantilla|{destino}"))

    # Por pagina de origen, con los destinos que no son de plantilla.
    for (tipo, origen), destinos in sorted(por_origen.items(),
                                           key=lambda x: (x[0][0], censo[x[0][1]].url)):
        propios = sorted(d for d in destinos if (tipo, d) not in de_plantilla)
        if not propios:
            continue
        emitir(origen, tipo, {
            "alcance": "pagina", "host": _partes(censo[origen].url)[0],
            "enlaces": sum(destinos[d] for d in propios), "destinos": len(propios),
            "ejemplos": [{"url": d, "enlazar_a": _enlazar_a(tipo, d)} for d in propios[:MUESTRA]]})

    # URLs tecnicas que el rastreo SI pidio: el aviso en cada una.
    for fila in sorted(censo.values(), key=lambda f: f.url):
        if any(t in fila.url.lower() for t in TECNICAS):
            emitir(fila.id, "shopify_url_tecnica", {"alcance": "url", "host": _partes(fila.url)[0]},
                   group_key=_clave("censo"))

    # Colecciones: vacias y «ver todo», en cada una.
    colecciones = [(f, COLECCION.match(_partes(f.url)[1])) for f in censo.values()
                   if f.status_code == 200 and f.is_html and not _partes(f.url)[2]]
    colecciones = sorted(((f, m.group(1)) for f, m in colecciones if m), key=lambda x: x[0].url)
    resumen["colecciones"] = len(colecciones)
    resumen["colecciones_con_productos"] = sum(1 for f, _ in colecciones if f.id in con_productos)
    for f, handle in colecciones:
        if f.id not in con_productos and resumen["colecciones_con_productos"]:
            emitir(f.id, "shopify_coleccion_vacia", {"alcance": "url", "host": _partes(f.url)[0]})
        if f.indexable and VER_TODO.match(handle.lower()):
            emitir(f.id, "shopify_coleccion_ver_todo", {"alcance": "url", "host": _partes(f.url)[0]})

    # Fichas cuyo canonical apunta a una coleccion (P26), en cada una.
    productos = [f for f in censo.values() if f.status_code == 200 and f.is_html
                 and PRODUCTO.match(_partes(f.url)[1])]
    resumen["productos"] = len(productos)
    malas = []
    ids = [f.id for f in productos]
    for i in range(0, len(ids), 2000):
        for uid, canonical in az.session.execute(
                select(HtmlMeta.url_id, HtmlMeta.canonical_href)
                .where(HtmlMeta.url_id.in_(ids[i:i + 2000]), HtmlMeta.canonical_href.isnot(None))):
            if COLECCION.match(_partes(canonical)[1]):
                malas.append((censo[uid], canonical))
    for f, canonical in sorted(malas, key=lambda x: x[0].url):
        emitir(f.id, "shopify_canonical_producto_a_coleccion",
               {"alcance": "url", "host": _partes(f.url)[0], "canonical": canonical})

    az._flush_issues()
    resumen["emitidos"] = dict(resumen["emitidos"])
    resumen["paginas"] = len(resumen["paginas"])
    if job is not None:
        adapters = dict(getattr(job, "adapters", None) or {})
        adapters[ADAPTADOR] = {**det, "analisis": resumen}
        job.adapters = adapters
    logger.info("Shopify: %s", resumen)
    return resumen
