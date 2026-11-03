"""Result endpoints: urls, issues, links, stats, CSV export for a job."""

from __future__ import annotations

import csv
import io
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, joinedload, subqueryload

from api.backup import stream_backup_zip

from shared import archivo_enlaces
from shared.database import get_session
from shared.models import (
    Job, Url, Issue, Link, HtmlMeta, PageContent,
    Heading, Hreflang, StructuredData, Resource, SecurityHeaders, CustomExtraction,
)

from api.schemas import (
    TopeDeNota,
    CategoryInsight,
    HeadingResponse,
    HreflangResponse,
    HostCount,
    InsightsResponse,
    IssueResponse,
    IssueTypeCount,
    JobStats,
    DestinosResponse,
    EnlacesResponse,
    LinkResponse,
    PaginatedResponse,
    Recommendation,
    ResourceResponse,
    ResourceTypeCount,
    SecurityHeadersResponse,
    StatusGroupCount,
    StructuredDataResponse,
    UrlDetailResponse,
    UrlResponse,
)

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["results"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


def _get_job_or_404(job_id: uuid.UUID, db: Session) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _paginate(
    items: list[Any],
    total: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
    }


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/urls
# ---------------------------------------------------------------------------
SORT_COLUMNS = {
    "url": Url.url,
    "status_code": Url.status_code,
    "word_count": Url.word_count,
    "content_word_count": Url.content_word_count,
    "response_time_ms": Url.response_time_ms,
    "ttfb_ms": Url.ttfb_ms,
    "content_length": Url.content_length,
    "transfer_size": Url.transfer_size,
    "crawl_depth": Url.crawl_depth,
    "click_depth": Url.click_depth,
    # Search Console, decision 142
    "gsc_clics": Url.gsc_clics,
    "gsc_impresiones": Url.gsc_impresiones,
    "gsc_posicion": Url.gsc_posicion,
    "inlinks_count": Url.inlinks_count,
    "outlinks_count": Url.outlinks_count,
    "external_outlinks_count": Url.external_outlinks_count,
    "unique_inlinks_count": Url.unique_inlinks_count,
    "pagerank": Url.pagerank,
    "pagerank_score": Url.pagerank_score,
    "pagerank_raw": Url.pagerank_raw,
    "pagerank_externo_score": Url.pagerank_externo_score,
    "backlinks_externos": Url.backlinks_externos,
    "backlinks_nofollow": Url.backlinks_nofollow,
    "backlinks_spam": Url.backlinks_spam,
    "backlinks_spam_pct": Url.backlinks_spam_pct,
    "autoridad_externa": Url.autoridad_externa,
    "googlebot_visitas": Url.googlebot_visitas,
    "near_duplicate_count": Url.near_duplicate_count,
    "url_length": Url.url_length,
    "folder_depth": Url.folder_depth,
    "text_ratio": Url.text_ratio,
    "host": Url.host,
    "segmento": Url.segmento,
    "last_crawled_at": Url.last_crawled_at,
    "title": HtmlMeta.title,
    "title_len": HtmlMeta.title_len,
    "meta_description": HtmlMeta.meta_description,
    "meta_description_len": HtmlMeta.meta_description_len,
    # Se ofrecian en la interfaz como ordenables y el servidor los ignoraba
    # (docs/INVESTIGACION_EXPLORADOR.md): el clic no hacia nada.
    "closest_similarity": Url.closest_similarity,
    "title_pixel_width": HtmlMeta.title_pixel_width,
    "meta_description_pixel_width": HtmlMeta.meta_description_pixel_width,
}
# Ordenar por una de estas exige unir con html_meta.
_SORT_META = {"title", "title_len", "meta_description", "meta_description_len",
              "title_pixel_width", "meta_description_pixel_width"}

# Numeric range filters mapped to (model_column, requires_html_meta_join)
_RANGE_FILTERS: dict[str, tuple[Any, bool]] = {
    "pagerank": (Url.pagerank, False),
    "pagerank_score": (Url.pagerank_score, False),
    "pagerank_raw": (Url.pagerank_raw, False),
    "pagerank_externo_score": (Url.pagerank_externo_score, False),
    "backlinks_externos": (Url.backlinks_externos, False),
    "backlinks_nofollow": (Url.backlinks_nofollow, False),
    "backlinks_spam": (Url.backlinks_spam, False),
    "backlinks_spam_pct": (Url.backlinks_spam_pct, False),
    "googlebot_visitas": (Url.googlebot_visitas, False),
    "near_duplicate_count": (Url.near_duplicate_count, False),
    "closest_similarity": (Url.closest_similarity, False),
    "content_length": (Url.content_length, False),
    "transfer_size": (Url.transfer_size, False),
    "word_count": (Url.word_count, False),
    "content_word_count": (Url.content_word_count, False),
    "response_time_ms": (Url.response_time_ms, False),
    "ttfb_ms": (Url.ttfb_ms, False),
    "inlinks_count": (Url.inlinks_count, False),
    "outlinks_count": (Url.outlinks_count, False),
    "external_outlinks_count": (Url.external_outlinks_count, False),
    "unique_inlinks_count": (Url.unique_inlinks_count, False),
    "url_length": (Url.url_length, False),
    "folder_depth": (Url.folder_depth, False),
    "text_ratio": (Url.text_ratio, False),
    "crawl_depth": (Url.crawl_depth, False),
    "click_depth": (Url.click_depth, False),
    "gsc_clics": (Url.gsc_clics, False),
    "gsc_impresiones": (Url.gsc_impresiones, False),
    "gsc_posicion": (Url.gsc_posicion, False),
    "status_code": (Url.status_code, False),
    "redirect_type": (Url.redirect_type, False),
    "title_len": (HtmlMeta.title_len, True),
    "meta_description_len": (HtmlMeta.meta_description_len, True),
    # Google corta por pixeles, no por caracteres (decision 54).
    "title_pixel_width": (HtmlMeta.title_pixel_width, True),
    "meta_description_pixel_width": (HtmlMeta.meta_description_pixel_width, True),
}

# String "contains" filters mapped to (model_column, requires_html_meta_join).
# Each entry exposes a `<key>` query parameter (e.g. ?host_contains=…).
_STRING_CONTAINS_FILTERS: dict[str, tuple[Any, bool]] = {
    "host_contains":                 (Url.host,                False),
    "content_type_contains":         (Url.content_type,        False),
    "status_text_contains":          (Url.status_text,         False),
    "redirect_url_contains":         (Url.redirect_url,        False),
    "indexability_status_contains":  (Url.indexability_status, False),
    "http_version_contains":         (Url.http_version,        False),
    "content_encoding_contains":     (Url.content_encoding,    False),
    "last_modified_contains":        (Url.last_modified,       False),
    "title_contains":                (HtmlMeta.title,                True),
    "description_contains":          (HtmlMeta.meta_description,     True),
    "canonical_contains":            (HtmlMeta.canonical_href,       True),
    "meta_robots_contains":          (HtmlMeta.meta_robots,          True),
    "og_title_contains":             (HtmlMeta.og_title,             True),
    "og_image_contains":             (HtmlMeta.og_image,             True),
    "og_type_contains":              (HtmlMeta.og_type,              True),
    "og_url_contains":               (HtmlMeta.og_url,               True),
    "twitter_card_contains":         (HtmlMeta.twitter_card,         True),
    # La URL tiene su propio filtro: compartia `search` con el buscador de
    # arriba y uno pisaba al otro sin avisar.
    "url_contains":                  (Url.url,                       False),
    "x_robots_tag_contains":         (HtmlMeta.x_robots_tag,         True),
    "canonical_header_contains":     (HtmlMeta.canonical_header,     True),
    "meta_refresh_contains":         (HtmlMeta.meta_refresh,         True),
    "redireccion_js_contains":       (HtmlMeta.redireccion_js,       True),
    "viewport_contains":             (HtmlMeta.viewport,             True),
    "html_lang_contains":            (HtmlMeta.html_lang,            True),
}

# Campos que se pueden pedir vacios o con valor: `?vacio=title,canonical_href`
# o `?con_valor=...`. «Sin title» o «sin canonical» no se podian pedir con un
# «contiene».
_VACIO_FILTERS: dict[str, tuple[Any, bool]] = {
    "title":            (HtmlMeta.title,            True),
    "meta_description": (HtmlMeta.meta_description, True),
    "canonical_href":   (HtmlMeta.canonical_href,   True),
    "meta_robots":      (HtmlMeta.meta_robots,      True),
    "x_robots_tag":     (HtmlMeta.x_robots_tag,     True),
    "og_title":         (HtmlMeta.og_title,         True),
    "og_image":         (HtmlMeta.og_image,         True),
    "redirect_url":     (Url.redirect_url,          False),
    "last_modified":    (Url.last_modified,         False),
}


_TIPOS_NO_ENLACE = ("redirect", "canonical")


def _job_archivado(db: Session, job_id: uuid.UUID) -> bool:
    """Si los enlaces del job viven en Parquet y no en `links` (decision 95)."""
    job = db.get(Job, job_id)
    return job is not None and archivo_enlaces.esta_archivado(job)


def _urls_de(db: Session, ids) -> dict[int, tuple[str, int | None]]:
    """(url, codigo) de cada id, por tramos."""
    ids = list({i for i in ids if i is not None})
    salida: dict[int, tuple[str, int | None]] = {}
    for i in range(0, len(ids), 1000):
        for uid, url, cod in (db.query(Url.id, Url.url, Url.status_code)
                              .filter(Url.id.in_(ids[i:i + 1000])).all()):
            salida[uid] = (url, cod)
    return salida


def _como_links(db: Session, job_id: uuid.UUID, filas: list[dict]) -> list[Any]:
    """Filas del Parquet con la forma de un `Link` del ORM, `from_url_rel`
    incluido, para que el resto del endpoint no distinga de donde vienen."""
    from types import SimpleNamespace

    urls = _urls_de(db, (f["from_url_id"] for f in filas))
    return [
        SimpleNamespace(**f, job_id=job_id, from_url_rel=SimpleNamespace(
            url=urls.get(f["from_url_id"], (None, None))[0]))
        for f in filas
    ]


def _sondas_de(db: Session, job_id: uuid.UUID, hashes) -> dict[str, tuple[str, int | None]]:
    """Veredicto y codigo de la sonda de cada destino (decision 123), filtrando
    `respuestas_sondeadas` por job y hash (su indice unico)."""
    from shared.models import RespuestaSondeada

    lista = sorted({h for h in hashes if h})
    if not lista:
        return {}
    return {
        h: (v, st) for h, v, st in db.query(
            RespuestaSondeada.url_hash, RespuestaSondeada.veredicto,
            RespuestaSondeada.status_code)
        .filter(RespuestaSondeada.job_id == job_id, RespuestaSondeada.url_hash.in_(lista))
    }


def _con_sondas(db: Session, job_id: uuid.UUID) -> bool:
    from shared.models import RespuestaSondeada

    return db.query(RespuestaSondeada.id).filter(
        RespuestaSondeada.job_id == job_id).first() is not None


def _es_enlace(tipo: str | None) -> bool:
    return tipo is None or tipo not in _TIPOS_NO_ENLACE


def _origenes(db: Session, job_id: uuid.UUID, hashes: list[str]) -> dict[str, tuple[str, int]]:
    """Para cada destino (url_hash): la pagina que mas veces lo enlaza y
    cuantas paginas distintas lo enlazan. Usa `ix_links_to_hash (job_id,
    to_url_hash)`: nunca recorre la tabla de enlaces entera (decision 37)."""
    if not hashes:
        return {}
    if _job_archivado(db, job_id):
        cuenta: dict[tuple[str, int], int] = {}
        for f in archivo_enlaces.leer(job_id, a_hashes=hashes,
                                      columnas=["to_url_hash", "from_url_id", "link_type"]):
            if _es_enlace(f["link_type"]):
                k = (f["to_url_hash"], f["from_url_id"])
                cuenta[k] = cuenta.get(k, 0) + 1
        urls = _urls_de(db, (o for _, o in cuenta))
        filas = [(h, urls[o][0], n) for (h, o), n in cuenta.items() if o in urls]
    else:
        filas = None
    filas = filas if filas is not None else (
        db.query(Link.to_url_hash, Url.url, func.count(Link.id))
        .join(Url, Url.id == Link.from_url_id)
        .filter(Link.job_id == job_id, Link.to_url_hash.in_(hashes),
                or_(Link.link_type.is_(None), Link.link_type.notin_(_TIPOS_NO_ENLACE)))
        .group_by(Link.to_url_hash, Url.url)
        .all()
    )
    mejor: dict[str, tuple[str, int]] = {}
    distintos: dict[str, int] = {}
    for h, origen, n in filas:
        distintos[h] = distintos.get(h, 0) + 1
        if h not in mejor or n > mejor[h][1] or (n == mejor[h][1] and origen < mejor[h][0]):
            mejor[h] = (origen, n)
    return {h: (mejor[h][0], distintos[h]) for h in mejor}


def _h1s(db: Session, ids: list[int]) -> dict[int, tuple[str | None, int]]:
    """Primer H1 visible y cuantos H1 visibles tiene cada URL."""
    if not ids:
        return {}
    salida: dict[int, tuple[str | None, int]] = {}
    for uid, texto in (
        db.query(Heading.url_id, Heading.text)
        .filter(Heading.url_id.in_(ids), Heading.tag == "h1", Heading.oculto.isnot(True))
        .order_by(Heading.url_id, Heading.position)
    ):
        primero, n = salida.get(uid, (None, 0))
        salida[uid] = (primero if primero is not None else texto, n + 1)
    return salida


def _referencia(db: Session, job_id: uuid.UUID, con: str | None) -> uuid.UUID | None:
    """El censo contra el que se compara: `?con=` o el de la comparacion
    automatica que guardo el worker (decision 71)."""
    if con:
        try:
            return uuid.UUID(con)
        except ValueError:
            return None
    job = db.get(Job, job_id)
    comp = job.comparacion if job is not None and isinstance(job.comparacion, dict) else {}
    try:
        return uuid.UUID(comp["comparado_con"]) if comp.get("comparado_con") else None
    except (ValueError, TypeError):
        return None


def _cambios(db: Session, ref: uuid.UUID | None, urls: list) -> dict[int, str | None]:
    """Que cambio cada URL frente al mismo `url_hash` en el censo `ref`.

    Mismos campos y criterio que la comparacion de censos (decision 67):
    codigo, indexabilidad, titulo, canonical y palabras si cambian mas de un
    20% sobre el MAYOR de los dos (si no, A->B y B->A dirian cosas distintas).
    Y lo extraido a medida, con los guardias de la decision 127 (decision 166).
    """
    if ref is None or not urls:
        return {}
    antes = {
        u.url_hash: u for u in db.query(Url).options(joinedload(Url.html_meta))
        .filter(Url.job_id == ref, Url.url_hash.in_([u.url_hash for u in urls]))
    }
    try:
        extraido = _cambios_extraidos(db, ref, urls, antes)
    except Exception:  # noqa: BLE001 — la columna sigue sin lo extraido
        import logging

        logging.getLogger(__name__).exception("cambios: no se pudo comparar lo extraido")
        extraido = {}
    salida: dict[int, str | None] = {}
    for u in urls:
        a = antes.get(u.url_hash)
        if a is None:
            salida[u.id] = "nueva"
            continue
        partes = []
        if a.status_code != u.status_code:
            partes.append(f"{a.status_code or '—'}→{u.status_code or '—'}")
        if a.indexable != u.indexable and None not in (a.indexable, u.indexable):
            partes.append("entra en el índice" if u.indexable else "sale del índice")
        ma, mu = a.html_meta, u.html_meta
        if ma is not None and mu is not None:
            if (ma.title or "").strip() != (mu.title or "").strip():
                partes.append("título")
            if (ma.canonical_href or "") != (mu.canonical_href or ""):
                partes.append("canonical")
        pa, pu = a.content_word_count or a.word_count, u.content_word_count or u.word_count
        if pa is not None and pu is not None and max(pa, pu) and abs(pa - pu) / max(pa, pu) > 0.2:
            partes.append(f"palabras {pa}→{pu}")
        partes.extend(extraido.get(u.id, []))
        salida[u.id] = "; ".join(partes) or None
    return salida


def _corto(valor, n: int = 30) -> str:
    v = " ".join(str(valor if valor is not None else "—").split())
    return v if len(v) <= n else v[:n - 1] + "…"


def _cambios_extraidos(db: Session, ref: uuid.UUID, urls: list, antes: dict) -> dict[int, list[str]]:
    """Lo extraido a medida que cambia en cada URL frente al censo `ref`, con
    los guardias de la comparacion de censos (decision 127): solo las reglas
    con el mismo nombre y la misma definicion en los dos censos, solo filas
    con dato (`ok`/`sin_coincidencia`) en los dos, y el mismo `render`. Sin
    fila en uno de los dos no es un cambio (104). Decision 166."""
    from shared.comparacion import (
        ESTADOS_CON_DATO, _mismo_valor, _reglas_comparables, reglas_a_medida,
    )

    job_id = urls[0].job_id
    jobs = {j.id: j for j in db.query(Job).filter(Job.id.in_([job_id, ref]))}
    if job_id not in jobs or ref not in jobs:
        return {}
    comparables, _fuera = _reglas_comparables(
        {"reglas_a_medida": reglas_a_medida(jobs[ref].config)},
        {"reglas_a_medida": reglas_a_medida(jobs[job_id].config)}, {}, {})
    if not comparables:
        return {}
    etiquetas = {n: (r.get("etiqueta") or n) for n, (_c, r) in reglas_del_job(jobs[job_id]).items()}
    CE = CustomExtraction

    def filas(jid, ids):
        out: dict[int, dict[str, dict]] = {}
        for f in (db.query(CE.url_id, CE.nombre, CE.estado, CE.valor_clave, CE.valor_num, CE.render)
                  .filter(CE.job_id == jid, CE.url_id.in_(ids), CE.nombre.in_(list(comparables)))):
            out.setdefault(f.url_id, {})[f.nombre] = {
                "estado": f.estado, "valor": f.valor_clave, "num": f.valor_num, "render": f.render}
        return out

    ahora = filas(job_id, [u.id for u in urls])
    ids_antes = {a.id: a.url_hash for a in antes.values()}
    previo_por_hash = {ids_antes[uid]: v for uid, v in filas(ref, list(ids_antes)).items()} \
        if ids_antes else {}
    salida: dict[int, list[str]] = {}
    for u in urls:
        pa, pb = previo_por_hash.get(u.url_hash) or {}, ahora.get(u.id) or {}
        partes = []
        for nombre in sorted(comparables):
            ea, eb = pa.get(nombre), pb.get(nombre)
            if ea is None or eb is None:
                continue
            if ea["estado"] not in ESTADOS_CON_DATO or eb["estado"] not in ESTADOS_CON_DATO:
                continue
            if None not in (ea["render"], eb["render"]) and bool(ea["render"]) != bool(eb["render"]):
                continue
            et = etiquetas.get(nombre, nombre)
            antes_ok, ahora_ok = ea["estado"] == "ok", eb["estado"] == "ok"
            if comparables[nombre] == "busqueda":
                if antes_ok != ahora_ok:
                    partes.append(f"{'pasa a contener' if ahora_ok else 'deja de contener'} {et}")
            elif antes_ok and ahora_ok and not _mismo_valor(ea, eb):
                partes.append(f"{et} {_corto(ea['valor'])}→{_corto(eb['valor'])}")
            elif antes_ok != ahora_ok:
                partes.append(f"{et} {'aparece' if ahora_ok else 'desaparece'}")
        if partes:
            salida[u.id] = partes
    return salida


def _anotar_uso(qp, *, csv: bool = False) -> None:
    """Cuenta la consulta si viene del Explorador (`?vista=explorador`).
    Nunca falla: ver api/uso.py."""
    if qp.get("vista") != "explorador":
        return
    try:
        from api import uso
        from api.dependencies import get_redis

        uso.anotar(get_redis(), qp, csv=csv)
    except Exception:  # noqa: BLE001
        pass


def _clausula_contiene(col_expr, valor):
    """`a|b` -> contiene a O b; `!a` -> no contiene a (o esta vacio).
    Se pueden mezclar: `!null|undefined` no es valido; la negacion vale para
    toda la expresion: `!a|b` = no contiene ni a ni b."""
    if valor in (None, ""):
        return None
    valor = str(valor)
    negar = valor.startswith("!")
    if negar:
        valor = valor[1:]
    partes = [p for p in (x.strip() for x in valor.split("|")) if p]
    if not partes:
        return None
    contiene = or_(*[col_expr.ilike(f"%{p}%") for p in partes])
    return or_(col_expr.is_(None), ~contiene) if negar else contiene


# ---------------------------------------------------------------------------
# Extraccion y busqueda a medida (#34, decision 104): columnas `x.<nombre>`
# ---------------------------------------------------------------------------
_ESTADOS_EVALUADOS = ("ok", "sin_coincidencia", "conversion_fallida")
from shared.extraccion_a_medida import SUFIJOS_FILTRO as _SUFIJOS_X  # noqa: E402


def reglas_del_job(job_o_config) -> dict[str, tuple[str, dict]]:
    """nombre -> (clase, regla) de las reglas a medida del censo."""
    config = getattr(job_o_config, "config", job_o_config)
    config = config if isinstance(config, dict) else {}
    salida: dict[str, tuple[str, dict]] = {}
    for clase, clave in (("extractor", "custom_extraction"), ("busqueda", "custom_search")):
        for nombre, regla in (config.get(clave) or {}).items():
            if isinstance(regla, dict):
                salida[nombre] = (clase, regla)
    return salida


def _es_numerica(clase: str, regla: dict) -> bool:
    return clase == "busqueda" or regla.get("cuantos") == "recuento" or regla.get("valor") == "numero"


def _regla_o_422(reglas: dict, nombre: str) -> tuple[str, dict]:
    if nombre not in reglas:
        # Una vista guardada con la regla de otro censo no puede devolver el
        # censo ENTERO como si el filtro no existiera.
        raise HTTPException(status_code=422,
                            detail=f'este censo no tiene la regla "{nombre}" (x.{nombre})')
    return reglas[nombre]


def _parametro_x(clave: str, reglas: dict) -> tuple[str, str] | None:
    """`x.precio_gte` -> ('precio', '_gte'); `x.gtm` -> ('gtm', ''). El nombre
    puede llevar `_`, asi que primero se mira si la clave entera es una regla."""
    if not clave.startswith("x."):
        return None
    resto = clave[2:]
    if resto in reglas:
        return resto, ""
    for suf in _SUFIJOS_X:
        if resto.endswith(suf):
            return resto[: -len(suf)], suf
    return resto, ""


def _filtros_a_medida(db: Session, job_id: uuid.UUID, qp) -> list:
    """Las clausulas de los filtros `x.*` sobre `Url`, cada una un
    `Url.id IN (select url_id ...)` por (job, nombre) con su indice.

    Sin fila = no evaluada. «No contiene» (`!a`, `=no`, `vacio`) solo mira las
    filas que SI se evaluaron: una pagina bloqueada por el WAF no «no contiene»
    el tag de GTM, simplemente no se sabe.
    """
    claves = [k for k in qp.keys() if k.startswith("x.")]
    vacios = {param: [c.strip() for c in (qp.get(param) or "").split(",")
                      if c.strip().startswith("x.")] for param in ("vacio", "con_valor")}
    if not claves and not any(vacios.values()):
        return []
    reglas = reglas_del_job(db.get(Job, job_id))
    CE = CustomExtraction
    clausulas: list = []

    def sub(nombre, *cond):
        return Url.id.in_(db.query(CE.url_id).filter(CE.job_id == job_id, CE.nombre == nombre, *cond))

    for clave in claves:
        valor = qp.get(clave)
        if valor in (None, ""):
            continue
        nombre, suf = _parametro_x(clave, reglas)
        clase, regla = _regla_o_422(reglas, nombre)
        col_num = CE.n if clase == "busqueda" else CE.valor_num
        if suf in ("_gte", "_lte"):
            try:
                v = float(valor)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"{clave}: no es un numero: {valor!r}")
            clausulas.append(sub(nombre, col_num >= v if suf == "_gte" else col_num <= v))
        elif suf == "_contains":
            negar = str(valor).startswith("!")
            cond = _clausula_contiene(CE.valor, valor)
            if cond is None:
                continue
            if negar:
                clausulas.append(sub(nombre, CE.estado.in_(("ok", "sin_coincidencia")), cond))
            else:
                clausulas.append(sub(nombre, cond))
        elif suf == "_estado":
            estados = [e.strip() for e in str(valor).split(",") if e.strip()]
            clausulas.append(sub(nombre, CE.estado.in_(estados)))
        else:
            si = str(valor).strip().lower() in ("si", "sí", "true", "1")
            no = str(valor).strip().lower() in ("no", "false", "0")
            if not (si or no):
                raise HTTPException(status_code=422, detail=f"{clave}: usa si o no")
            clausulas.append(sub(nombre, CE.estado == ("ok" if si else "sin_coincidencia")))
    for param, campos in vacios.items():
        for campo in campos:
            nombre = campo[2:]
            _regla_o_422(reglas, nombre)
            if param == "vacio":
                # «Vacio» es exactamente «se evaluo y no hubo nada»: sin fila no
                # es vacio, es no evaluada.
                clausulas.append(sub(nombre, CE.estado == "sin_coincidencia"))
            else:
                clausulas.append(sub(nombre, CE.valor.isnot(None), CE.estado.in_(_ESTADOS_EVALUADOS)))
    return clausulas


def _ordenar(q, sort_by: str | None, sort_dir: str, db: Session, job_id: uuid.UUID):
    """El orden del Explorador, compartido por `/urls` y su CSV.

    `x.<nombre>` ordena por el valor numerico y luego por el texto (o por el
    numero de coincidencias en una busqueda), con las no evaluadas al final en
    los dos sentidos."""
    if sort_by and sort_by.startswith("x."):
        nombre = sort_by[2:]
        clase, regla = _regla_o_422(reglas_del_job(db.get(Job, job_id)), nombre)
        from sqlalchemy.orm import aliased

        A = aliased(CustomExtraction)
        # El job_id en la condicion del join no es redundante: sin el, Postgres
        # recorre las filas de esa regla de TODOS los censos (decision 37).
        q = q.outerjoin(A, and_(A.url_id == Url.id, A.job_id == job_id, A.nombre == nombre))
        cols = [A.n] if clase == "busqueda" else [A.valor_num, A.valor_clave]
        orden = [c.desc().nullslast() if sort_dir == "desc" else c.asc().nullslast() for c in cols]
        return q.order_by(*orden, Url.id)
    if sort_by and sort_by in SORT_COLUMNS:
        col = SORT_COLUMNS[sort_by]
        return q.order_by(col.desc().nullslast() if sort_dir == "desc" else col.asc().nullsfirst(),
                          Url.id)
    return q.order_by(Url.id)


def _a_medida(db: Session, job_id: uuid.UUID, ids: list[int],
              nombres: list[str] | None = None) -> dict[int, dict[str, dict]]:
    """url_id -> {nombre: fila}. Una consulta por tramo, como `_h1s`."""
    if not ids:
        return {}
    CE = CustomExtraction
    q = db.query(CE.url_id, CE.nombre, CE.clase, CE.estado, CE.n, CE.valor, CE.valor_num,
                 CE.valores, CE.truncado, CE.render, CE.detalle).filter(
        CE.job_id == job_id, CE.url_id.in_(ids))
    if nombres:
        q = q.filter(CE.nombre.in_(nombres))
    salida: dict[int, dict[str, dict]] = {}
    for f in q:
        salida.setdefault(f.url_id, {})[f.nombre] = {
            "clase": f.clase, "estado": f.estado, "n": f.n, "valor": f.valor,
            "valor_num": f.valor_num, "valores": f.valores, "truncado": bool(f.truncado),
            "render": f.render, "detalle": f.detalle,
        }
    return salida


def _nombres_pedidos(reglas: dict, pedido: str | None) -> list[str]:
    if not pedido:
        return []
    if pedido.strip() == "todas":
        return list(reglas)
    nombres = [n.strip() for n in pedido.split(",") if n.strip()]
    for n in nombres:
        _regla_o_422(reglas, n)
    return nombres


_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def celda_segura(v):
    """Un valor sacado de la pagina en una celda de CSV, sin que Excel o Sheets
    lo ejecuten como formula (`=HYPERLINK(...)`, `@SUM`). Los numeros no se
    tocan: un -5 sigue siendo un numero."""
    if isinstance(v, str) and v.startswith(_FORMULA):
        return "'" + v
    return v


def valor_csv_a_medida(fila: dict | None, clase: str, regla: dict, posicion: int | None = None):
    """Lo que va en la celda de una regla. Vacio = no evaluada o sin
    coincidencia; una busqueda dice `si`/`no`; un estado que no es un resultado
    va entre corchetes (`[pagina_bloqueada]`) para que no se lea como «vacio»."""
    if fila is None:
        return ""
    estado = fila["estado"]
    if clase == "busqueda":
        return {"ok": "si", "sin_coincidencia": "no"}.get(estado, f"[{estado}]")
    if estado == "sin_coincidencia":
        return ""
    if estado not in ("ok", "conversion_fallida"):
        return f"[{estado}]"
    if posicion is not None:
        valores = fila.get("valores") or []
        return celda_segura(valores[posicion]) if posicion < len(valores) else ""
    if estado == "ok" and fila.get("valor_num") is not None and _es_numerica(clase, regla):
        num = fila["valor_num"]
        return int(num) if float(num).is_integer() else num
    return celda_segura(fila.get("valor"))


# ---------------------------------------------------------------------------
# Segmentos de negocio (decision 125): `urls.segmento`, materializado al analizar
# ---------------------------------------------------------------------------
def segmentos_pedidos(qp) -> list[str]:
    """`?segmento=a&segmento=b` (O). Repetido y no separado por comas: la forma
    de la ruta, que es el segmento por defecto, puede llevar una coma."""
    valores = qp.getlist("segmento") if hasattr(qp, "getlist") else [qp.get("segmento")]
    return [v for v in valores if v not in (None, "")]


def urls_de_segmentos(db: Session, job_id: uuid.UUID, segmentos: list[str]):
    """Subconsulta de los ids de URL de esos segmentos, con el `job_id` delante
    (lo que usa el indice; `segmento` no tiene uno propio, decision 125)."""
    return db.query(Url.id).filter(Url.job_id == job_id, Url.segmento.in_(segmentos))


def incidencia_por_pagina():
    """Las incidencias que son de SU pagina. Las que se emiten una vez por
    hallazgo (una imagen sin alt en mil paginas, una cabecera por host, un
    bloque de datos estructurados de plantilla, un enlace de plantilla:
    decisiones 53, 64, 73 y 106) llevan `paginas_afectadas` y cuelgan de una
    pagina de anclaje: repartirlas por el segmento de esa pagina afirmaria algo
    que no se sabe.

    Con `paginas_afectadas` = 1 el hallazgo SI es de una sola pagina —la foto
    propia de un producto—, y es la de anclaje: esa se reparte. Son la mayoria
    de las imagenes sin alt (310 de 354 en progym)."""
    pa = Issue.details["paginas_afectadas"].as_integer()
    return or_(pa.is_(None), pa <= 1)


def incidencia_agregada():
    """El complemento de `incidencia_por_pagina`: un hallazgo de varias paginas."""
    return Issue.details["paginas_afectadas"].as_integer() > 1


def _urls_filtradas(db: Session, job_id: uuid.UUID, qp, *, unir_meta: bool = False) -> Any:
    """Las URLs de un job con los filtros del Explorador aplicados.

    `unir_meta`: une con html_meta aunque ningun filtro lo pida (para ordenar
    por titulo o leer sus columnas en el CSV).

    La usan el listado (`/urls`) y el CSV de la vista (`/urls/export`): dos
    filtrados escritos por separado acabarian exportando otra lista que la que
    se ve en pantalla.
    """
    def _bool(v):
        return None if v in (None, "") else str(v).lower() in ("1", "true", "si", "sí")

    q = db.query(Url).filter(Url.job_id == job_id)
    clauses: list = []
    necesita_meta = False

    # 1) Rangos numericos: <col>_gte / <col>_lte
    for col_name, (col_expr, needs_meta) in _RANGE_FILTERS.items():
        gte_raw = qp.get(f"{col_name}_gte")
        lte_raw = qp.get(f"{col_name}_lte")
        if (gte_raw in (None, "")) and (lte_raw in (None, "")):
            continue
        try:
            if gte_raw not in (None, ""):
                clauses.append(col_expr >= float(gte_raw))
            if lte_raw not in (None, ""):
                clauses.append(col_expr <= float(lte_raw))
        except ValueError:
            continue  # numero mal escrito: se ignora
        necesita_meta |= needs_meta

    # 2) «Contiene». `a|b` = contiene a o b; `!a` = no contiene a (#131).
    #    Sin expresiones regulares: SQLite (los tests) no las tiene y en un
    #    filtro de tabla bastan estas dos.
    for param_name, (col_expr, needs_meta) in _STRING_CONTAINS_FILTERS.items():
        clausula = _clausula_contiene(col_expr, qp.get(param_name))
        if clausula is None:
            continue
        clauses.append(clausula)
        necesita_meta |= needs_meta

    # 3) Vacio / con valor
    for param, vacio in (("vacio", True), ("con_valor", False)):
        for campo in (qp.get(param) or "").split(","):
            campo = campo.strip()
            if campo not in _VACIO_FILTERS:
                continue
            col_expr, needs_meta = _VACIO_FILTERS[campo]
            clauses.append(or_(col_expr.is_(None), func.trim(col_expr) == "") if vacio
                           else (col_expr.isnot(None) & (func.trim(col_expr) != "")))
            necesita_meta |= needs_meta

    search = qp.get("search")
    if search or necesita_meta or unir_meta:
        q = q.outerjoin(HtmlMeta, Url.id == HtmlMeta.url_id)

    for campo, col in (("status_group", Url.status_group), ("resource_type", Url.resource_type)):
        if qp.get(campo) not in (None, ""):
            q = q.filter(col == qp.get(campo))
    for campo, col in (("is_internal", Url.is_internal), ("indexable", Url.indexable),
                       ("in_sitemap", Url.in_sitemap),
                       ("bloqueada_googlebot", Url.bloqueada_googlebot)):
        v = _bool(qp.get(campo))
        if v is not None:
            q = q.filter(col == v)
    # Varios codigos a la vez: `301,302`.
    if qp.get("status_code") not in (None, ""):
        try:
            codigos = [int(c) for c in str(qp.get("status_code")).split(",") if c.strip()]
            q = q.filter(Url.status_code.in_(codigos))
        except ValueError:
            pass

    for clause in clauses:
        q = q.filter(clause)
    for clause in _filtros_a_medida(db, job_id, qp):
        q = q.filter(clause)

    # Una URL exacta: la ficha de una pagina de la que solo se sabe la
    # direccion (trafico entre censos). Con `search` («contiene») una URL corta
    # como /es casa con miles y la exacta no salia entre las primeras
    # (revision de UX del 25-oct, 3.3).
    if qp.get("url_exacta"):
        q = q.filter(Url.url == qp.get("url_exacta"))

    # Buscador de arriba: URL o titulo
    if search:
        pattern = f"%{search}%"
        q = q.filter(or_(Url.url.ilike(pattern), HtmlMeta.title.ilike(pattern)))

    # URLs con alguna incidencia de esos tipos (lista separada por comas: las
    # vistas por ambito piden varios a la vez) y/o de esa gravedad.
    tipos = [t.strip() for t in (qp.get("issue_type") or "").split(",") if t.strip()]
    severidad = qp.get("severity")
    segmentos = segmentos_pedidos(qp)
    if tipos or severidad:
        sub = db.query(Issue.url_id).filter(Issue.job_id == job_id)
        if tipos:
            sub = sub.filter(Issue.issue_type.in_(tipos))
        if severidad:
            sub = sub.filter(Issue.severity == severidad)
        if segmentos:
            # Lo mismo que cuenta Problemas con ese segmento: la pagina de
            # anclaje de un hallazgo de muchas paginas no es «la» pagina del
            # segmento con ese problema (decision 125).
            sub = sub.filter(incidencia_por_pagina())
        q = q.filter(Url.id.in_(sub))

    if segmentos:
        q = q.filter(Url.segmento.in_(segmentos))

    # Una plantilla (forma de ruta, `shared.plantillas.firma_de_ruta`). La
    # forma se calcula en Python —no hay forma de escribirla en SQL sin atarse a
    # Postgres—, sobre lo que ya ha filtrado lo demas.
    plantilla = qp.get("plantilla")
    if plantilla:
        from shared.plantillas import firma_de_ruta

        ids = [i for i, ruta in q.with_entities(Url.id, Url.path).all() if firma_de_ruta(ruta or "/") == plantilla]
        q = q.filter(Url.id.in_(ids or [-1]))
    return q


@router.get("/urls", response_model=PaginatedResponse[UrlResponse])
def list_urls(
    job_id: uuid.UUID,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status_group: str | None = Query(None),
    is_internal: bool | None = Query(None),
    resource_type: str | None = Query(None),
    search: str | None = Query(None),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    indexable: bool | None = Query(None),
    status_code: str | None = Query(None, description="Uno o varios codigos: 301,302"),
    issue_type: str | None = Query(None, description="Uno o varios tipos separados por comas"),
    severity: str | None = Query(None),
    in_sitemap: bool | None = Query(None),
    ligero: bool = Query(False, description="Sin page_content: es el 89% del peso y la tabla no lo usa"),
    origenes: bool = Query(False, description="Anade enlazada_desde y origenes a cada fila"),
    h1: bool = Query(False, description="Anade el primer H1 visible y cuantos hay"),
    cambios: bool = Query(False, description="Anade que cambio frente al censo de referencia"),
    con: str | None = Query(None, description="Censo de referencia para `cambios` (por defecto, el de la comparacion automatica)"),
    a_medida: str | None = Query(None, description="Reglas a medida a anadir a cada fila: nombres por comas o `todas`"),
    db: Session = Depends(get_session),
):
    job = _get_job_or_404(job_id, db)
    _anotar_uso(request.query_params)

    q = _urls_filtradas(db, job_id, request.query_params, unir_meta=sort_by in _SORT_META)
    nombres_x = _nombres_pedidos(reglas_del_job(job), a_medida)

    total = q.count()

    q = _ordenar(q, sort_by, sort_dir, db, job_id)

    # `ligero`: el Explorador no pinta el texto de cada pagina y el panel lo
    # pide aparte; con el, una pagina de 100 filas eran 1,6 MB (89% texto).
    # Ni se carga ni se toca la relacion (tocarla la cargaria fila a fila).
    opciones = [joinedload(Url.html_meta)]
    if not ligero:
        opciones.append(joinedload(Url.page_content))
    rows = (
        q.options(*opciones)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    if ligero:
        campos = [f for f in UrlResponse.model_fields if f != "page_content"]
        items = [UrlResponse.model_validate({f: getattr(r, f, None) for f in campos}, from_attributes=True)
                 for r in rows]
    else:
        items = [UrlResponse.model_validate(r) for r in rows]
    if origenes:
        o = _origenes(db, job_id, [r.url_hash for r in rows])
        for it, r in zip(items, rows):
            it.enlazada_desde, it.origenes = o.get(r.url_hash, (None, 0))
    if h1:
        hs = _h1s(db, [r.id for r in rows])
        for it, r in zip(items, rows):
            it.h1, it.h1_count = hs.get(r.id, (None, 0))
    if cambios:
        cs = _cambios(db, _referencia(db, job_id, con), rows)
        for it, r in zip(items, rows):
            it.cambio = cs.get(r.id)
    if nombres_x:
        xs = _a_medida(db, job_id, [r.id for r in rows], nombres_x)
        for it, r in zip(items, rows):
            it.a_medida = xs.get(r.id, {})

    return _paginate(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/urls/plantillas  -- la vista agrupada por plantilla
# ---------------------------------------------------------------------------
class _Plantilla(BaseModel):
    plantilla: str
    urls: int
    indexables: int = 0
    por_estado: dict[str, int] = {}
    con_errores: int = 0
    palabras_mediana: float | None = None
    pagerank_mediana: float | None = None
    clics_mediana: float | None = None
    inlinks: int = 0
    tramos_repetidos: list[dict] = []   # [{tramo, veces}], los que se repiten
    ejemplos: list[str] = []


class _VistaPorPlantilla(BaseModel):
    plantillas: list[_Plantilla]
    # Ultimos tramos que se repiten en TODA la vista, crucen o no de plantilla:
    # `null` aparecia en /es/null, /en/corporate/null y /es/corporativa/null.
    tramos_repetidos: list[dict] = []
    urls: int = 0


def _mediana(valores: list) -> float | None:
    v = sorted(x for x in valores if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return float(v[m]) if len(v) % 2 else (v[m - 1] + v[m]) / 2


@router.get("/urls/plantillas", response_model=_VistaPorPlantilla)
def urls_por_plantilla(
    job_id: uuid.UUID,
    request: Request,
    limite: int = Query(300, ge=1, le=2000),
    agrupar: str = Query("plantilla", pattern="^(plantilla|segmento)$",
                         description="Por la forma de la ruta o por `urls.segmento` (decision 125)"),
    db: Session = Depends(get_session),
):
    """Las URLs de la vista agrupadas por la forma de su ruta (o por segmento).

    En SEO tecnico casi nada se arregla URL a URL: se arregla una plantilla. En
    Lopesan, `/de/null`, `/en/null`, `/es/null`… salian como doce 404 sueltos
    y son un solo fallo (docs/INVESTIGACION_EXPLORADOR.md). La forma normaliza
    el ultimo tramo, asi que cada grupo dice ademas que ultimo tramo se repite
    (`null` × 9): es lo que delata el fallo.
    """
    from collections import Counter, defaultdict

    from shared.plantillas import firma_de_ruta

    _get_job_or_404(job_id, db)
    _anotar_uso(request.query_params)
    q = _urls_filtradas(db, job_id, request.query_params)
    filas = q.with_entities(
        Url.id, Url.url, Url.path, Url.status_group, Url.indexable, Url.content_word_count,
        Url.word_count, Url.pagerank_score, Url.click_depth, Url.inlinks_count, Url.segmento,
    ).all()
    con_error = {
        uid for (uid,) in db.query(Issue.url_id)
        .filter(Issue.job_id == job_id, Issue.severity == "error").distinct()
    } if filas else set()

    def ultimo(f):
        return (f.path or "/").rstrip("/").rsplit("/", 1)[-1] or "/"

    def repetidos(cuenta: Counter, n: int, minimo: int = 2) -> list[dict]:
        # Solo dicen algo si se repiten: en una plantilla sana cada pagina
        # tiene su slug.
        return [{"tramo": t, "veces": v} for t, v in cuenta.most_common(n) if v >= minimo]

    grupos: dict[str, list] = defaultdict(list)
    for f in filas:
        if agrupar == "segmento":
            # Sin segmentar = censo analizado antes de la columna: se dice, no se
            # inventa la forma de la ruta como si fuera su segmento.
            grupos[f.segmento if f.segmento is not None else "(sin segmentar)"].append(f)
        else:
            grupos[firma_de_ruta(f.path or "/")].append(f)

    salida = []
    for forma, fs in grupos.items():
        salida.append(_Plantilla(
            plantilla=forma, urls=len(fs),
            indexables=sum(1 for f in fs if f.indexable),
            por_estado=dict(Counter(f.status_group or "?" for f in fs)),
            con_errores=sum(1 for f in fs if f.id in con_error),
            palabras_mediana=_mediana([f.content_word_count if f.content_word_count is not None else f.word_count for f in fs]),
            pagerank_mediana=_mediana([f.pagerank_score for f in fs]),
            clics_mediana=_mediana([f.click_depth for f in fs]),
            inlinks=sum(f.inlinks_count or 0 for f in fs),
            tramos_repetidos=repetidos(Counter(ultimo(f) for f in fs), 3),
            ejemplos=[f.url for f in fs[:3]],
        ))
    salida.sort(key=lambda p: (-p.urls, p.plantilla))
    return _VistaPorPlantilla(
        plantillas=salida[:limite],
        tramos_repetidos=repetidos(Counter(ultimo(f) for f in filas), 8, minimo=3),
        urls=len(filas),
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/urls/export  -- CSV de LA VISTA del Explorador
# ---------------------------------------------------------------------------
def _m(campo):
    return lambda u: getattr(u.html_meta, campo, None) if u.html_meta else None


def _si_no(v):
    return "" if v is None else ("si" if v else "no")


# Las columnas del Explorador (mismas claves que EXP_COLUMN_DEFS en app.js):
# (cabecera, valor). Lo que no esta aqui no se exporta en vez de inventarse.
COLUMNAS_VISTA: dict[str, tuple[str, Any]] = {
    "url": ("URL", lambda u: u.url),
    "status_code": ("Estado", lambda u: u.status_code),
    "status_text": ("Texto estado", lambda u: u.status_text),
    "content_type": ("Tipo", lambda u: (u.content_type or "").split(";")[0] or None),
    "content_length": ("Tamaño (bytes)", lambda u: u.content_length),
    "transfer_size": ("Transferido (bytes)", lambda u: u.transfer_size),
    "response_time_ms": ("Tiempo (ms)", lambda u: u.response_time_ms),
    "ttfb_ms": ("TTFB (ms)", lambda u: u.ttfb_ms),
    "content_encoding": ("Compresión", lambda u: u.content_encoding),
    "click_depth": ("Clics desde home", lambda u: u.click_depth),
    "gsc_clics": ("Clics Google (90 d)", lambda u: u.gsc_clics),
    "gsc_impresiones": ("Impresiones Google (90 d)", lambda u: u.gsc_impresiones),
    "gsc_posicion": ("Posición media Google", lambda u: u.gsc_posicion),
    "crawl_depth": ("Prof. rastreo", lambda u: u.crawl_depth),
    "folder_depth": ("Niveles", lambda u: u.folder_depth),
    "word_count": ("Palabras", lambda u: u.word_count),
    "content_word_count": ("Palabras contenido", lambda u: u.content_word_count),
    "text_ratio": ("% texto", lambda u: u.text_ratio),
    "url_length": ("Long. URL", lambda u: u.url_length),
    "inlinks_count": ("Inlinks", lambda u: u.inlinks_count),
    "unique_inlinks_count": ("Inlinks únicos", lambda u: u.unique_inlinks_count),
    "outlinks_count": ("Outlinks", lambda u: u.outlinks_count),
    "external_outlinks_count": ("Outlinks ext.", lambda u: u.external_outlinks_count),
    "pagerank_score": ("PageRank (0-100)", lambda u: u.pagerank_score),
    "pagerank_externo_score": ("PageRank desde fuera (0-100)", lambda u: u.pagerank_externo_score),
    "backlinks_externos": ("Backlinks dofollow", lambda u: u.backlinks_externos),
    "backlinks_nofollow": ("Backlinks nofollow", lambda u: u.backlinks_nofollow),
    "backlinks_spam": ("Backlinks spam", lambda u: u.backlinks_spam),
    "backlinks_spam_pct": ("% backlinks spam", lambda u: u.backlinks_spam_pct),
    "googlebot_visitas": ("Visitas Googlebot", lambda u: u.googlebot_visitas),
    "pagerank_raw": ("PageRank (x media)", lambda u: u.pagerank_raw),
    "pagerank": ("PageRank (0-10, antiguo)", lambda u: u.pagerank),
    "near_duplicate_count": ("Casi duplicadas", lambda u: u.near_duplicate_count),
    "closest_similarity": ("Similitud máx.", lambda u: u.closest_similarity),
    "redirect_url": ("Redirige a", lambda u: u.redirect_url),
    "redirect_type": ("Cód. redir.", lambda u: u.redirect_type),
    "indexable": ("Indexable", lambda u: _si_no(u.indexable)),
    "indexability_status": ("Indexabilidad", lambda u: u.indexability_status),
    "is_internal": ("Interna", lambda u: _si_no(u.is_internal)),
    "in_sitemap": ("En el sitemap", lambda u: _si_no(u.in_sitemap)),
    # Segun el robots.txt guardado (decision 113); vacio = no evaluado.
    "bloqueada_googlebot": ("Bloqueada para Googlebot", lambda u: _si_no(u.bloqueada_googlebot)),
    "host": ("Host", lambda u: u.host),
    "segmento": ("Segmento", lambda u: u.segmento),
    "title": ("Título", _m("title")),
    "title_len": ("Long. título", _m("title_len")),
    "title_pixel_width": ("Título (px)", _m("title_pixel_width")),
    "meta_description": ("Descripción", _m("meta_description")),
    "meta_description_len": ("Long. desc.", _m("meta_description_len")),
    "meta_description_pixel_width": ("Descripción (px)", _m("meta_description_pixel_width")),
    "canonical_href": ("Canonical", _m("canonical_href")),
    "canonical_header": ("Canonical (cabecera)", _m("canonical_header")),
    "rel_next": ("rel=next", _m("rel_next")),
    "rel_prev": ("rel=prev", _m("rel_prev")),
    "meta_robots": ("Meta robots", _m("meta_robots")),
    "x_robots_tag": ("X-Robots-Tag", _m("x_robots_tag")),
    "meta_refresh": ("Meta refresh", _m("meta_refresh")),
    "redireccion_js": ("Redirección JS", _m("redireccion_js")),
    "viewport": ("Viewport", _m("viewport")),
    "html_lang": ("html lang", _m("html_lang")),
    "og_title": ("OG title", _m("og_title")),
    "og_image": ("OG image", _m("og_image")),
    "og_type": ("OG type", _m("og_type")),
    "og_url": ("OG url", _m("og_url")),
    "twitter_card": ("Twitter card", _m("twitter_card")),
    "http_version": ("HTTP", lambda u: u.http_version),
    "last_modified": ("Last-Modified", lambda u: u.last_modified),
    "last_crawled_at": ("Último rastreo", lambda u: u.last_crawled_at.isoformat() if u.last_crawled_at else None),
    # Calculadas por tramo con `_origenes` (no son columnas de `urls`).
    "enlazada_desde": ("Enlazada desde", lambda u: getattr(u, "_origen", (None, 0))[0]),
    "origenes": ("Páginas que la enlazan", lambda u: getattr(u, "_origen", (None, 0))[1]),
    "h1": ("H1", lambda u: getattr(u, "_h1", (None, 0))[0]),
    "h1_count": ("Nº de H1", lambda u: getattr(u, "_h1", (None, 0))[1]),
    "cambio": ("Cambio frente al anterior", lambda u: getattr(u, "_cambio", None)),
}


@router.get("/urls/export")
def export_vista(
    job_id: uuid.UUID,
    request: Request,
    columnas: str = Query("url,status_code,title,indexable",
                          description="Claves de columna del Explorador, separadas por comas"),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_session),
):
    """Lo que se ve en el Explorador, como CSV: mismos filtros (los de
    `/urls`), mismo orden y solo las columnas visibles.

    El boton CSV del Explorador llamaba a `/export`, el censo entero con 83
    columnas: quien filtraba «4xx con enlaces entrantes» para mandarselo a
    desarrollo recibia todas las URLs (docs/INVESTIGACION_EXPLORADOR.md).

    Como `/export`, sesion nueva por ventana de 1.000 filas (decision 5): se
    sacan primero los ids en el orden de la vista y luego se leen por tramos.
    """
    job = _get_job_or_404(job_id, db)
    _anotar_uso(request.query_params, csv=True)
    reglas = reglas_del_job(job)
    pedidas = [x.strip() for x in columnas.split(",") if x.strip()]
    for c in pedidas:
        if c.startswith("x."):
            _regla_o_422(reglas, c[2:])
    claves = [c for c in pedidas if c in COLUMNAS_VISTA or c.startswith("x.")]
    if not claves:
        raise HTTPException(status_code=422, detail="Ninguna columna exportable: " + columnas)

    # Las columnas a medida: (clave, cabecera, nombre, posicion). Con `todos`,
    # una columna por posicion («Precio 1», «Precio 2»...), tantas como el
    # maximo de coincidencias del censo con el tope de la regla.
    cabeceras: list[tuple[str, str, str | None, int | None]] = []
    for c in claves:
        if not c.startswith("x."):
            cabeceras.append((c, COLUMNAS_VISTA[c][0], None, None))
            continue
        nombre = c[2:]
        clase, regla = reglas[nombre]
        etiqueta = regla.get("etiqueta") or nombre
        if clase == "extractor" and regla.get("cuantos") == "todos":
            maximo = db.query(func.max(CustomExtraction.n)).filter(
                CustomExtraction.job_id == job_id, CustomExtraction.nombre == nombre).scalar() or 1
            for i in range(min(int(maximo), int(regla.get("max_valores") or 20))):
                cabeceras.append((c, f"{etiqueta} {i + 1}", nombre, i))
        else:
            cabeceras.append((c, etiqueta, nombre, None))
    nombres_x = sorted({n for _, _, n, _ in cabeceras if n})

    q = _urls_filtradas(db, job_id, request.query_params, unir_meta=sort_by in _SORT_META)
    q = _ordenar(q, sort_by, sort_dir, db, job_id)
    ids = [i for (i,) in q.with_entities(Url.id).all()]
    ref = _referencia(db, job_id, request.query_params.get("con")) if "cambio" in claves else None
    # Sesiones por tramo sobre el MISMO motor que la peticion (en los tests,
    # SQLite): SessionLocal iria siempre a la BD configurada.
    from sqlalchemy.orm import sessionmaker
    Sesion = sessionmaker(bind=db.get_bind())

    def filas():
        buf = io.StringIO()
        w = csv.writer(buf)
        buf.write("\ufeff")  # BOM: Excel abre el UTF-8 con las tildes bien
        w.writerow([cab for _, cab, _, _ in cabeceras])
        yield buf.getvalue()
        for i in range(0, len(ids), 1000):
            tramo = ids[i:i + 1000]
            with Sesion() as s:
                por_id = {u.id: u for u in s.query(Url).options(joinedload(Url.html_meta))
                          .filter(Url.id.in_(tramo)).all()}
                if {"enlazada_desde", "origenes"} & set(claves):
                    o = _origenes(s, job_id, [u.url_hash for u in por_id.values()])
                    for u in por_id.values():
                        u._origen = o.get(u.url_hash, (None, 0))
                if "cambio" in claves:
                    cs = _cambios(s, ref, list(por_id.values()))
                    for u in por_id.values():
                        u._cambio = cs.get(u.id)
                if {"h1", "h1_count"} & set(claves):
                    hs = _h1s(s, list(por_id))
                    for u in por_id.values():
                        u._h1 = hs.get(u.id, (None, 0))
                xs = _a_medida(s, job_id, list(por_id), nombres_x) if nombres_x else {}
                buf = io.StringIO()
                w = csv.writer(buf)
                for uid in tramo:
                    u = por_id.get(uid)
                    if u is None:
                        continue
                    fila = []
                    for c, _cab, nombre, pos in cabeceras:
                        if nombre:
                            clase, regla = reglas[nombre]
                            fila.append(valor_csv_a_medida(xs.get(uid, {}).get(nombre), clase, regla, pos))
                        else:
                            v = COLUMNAS_VISTA[c][1](u)
                            # Una celda de texto de la pagina (titulo, url, anchor)
                            # que empiece por `=`/`+`/`-`/`@` se escapa para que
                            # la hoja de calculo no la ejecute (decision 207).
                            fila.append("" if v is None else celda_segura(v))
                    w.writerow(fila)
                yield buf.getvalue()

    nombre = f"explorador-{str(job_id)[:8]}-{len(ids)}-urls.csv"
    return StreamingResponse(filas(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/urls/enlaces-entrantes  -- de donde se enlaza la vista
# ---------------------------------------------------------------------------
@router.get("/urls/enlaces-entrantes")
def export_enlaces_entrantes(
    job_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_session),
):
    """Todos los enlaces que apuntan a las URLs de la vista, como CSV: destino,
    su codigo, origen, ancla, posicion y follow. Es la lista que se le pasa a
    quien tiene que corregir los enlaces a 404 o a redirecciones (#131).

    Se recorre por tramos de 500 destinos con el indice (job_id, to_url_hash).
    """
    _get_job_or_404(job_id, db)
    _anotar_uso(request.query_params, csv=True)
    destinos = _urls_filtradas(db, job_id, request.query_params).with_entities(
        Url.url_hash, Url.url, Url.status_code).order_by(Url.id).all()
    from sqlalchemy.orm import aliased, sessionmaker

    Sesion = sessionmaker(bind=db.get_bind())
    Origen = aliased(Url)
    archivado = _job_archivado(db, job_id)

    def filas():
        buf = io.StringIO()
        w = csv.writer(buf)
        buf.write("\ufeff")
        w.writerow(["Destino", "Estado destino", "Origen", "Estado origen", "Ancla", "Posición", "Follow", "Tipo"])
        yield buf.getvalue()
        for i in range(0, len(destinos), 500):
            tramo = {h: (u, c) for h, u, c in destinos[i:i + 500]}
            with Sesion() as s:
                if archivado:
                    crudas = [f for f in archivo_enlaces.leer(job_id, a_hashes=list(tramo))
                              if _es_enlace(f["link_type"])]
                    urls = _urls_de(s, (f["from_url_id"] for f in crudas))
                    enlaces = sorted(
                        ((f["to_url_hash"], *urls.get(f["from_url_id"], ("", None)),
                          f["anchor_text"], f["link_position"], f["follow"], f["link_type"])
                         for f in crudas),
                        key=lambda e: (e[0], e[1] or ""))
                else:
                    enlaces = None
                enlaces = enlaces if enlaces is not None else (
                    s.query(Link.to_url_hash, Origen.url, Origen.status_code, Link.anchor_text,
                            Link.link_position, Link.follow, Link.link_type)
                    .join(Origen, Origen.id == Link.from_url_id)
                    .filter(Link.job_id == job_id, Link.to_url_hash.in_(list(tramo)),
                            or_(Link.link_type.is_(None), Link.link_type.notin_(_TIPOS_NO_ENLACE)))
                    .order_by(Link.to_url_hash, Origen.url)
                    .all()
                )
            buf = io.StringIO()
            w = csv.writer(buf)
            for h, origen, cod_origen, ancla, pos, follow, tipo in enlaces:
                destino, cod = tramo[h]
                # Ancla, destino y origen vienen de la pagina: se escapan para que
                # una hoja de calculo no los ejecute como formula (decision 207).
                w.writerow([celda_segura(destino), cod, celda_segura(origen), cod_origen,
                            celda_segura(ancla or ""), pos or "",
                            "si" if follow else "no", tipo or ""])
            yield buf.getvalue()

    nombre = f"enlaces-entrantes-{str(job_id)[:8]}-{len(destinos)}-destinos.csv"
    return StreamingResponse(filas(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


def _sitemaps_de_url(db: Session, job_id: uuid.UUID, url_hash: str) -> list[dict]:
    """Los ficheros de sitemap que declaran la URL, con su lastmod (decision
    126) y su hreflang (decision 167: [[idioma, href]], o None si no se sabe).
    Por el indice (job_id, url_hash). Sin tabla, lista vacia: es un dato
    opcional del censo, como las capturas."""
    from shared.models import SitemapEntry as E
    from shared.sitemaps import expandir_hreflang

    try:
        with db.begin_nested():
            filas = (db.query(E.fichero, E.lastmod, E.url, E.hreflang)
                     .filter(E.job_id == job_id, E.url_hash == url_hash)
                     .order_by(E.fichero).all())
    except Exception:  # noqa: BLE001
        return []
    salida = []
    for f, lm, url, hl in filas:
        pares = expandir_hreflang(url, hl)
        salida.append({"fichero": f, "lastmod": lm,
                       "hreflang": None if pares is None else [list(p) for p in pares]})
    return salida


def _capturas_alternativas(db: Session, job_id: uuid.UUID, url_id: int) -> list[dict]:
    """Las capturas de la URL con otro perfil (decision 119), una por perfil.

    Sin tabla (una base que aun no paso `init_db`) la ficha sale sin ellas en
    vez de dar un 500: es un dato opcional del censo.
    """
    from shared.models import CapturaAlternativa as C

    try:
        with db.begin_nested():
            filas = (db.query(C).filter(C.job_id == job_id, C.url_id == url_id)
                     .order_by(C.perfil).all())
    except Exception:  # noqa: BLE001
        return []
    return [{
        "perfil": c.perfil, "modo": c.modo, "estado": c.estado, "plantilla": c.plantilla,
        "user_agent": c.user_agent, "status_code": c.status_code,
        "response_class": c.response_class, "redirige_a": c.redirige_a,
        "vary_base": c.vary_base, "vary": c.vary, "medidas": c.medidas,
        "diferencias": c.diferencias or [], "volatiles": c.volatiles or [],
        "detalle": c.detalle,
        "capturada_at": c.capturada_at.isoformat() if c.capturada_at else None,
    } for c in filas]


def _capturas_pantalla(job_id: uuid.UUID, url_obj: Url) -> list[dict]:
    """Las capturas de pantalla de la URL (decision 173), con la ruta de su
    imagen. Del volumen de archivo, por `url_hash`; vacia si no hay."""
    from shared import capturas_pantalla

    return [{**m, "src": f"/api/jobs/{job_id}/urls/{url_obj.id}/captura/{m['perfil']}"}
            for m in capturas_pantalla.de_url(job_id, url_obj.url_hash)]


@router.get("/capturas")
def listar_capturas(job_id: uuid.UUID, db: Session = Depends(get_session)):
    """Las capturas de pantalla del censo (decision 173): metadatos, sin la
    imagen. `capturas_muestra` en `crawl_behavior` las enciende; sin ella la
    lista sale vacia, que no es lo mismo que «la pagina no se pinta»."""
    from shared import capturas_pantalla

    job = _get_job_or_404(job_id, db)
    cb = (job.config or {}).get("crawl_behavior") or {}
    return {"job_id": str(job_id), "pedidas": int(cb.get("capturas_muestra") or 0),
            "capturas": capturas_pantalla.listar(job_id)}


@router.get("/urls/{url_id}/captura/{perfil}")
def imagen_de_captura(job_id: uuid.UUID, url_id: int, perfil: str,
                      db: Session = Depends(get_session)):
    """El JPEG de la captura de una URL con un perfil (decision 173)."""
    from fastapi.responses import FileResponse

    from shared import capturas_pantalla

    if perfil not in capturas_pantalla.PERFILES:
        raise HTTPException(status_code=404, detail="Perfil desconocido")
    url_hash = db.query(Url.url_hash).filter(Url.id == url_id, Url.job_id == job_id).scalar()
    if not url_hash:
        raise HTTPException(status_code=404, detail="URL no encontrada en este censo")
    ruta = capturas_pantalla.ruta_imagen(job_id, url_hash, perfil)
    if not ruta.is_file():
        raise HTTPException(status_code=404, detail="Esta URL no tiene captura con ese perfil")
    # Privada: la imagen es del censo de un cliente y la API pide token.
    return FileResponse(ruta, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/urls/{url_id}  -- full detail for a single URL
# ---------------------------------------------------------------------------
def _filas_robots(db: Session, job_id: uuid.UUID, host: str | None = None,
                  con_cuerpo: bool = True) -> dict[str, Any]:
    """Las filas de `robots_txt` del job por origen; la primera de cada uno.

    `host` limita a las de ese host: la ficha de una URL solo necesita la suya,
    y cada fila lleva hasta 500 KiB de cuerpo (hasta 200 hosts por job). Sin
    `con_cuerpo` el cuerpo no se lee (`GET /robots` no lo devuelve).
    """
    from sqlalchemy.orm import defer

    from shared.models import RobotsTxt
    from shared.robots_txt import origen

    filas: dict[str, Any] = {}
    try:
        with db.begin_nested():
            q = db.query(RobotsTxt).filter(RobotsTxt.job_id == job_id)
            if host is not None:
                q = q.filter(RobotsTxt.host == host)
            if not con_cuerpo:
                q = q.options(defer(RobotsTxt.cuerpo))
            for fila in q.order_by(RobotsTxt.id):
                o = origen(fila.url)
                if o is not None and o not in filas:
                    filas[o] = fila
    except Exception:  # noqa: BLE001 -- una base sin la tabla: sin robots.txt
        return {}
    return filas


def _robots_regla(db: Session, job_id: uuid.UUID, url_obj: Url) -> dict[str, Any] | None:
    """La linea que bloquea la URL (decision 129). Se calcula al pedir la
    ficha con el cuerpo guardado: vale para cualquier censo con `robots_txt`,
    sin re-rastrear ni re-analizar."""
    from shared.config import DEFAULT_USER_AGENT
    from shared.robots_regla import reglas_de_url
    from shared.robots_txt import origen

    bloqueada_rastreo = bool(url_obj.blocked_by_robots) or (
        url_obj.status_code is None
        and (url_obj.indexability_status or "").startswith("Blocked by robots"))
    if not (url_obj.bloqueada_googlebot or bloqueada_rastreo):
        return None
    o = origen(url_obj.url)
    if o is None:
        return None
    from urllib.parse import urlsplit

    fila = _filas_robots(db, job_id, host=(urlsplit(o).hostname or "")).get(o)
    if fila is None:
        return None
    job = db.get(Job, job_id)
    config = (job.config or {}) if job else {}
    try:
        return reglas_de_url(
            fila, url_obj.url, bloqueada_googlebot=url_obj.bloqueada_googlebot,
            blocked_by_robots=bloqueada_rastreo,
            user_agent=config.get("user_agent") or DEFAULT_USER_AGENT,
            robots_mode=config.get("robots_mode"))
    except Exception:  # noqa: BLE001 -- la linea es un extra de la ficha
        return None


@router.get("/robots")
def get_robots(job_id: uuid.UUID, db: Session = Depends(get_session)):
    """robots.txt de cada host del censo y que bloquea cada bot (decision 129).

    `bots` es el catalogo (token, proveedor y tipo: buscador, busqueda_ia,
    usuario_ia o entrenamiento); `hosts[].bots` lo que escribio el analisis
    para la home y la muestra por plantilla. Un censo analizado antes de la
    decision 129 trae `hosts[].bots` a None: hay que re-analizarlo.
    """
    from shared.robots_regla import estado_guardado
    from shared.robots_txt import BOTS_INFO

    _get_job_or_404(job_id, db)
    hosts = []
    for o, fila in sorted(_filas_robots(db, job_id, con_cuerpo=False).items()):
        ev = fila.evaluacion if isinstance(fila.evaluacion, dict) else {}
        hosts.append({
            "origen": o, "host": fila.host, "url": fila.url, "url_final": fila.url_final,
            "status_code": fila.status_code, "error": fila.error,
            "estado": estado_guardado(fila), "bytes": fila.bytes, "sha256": fila.sha256,
            "recortado": fila.recortado, "fecha": fila.fecha,
            "googlebot": ev.get("googlebot"), "bots": ev.get("bots"),
        })
    return {"bots": BOTS_INFO, "hosts": hosts}


@router.get("/robots/cuerpo")
def get_robots_cuerpo(job_id: uuid.UUID, origen: str = Query(..., max_length=300),
                      db: Session = Depends(get_session)):
    """El robots.txt guardado de un origen del censo, en texto: el punto de
    partida del robots.txt de prueba (decision 171). 404 si no hay fila o se
    guardo sin cuerpo (no respondio, o no era un 2xx)."""
    from urllib.parse import urlsplit

    from shared.robots_txt import origen as origen_de

    _get_job_or_404(job_id, db)
    o = origen_de(origen) or origen
    fila = _filas_robots(db, job_id, host=(urlsplit(o).hostname or "")).get(o)
    if fila is None or fila.cuerpo is None:
        raise HTTPException(404, "No hay robots.txt guardado de ese origen en este censo")
    return {"origen": o, "url": fila.url, "cuerpo": fila.cuerpo,
            "recortado": fila.recortado, "fecha": fila.fecha}
@router.get("/accesibilidad")
def get_accesibilidad(job_id: uuid.UUID, db: Session = Depends(get_session)):
    """Accesibilidad con axe-core por muestra de plantilla (decision 174).

    `pedida`: si el job tenia `crawl_behavior.axe_muestra` > 0. `paginas`:
    capturas por estado y motivo de las no evaluadas. `reglas`: las
    violaciones por regla (WCAG 2.x A/AA), de mas a menos grave, con sus
    plantillas (paginas afectadas sobre muestreadas); son las mismas que los
    avisos `accesibilidad_*`. `incompletas`: lo que axe no pudo decidir, que
    NO se afirma. `coste`: milisegundos de axe y de la descarga entera (render
    y axe) por pagina evaluada. Sin capturas (apagado o rastreo anterior),
    `reglas` va vacio y `paginas.evaluadas` a 0: nunca «sin problemas».
    """
    from shared.accesibilidad import PERFIL, agregar, filas_evaluadas, por_regla
    from shared.models import CapturaAlternativa as C

    job = _get_job_or_404(job_id, db)
    cb = (job.config or {}).get("crawl_behavior") or {}
    salida: dict[str, Any] = {
        "pedida": int(cb.get("axe_muestra") or 0) > 0,
        "muestra": int(cb.get("axe_muestra") or 0), "por_plantilla": cb.get("axe_por_plantilla"),
        "axe": None, "paginas": {"evaluadas": 0, "no_evaluadas": 0, "motivos": {}},
        "plantillas": 0, "reglas": [], "incompletas": [], "coste": None,
    }
    try:
        with db.begin_nested():
            capturas = (db.query(C.url_id, C.estado, C.detalle, C.medidas)
                        .filter(C.job_id == job_id, C.perfil == PERFIL).all())
            filas = filas_evaluadas(db, job_id)
    except Exception:  # noqa: BLE001 -- sin tabla: un dato opcional del censo
        return salida
    validas = {f[0] for f in filas}
    ms_axe, ms_total = [], []
    for url_id, estado, detalle, medidas in capturas:
        detalle = detalle if isinstance(detalle, dict) else {}
        if url_id in validas:
            salida["paginas"]["evaluadas"] += 1
            if isinstance(detalle.get("ms_axe"), (int, float)):
                ms_axe.append(detalle["ms_axe"])
            if isinstance(detalle.get("ms_total"), (int, float)):
                ms_total.append(detalle["ms_total"])
            if isinstance(medidas, dict) and medidas.get("axe"):
                salida["axe"] = medidas["axe"]
            continue
        # Evaluada, pero la pagina del censo ya no es una HTML 2xx valida: no
        # cuenta, como en los avisos.
        motivo = "pagina_del_censo_no_valida" if estado == "evaluada" else (detalle.get("motivo") or "?")
        salida["paginas"]["no_evaluadas"] += 1
        salida["paginas"]["motivos"][motivo] = salida["paginas"]["motivos"].get(motivo, 0) + 1
    datos = agregar(filas)
    salida["plantillas"] = len(datos["muestreadas"])
    salida["reglas"] = por_regla(datos["violaciones"], datos["muestreadas"])
    salida["incompletas"] = por_regla(datos["incompletas"], datos["muestreadas"])

    def mediana(v: list) -> int | None:
        v = sorted(v)
        return round(v[len(v) // 2]) if v else None

    if ms_axe or ms_total:
        salida["coste"] = {
            "ms_axe_mediana": mediana(ms_axe), "ms_axe_max": round(max(ms_axe)) if ms_axe else None,
            "ms_pagina_mediana": mediana(ms_total),
            "s_total": round(sum(ms_total) / 1000, 1) if ms_total else None,
        }
    return salida


# ---------------------------------------------------------------------------
# WordPress por su REST API (decision 161)
# ---------------------------------------------------------------------------
@router.get("/wordpress")
def get_wordpress(job_id: uuid.UUID, db: Session = Depends(get_session)):
    """Lo que leyo el adaptador WordPress y lo que hay de cada tipo.

    `resumen` es `jobs.adapters["wordpress"]` tal cual (detectado, estado de la
    REST API, plugin SEO, totales de `X-WP-Total`, si se corto, y el
    `analisis`: lo que se afirmo y lo que no, y por que). `por_tipo`, cuantas
    entidades se leyeron y cuantas estan en el censo, por (job_id, url_hash).
    NULL en `resumen` = rastreo anterior o adaptador apagado.
    """
    from shared.models import AdapterEntity as E

    job = _get_job_or_404(job_id, db)
    resumen = (job.adapters or {}).get("wordpress") if job.adapters else None
    # Como el analisis: por `url_hash` o por la misma URL con el otro esquema.
    en_censo = exists().where(Url.job_id == E.job_id,
                              or_(Url.url_hash == E.url_hash, Url.url_hash == E.url_hash_alt))
    filas = (
        db.query(E.tipo, func.count(E.id), func.sum(case((en_censo, 1), else_=0)))
        .filter(E.job_id == job_id, E.adaptador == "wordpress")
        .group_by(E.tipo).order_by(E.tipo).all()
    )
    return {
        "resumen": resumen,
        "por_tipo": [{"tipo": t, "leidas": int(n), "en_el_censo": int(c or 0)}
                     for t, n, c in filas],
    }


@router.get("/wordpress/entidades")
def get_wordpress_entidades(
    job_id: uuid.UUID,
    tipo: str | None = Query(None, max_length=64),
    solo_no_rastreadas: bool = False,
    buscar: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_session),
):
    """Entidades de la REST API de WordPress (y sus sondas), paginadas.

    `solo_no_rastreadas=true` deja las que no tienen fila en `urls` (ni con
    el otro esquema): la lista «solo en WordPress» del Explorador (decision
    168), sin las sondas, que no son entidades del sitio sino peticiones del
    adaptador. Que no esten en el censo no es por si solo un hallazgo: en un
    censo truncado o cortado por la profundidad no se afirma (ver
    `resumen.analisis` en `/wordpress`). `buscar`, texto dentro de la URL.
    """
    from shared.models import AdapterEntity as E

    _get_job_or_404(job_id, db)
    q = db.query(E).filter(E.job_id == job_id, E.adaptador == "wordpress")
    if tipo:
        q = q.filter(E.tipo == tipo)
    if buscar:
        q = q.filter(E.url.icontains(buscar, autoescape=True))
    if solo_no_rastreadas:
        q = q.filter(
            ~E.tipo.startswith("sonda_", autoescape=True),
            ~exists().where(Url.job_id == E.job_id, Url.url_hash == E.url_hash),
            or_(E.url_hash_alt.is_(None),
                ~exists().where(Url.job_id == E.job_id, Url.url_hash == E.url_hash_alt)),
        )
    total = q.count()
    filas = q.order_by(E.tipo, E.url, E.id).offset((page - 1) * page_size).limit(page_size).all()
    items = [{
        "tipo": e.tipo, "id_externo": e.id_externo, "url": e.url, "en_alcance": e.en_alcance,
        "estado": e.estado, "status_code": e.status_code, "cuenta": e.cuenta,
        "modificado": e.modificado, "datos": e.datos,
    } for e in filas]
    return _paginate(items, total, page, page_size)


# Plugins y tema por la ruta de sus ficheros (decision 168). El nombre sale de
# la carpeta (`/wp-content/plugins/<slug>/`): eso es fiable, el fichero esta
# ahi. El `?ver=` no tanto: lo pone quien encola el fichero y, si no pasa
# version, WordPress pone la suya; WP Rocket y similares sirven copias en
# `/wp-content/cache/` con un numero de cache. Solo cuenta como version un
# `ver` con forma de version (con un punto) y fuera de una copia de cache.
_RE_WP_ASSET = re.compile(r"/wp-content/(plugins|themes)/([A-Za-z0-9._-]{1,100})/")
_RE_WP_VER = re.compile(r"[?&]ver=([^&#]{1,40})")
# Cada tramo opcional empieza por su separador: sin ambiguedad al partir, asi
# un `ver` raro no hace retroceder la regex de forma exponencial.
_RE_FORMA_VERSION = re.compile(r"^\d+(\.\d+)+[A-Za-z0-9]*([.-][A-Za-z0-9]+)*$")
WP_ASSETS_MUESTRA = 2000


def _inventario_wp(filas, version_wp: str | None) -> dict[str, list[dict]]:
    """`filas` = (resource_url, paginas). Plugins y temas con las paginas en
    las que aparece cada uno (la mayor de sus ficheros: un mismo plugin carga
    varios en la misma pagina) y las versiones vistas, de mas a menos paginas."""
    grupos: dict[tuple[str, str], dict] = {}
    for url, paginas in filas:
        m = _RE_WP_ASSET.search(url or "")
        if not m:
            continue
        clase = "plugins" if m.group(1) == "plugins" else "temas"
        g = grupos.setdefault((clase, m.group(2)), {"slug": m.group(2), "paginas": 0,
                                                    "versiones": {}})
        g["paginas"] = max(g["paginas"], int(paginas or 0))
        v = _RE_WP_VER.search(url)
        if v and "/wp-content/cache/" not in url and _RE_FORMA_VERSION.match(v.group(1)):
            g["versiones"][v.group(1)] = max(g["versiones"].get(v.group(1), 0), int(paginas or 0))
    salida: dict[str, list[dict]] = {"plugins": [], "temas": []}
    for (clase, _), g in sorted(grupos.items(), key=lambda kv: (-kv[1]["paginas"], kv[0][1])):
        salida[clase].append({
            "slug": g["slug"], "paginas": g["paginas"],
            "versiones": [{"version": v, "paginas": n,
                           "igual_que_wordpress": bool(version_wp) and v == version_wp}
                          for v, n in sorted(g["versiones"].items(), key=lambda kv: -kv[1])],
        })
    return salida


@router.get("/wordpress/assets")
def get_wordpress_assets(
    job_id: uuid.UUID,
    muestra: int = Query(WP_ASSETS_MUESTRA, ge=1, le=20_000),
    db: Session = Depends(get_session),
):
    """Plugins y tema de un WordPress por los CSS y JS que cargan sus paginas
    (decision 168), en las primeras `muestra` paginas HTML del censo (las
    menos profundas primero, que cubren las plantillas; a igual profundidad,
    por orden de rastreo).

    Lo que no sale aqui no se afirma que no exista: un plugin sin CSS ni JS
    propios, uno que solo carga en una plantilla fuera de la muestra, o un
    sitio que renombra `wp-content`. Con la muestra entera de Lopesan
    (5.700 paginas) la consulta tarda 3 s en produccion: por eso la muestra.
    """
    from shared.models import Resource

    job = _get_job_or_404(job_id, db)
    resumen = ((job.adapters or {}).get("wordpress") or {}) if job.adapters else {}
    # Los ids primero y luego `url_id IN (...)` por lotes: con la subconsulta
    # dentro, Postgres estimaba mal y recorria `resources` entera (9,7 M filas,
    # 2,6 s en produccion); con la lista va por `ix_resources_url_id` (0,75 s).
    # Por profundidad y no solo por `id`: con `ORDER BY id LIMIT` Postgres podia
    # recorrer `urls_pkey` filtrando el job, y leer las filas de todos los jobs
    # con ids anteriores (coste que crece con la base, no con el censo). Sin
    # indice que de este orden, entra por el `job_id` y ordena lo del job.
    ids = [i for (i,) in db.execute(
        select(Url.id).where(Url.job_id == job_id, Url.is_html.is_(True))
        .order_by(Url.crawl_depth.asc().nulls_last(), Url.id).limit(muestra))]
    por_url: dict[str, int] = {}
    for n in range(0, len(ids), 1000):
        for recurso, paginas in db.execute(
                select(Resource.resource_url, func.count(func.distinct(Resource.url_id)))
                .where(Resource.url_id.in_(ids[n:n + 1000]),
                       Resource.resource_type.in_(("css", "js")),
                       Resource.resource_url.like("%/wp-content/%"))
                .group_by(Resource.resource_url)):
            # Lotes de paginas distintas: las cuentas se suman sin repetir.
            por_url[recurso] = por_url.get(recurso, 0) + int(paginas)
    return {"paginas_miradas": len(ids), "muestra": muestra,
            "version_wordpress": resumen.get("version"),
            **_inventario_wp(por_url.items(), resumen.get("version"))}


def _wordpress_de_url(db: Session, job_id: uuid.UUID, url_hash: str | None) -> list[dict]:
    """Las entidades de la REST API de WordPress que son esta URL (decision
    168): por `url_hash` (indice `ix_adent_job_hash`) o por `url_hash_alt`, la
    misma URL con el otro esquema (indice `ix_adent_job_hash_alt`), como el
    analisis: con los dos indices el OR es un BitmapOr y no un recorrido de
    todas las entidades del job cada vez que se abre una ficha. Sin las sondas, que no
    son entidades. Sin tabla, lista vacia (dato opcional, como los sitemaps)."""
    from shared.models import AdapterEntity as E

    if not url_hash:
        return []
    try:
        with db.begin_nested():
            filas = (db.query(E.tipo, E.id_externo, E.estado, E.modificado, E.cuenta, E.url)
                     .filter(E.job_id == job_id, E.adaptador == "wordpress",
                             or_(E.url_hash == url_hash, E.url_hash_alt == url_hash),
                             ~E.tipo.startswith("sonda_", autoescape=True))
                     .order_by(E.tipo, E.id).limit(20).all())
    except Exception:  # noqa: BLE001
        return []
    return [{"tipo": t, "id": i, "estado": st, "modificado": m, "cuenta": c, "url": u}
            for t, i, st, m, c, u in filas]


def _inspeccion_google(db: Session, job: Job, url_obj: Url) -> dict | None:
    """La ultima inspeccion de Google de esta URL (decision 189, sobre la 144):
    si la tiene indexada y que canonical elige. Es una muestra diaria y
    rotatoria del CLIENTE, no del censo, y `gsc_inspecciones` guarda una fila
    por URL que se reescribe en cada inspeccion: va con su fecha y la de la
    ultima visita de Google. Solo se compara con la canonical que declaraba la
    pagina EN ESTE CENSO si la inspeccion cae en la ventana de la 144 (30 dias
    antes, 14 despues; `shared.gsc.ventana_de_inspeccion`, la misma de los
    avisos): fuera de ella, comparar dos fechas distintas no dice nada y la
    tarjeta contradiria a los avisos de la misma ficha. Las comparaciones, con
    `shared.indexabilidad.misma_url`, la regla del analisis. Sin cliente, sin
    inspeccion o sin la tabla: None. Best-effort: el `try` cubre la funcion
    entera (decision 40)."""
    try:
        if not getattr(job, "cliente_id", None):
            return None
        from shared.gsc import clave_de_url, ventana_de_inspeccion
        from shared.indexabilidad import misma_url
        from shared.models import GscInspeccion as G

        with db.begin_nested():
            fila = (db.query(G)
                    .filter(G.cliente_id == job.cliente_id, G.url_clave == clave_de_url(url_obj.url),
                            G.error.is_(None))
                    .order_by(G.fecha.desc()).first())
        if fila is None:
            return None
        desde, hasta = ventana_de_inspeccion(job)
        fecha = fila.fecha
        if fecha is not None and fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)
        en_ventana = fecha is not None and desde <= fecha <= hasta
        meta = url_obj.html_meta
        declarado = (meta.canonical_href or meta.canonical_header) if meta else None
        declarado = declarado or url_obj.url

        def _igual(a, b):
            return misma_url(a, b) if en_ventana and a and b else None

        return {
            "fecha": fila.fecha.isoformat() if fila.fecha else None,
            "ultimo_rastreo": fila.ultimo_rastreo.isoformat() if fila.ultimo_rastreo else None,
            "verdict": fila.verdict,
            "cobertura": fila.cobertura,
            "canonical_google": fila.canonical_google,
            "canonical_visto": fila.canonical_usuario,
            # La inspeccion vale para este censo (ventana de la decision 144)
            "en_ventana_del_censo": en_ventana,
            # Google eligio la misma que vio declarada (None: falta alguna).
            # No depende del censo: las dos son de la inspeccion.
            "google_acepta": (misma_url(fila.canonical_google, fila.canonical_usuario)
                              if fila.canonical_google and fila.canonical_usuario else None),
            # Lo que Google vio declarado es lo que declaraba la pagina en este
            # censo: si no, su eleccion es de una version anterior (144).
            "visto_igual_que_censo": _igual(fila.canonical_usuario, declarado),
            # La que elige Google es la que declaraba la pagina en este censo:
            # con lo visto distinto, Google ya la sigue y no hay que esperar.
            "google_igual_que_censo": _igual(fila.canonical_google, declarado),
        }
    except Exception:  # noqa: BLE001
        return None


@router.get("/urls/{url_id}", response_model=UrlDetailResponse)
def get_url_detail(
    job_id: uuid.UUID,
    url_id: int,
    db: Session = Depends(get_session),
):
    job = _get_job_or_404(job_id, db)

    url_obj = (
        db.query(Url)
        .options(
            joinedload(Url.html_meta),
            joinedload(Url.page_content),
            joinedload(Url.security),
            subqueryload(Url.headings),
            subqueryload(Url.hreflangs),
            subqueryload(Url.structured_data),
            subqueryload(Url.resources),
            subqueryload(Url.issues),
        )
        .filter(Url.id == url_id, Url.job_id == job_id)
        .first()
    )
    if url_obj is None:
        raise HTTPException(status_code=404, detail="URL not found")

    # Build outlinks using a join to get from_url string directly
    from sqlalchemy.orm import aliased
    UrlAlias = aliased(Url)

    if _job_archivado(db, job_id):
        def _fila(lk):
            return lk, lk.from_url_rel.url
        salientes = sorted(archivo_enlaces.leer(job_id, de_url_id=url_id), key=lambda f: f["id"])
        entrantes = sorted(archivo_enlaces.leer(job_id, a_hashes=[url_obj.url_hash]),
                           key=lambda f: f["id"])
        outlink_rows = [_fila(lk) for lk in _como_links(db, job_id, salientes[:200])]
        inlink_rows = [_fila(lk) for lk in _como_links(db, job_id, entrantes[:200])]
    else:
        outlink_rows = inlink_rows = None

    outlink_rows = outlink_rows if outlink_rows is not None else (
        db.query(Link, UrlAlias.url.label("src_url"))
        .outerjoin(UrlAlias, Link.from_url_id == UrlAlias.id)
        .filter(Link.from_url_id == url_id)
        .order_by(Link.id)
        .limit(200)
        .all()
    )

    # Build inlinks using to_url_hash match
    inlink_rows = inlink_rows if inlink_rows is not None else (
        db.query(Link, UrlAlias.url.label("src_url"))
        .outerjoin(UrlAlias, Link.from_url_id == UrlAlias.id)
        .filter(Link.job_id == job_id, Link.to_url_hash == url_obj.url_hash)
        .order_by(Link.id)
        .limit(200)
        .all()
    )

    # Serialize
    resp = UrlDetailResponse.model_validate(url_obj)
    resp.headings = [HeadingResponse.model_validate(h) for h in url_obj.headings]
    resp.resources = [ResourceResponse.model_validate(r) for r in url_obj.resources]
    resp.hreflangs = [HreflangResponse.model_validate(h) for h in url_obj.hreflangs]
    resp.structured_data = [StructuredDataResponse.model_validate(s) for s in url_obj.structured_data]
    resp.security = SecurityHeadersResponse.model_validate(url_obj.security) if url_obj.security else None
    resp.issues = [IssueResponse.model_validate(i) for i in url_obj.issues]
    # La ficha lleva todas las reglas a medida evaluadas en la URL (decision 104)
    resp.a_medida = _a_medida(db, job_id, [url_obj.id]).get(url_obj.id, {})
    resp.capturas_alternativas = _capturas_alternativas(db, job_id, url_obj.id)
    resp.capturas_pantalla = _capturas_pantalla(job_id, url_obj)
    resp.robots_regla = _robots_regla(db, job_id, url_obj)
    resp.sitemaps = _sitemaps_de_url(db, job_id, url_obj.url_hash)
    resp.wordpress = _wordpress_de_url(db, job_id, url_obj.url_hash)
    resp.google_inspeccion = _inspeccion_google(db, job, url_obj)

    out_items = []
    for link_obj, src_url in outlink_rows:
        item = LinkResponse.model_validate(link_obj)
        item.from_url = src_url
        out_items.append(item)
    resp.outlinks = out_items

    in_items = []
    for link_obj, src_url in inlink_rows:
        item = LinkResponse.model_validate(link_obj)
        item.from_url = src_url
        in_items.append(item)
    resp.inlinks = in_items

    return resp


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/issues
# ---------------------------------------------------------------------------
@router.get("/issues", response_model=PaginatedResponse[IssueResponse])
def list_issues(
    job_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    severity: str | None = Query(None),
    issue_type: str | None = Query(None),
    segmento: list[str] | None = Query(None, description="Solo las de paginas de esos segmentos (decision 125)"),
    db: Session = Depends(get_session),
):
    _get_job_or_404(job_id, db)

    q = db.query(Issue).filter(Issue.job_id == job_id)
    segs = [x for x in (segmento or []) if x]
    if segs:
        q = q.filter(Issue.url_id.in_(urls_de_segmentos(db, job_id, segs)), incidencia_por_pagina())

    if severity is not None:
        q = q.filter(Issue.severity == severity)
    if issue_type is not None:
        q = q.filter(Issue.issue_type == issue_type)

    total = q.count()

    # Por gravedad y luego por tipo: ordenado por `id` salian los `info`
    # (noindex) por delante de los avisos y los errores quedaban repartidos
    # en el orden en que los escribio el analisis (UX-04).
    gravedad = case(
        (Issue.severity == "error", 0),
        (Issue.severity == "warning", 1),
        (Issue.severity == "info", 2),
        else_=3,
    )
    rows = (
        q.options(joinedload(Issue.url_rel))
        .order_by(gravedad, Issue.issue_type, Issue.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = []
    for r in rows:
        resp = IssueResponse.model_validate(r)
        if r.url_rel:
            resp.url = r.url_rel.url
        items.append(resp)

    return _paginate(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/issues/resumen — una fila por tipo de incidencia
# ---------------------------------------------------------------------------
class _EjemploIssue(BaseModel):
    url_id: int
    url: str | None = None


class _PorSegmento(BaseModel):
    segmento: str | None
    paginas: int          # paginas del segmento con esta incidencia
    urls: int             # URLs del segmento: el denominador
    pct: float            # paginas / urls, en %


class _ResumenIssue(BaseModel):
    issue_type: str
    severity: str
    incidencias: int
    paginas: int
    ejemplos: list[_EjemploIssue] = []
    # Decision 125. Con `?segmento=`: sobre las URLs de esos segmentos.
    urls_denominador: int | None = None
    pct_paginas: float | None = None
    # Con `?por_segmento=true`: los segmentos con mas paginas afectadas, y
    # cuantas incidencias de este tipo NO se pueden repartir (una por
    # hallazgo, ver `incidencia_por_pagina`).
    por_segmento: list[_PorSegmento] | None = None
    agregadas: int | None = None
    # Decision 136 (Ola 4.3): suma de la importancia (0,1-1) de las paginas
    # afectadas —«paginas equivalentes»— y gravedad x eso. Lo que se arregla
    # primero.
    importancia: float | None = None
    prioridad: float | None = None
    # Paginas distintas con este tipo en CUALQUIER gravedad (decision 202):
    # la interfaz pinta una fila por tipo («39 aviso · 157 info») y sumar las
    # paginas de cada gravedad contaria dos veces la que tenga las dos.
    paginas_tipo: int | None = None


@router.get("/issues/resumen", response_model=list[_ResumenIssue])
def resumen_issues(
    job_id: uuid.UUID,
    ejemplos: int = Query(3, ge=0, le=10),
    segmento: list[str] | None = Query(None, description="Solo paginas de esos segmentos (decision 125)"),
    por_segmento: bool = Query(False, description="Anade el % de paginas afectadas por segmento"),
    segmentos_max: int = Query(10, ge=1, le=200),
    orden: Literal["gravedad", "prioridad"] = Query(
        "gravedad", description="prioridad = gravedad x importancia de las paginas (decision 136)"),
    db: Session = Depends(get_session),
):
    """Lo que enseña la vista agrupada de Problemas (UX-04): cuántas
    incidencias y cuántas PÁGINAS distintas de cada tipo, de más grave a menos.

    Las páginas van aparte de las incidencias porque no son lo mismo: un
    hreflang sin retorno emite una incidencia por idioma, y una imagen sin alt
    se cuenta una vez aunque esté en mil páginas (decisión 64).
    """
    _get_job_or_404(job_id, db)

    gravedad = case(
        (Issue.severity == "error", 0),
        (Issue.severity == "warning", 1),
        (Issue.severity == "info", 2),
        else_=3,
    )
    segs = [x for x in (segmento or []) if x]
    filtro_seg: list = []
    if segs:
        filtro_seg = [Issue.url_id.in_(urls_de_segmentos(db, job_id, segs)), incidencia_por_pagina()]
    filas = (
        db.query(
            Issue.issue_type, Issue.severity,
            func.count(Issue.id), func.count(func.distinct(Issue.url_id)),
        )
        .filter(Issue.job_id == job_id, *filtro_seg)
        .group_by(Issue.issue_type, Issue.severity)
        .order_by(gravedad, func.count(func.distinct(Issue.url_id)).desc(), Issue.issue_type)
        .all()
    )

    resultado = []
    for tipo, sev, n, paginas in filas:
        muestra = []
        if ejemplos:
            # Una consulta corta por tipo, por el indice (job_id, issue_type):
            # son unas decenas de tipos, y un ROW_NUMBER sobre todo el censo
            # (841.901 incidencias en el mayor) ordenaria filas que no se piden.
            # Paginas DISTINTAS: un hreflang sin retorno emite una incidencia
            # por idioma, y tres ejemplos de la misma URL no ensenan nada (y
            # repetian la clave del x-for de la interfaz).
            vistos: set[int] = set()
            for uid, u in (
                db.query(Issue.url_id, Url.url)
                .join(Url, Url.id == Issue.url_id)
                .filter(Issue.job_id == job_id, Issue.issue_type == tipo, Issue.severity == sev,
                        *filtro_seg)
                .order_by(Issue.id)
                .limit(ejemplos * 5)
                .all()
            ):
                if uid in vistos:
                    continue
                vistos.add(uid)
                muestra.append(_EjemploIssue(url_id=uid, url=u))
                if len(muestra) == ejemplos:
                    break
        resultado.append(_ResumenIssue(
            issue_type=tipo, severity=sev, incidencias=n, paginas=paginas, ejemplos=muestra,
        ))
    if segs or por_segmento:
        _anadir_segmentos(db, job_id, resultado, segs, por_segmento, segmentos_max)
    # Una consulta agrupada por tipo (decision 202), con el mismo filtro.
    por_tipo = dict(
        db.query(Issue.issue_type, func.count(func.distinct(Issue.url_id)))
        .filter(Issue.job_id == job_id, *filtro_seg)
        .group_by(Issue.issue_type).all())
    for r in resultado:
        r.paginas_tipo = int(por_tipo.get(r.issue_type, 0))
    _anadir_prioridad(db, job_id, resultado, filtro_seg)
    if orden == "prioridad":
        resultado.sort(key=lambda r: (-(r.prioridad or 0), _ORDEN_GRAVEDAD.get(r.severity, 3),
                                      -r.paginas, r.issue_type))
    return resultado


def _anadir_prioridad(db: Session, job_id: uuid.UUID, resultado: list, filtro_seg: list) -> None:
    """Decision 136. Dos consultas agrupadas sobre todo el censo, no una por
    tipo. Una incidencia de su pagina cuenta la importancia de esa pagina UNA
    vez (un hreflang sin retorno emite una por idioma); un hallazgo de muchas
    paginas (imagen de plantilla, cabecera por host) cuenta `paginas_afectadas`
    veces la de su pagina de anclaje, que es la unica que se conoce."""
    from shared.prioridad import expresion_importancia, prioridad

    imp = expresion_importancia(Url)
    pares = (
        db.query(Issue.issue_type.label("t"), Issue.severity.label("sv"), Issue.url_id.label("u"))
        .filter(Issue.job_id == job_id, incidencia_por_pagina(), *filtro_seg)
        .distinct()
        .subquery()
    )
    suma: dict[tuple[str, str], float] = {}
    for t, sv, v in (
        db.query(pares.c.t, pares.c.sv, func.sum(imp))
        .join(Url, Url.id == pares.c.u)
        .group_by(pares.c.t, pares.c.sv)
    ):
        suma[(t, sv)] = float(v or 0)
    if not filtro_seg:
        pa = Issue.details["paginas_afectadas"].as_integer()
        for t, sv, v in (
            db.query(Issue.issue_type, Issue.severity, func.sum(pa * imp))
            .join(Url, Url.id == Issue.url_id)
            .filter(Issue.job_id == job_id, incidencia_agregada())
            .group_by(Issue.issue_type, Issue.severity)
        ):
            suma[(t, sv)] = suma.get((t, sv), 0.0) + float(v or 0)
    # Tope: el sitio entero. Los hallazgos de plantilla se solapan (el mismo
    # logo sin alt en cinco variantes, cada una en todas las paginas).
    tope = float(
        db.query(func.sum(imp))
        .filter(Url.job_id == job_id, Url.is_internal.is_(True), Url.is_html.is_(True),
                Url.status_code >= 200, Url.status_code < 300)
        .scalar() or 0.0)
    for r in resultado:
        total = suma.get((r.issue_type, r.severity), 0.0)
        if tope:
            total = min(total, tope)
        r.importancia = round(total, 2)
        r.prioridad = prioridad(r.severity, total)


_ORDEN_GRAVEDAD = {"error": 0, "warning": 1, "info": 2}


def _anadir_segmentos(db: Session, job_id: uuid.UUID, resultado: list, segs: list[str],
                      por_segmento: bool, maximo: int) -> None:
    """El denominador es el numero de URLs del segmento, TODAS (con sus 404 y
    sus saltos): «el 12 % de las fichas» tiene que poder leerse sin preguntar
    sobre que. Tres consultas agrupadas, no una por tipo."""
    urls_por_seg = dict(
        db.query(Url.segmento, func.count(Url.id)).filter(Url.job_id == job_id)
        .group_by(Url.segmento).all())
    agregadas = dict(
        ((t, sv), n) for t, sv, n in
        db.query(Issue.issue_type, Issue.severity, func.count(Issue.id))
        .filter(Issue.job_id == job_id, incidencia_agregada())
        .group_by(Issue.issue_type, Issue.severity))
    if segs:
        # Un tipo que solo tiene hallazgos de muchas paginas no puede
        # desaparecer del filtro: se leeria «este segmento no tiene ninguno»
        # cuando es «no se puede repartir» (decisiones 67 y 89). Sale con 0
        # paginas y sus `agregadas`.
        vistos = {(r.issue_type, r.severity) for r in resultado}
        for (t, sv), n in agregadas.items():
            if (t, sv) not in vistos:
                resultado.append(_ResumenIssue(issue_type=t, severity=sv, incidencias=0, paginas=0))
        resultado.sort(key=lambda r: (_ORDEN_GRAVEDAD.get(r.severity, 3), -r.paginas, r.issue_type))
        den = sum(urls_por_seg.get(x, 0) for x in segs)
        for r in resultado:
            r.urls_denominador = den
            r.pct_paginas = round(100.0 * r.paginas / den, 2) if den else None
    for r in resultado:
        r.agregadas = agregadas.get((r.issue_type, r.severity), 0)
    if not por_segmento:
        return
    cond = [Issue.job_id == job_id, incidencia_por_pagina()]
    if segs:
        cond.append(Url.segmento.in_(segs))
    reparto: dict[tuple[str, str], list] = {}
    for tipo, sev, seg, paginas in (
        db.query(Issue.issue_type, Issue.severity, Url.segmento, func.count(func.distinct(Issue.url_id)))
        .join(Url, Url.id == Issue.url_id)
        .filter(*cond)
        .group_by(Issue.issue_type, Issue.severity, Url.segmento)
    ):
        total = urls_por_seg.get(seg, 0)
        reparto.setdefault((tipo, sev), []).append(_PorSegmento(
            segmento=seg, paginas=paginas, urls=total,
            pct=round(100.0 * paginas / total, 2) if total else 0.0))
    for r in resultado:
        filas = sorted(reparto.get((r.issue_type, r.severity), []),
                       key=lambda p: (-p.paginas, -p.pct, p.segmento or ""))
        r.por_segmento = filas[:maximo]


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/issues/urls — URLs affected by specific issue types
# ---------------------------------------------------------------------------
class _AffectedUrl(BaseModel):
    id: int
    url: str
    status_code: int | None = None


@router.get("/issues/urls", response_model=list[_AffectedUrl])
def list_issue_urls(
    job_id: uuid.UUID,
    issue_type: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_session),
):
    """Return distinct URLs affected by a given issue type."""
    _get_job_or_404(job_id, db)

    rows = (
        db.query(Url.id, Url.url, Url.status_code)
        .join(Issue, Issue.url_id == Url.id)
        .filter(Issue.job_id == job_id, Issue.issue_type == issue_type)
        .distinct()
        .order_by(Url.id)
        .limit(limit)
        .all()
    )
    return [_AffectedUrl(id=r.id, url=r.url, status_code=r.status_code) for r in rows]


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/links
# ---------------------------------------------------------------------------
def _filtros_enlaces(
    destino: str | None = Query(None, description="La URL de destino contiene esto"),
    exacto: bool = Query(False, description="`destino` es la URL exacta, no un trozo"),
    destino_hash: str | None = Query(None, max_length=64,
                                     description="El destino por su hash: quien enlaza a esa URL"),
    origen: str | None = Query(None, description="La URL de la pagina que enlaza contiene esto"),
    ancla: str | None = Query(None, description="El texto del enlace (o el alt de su imagen) contiene esto"),
    tipo: Literal["interno", "externo"] | None = None,
    follow: Literal["si", "no"] | None = None,
    posicion: Literal["nav", "header", "content", "sidebar", "footer", "sin"] | None = None,
    estado: Literal["roto", "redireccion", "no_concluyente", "sin_dato", "ok"] | None = Query(
        None, description="Estado del destino (el del censo o el de la sonda de externos)"),
    codigo: int | None = Query(None, ge=0, le=999, description="Codigo HTTP del destino"),
):
    from api.enlaces import FiltrosEnlaces

    return FiltrosEnlaces(
        destino=(destino or "").strip(), destino_exacto=bool(exacto and destino),
        destino_hash=(destino_hash or "").strip(), origen=(origen or "").strip(),
        ancla=(ancla or "").strip(), tipo=tipo or "", follow=follow or "",
        posicion=posicion or "", estado=estado or "", codigo=codigo,
    )


@router.get("/links", response_model=EnlacesResponse)
def list_links(
    job_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    orden: Literal["estado", "destino"] = Query(
        "estado", description="estado: destinos rotos primero; destino: solo agrupados por destino"),
    filtros=Depends(_filtros_enlaces),
    db: Session = Depends(get_session),
):
    """Enlaces del censo, filtrados en el servidor (decision 195): destino,
    origen, ancla, interno/externo, follow, posicion y estado del destino.
    Siempre sobre `links.job_id`, o sobre el Parquet si el censo esta
    archivado (decisiones 37, 95 y 150)."""
    from api import enlaces as E

    job = _get_job_or_404(job_id, db)
    r = E.listar_enlaces(db, job, filtros, orden, page, page_size)
    filas = r["filas"]
    if r["archivado"]:
        filas = _como_links(db, job_id, filas)
    destinos = E.destinos_de(db, job_id, (getattr(x, "to_url_hash", None) for x in filas))
    items = []
    for x in filas:
        resp = LinkResponse.model_validate(x)
        if x.from_url_rel is not None:
            resp.from_url = x.from_url_rel.url
        d = destinos.get(x.to_url_hash) or E.Destino("sin_dato")
        resp.estado_destino, resp.status_destino = d.grupo, d.status
        # Los dos campos de la sonda (decision 123), como antes: solo externos.
        if not x.is_internal and d.veredicto is not None:
            resp.estado_externo, resp.status_externo = d.veredicto, d.status
        items.append(resp)
    out = _paginate(items=items, total=r["total"], page=page, page_size=page_size)
    out.update(orden=orden, por_estado=r["por_estado"], filtros=filtros.activos(),
               archivado=r["archivado"])
    return out


@router.get("/links/destinos", response_model=DestinosResponse)
def list_link_destinations(
    job_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    orden: Literal["estado", "paginas", "url"] = Query(
        "estado", description="estado: rotos primero y luego los mas enlazados; paginas; url"),
    filtros=Depends(_filtros_enlaces),
    db: Session = Depends(get_session),
):
    """Enlaces agrupados por URL de destino (decision 195): cuantas paginas la
    enlazan, cuantos enlaces y apariciones, sus anclas mas usadas y su estado.
    Los filtros de enlace (origen, ancla, posicion...) se aplican antes de
    agrupar; los de estado y codigo, al destino."""
    from api import enlaces as E

    job = _get_job_or_404(job_id, db)
    r = E.listar_destinos(db, job, filtros, orden, page, page_size)
    out = _paginate(items=r["items"], total=r["total"], page=page, page_size=page_size)
    out.update(orden=orden, por_estado=r["por_estado"], filtros=filtros.activos(),
               archivado=r["archivado"])
    return out


@router.get("/links/resumen")
def links_summary(job_id: uuid.UUID, db: Session = Depends(get_session)):
    """Enlaces y destinos internos y externos del censo, y los destinos por
    estado (decision 195). Lo que la barra del Explorador pone en «Externas»."""
    from api import enlaces as E

    job = _get_job_or_404(job_id, db)
    return E.resumen(db, job)


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/stats
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/diff/{otro_id}  --  que cambio entre dos censos
# ---------------------------------------------------------------------------
@router.get("/diff/{otro_id}")
def get_diff(
    job_id: uuid.UUID,
    otro_id: uuid.UUID,
    map_host: str | None = None,
    map_rutas: str | None = None,
    db: Session = Depends(get_session),
):
    """Que cambio entre este censo y otro del mismo sitio.

    `map_host=pre.x.com=x.com` reescribe el host del primero, para comparar
    preproduccion contra produccion; sin el, dos origenes distintos se
    rechazan en vez de devolver "ha desaparecido el sitio entero" (#32).

    `map_rutas` (decision 131) es una lista JSON de pares `[patron,
    reemplazo]` que reescriben la RUTA de las URLs del censo ANTERIOR antes de
    emparejar: una migracion (`[["^/es/hoteles/(.+)\\.html$", "/es/hotel/\\1/"]]`).
    Va en JSON y no como `map_host` porque una regex lleva comas e iguales.
    Una regex que no compila es un 422 que dice cual; la respuesta lleva
    `mapeo_rutas` con cuantas URLs reescribe cada regla y el % emparejado.
    """
    import json as _json

    from shared.comparacion import (
        _truncado, comparar_censos, comparar_incidencias, compilar_mapa_rutas,
        incidencias_de_censo, paginas_de_censo, resumen_de_job,
    )

    a = _get_job_or_404(job_id, db)
    b = _get_job_or_404(otro_id, db)

    mapa: dict[str, str] = {}
    if map_host:
        for par in map_host.split(","):
            if "=" in par:
                origen, destino = par.split("=", 1)
                mapa[origen.strip().lower()] = destino.strip().lower()

    rutas = None
    if map_rutas:
        try:
            rutas = _json.loads(map_rutas)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=(
                f"map_rutas tiene que ser una lista JSON de pares [patron, "
                f"reemplazo]: {e}"))
        try:
            compilar_mapa_rutas(rutas)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"map_rutas: {e}")

    # Cada censo se lee UNA vez: con los datos estructurados y el hreflang
    # (decision 131) la lectura ya no es barata para repetirla tres veces.
    pag_a = paginas_de_censo(db, job_id)
    pag_b = paginas_de_censo(db, otro_id)
    resultado = comparar_censos(
        pag_a,
        pag_b,
        job_a=resumen_de_job(a),
        job_b=resumen_de_job(b),
        mapa_hosts=mapa,
        mapa_rutas=rutas,
    )
    # Que se arreglo, que aparecio y que sigue. Comparar paginas no contesta
    # "que arreglo el cliente desde la auditoria anterior", que es para lo que
    # se mira un seguimiento mensual (#32).
    if resultado.get("comparable"):
        from shared.comparacion import _aplicar_mapa

        def _aplicar(u):
            return _aplicar_mapa(u, mapa)

        antes, ahora = resultado["antes"], resultado["ahora"]
        # Las paginas vienen ordenadas por fecha, asi que hay que mirar CUAL de
        # los dos jobs es el anterior, no el primer parametro.
        viejo_id = job_id if antes.get("fecha") == _resumen_fecha(a) else otro_id
        nuevo_id = otro_id if viejo_id == job_id else job_id
        pag_viejo, pag_nuevo = (pag_a, pag_b) if viejo_id == job_id else (pag_b, pag_a)
        from shared.comparacion import _aplicar_rutas, _norm
        from shared.respuestas import NO_VALIDAS

        from shared.accesibilidad import plantillas_evaluadas

        reglas_rutas = compilar_mapa_rutas(rutas)
        resultado["incidencias"] = comparar_incidencias(
            incidencias_de_censo(db, viejo_id),
            incidencias_de_censo(db, nuevo_id),
            mapa_hosts=mapa,
            mapa_rutas=rutas,
            puede_afirmar_resueltas=not _truncado(
                antes.get("status"), antes.get("finish_reason")),
            # Una incidencia cuya pagina ya no esta en el censo no esta
            # resuelta: no se sabe.
            # Ni si ahora es un muro: no se ha visto (decision 103).
            urls_del_nuevo={_norm(_aplicar(p["url"]))
                            for p in pag_nuevo
                            if p.get("response_class") not in NO_VALIDAS},
            # Nueva en una URL que ya existia (regresion) o en una nueva
            # (publicada mal), con el mapeo de rutas ya aplicado (131).
            urls_del_anterior={_norm(_aplicar_rutas(_aplicar(p["url"]), reglas_rutas)[0])
                               for p in pag_viejo
                               if p.get("response_class") not in NO_VALIDAS},
            # Dos censos analizados con codigo distinto no se comparan por
            # incidencias: un hallazgo puede salir "resuelto" solo porque la
            # regla que lo emitia ha cambiado.
            analisis_a=antes.get("analisis_version"),
            analisis_b=ahora.get("analisis_version"),
            # Un aviso de axe solo es «nuevo» o «resuelto» si el otro censo
            # evaluo su plantilla (decision 174).
            plantillas_axe_a=plantillas_evaluadas(db, viejo_id),
            plantillas_axe_b=plantillas_evaluadas(db, nuevo_id),
        )

    # `antes` y `ahora` los pone la comparacion, por FECHA: aqui se asignaban
    # por el orden de los parametros, asi que elegir el censo viejo en el
    # desplegable daba la vuelta al informe entero.
    return resultado


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/veredicto  --  pasa / falla / no_concluyente (128)
# ---------------------------------------------------------------------------
@router.get("/veredicto")
def get_veredicto(job_id: uuid.UUID, db: Session = Depends(get_session)):
    """Veredicto para un CI de despliegue: `pasa`, `falla` o `no_concluyente`.

    **Siempre 200** (para un job que existe) y el veredicto en el cuerpo: un CI
    no puede confundir «el despliegue esta roto» con «la API ha fallado». Lo
    no concluyente —sin referencia, truncado, bloqueado, sin terminar— no es
    `pasa`: quien lo lea como verde despliega a ciegas. Ver
    `shared.modo_lista.veredicto` y la decision 128.
    """
    from shared.modo_lista import veredicto

    return veredicto(db, _get_job_or_404(job_id, db))


def _resumen_fecha(job) -> str | None:
    return job.started_at.isoformat() if job.started_at else None


@router.get("/stats", response_model=JobStats)
def get_stats(
    job_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    job = _get_job_or_404(job_id, db)

    # Total URL count for this job
    total_urls = db.query(func.count(Url.id)).filter(Url.job_id == job_id).scalar() or 0

    # URLs by status group
    status_rows = (
        db.query(Url.status_group, func.count(Url.id))
        .filter(Url.job_id == job_id, Url.status_group.isnot(None))
        .group_by(Url.status_group)
        .all()
    )
    urls_by_status = [
        StatusGroupCount(status_group=sg, count=c) for sg, c in status_rows
    ]

    # Issues by type + severity
    issue_rows = (
        db.query(Issue.issue_type, Issue.severity, func.count(Issue.id))
        .filter(Issue.job_id == job_id)
        .group_by(Issue.issue_type, Issue.severity)
        .all()
    )
    issues_by_type = [
        IssueTypeCount(issue_type=it, severity=sev, count=c)
        for it, sev, c in issue_rows
    ]

    # Top 20 hosts
    host_rows = (
        db.query(Url.host, func.count(Url.id))
        .filter(Url.job_id == job_id, Url.host.isnot(None))
        .group_by(Url.host)
        .order_by(func.count(Url.id).desc())
        .limit(20)
        .all()
    )
    top_hosts = [HostCount(host=h, count=c) for h, c in host_rows]

    # URLs by resource_type
    rt_rows = (
        db.query(Url.resource_type, func.count(Url.id))
        .filter(Url.job_id == job_id, Url.resource_type.isnot(None))
        .group_by(Url.resource_type)
        .all()
    )
    urls_by_rt = [
        ResourceTypeCount(resource_type=rt, count=c) for rt, c in rt_rows
    ]

    # Internal / external counts
    internal_count = db.query(func.count(Url.id)).filter(
        Url.job_id == job_id, Url.is_internal == True,
    ).scalar() or 0
    external_count = total_urls - internal_count

    # Paginas HTML internas con 2xx y cuantas son indexables. `indexable` NULL
    # (rastreo sin analizar) no cuenta en ninguno de los dos lados.
    paginas_html, indexables, no_indexables = db.query(
        func.count(Url.id),
        func.count(Url.id).filter(Url.indexable.is_(True)),
        func.count(Url.id).filter(Url.indexable.is_(False)),
    ).filter(
        Url.job_id == job_id, Url.is_internal.is_(True), Url.is_html.is_(True),
        Url.status_group == "2xx",
    ).one()

    click_depth_calculada = db.query(
        exists().where(Url.job_id == job_id, Url.click_depth.isnot(None))
    ).scalar()

    # La tarjeta de errores en paginas y no en incidencias (revision de UX del
    # 25-oct, 1.11): la misma cuenta que el tope de la Puntuacion.
    paginas_con_error = db.query(func.count(func.distinct(Issue.url_id))).filter(
        Issue.job_id == job_id, Issue.severity == "error",
    ).scalar() or 0

    return JobStats(
        job_id=job.id,
        total_urls=total_urls,
        # En un rastreo terminado la verdad son las filas guardadas: el
        # contador de la tuberia se escribia por proceso y los rastreos
        # reanudados antes del arreglo se quedaron con el ultimo tramo (802
        # frente a 34.704 reales). `total_urls` ya esta contado aqui arriba.
        total_urls_crawled=(
            max(job.total_urls_crawled or 0, total_urls)
            if job.status in ("completed", "failed", "cancelled", "stalled")
            else job.total_urls_crawled
        ),
        total_urls_failed=job.total_urls_failed,
        urls_by_status_group=urls_by_status,
        issues_by_type=issues_by_type,
        top_hosts=top_hosts,
        urls_by_resource_type=urls_by_rt,
        internal_count=internal_count,
        external_count=external_count,
        paginas_html=paginas_html or 0,
        indexables=indexables or 0,
        no_indexables=no_indexables or 0,
        click_depth_calculada=bool(click_depth_calculada),
        paginas_con_error=paginas_con_error,
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/export  --  stream CSV of all URLs + metadata
# ---------------------------------------------------------------------------
CSV_COLUMNS = [
    "url",
    "host",
    "path",
    "scheme",
    "is_internal",
    "crawl_depth",
    "click_depth",
    "status_code",
    "status_group",
    "status_text",
    "content_type",
    "content_length",
    "transfer_size",
    "response_time_ms",
    "is_html",
    "resource_type",
    "redirect_url",
    "redirect_type",
    "indexable",
    "indexability_status",
    "url_length",
    "folder_depth",
    "word_count",
    "content_word_count",
    "text_ratio",
    "last_modified",
    "http_version",
    "inlinks_count",
    "unique_inlinks_count",
    "outlinks_count",
    "external_outlinks_count",
    "pagerank",
    # La que hay que leer: 0-100 logaritmica. La de 0-10 se queda por
    # compatibilidad, pero aplasta el 97,8% del sitio en 0,00xx.
    "pagerank_score",
    "pagerank_raw",
    # False = hay plantillas que montan enlaces con JavaScript y el rastreo fue
    # sin render: el grafo esta incompleto y estas cifras salen de un grafo
    # parcial. Vacio = no se llego a comprobar.
    "pagerank_fiable",
    "in_sitemap",
    "near_duplicate_count",
    "closest_similarity",
    "title",
    "title_len",
    "title_pixel_width",
    "meta_description",
    "meta_description_len",
    "meta_description_pixel_width",
    "meta_robots",
    "x_robots_tag",
    "canonical_href",
    "canonical_header",
    "meta_keywords",
    "rel_next",
    "rel_prev",
    "meta_refresh",
    "has_meta_outside_head",
    # Lo que el HTML declara de si mismo (decision 108)
    "viewport",
    "html_lang",
    "content_language",
    "canonical_crudo",
    "redireccion_js",
    "charset_meta",
    "texto_mal_codificado",
    # Encabezados: lo primero que mira cualquier auditoria y lo unico que
    # obligaba a abrir el backup ZIP para verlo.
    "h1_count",
    "h1_1",
    "h1_2",
    "h2_count",
    "h2_1",
    "h2_2",
    # Social
    "og_title",
    "og_description",
    "og_image",
    "og_type",
    "twitter_card",
    "twitter_title",
    "twitter_description",
    "twitter_image",
    # Internacionalizacion
    "hreflang_count",
    "hreflang_langs",
    # Datos estructurados
    "structured_data_count",
    "structured_data_types",
    "structured_data_status",
    # Imagenes
    "images_count",
    "images_missing_alt",
    # Seguridad
    "is_https",
    "has_hsts",
    "has_csp",
    "has_mixed_content",
    # Otros
    "blocked_by_robots",
    # Si Googlebot puede pedirla segun el robots.txt guardado (decision 113)
    "bloqueada_googlebot",
    # La respuesta era la pagina o un muro delante (decision 103)
    "response_class",
    "body_hash",
    "content_hash",
    "last_crawled_at",
    "content_text_first_500",
    "content_char_count",
]


def _val(v) -> str:
    """Format a value for CSV output.

    Una cadena sacada de la pagina rastreada (titulo, meta, anchor, contenido)
    que empiece por un caracter de formula se escapa, para que Excel o Sheets
    no la ejecuten al abrir el CSV (decision 207); los numeros no se tocan.
    """
    if v is None:
        return ""
    if isinstance(v, str) and v.startswith(_FORMULA):
        return "'" + v
    return str(v)


def _csv_row(url_obj: Url, extras: dict[str, Any] | None = None) -> list[str]:
    """Build a flat CSV row from a Url + optional HtmlMeta + PageContent.

    *extras* trae lo agregado por lote (encabezados, hreflang, datos
    estructurados, imagenes): recorrerlo por relacion ORM haria una consulta
    por URL y por tabla.
    """
    meta: HtmlMeta | None = url_obj.html_meta
    pc: PageContent | None = url_obj.page_content
    sec: SecurityHeaders | None = url_obj.security
    ex = extras or {}

    # El texto va recortado a 500 caracteres a proposito (el CSV completo es
    # /content/export). La columna lo dice en el nombre: antes se llamaba
    # "content_text" y al lado iba la longitud COMPLETA, asi que parecia el
    # texto entero recortado por Excel.
    content_text_val = ""
    if pc and pc.content_text:
        content_text_val = pc.content_text[:500]

    return [
        _val(url_obj.url),
        _val(url_obj.host),
        _val(url_obj.path),
        _val(url_obj.scheme),
        _val(url_obj.is_internal),
        _val(url_obj.crawl_depth),
        _val(url_obj.click_depth),
        _val(url_obj.status_code),
        _val(url_obj.status_group),
        _val(url_obj.status_text),
        _val(url_obj.content_type),
        _val(url_obj.content_length),
        _val(url_obj.transfer_size),
        _val(url_obj.response_time_ms),
        _val(url_obj.is_html),
        _val(url_obj.resource_type),
        _val(url_obj.redirect_url),
        _val(url_obj.redirect_type),
        _val(url_obj.indexable),
        _val(url_obj.indexability_status),
        _val(url_obj.url_length),
        _val(url_obj.folder_depth),
        _val(url_obj.word_count),
        _val(url_obj.content_word_count),
        _val(url_obj.text_ratio),
        _val(url_obj.last_modified),
        _val(url_obj.http_version),
        _val(url_obj.inlinks_count),
        _val(url_obj.unique_inlinks_count),
        _val(url_obj.outlinks_count),
        _val(url_obj.external_outlinks_count),
        _val(url_obj.pagerank),
        _val(url_obj.pagerank_score),
        _val(url_obj.pagerank_raw),
        _val(ex.get("pagerank_fiable")),
        _val(url_obj.in_sitemap),
        _val(url_obj.near_duplicate_count),
        _val(url_obj.closest_similarity),
        # HtmlMeta fields
        _val(meta.title) if meta else "",
        _val(meta.title_len) if meta else "",
        _val(meta.title_pixel_width) if meta else "",
        _val(meta.meta_description) if meta else "",
        _val(meta.meta_description_len) if meta else "",
        _val(meta.meta_description_pixel_width) if meta else "",
        _val(meta.meta_robots) if meta else "",
        _val(meta.x_robots_tag) if meta else "",
        _val(meta.canonical_href) if meta else "",
        _val(meta.canonical_header) if meta else "",
        _val(meta.meta_keywords) if meta else "",
        _val(meta.rel_next) if meta else "",
        _val(meta.rel_prev) if meta else "",
        _val(meta.meta_refresh) if meta else "",
        _val(meta.has_meta_outside_head) if meta else "",
        _val(meta.viewport) if meta else "",
        _val(meta.html_lang) if meta else "",
        _val(meta.content_language) if meta else "",
        _val(meta.canonical_crudo) if meta else "",
        _val(meta.redireccion_js) if meta else "",
        _val(meta.charset_meta) if meta else "",
        _val(meta.texto_mal_codificado) if meta else "",
        # Encabezados
        _val(ex.get("h1_count", 0)),
        _val(ex.get("h1_1")),
        _val(ex.get("h1_2")),
        _val(ex.get("h2_count", 0)),
        _val(ex.get("h2_1")),
        _val(ex.get("h2_2")),
        # Social
        _val(meta.og_title) if meta else "",
        _val(meta.og_description) if meta else "",
        _val(meta.og_image) if meta else "",
        _val(meta.og_type) if meta else "",
        _val(meta.twitter_card) if meta else "",
        _val(meta.twitter_title) if meta else "",
        _val(meta.twitter_description) if meta else "",
        _val(meta.twitter_image) if meta else "",
        # Hreflang
        _val(ex.get("hreflang_count", 0)),
        _val(ex.get("hreflang_langs")),
        # Datos estructurados
        _val(ex.get("sd_count", 0)),
        _val(ex.get("sd_types")),
        _val(ex.get("sd_status")),
        # Imagenes
        _val(ex.get("img_count", 0)),
        _val(ex.get("img_sin_alt", 0)),
        # Seguridad
        _val(sec.is_https) if sec else "",
        _val(sec.has_hsts) if sec else "",
        _val(sec.has_csp) if sec else "",
        _val(sec.has_mixed_content) if sec else "",
        # Otros
        _val(url_obj.blocked_by_robots),
        _val(getattr(url_obj, "bloqueada_googlebot", None)),
        _val(getattr(url_obj, "response_class", None)),
        _val(url_obj.body_hash),
        _val(url_obj.content_hash),
        _val(url_obj.last_crawled_at.isoformat() if url_obj.last_crawled_at else None),
        # PageContent fields
        content_text_val,
        _val(pc.content_length) if pc else "",
    ]


_ORDEN_VALIDACION = {"error": 0, "warning": 1, "info": 2, "ok": 3}


def _peor_validacion(estados: str | None) -> str | None:
    """El peor `validation_status` de los bloques de una pagina («a|b|c»).

    `info` (un FAQPage o HowTo retirados, decision 97) va entre `warning` y
    `ok`: una pagina con un Organization bien y un FAQ retirado es `info`, no
    `ok`, y una con un warning sigue siendo `warning`. Un estado desconocido va
    al final, para que nunca tape a uno conocido.
    """
    if not estados:
        return None
    return sorted(estados.split("|"), key=lambda e: _ORDEN_VALIDACION.get(e, 9))[0]


def _extras_por_lote(session: Session, url_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Agrega encabezados, hreflang, datos estructurados e imagenes del lote.

    Cuatro consultas por ventana de 1.000 URLs en lugar de cuatro por URL:
    recorrerlo por relaciones ORM son 4.000 consultas por ventana y convierte
    un export de 30.000 paginas en una espera de minutos.
    """
    extras: dict[int, dict[str, Any]] = {uid: {} for uid in url_ids}
    if not url_ids:
        return extras

    # Encabezados: solo h1/h2 y en orden de documento; guardamos los dos
    # primeros de cada uno, como hace Screaming Frog.
    filas = (
        session.query(Heading.url_id, Heading.tag, Heading.text)
        .filter(Heading.url_id.in_(url_ids), Heading.tag.in_(("h1", "h2")),
                # Los que no se pintan no son el titular de la pagina: el CSV
                # daria el clon movil como h1_1 segun el orden del DOM.
                Heading.oculto.isnot(True))
        .order_by(Heading.url_id, Heading.position)
        .all()
    )
    for url_id, tag, texto in filas:
        d = extras[url_id]
        clave_n = f"{tag}_count"
        d[clave_n] = d.get(clave_n, 0) + 1
        if d[clave_n] <= 2:
            d[f"{tag}_{d[clave_n]}"] = texto

    for url_id, n_hl, langs in (
        session.query(
            Hreflang.url_id,
            func.count(Hreflang.id),
            func.string_agg(Hreflang.lang.distinct(), "|"),
        )
        .filter(Hreflang.url_id.in_(url_ids))
        .group_by(Hreflang.url_id)
        .all()
    ):
        extras[url_id].update(hreflang_count=n_hl, hreflang_langs=langs)

    for url_id, n_sd, tipos, estados in (
        session.query(
            StructuredData.url_id,
            func.count(StructuredData.id),
            func.string_agg(StructuredData.schema_type.distinct(), "|"),
            func.string_agg(StructuredData.validation_status.distinct(), "|"),
        )
        .filter(StructuredData.url_id.in_(url_ids))
        .group_by(StructuredData.url_id)
        .all()
    ):
        extras[url_id].update(sd_count=n_sd, sd_types=tipos,
                              sd_status=_peor_validacion(estados))

    for url_id, n_img, sin_alt in (
        session.query(
            Resource.url_id,
            func.count(Resource.id),
            func.count(Resource.id).filter(
                or_(Resource.alt_text.is_(None), Resource.alt_text == "")
            ),
        )
        .filter(Resource.url_id.in_(url_ids), Resource.resource_type == "image")
        .group_by(Resource.url_id)
        .all()
    ):
        extras[url_id].update(img_count=n_img, img_sin_alt=sin_alt)

    return extras


def _pagerank_fiable(session: Session, job_id: uuid.UUID):
    """Si el grafo de enlaces del job es fiable (A7 de #24).

    Va en cada fila del CSV a proposito: quien ordena por PageRank en una hoja
    de calculo no abre el endpoint del job, y sin esto se lleva unas cifras
    calculadas sobre un grafo incompleto sin saberlo.
    """
    # OJO con el orden: el analisis escribe `pagerank_resumen` ANTES de que el
    # worker lance la comprobacion de render, asi que en un rastreo recien
    # terminado la clave existe con valor None. Mirar solo si la clave esta
    # dejaba la columna VACIA en todas las filas del CSV aunque el `js_check`
    # dijera luego que si: medido en el censo de progym, 4.320 filas sin el
    # aviso con `js_check.grafo_fiable = true`. Un None es "aun no se sabe", no
    # una respuesta.
    resumen = session.query(Job.pagerank_resumen).filter(Job.id == job_id).scalar()
    if isinstance(resumen, dict) and resumen.get("grafo_fiable") is not None:
        return resumen["grafo_fiable"]
    js_check = session.query(Job.js_check).filter(Job.id == job_id).scalar()
    if isinstance(js_check, dict) and js_check.get("grafo_fiable") is not None:
        return js_check["grafo_fiable"]
    # Con `render_js` la comprobacion no llega a correr —existe justamente para
    # los rastreos SIN render—, asi que no hay js_check que mirar y la columna
    # se quedaba vacia tambien ahi. Un rastreo que renderiza ya ha visto los
    # enlaces que monta el JavaScript, que es lo unico que esta columna dice.
    config = session.query(Job.config).filter(Job.id == job_id).scalar()
    if isinstance(config, dict) and config.get("render_js"):
        return True
    return None


def columnas_a_medida_export(config) -> list[tuple[str, str, str, dict]]:
    """Las columnas `x_<nombre>` del CSV completo: AL FINAL y solo si el job
    tiene reglas (decision 104). Las fijas no se mueven, asi que un informe
    montado sobre sus posiciones sigue valiendo."""
    return [(f"x_{nombre}", nombre, clase, regla)
            for nombre, (clase, regla) in reglas_del_job(config).items()]


def _stream_csv(job_id: uuid.UUID):
    """Generator that yields CSV content in chunks using windowed queries."""
    # Each chunk opens its own session so we do not hold one long transaction.
    from shared.database import SessionLocal

    batch_size = 1000
    last_id = 0

    session = SessionLocal()
    try:
        x_cols = columnas_a_medida_export(
            session.query(Job.config).filter(Job.id == job_id).scalar())
    finally:
        session.close()

    # Header row. Prefix a UTF-8 BOM so Excel opens the file with the correct
    # encoding (otherwise accented/Spanish characters render as mojibake).
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS + [c for c, _, _, _ in x_cols])
    yield "\ufeff" + buf.getvalue()

    while True:
        session = SessionLocal()
        try:
            rows = (
                session.query(Url)
                .options(
                    joinedload(Url.html_meta),
                    joinedload(Url.page_content),
                    joinedload(Url.security),
                )
                .filter(Url.job_id == job_id, Url.id > last_id)
                .order_by(Url.id)
                .limit(batch_size)
                .all()
            )

            if not rows:
                break

            extras = _extras_por_lote(session, [r.id for r in rows])
            fiable = _pagerank_fiable(session, job_id)
            for datos in extras.values():
                datos["pagerank_fiable"] = fiable

            xs = _a_medida(session, job_id, [r.id for r in rows]) if x_cols else {}

            buf = io.StringIO()
            writer = csv.writer(buf)
            for row in rows:
                fila = _csv_row(row, extras.get(row.id))
                for _c, nombre, clase, regla in x_cols:
                    fila.append(_val(valor_csv_a_medida(
                        xs.get(row.id, {}).get(nombre), clase, regla)))
                writer.writerow(fila)
                last_id = row.id

            yield buf.getvalue()
        finally:
            session.close()


@router.get("/export")
def export_csv(
    job_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    _get_job_or_404(job_id, db)

    return StreamingResponse(
        _stream_csv(job_id),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=job_{job_id}_urls.csv",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/links/export  --  stream CSV of all links
# ---------------------------------------------------------------------------
LINKS_CSV_COLUMNS = [
    "from_url",
    "to_url",
    "anchor_text",
    "link_type",
    "link_position",
    "rel",
    "follow",
    "target",
    "is_internal",
    "alt_text",
    "repeticiones",
    # Sonda de enlaces externos (decision 123); vacias si no se sondeo.
    "estado_externo",
    "status_externo",
]


def _links_csv_row(link_obj: Link, sondas: dict | None = None) -> list[str]:
    """Build a flat CSV row from a Link (+ resolved source URL)."""
    from_url = link_obj.from_url_rel.url if link_obj.from_url_rel else ""
    estado, status = (sondas or {}).get(getattr(link_obj, "to_url_hash", None), (None, None))
    return [
        _val(from_url),
        _val(link_obj.to_url),
        _val(link_obj.anchor_text),
        _val(link_obj.link_type),
        _val(link_obj.link_position),
        _val(link_obj.rel),
        _val(link_obj.follow),
        _val(link_obj.target),
        _val(link_obj.is_internal),
        _val(link_obj.alt_text),
        _val(link_obj.repeticiones),
        _val(estado),
        _val(status),
    ]


def _stream_links_csv(job_id: uuid.UUID, archivado_en=None):
    """Generator that yields the link graph as CSV in windowed chunks.

    Con `archivado_en` (un motor) los enlaces salen del Parquet del job
    (decision 95) y las URLs de origen se resuelven contra ese motor. Salen
    las mismas filas, pero agrupadas por destino —el orden del fichero— y no
    por id: ordenarlas por id obligaria a cargar el censo entero."""
    from shared.database import SessionLocal

    batch_size = 1000
    last_id = 0

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(LINKS_CSV_COLUMNS)
    yield "\ufeff" + buf.getvalue()

    # Si el censo tiene sondas (decision 123), una consulta por lote por el
    # indice (job_id, url_hash); si no, ninguna.
    with SessionLocal() as s:
        con_sondas = _con_sondas(s, job_id)

    def _sondas(s, filas):
        if not con_sondas:
            return {}
        return _sondas_de(s, job_id, (getattr(f, "to_url_hash", None) for f in filas
                                      if not getattr(f, "is_internal", True)))

    if archivado_en is not None:
        from sqlalchemy.orm import sessionmaker

        Sesion = sessionmaker(bind=archivado_en)
        lote: list[dict] = []

        def _volcar(lote):
            with Sesion() as s:
                buf = io.StringIO()
                writer = csv.writer(buf)
                filas = _como_links(s, job_id, lote)
                sondas = _sondas(s, filas)
                for lk in filas:
                    writer.writerow(_links_csv_row(lk, sondas))
                return buf.getvalue()

        for fila in archivo_enlaces.recorrer(job_id):
            lote.append(fila)
            if len(lote) >= batch_size:
                yield _volcar(lote)
                lote = []
        if lote:
            yield _volcar(lote)
        return

    while True:
        session = SessionLocal()
        try:
            rows = (
                session.query(Link)
                .options(joinedload(Link.from_url_rel))
                .filter(Link.job_id == job_id, Link.id > last_id)
                .order_by(Link.id)
                .limit(batch_size)
                .all()
            )

            if not rows:
                break

            buf = io.StringIO()
            writer = csv.writer(buf)
            sondas = _sondas(session, rows)
            for row in rows:
                writer.writerow(_links_csv_row(row, sondas))
                last_id = row.id

            yield buf.getvalue()
        finally:
            session.close()


@router.get("/links/export")
def export_links_csv(
    job_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    job = _get_job_or_404(job_id, db)
    archivado_en = db.get_bind() if archivo_enlaces.esta_archivado(job) else None

    return StreamingResponse(
        _stream_links_csv(job_id, archivado_en),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=job_{job_id}_links.csv",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/urls/{url_id}/raw-html  --  el HTML tal cual
# ---------------------------------------------------------------------------
@router.get("/urls/{url_id}/raw-html", response_class=PlainTextResponse)
def get_raw_html(
    job_id: uuid.UUID,
    url_id: int,
    db: Session = Depends(get_session),
):
    """HTML guardado de una URL, si el job se lanzo con `store_raw_html`.

    Endpoint aparte y no un campo del detalle de la URL a proposito: son 170 kB
    de media por pagina, y el detalle lo pide la interfaz cada vez que se abre
    una fila. Devolverlo ahi dentro convertiria una ficha en una descarga.
    """
    _get_job_or_404(job_id, db)
    fila = (
        db.query(PageContent.raw_html)
        .join(Url, Url.id == PageContent.url_id)
        .filter(Url.job_id == job_id, Url.id == url_id)
        .first()
    )
    if fila is None:
        raise HTTPException(status_code=404, detail="URL no encontrada en este rastreo")
    if not fila[0]:
        raise HTTPException(
            status_code=404,
            detail=(
                "Sin HTML guardado: el rastreo no se lanzo con "
                "extraction.store_raw_html"
            ),
        )
    return fila[0]


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/content/export  --  stream CSV of page content
# ---------------------------------------------------------------------------
CONTENT_CSV_COLUMNS = [
    "url",
    "status_code",
    "title",
    "meta_description",
    "word_count",
    "content_word_count",
    "content_char_count",
    "content_text",
    "content_markdown",
]


def _content_csv_row(url_obj: Url) -> list[str]:
    """Build a flat CSV row with the full extracted page content."""
    meta: HtmlMeta | None = url_obj.html_meta
    pc: PageContent | None = url_obj.page_content
    return [
        _val(url_obj.url),
        _val(url_obj.status_code),
        _val(meta.title) if meta else "",
        _val(meta.meta_description) if meta else "",
        _val(url_obj.word_count),
        _val(url_obj.content_word_count),
        _val(pc.content_length) if pc else "",
        _val(pc.content_text) if pc else "",
        _val(pc.content_markdown) if pc else "",
    ]


def _stream_content_csv(job_id: uuid.UUID):
    """Generator that yields full page content as CSV in windowed chunks.

    Only URLs that actually have extracted content are included.
    """
    from shared.database import SessionLocal

    batch_size = 500  # smaller window: rows carry full page text
    last_id = 0

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CONTENT_CSV_COLUMNS)
    yield "﻿" + buf.getvalue()

    while True:
        session = SessionLocal()
        try:
            rows = (
                session.query(Url)
                .join(PageContent, PageContent.url_id == Url.id)
                .options(joinedload(Url.html_meta), joinedload(Url.page_content))
                .filter(Url.job_id == job_id, Url.id > last_id)
                .order_by(Url.id)
                .limit(batch_size)
                .all()
            )

            if not rows:
                break

            buf = io.StringIO()
            writer = csv.writer(buf)
            for row in rows:
                writer.writerow(_content_csv_row(row))
                last_id = row.id

            yield buf.getvalue()
        finally:
            session.close()


@router.get("/content/export")
def export_content_csv(
    job_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    _get_job_or_404(job_id, db)

    return StreamingResponse(
        _stream_content_csv(job_id),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=job_{job_id}_content.csv",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/backup  --  full backup as ZIP with NDJSON
# ---------------------------------------------------------------------------
@router.get("/backup")
def export_backup(
    job_id: uuid.UUID,
    include_content: bool = Query(True),
    db: Session = Depends(get_session),
):
    job = _get_job_or_404(job_id, db)

    if job.status in ("pending", "running", "analyzing"):
        raise HTTPException(
            status_code=409,
            detail="No se puede exportar un job que aun esta en ejecucion",
        )

    return StreamingResponse(
        stream_backup_zip(job_id, include_content),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="backup_{job_id}.zip"',
        },
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/insights  --  SEO insights report
# ---------------------------------------------------------------------------
def _safe_pct(numerator: int, denominator: int) -> float:
    """Return percentage (0-100) or 0 if denominator is 0."""
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def _clamp_score(val: float) -> int:
    return max(0, min(100, round(val)))


def _html_2xx(job_id: uuid.UUID, db: Session) -> int:
    """Paginas HTML internas que responden 2xx.

    Es el denominador de todo lo que depende del contenido: solo de ellas se
    extraen title, h1 y texto, y solo ellas pueden ser indexables. Dividir
    tambien por saltos 3xx, 404 y PDFs hundia los porcentajes.
    """
    return db.query(func.count(Url.id)).filter(
        Url.job_id == job_id, Url.is_internal == True, Url.is_html == True,
        Url.status_code >= 200, Url.status_code < 300,
    ).scalar() or 0


def _paginas_con(job_id: uuid.UUID, db: Session, tipos: list[str]) -> int:
    """PAGINAS distintas con alguna de esas incidencias.

    Sumar incidencias contaba dos veces una pagina con `title_too_long` y
    `title_duplicate`, y `pct_thin` podia pasar del 100%.
    """
    return db.query(func.count(func.distinct(Issue.url_id))).filter(
        Issue.job_id == job_id, Issue.issue_type.in_(tipos),
    ).scalar() or 0


def _paginas_de_mas_en_grupos(job_id: uuid.UUID, db: Session, tipo: str) -> int:
    """Paginas que cubre una incidencia agrupada ADEMAS de la suya.

    `title_generico` (decision 121) es una fila por valor, en la pagina de URL
    menor, con `paginas_afectadas`, y les quita a las demas su
    `title_duplicate` y su `title_too_short` (36). `_paginas_con` cuenta
    `url_id` distintos, asi que sin esto tres paginas «Sin título | Marca»
    restaban una y la nota SUBIA por un hallazgo mas preciso (revision de
    #159, el mismo caso que la soft 404 de la decision 105). Puede contar dos
    veces una de esas paginas si ademas tiene `title_too_long`: el resultado
    se acota abajo con `max(0, ...)` y la pagina sigue teniendo un problema.
    """
    extra = 0
    for (detalles,) in db.query(Issue.details).filter(
        Issue.job_id == job_id, Issue.issue_type == tipo,
    ):
        n = detalles.get("paginas_afectadas") if isinstance(detalles, dict) else None
        if isinstance(n, int) and n > 1:
            extra += n - 1
    return extra


def _calc_crawlability(job_id: uuid.UUID, db: Session) -> CategoryInsight:
    """Crawlability: status codes, indexability, redirects."""
    total = db.query(func.count(Url.id)).filter(
        Url.job_id == job_id, Url.is_internal == True,
    ).scalar() or 0

    status_counts: dict[str, int] = {}
    rows = (
        db.query(Url.status_group, func.count(Url.id))
        .filter(Url.job_id == job_id, Url.is_internal == True)
        .group_by(Url.status_group)
        .all()
    )
    for sg, c in rows:
        if sg:
            status_counts[sg] = c

    ok_2xx = status_counts.get("2xx", 0)
    redirects_3xx = status_counts.get("3xx", 0)
    errors_4xx = status_counts.get("4xx", 0)
    errors_5xx = status_counts.get("5xx", 0)

    indexable_count = db.query(func.count(Url.id)).filter(
        Url.job_id == job_id, Url.is_internal == True, Url.indexable == True,
    ).scalar() or 0

    # Indexable solo puede serlo una pagina HTML que responde 2xx; en saltos,
    # errores y PDFs `indexable` es NULL y contaban como "no indexables".
    candidatas = _html_2xx(job_id, db)
    pct_2xx = _safe_pct(ok_2xx, total)
    pct_indexable = _safe_pct(indexable_count, candidatas)
    pct_redirects = _safe_pct(redirects_3xx, total)
    pct_4xx = _safe_pct(errors_4xx, total)
    pct_5xx = _safe_pct(errors_5xx, total)

    # Score: base from 2xx%, penalized by errors
    score = pct_2xx * 0.5 + pct_indexable * 0.3 + max(0, 100 - pct_4xx * 5 - pct_5xx * 10) * 0.2

    recs: list[Recommendation] = []
    if errors_4xx > 0:
        recs.append(Recommendation(
            priority="alta", title="Corregir errores 4xx",
            description=f"Hay {errors_4xx} URLs internas que devuelven errores 4xx (no encontrado). Revisa los enlaces rotos y corrige o elimina las referencias.",
            affected_count=errors_4xx,
            url_filter={"status_group": "4xx", "is_internal": "true"},
        ))
    if errors_5xx > 0:
        recs.append(Recommendation(
            priority="alta", title="Corregir errores 5xx",
            description=f"Hay {errors_5xx} URLs internas con errores de servidor (5xx). Investiga los problemas del servidor para estas paginas.",
            affected_count=errors_5xx,
            url_filter={"status_group": "5xx", "is_internal": "true"},
        ))
    if pct_redirects > 10:
        recs.append(Recommendation(
            priority="media", title="Reducir redirecciones",
            description=f"El {pct_redirects}% de las URLs internas son redirecciones. Actualiza los enlaces para apuntar directamente a las URLs finales.",
            affected_count=redirects_3xx,
            url_filter={"status_group": "3xx", "is_internal": "true"},
        ))
    non_indexable = candidatas - indexable_count
    if candidatas > 0 and pct_indexable < 80:
        recs.append(Recommendation(
            priority="media", title="Mejorar indexabilidad",
            description=f"Solo el {pct_indexable}% de las paginas HTML que responden 200 son indexables. Revisa las directivas noindex y canonicals para asegurar que las paginas importantes sean rastreables.",
            affected_count=non_indexable,
            url_filter={"indexable": "false", "is_internal": "true"},
        ))

    return CategoryInsight(
        key="crawlability", name="Rastreabilidad", icon="🔍",
        score=_clamp_score(score),
        metrics={
            "total_internal": total, "html_2xx": candidatas,
            "pct_2xx": pct_2xx, "pct_indexable": pct_indexable,
            "pct_redirects": pct_redirects, "pct_4xx": pct_4xx, "pct_5xx": pct_5xx,
            "errors_4xx": errors_4xx, "errors_5xx": errors_5xx, "redirects_3xx": redirects_3xx,
        },
        recommendations=recs,
    )


def _calc_content(job_id: uuid.UUID, db: Session) -> CategoryInsight:
    """Content quality: titles, descriptions, word count, thin content."""
    total_html = _html_2xx(job_id, db)

    # Issue counts for content-related issues
    content_issue_types = [
        "title_missing", "title_too_short", "title_too_long", "title_duplicate",
        "description_missing", "description_too_short", "description_too_long", "description_duplicate",
        "h1_missing", "h1_multiple", "h1_duplicate", "low_word_count",
        "very_low_text_ratio", "low_text_ratio", "duplicate_content",
    ]
    issue_rows = (
        db.query(Issue.issue_type, func.count(Issue.id))
        .filter(Issue.job_id == job_id, Issue.issue_type.in_(content_issue_types))
        .group_by(Issue.issue_type)
        .all()
    )
    issue_map: dict[str, int] = {it: c for it, c in issue_rows}

    title_missing = issue_map.get("title_missing", 0)
    title_relleno_extra = _paginas_de_mas_en_grupos(job_id, db, "title_generico")
    title_problems = _paginas_con(job_id, db, ["title_missing", "title_too_short", "title_too_long", "title_duplicate", "title_generico"]) + title_relleno_extra
    desc_missing = issue_map.get("description_missing", 0)
    desc_problems = _paginas_con(job_id, db, ["description_missing", "description_too_short", "description_too_long", "description_duplicate"])
    h1_problems = _paginas_con(job_id, db, ["h1_missing", "h1_multiple", "h1_duplicate"])
    thin_content = _paginas_con(job_id, db, ["low_word_count", "very_low_text_ratio", "low_text_ratio"])
    # Soft 404 (decision 105). El analisis le QUITA a esas paginas el contenido
    # escaso, el titulo, la description y el h1 (un aviso por hallazgo), asi
    # que sin contarlas aqui la nota SUBIA por un hallazgo peor. En la nota
    # cuentan como fallo en cada criterio de contenido —sirven una pagina de
    # error—; en las recomendaciones, solo en la suya.
    soft404 = _paginas_con(job_id, db, ["soft_404"])
    soft404_indexables = db.query(func.count(func.distinct(Issue.url_id))).filter(
        Issue.job_id == job_id, Issue.issue_type == "soft_404",
        Issue.severity.in_(("error", "warning")),
    ).scalar() or 0
    soft404_candidatos = _paginas_con(job_id, db, ["soft_404_candidato"])
    title_nota = _paginas_con(job_id, db, ["title_missing", "title_too_short", "title_too_long", "title_duplicate", "title_generico", "soft_404"]) + title_relleno_extra
    desc_nota = _paginas_con(job_id, db, ["description_missing", "description_too_short", "description_too_long", "description_duplicate", "soft_404"])
    h1_nota = _paginas_con(job_id, db, ["h1_missing", "h1_multiple", "h1_duplicate", "soft_404"])
    thin_nota = _paginas_con(job_id, db, ["low_word_count", "very_low_text_ratio", "low_text_ratio", "soft_404"])

    # Average word count
    avg_wc = float(db.query(func.avg(Url.word_count)).filter(
        Url.job_id == job_id, Url.is_internal == True, Url.is_html == True,
        Url.status_code >= 200, Url.status_code < 300, Url.word_count.isnot(None),
    ).scalar() or 0)

    pct_title_ok = _safe_pct(max(0, total_html - title_nota), total_html)
    pct_desc_ok = _safe_pct(max(0, total_html - desc_nota), total_html)
    pct_h1_ok = _safe_pct(max(0, total_html - h1_nota), total_html)
    pct_thin = _safe_pct(thin_nota, total_html)

    score = pct_title_ok * 0.3 + pct_desc_ok * 0.25 + pct_h1_ok * 0.2 + max(0, 100 - pct_thin * 2) * 0.15 + min(100, avg_wc / 3) * 0.1

    recs: list[Recommendation] = []
    if soft404 > 0:
        recs.append(Recommendation(
            priority="alta" if soft404_indexables else "media",
            title="Corregir paginas de error que responden 200 (soft 404)",
            description=(
                f"Hay {soft404} paginas que responden 200 pero son una pagina de error"
                + (f" ({soft404_indexables} indexables)" if soft404_indexables else "")
                + ". Google las trata como «Soft 404» y las saca del indice; cada enlace interno "
                "a ellas es un enlace roto. Si el contenido ya no existe, responder 404 o 410 "
                "(o 301 a su sustituto) y quitarlas del sitemap."),
            affected_count=soft404,
            issue_types=["soft_404"],
        ))
    if soft404_candidatos > 0:
        recs.append(Recommendation(
            priority="baja", title="Revisar posibles soft 404",
            description=f"Hay {soft404_candidatos} paginas con indicios de pagina de error sin certeza (un titular que menciona un error, un listado vacio, un producto descatalogado). Revisalas a mano.",
            affected_count=soft404_candidatos,
            issue_types=["soft_404_candidato"],
        ))
    if title_missing > 0:
        recs.append(Recommendation(
            priority="alta", title="Agregar titulos faltantes",
            description=f"Hay {title_missing} paginas sin etiqueta title. El titulo es crucial para el posicionamiento y el CTR en los resultados de busqueda.",
            affected_count=title_missing,
            issue_types=["title_missing"],
        ))
    if title_problems - title_missing > 0:
        recs.append(Recommendation(
            priority="media", title="Optimizar titulos",
            description=f"Hay {title_problems - title_missing} paginas con titulos problematicos (de relleno, demasiado cortos, largos o duplicados). Optimiza cada titulo para que sea unico, tenga al menos 10 caracteres y no pase de 580 pixeles de ancho (que es por donde Google lo corta).",
            affected_count=title_problems - title_missing,
            issue_types=["title_too_short", "title_too_long", "title_duplicate", "title_generico"],
        ))
    if desc_missing > 0:
        recs.append(Recommendation(
            priority="alta", title="Agregar meta descripciones",
            description=f"Hay {desc_missing} paginas sin meta descripcion. Las descripciones ayudan a mejorar el CTR en los resultados de busqueda.",
            affected_count=desc_missing,
            issue_types=["description_missing"],
        ))
    if h1_problems > 0:
        recs.append(Recommendation(
            priority="media", title="Corregir encabezados H1",
            description=f"Hay {h1_problems} paginas con problemas en el H1 (faltante, multiples o duplicados). Cada pagina debe tener exactamente un H1 unico.",
            affected_count=h1_problems,
            issue_types=["h1_missing", "h1_multiple", "h1_duplicate"],
        ))
    if thin_content > 0:
        recs.append(Recommendation(
            priority="media", title="Mejorar contenido delgado",
            description=f"Hay {thin_content} paginas con contenido escaso (pocas palabras o ratio de texto bajo). Amplia el contenido de estas paginas para aportar mas valor.",
            affected_count=thin_content,
            issue_types=["low_word_count", "very_low_text_ratio", "low_text_ratio"],
        ))

    return CategoryInsight(
        key="content", name="Contenido", icon="📝",
        score=_clamp_score(score),
        metrics={
            "total_html": total_html, "pct_title_ok": pct_title_ok, "pct_desc_ok": pct_desc_ok,
            "pct_h1_ok": pct_h1_ok, "avg_word_count": round(avg_wc),
            "pct_thin": pct_thin, "thin_count": thin_content,
            "soft404_count": soft404, "soft404_indexables": soft404_indexables,
            "soft404_candidatos": soft404_candidatos,
            "title_problems": title_problems, "desc_problems": desc_problems,
        },
        recommendations=recs,
    )


TIPOS_SIN_ENLACE_QUE_CUENTE = (
    "orphan_page", "sitemap_orphan", "solo_enlazada_desde_paginacion_excluida",
)


def _calc_links(job_id: uuid.UUID, db: Session) -> CategoryInsight:
    """Links: orphan pages, inlinks distribution, nofollow, broken links."""
    # Huerfana solo puede serlo una pagina 200 (ver analyze_links)
    total_internal = _html_2xx(job_id, db)

    # Paginas sin un enlace que cuente: las huerfanas, las del sitemap que
    # nadie enlaza y las que solo cuelgan de una paginacion excluida (decision
    # 122). La 122 pasa paginas de las dos primeras a la tercera: contando solo
    # `orphan_page`, la nota SUBIA en el censo donde se encuentra el problema.
    # Paginas distintas, no incidencias.
    orphan_count = db.query(func.count(func.distinct(Issue.url_id))).filter(
        Issue.job_id == job_id, Issue.issue_type.in_(TIPOS_SIN_ENLACE_QUE_CUENTE),
    ).scalar() or 0

    # Average inlinks
    avg_inlinks = float(db.query(func.avg(Url.inlinks_count)).filter(
        Url.job_id == job_id, Url.is_internal == True, Url.is_html == True,
    ).scalar() or 0)

    # Nofollow internal links
    # Por aparicion, como siempre: una fila agrupa sus repeticiones (decision 94)
    job = db.get(Job, job_id)
    if job is not None and archivo_enlaces.esta_archivado(job):
        # Guardadas al archivar: las mismas sumas, sin leer el fichero
        total_internal_links = job.enlaces_archivados.get("internos", 0)
        nofollow_links = job.enlaces_archivados.get("nofollow_internos", 0)
    else:
        # Un solo recorrido de `links` del job, no dos (decision 41): en el
        # censo de Lopesan (1,43 M filas) eran 12,5 s de los 11-17 que
        # tardaban /insights y el informe.
        total_internal_links, nofollow_links = db.query(
            func.sum(Link.repeticiones),
            func.sum(case((Link.follow == False, Link.repeticiones), else_=0)),  # noqa: E712
        ).filter(Link.job_id == job_id, Link.is_internal == True).one()  # noqa: E712
        total_internal_links = total_internal_links or 0
        nofollow_links = nofollow_links or 0

    # Broken links (4xx/5xx issue counts)
    broken_link_issues = db.query(func.count(Issue.id)).filter(
        Issue.job_id == job_id, Issue.issue_type.in_(["4xx_error", "5xx_error"]),
    ).scalar() or 0

    # High outlinks
    high_outlinks = db.query(func.count(Issue.id)).filter(
        Issue.job_id == job_id, Issue.issue_type == "high_outlink_count",
    ).scalar() or 0

    pct_orphan = _safe_pct(orphan_count, total_internal)
    pct_nofollow = _safe_pct(nofollow_links, total_internal_links)

    score = (
        max(0, 100 - pct_orphan * 3) * 0.35
        + min(100, avg_inlinks * 10) * 0.25
        + max(0, 100 - pct_nofollow * 2) * 0.15
        + max(0, 100 - _safe_pct(broken_link_issues, total_internal) * 5) * 0.25
    )

    recs: list[Recommendation] = []
    if orphan_count > 0:
        recs.append(Recommendation(
            priority="alta", title="Enlazar paginas huerfanas",
            description=f"Hay {orphan_count} paginas sin un enlace interno que los buscadores sigan: nadie las enlaza, o solo las enlazan paginas 2+ de un listado en noindex o canonicalizadas a la 1. Agrega enlaces desde paginas indexables (o arregla esa paginacion) para que los buscadores las descubran.",
            affected_count=orphan_count,
            issue_types=list(TIPOS_SIN_ENLACE_QUE_CUENTE),
        ))
    if broken_link_issues > 0:
        recs.append(Recommendation(
            priority="alta", title="Corregir enlaces rotos",
            description=f"Se detectaron {broken_link_issues} paginas con errores HTTP. Corrige o elimina los enlaces que apuntan a estas paginas.",
            affected_count=broken_link_issues,
            issue_types=["4xx_error", "5xx_error"],
        ))
    if high_outlinks > 0:
        recs.append(Recommendation(
            priority="baja", title="Reducir enlaces salientes excesivos",
            description=f"Hay {high_outlinks} paginas con demasiados enlaces salientes, lo que puede diluir la autoridad de enlace.",
            affected_count=high_outlinks,
            issue_types=["high_outlink_count"],
        ))

    return CategoryInsight(
        key="links", name="Enlaces", icon="🔗",
        score=_clamp_score(score),
        metrics={
            "total_internal_pages": total_internal, "orphan_count": orphan_count,
            "pct_orphan": pct_orphan, "avg_inlinks": round(avg_inlinks, 1),
            "total_internal_links": total_internal_links,
            "nofollow_links": nofollow_links, "pct_nofollow": pct_nofollow,
            "broken_link_issues": broken_link_issues, "high_outlinks": high_outlinks,
        },
        recommendations=recs,
    )


def _calc_security(job_id: uuid.UUID, db: Session) -> CategoryInsight:
    """Security: HTTPS, HSTS, CSP, mixed content."""
    # Count security header stats across all internal HTML pages
    total_with_sec = db.query(func.count(SecurityHeaders.url_id)).join(
        Url, SecurityHeaders.url_id == Url.id,
    ).filter(Url.job_id == job_id, Url.is_internal == True).scalar() or 0

    if total_with_sec == 0:
        return CategoryInsight(
            key="security", name="Seguridad", icon="🔒", score=0,
            metrics={"total_checked": 0, "pct_https": 0, "pct_hsts": 0, "pct_csp": 0, "pct_mixed": 0},
            recommendations=[Recommendation(
                priority="baja", title="Sin datos de seguridad",
                description="No se encontraron cabeceras de seguridad en las paginas rastreadas.",
                affected_count=0,
            )],
        )

    agg = db.query(
        func.sum(case((SecurityHeaders.is_https == True, 1), else_=0)).label("https_count"),
        func.sum(case((SecurityHeaders.has_hsts == True, 1), else_=0)).label("hsts_count"),
        func.sum(case((SecurityHeaders.has_csp == True, 1), else_=0)).label("csp_count"),
        func.sum(case((SecurityHeaders.has_mixed_content == True, 1), else_=0)).label("mixed_count"),
        func.sum(case((SecurityHeaders.has_x_content_type_options == True, 1), else_=0)).label("xcto_count"),
        func.sum(case((SecurityHeaders.has_x_frame_options == True, 1), else_=0)).label("xfo_count"),
    ).join(Url, SecurityHeaders.url_id == Url.id).filter(
        Url.job_id == job_id, Url.is_internal == True,
    ).first()

    https_count = agg.https_count or 0
    hsts_count = agg.hsts_count or 0
    csp_count = agg.csp_count or 0
    mixed_count = agg.mixed_count or 0
    xcto_count = agg.xcto_count or 0
    xfo_count = agg.xfo_count or 0

    pct_https = _safe_pct(https_count, total_with_sec)
    pct_hsts = _safe_pct(hsts_count, total_with_sec)
    pct_csp = _safe_pct(csp_count, total_with_sec)
    pct_mixed = _safe_pct(mixed_count, total_with_sec)

    score = pct_https * 0.35 + pct_hsts * 0.2 + pct_csp * 0.15 + max(0, 100 - pct_mixed * 5) * 0.15 + _safe_pct(xcto_count, total_with_sec) * 0.075 + _safe_pct(xfo_count, total_with_sec) * 0.075

    recs: list[Recommendation] = []
    non_https = total_with_sec - https_count
    if non_https > 0:
        recs.append(Recommendation(
            priority="alta", title="Migrar a HTTPS",
            description=f"Hay {non_https} paginas servidas sin HTTPS. HTTPS es fundamental para la seguridad y es un factor de posicionamiento.",
            affected_count=non_https,
            issue_types=["http_url"],
        ))
    if mixed_count > 0:
        recs.append(Recommendation(
            priority="alta", title="Eliminar contenido mixto",
            description=f"Hay {mixed_count} paginas con contenido mixto (recursos HTTP en paginas HTTPS). Actualiza todas las referencias a HTTPS.",
            affected_count=mixed_count,
            issue_types=["mixed_content"],
        ))
    non_hsts = total_with_sec - hsts_count
    if non_hsts > 0 and https_count > 0:
        recs.append(Recommendation(
            priority="media", title="Implementar HSTS",
            description=f"Hay {non_hsts} paginas sin la cabecera HSTS. HSTS fuerza conexiones seguras y previene ataques de downgrade.",
            affected_count=non_hsts,
            issue_types=["missing_hsts"],
        ))
    non_csp = total_with_sec - csp_count
    if non_csp > 0:
        recs.append(Recommendation(
            priority="baja", title="Agregar Content-Security-Policy",
            description=f"Hay {non_csp} paginas sin politica CSP. CSP protege contra ataques XSS e inyeccion de datos.",
            affected_count=non_csp,
            issue_types=["missing_csp"],
        ))

    return CategoryInsight(
        key="security", name="Seguridad", icon="🔒",
        score=_clamp_score(score),
        metrics={
            "total_checked": total_with_sec, "https_count": https_count,
            "pct_https": pct_https, "pct_hsts": pct_hsts, "pct_csp": pct_csp,
            "pct_mixed": pct_mixed, "mixed_count": mixed_count,
        },
        recommendations=recs,
    )


def _calc_structured_data(job_id: uuid.UUID, db: Session) -> CategoryInsight:
    """Structured data: pages with SD, types, validation errors."""
    total_html = db.query(func.count(Url.id)).filter(
        Url.job_id == job_id, Url.is_internal == True, Url.is_html == True,
    ).scalar() or 0

    # Pages that have at least one structured data item
    pages_with_sd = db.query(func.count(func.distinct(StructuredData.url_id))).join(
        Url, StructuredData.url_id == Url.id,
    ).filter(Url.job_id == job_id, Url.is_internal == True).scalar() or 0

    # Schema types used
    type_rows = (
        db.query(StructuredData.schema_type, func.count(StructuredData.id))
        .join(Url, StructuredData.url_id == Url.id)
        .filter(Url.job_id == job_id, StructuredData.schema_type.isnot(None))
        .group_by(StructuredData.schema_type)
        .order_by(func.count(StructuredData.id).desc())
        .limit(10)
        .all()
    )
    types_used = {t: c for t, c in type_rows}

    # Validation errors
    sd_errors = db.query(func.count(StructuredData.id)).join(
        Url, StructuredData.url_id == Url.id,
    ).filter(
        Url.job_id == job_id, StructuredData.validation_status == "error",
    ).scalar() or 0

    total_sd = db.query(func.count(StructuredData.id)).join(
        Url, StructuredData.url_id == Url.id,
    ).filter(Url.job_id == job_id).scalar() or 0

    pct_with_sd = _safe_pct(pages_with_sd, total_html)
    pct_errors = _safe_pct(sd_errors, total_sd)

    score = min(100, pct_with_sd * 1.2) * 0.6 + max(0, 100 - pct_errors * 3) * 0.4

    recs: list[Recommendation] = []
    pages_without = total_html - pages_with_sd
    if pages_without > 0 and pct_with_sd < 50:
        recs.append(Recommendation(
            priority="media", title="Agregar datos estructurados",
            description=f"Hay {pages_without} paginas HTML sin datos estructurados. Agrega Schema.org (JSON-LD) para mejorar la visibilidad en resultados de busqueda.",
            affected_count=pages_without,
        ))
    if sd_errors > 0:
        recs.append(Recommendation(
            priority="alta", title="Corregir errores de validacion",
            description=f"Hay {sd_errors} bloques de datos estructurados con errores de validacion. Corrigelos para que los buscadores los interpreten correctamente.",
            affected_count=sd_errors,
            issue_types=["structured_data_error"],
        ))

    return CategoryInsight(
        key="structured_data", name="Datos estructurados", icon="📊",
        score=_clamp_score(score),
        metrics={
            "total_html": total_html, "pages_with_sd": pages_with_sd,
            "pct_with_sd": pct_with_sd, "types_used": types_used,
            "total_sd_blocks": total_sd, "sd_errors": sd_errors, "pct_errors": pct_errors,
        },
        recommendations=recs,
    )


def _calc_i18n(job_id: uuid.UUID, db: Session) -> CategoryInsight:
    """Internationalization: hreflang tags, return tags, valid langs."""
    total_hreflang = db.query(func.count(Hreflang.id)).join(
        Url, Hreflang.url_id == Url.id,
    ).filter(Url.job_id == job_id).scalar() or 0

    # Sin filas en `hreflang` el sitio puede declararlo solo en el sitemap
    # (decision 167): esas anotaciones no tienen fila, pero sus avisos si.
    # Solo sin ninguno de los dos no hay nada que contar.
    solo_sitemap = False
    if total_hreflang == 0:
        hay_avisos = db.query(Issue.id).filter(
            Issue.job_id == job_id, Issue.issue_type.like("hreflang\\_%", escape="\\"),
        ).first() is not None
        if not hay_avisos:
            return CategoryInsight(
                key="i18n", name="Internacionalización", icon="🌐", score=100,
                metrics={"total_hreflang": 0, "languages": [], "pct_return_ok": 0, "pct_lang_valid": 0},
                recommendations=[],
            )
        solo_sitemap = True

    # Languages detected
    lang_rows = (
        db.query(Hreflang.lang, func.count(Hreflang.id))
        .join(Url, Hreflang.url_id == Url.id)
        .filter(Url.job_id == job_id)
        .group_by(Hreflang.lang)
        .all()
    )
    languages = [lang for lang, _ in lang_rows]

    # Return tags / lang valid. NULL es "sin verificar" (autorreferencia,
    # x-default, destino no rastreado, o un analisis anterior), NO un fallo:
    # antes `missing_return = total - ok` los contaba como "sin retorno", y un
    # cluster de 3 idiomas perfecto con x-default salia al ~50% con una
    # recomendacion de prioridad alta. En un censo sin verificar (Lopesan,
    # 17.228 hreflang con NULL) daba nota 0 y dos recomendaciones falsas.
    def _cuenta(col, valor):
        return db.query(func.count(Hreflang.id)).join(
            Url, Hreflang.url_id == Url.id,
        ).filter(Url.job_id == job_id, col.is_(valor)).scalar() or 0

    return_ok = _cuenta(Hreflang.return_tag_ok, True)
    missing_return = _cuenta(Hreflang.return_tag_ok, False)
    lang_valid = _cuenta(Hreflang.lang_valid, True)
    invalid_lang = _cuenta(Hreflang.lang_valid, False)
    return_unknown = total_hreflang - return_ok - missing_return
    lang_unknown = total_hreflang - lang_valid - invalid_lang

    # Anotaciones hacia un destino que Google descarta: roto (4xx/5xx) o no
    # indexable (canonicalizado, noindex, robots). Las dos son `error` y una
    # incidencia por anotacion (decisiones 56 y 99), y su `return_tag_ok` va a
    # NULL —el retorno de un destino descartado no se puede afirmar—, asi que
    # sin contarlas aqui salian del denominador: Lopesan, con 31 errores de
    # hreflang abiertos en Problemas, pasaba de 96 a 100 sin una sola
    # recomendacion.
    def _incidencias(*tipos):
        return db.query(func.count(Issue.id)).filter(
            Issue.job_id == job_id, Issue.issue_type.in_(tipos),
        ).scalar() or 0

    destino_malo = _incidencias("hreflang_broken_target",
                                "hreflang_destino_no_indexable")
    sin_autorref = _incidencias("hreflang_sin_autorreferencia")
    if solo_sitemap:
        # Sin filas no hay porcentaje que calcular, pero lo que el analisis
        # avisa del sitemap se recomienda igual (los dos son una incidencia
        # por anotacion), y un error abierto baja la nota abajo: un 100 sin
        # recomendaciones con errores en Problemas era afirmar «bueno».
        missing_return = _incidencias("hreflang_missing_return")
        invalid_lang = _incidencias("hreflang_invalid_lang")

    pct_return_ok = _safe_pct(return_ok, return_ok + missing_return)
    pct_lang_valid = _safe_pct(lang_valid, lang_valid + invalid_lang)
    # De las anotaciones verificadas hacia otra pagina, las que llegan a una
    # alternativa que Google puede usar.
    verificadas = return_ok + missing_return + destino_malo
    pct_destino_ok = _safe_pct(return_ok + missing_return, verificadas)

    # La nota solo con lo verificado. Sin nada verificado no hay nota que dar:
    # se deja en 100 (nada que corregir que sepamos) y se avisa abajo.
    # Solo del sitemap no hay denominador (las anotaciones correctas no tienen
    # fila): un porcentaje sobre los avisos daria 0 % y se queda en 100 con el
    # tope de abajo si hay un error.
    partes = []
    if solo_sitemap:
        pct_return_ok = pct_lang_valid = pct_destino_ok = 0
    else:
        if return_ok + missing_return:
            partes.append(pct_return_ok)
        if lang_valid + invalid_lang:
            partes.append(pct_lang_valid)
        if destino_malo:
            partes.append(pct_destino_ok)
    score = sum(partes) / len(partes) if partes else 100
    # Y con un error abierto la categoria no puede decir «bueno», por pocas
    # anotaciones que sean (el criterio de la nota global, decision 92): en
    # Lopesan los 31 son el 0,9% de las verificadas y la media sola seguia
    # redondeando a 100.
    if destino_malo:
        score = min(score, TOPE_CON_ERRORES)

    recs: list[Recommendation] = []
    if destino_malo > 0:
        recs.append(Recommendation(
            priority="alta", title="Corregir hreflang hacia URLs que Google descarta",
            description=f"Hay {destino_malo} etiquetas hreflang que apuntan a una URL rota, canonicalizada a otra, en noindex o bloqueada por robots.txt. Google descarta esa alternativa y ese idioma se queda sin su version.",
            affected_count=destino_malo,
            issue_types=["hreflang_broken_target", "hreflang_destino_no_indexable"],
        ))
    if missing_return > 0:
        recs.append(Recommendation(
            priority="alta", title="Corregir etiquetas hreflang sin retorno",
            description=f"Hay {missing_return} etiquetas hreflang cuya pagina de destino no enlaza de vuelta. Cada hreflang debe tener una referencia reciproca.",
            affected_count=missing_return,
            issue_types=["hreflang_missing_return"],
        ))
    if invalid_lang > 0:
        recs.append(Recommendation(
            priority="media", title="Corregir codigos de idioma invalidos",
            description=f"Hay {invalid_lang} etiquetas hreflang con codigos de idioma no validos. Usa codigos ISO 639-1 (ej: es, en, fr).",
            affected_count=invalid_lang,
            issue_types=["hreflang_invalid_lang"],
        ))
    if sin_autorref > 0:
        recs.append(Recommendation(
            priority="media", title="Anadir la autorreferencia hreflang",
            description=f"Hay {sin_autorref} paginas que anotan sus otras versiones pero no a si mismas (o se anotan con otra URL, como la misma ruta con un parametro).",
            affected_count=sin_autorref,
            issue_types=["hreflang_sin_autorreferencia"],
        ))
    if not partes and not solo_sitemap:
        recs.append(Recommendation(
            priority="baja", title="Hreflang sin verificar",
            description=f"Las {total_hreflang} etiquetas hreflang no se han podido verificar (retorno e idioma). Relanza el analisis del job para comprobarlas.",
            affected_count=total_hreflang,
        ))

    return CategoryInsight(
        key="i18n", name="Internacionalización", icon="🌐",
        score=_clamp_score(score),
        metrics={
            "total_hreflang": total_hreflang, "languages": languages,
            "pct_return_ok": pct_return_ok, "pct_lang_valid": pct_lang_valid,
            "return_missing": missing_return, "return_unknown": return_unknown,
            "destino_malo": destino_malo, "pct_destino_ok": pct_destino_ok,
            "sin_autorreferencia": sin_autorref,
            "invalid_lang": invalid_lang, "lang_unknown": lang_unknown,
            "solo_sitemap": solo_sitemap,
        },
        recommendations=recs,
    )


_INSIGHTS_TTL_S = 7 * 24 * 3600


def _clave_insights(db: Session, job: Job) -> str:
    """Lo que hace cambiar la nota: un re-analisis (otra version del codigo, u
    otras incidencias con la misma). Contar las incidencias es un indice, no un
    recorrido."""
    n = db.query(func.count(Issue.id)).filter(Issue.job_id == job.id).scalar() or 0
    return f"insights:{job.id}:{job.analisis_version or '-'}:{n}"


@router.get("/insights", response_model=InsightsResponse)
def get_insights(
    job_id: uuid.UUID,
    db: Session = Depends(get_session),
):
    """La nota del censo. Cacheada en Redis por (job, version del analisis,
    numero de incidencias): solo cambia al re-analizar, y calcularla son 10 s
    en un censo como el de Lopesan (1,4 M enlaces), lo que tardaba en abrirse
    el informe —tambien el enlace del cliente, decision 143—."""
    from api import dependencies

    job = _get_job_or_404(job_id, db)
    r = dependencies.redis_client
    clave = None
    if r is not None and job.status == "completed":
        try:
            clave = _clave_insights(db, job)
            guardado = r.get(clave)
            if guardado:
                return InsightsResponse.model_validate_json(guardado)
        except Exception:  # noqa: BLE001 — sin Redis, se calcula
            clave = None
    resultado = _calcular_insights(job_id, db)
    if clave is not None:
        try:
            r.set(clave, resultado.model_dump_json(), ex=_INSIGHTS_TTL_S)
        except Exception:  # noqa: BLE001
            pass
    return resultado


def _calcular_insights(job_id: uuid.UUID, db: Session) -> InsightsResponse:

    categories = [
        _calc_crawlability(job_id, db),
        _calc_content(job_id, db),
        _calc_links(job_id, db),
        _calc_security(job_id, db),
        _calc_structured_data(job_id, db),
        _calc_i18n(job_id, db),
    ]

    # Weighted average: crawlability 25%, content 25%, links 20%, security 15%, SD 10%, i18n 5%
    weights = [0.25, 0.25, 0.20, 0.15, 0.10, 0.05]
    media = _clamp_score(sum(c.score * w for c, w in zip(categories, weights)))
    tope = _tope_por_errores(job_id, db)
    nota = min(media, tope.tope) if tope else media

    return InsightsResponse(
        job_id=job_id,
        overall_score=nota,
        overall_score_sin_tope=media,
        tope=tope if tope and tope.tope < media else None,
        categories=categories,
        generated_at=datetime.now(timezone.utc),
    )


# Topes de la nota global (UX-05, decision 92). Una media ponderada no puede
# decir «Bueno» de un censo con errores abiertos: el de Lopesan sacaba 88 con
# 2.367 paginas canonicalizadas a otro dominio, la mitad del sitio fuera del
# indice. Con cualquier error, como mucho «Mejorable»; si afecta al 10% de las
# URLs internas o mas, como mucho «Critico».
TOPE_CON_ERRORES = 79
TOPE_CON_ERRORES_EXTENDIDOS = 49
UMBRAL_ERRORES_EXTENDIDOS = 10.0


def _tope_por_errores(job_id: uuid.UUID, db: Session) -> TopeDeNota | None:
    paginas = db.query(func.count(func.distinct(Issue.url_id))).filter(
        Issue.job_id == job_id, Issue.severity == "error",
    ).scalar() or 0
    if not paginas:
        return None
    internas = db.query(func.count(Url.id)).filter(
        Url.job_id == job_id, Url.is_internal == True,
    ).scalar() or 0
    pct = _safe_pct(paginas, internas)
    if pct >= UMBRAL_ERRORES_EXTENDIDOS:
        return TopeDeNota(
            tope=TOPE_CON_ERRORES_EXTENDIDOS, paginas_con_error=paginas, de=internas, pct=pct,
            motivo=f"El {pct}% de las URLs internas tiene algun error: la nota no puede pasar de {TOPE_CON_ERRORES_EXTENDIDOS}.",
        )
    return TopeDeNota(
        tope=TOPE_CON_ERRORES, paginas_con_error=paginas, de=internas, pct=pct,
        motivo=f"Hay {paginas} URLs con algun error: la nota no puede pasar de {TOPE_CON_ERRORES} mientras sigan abiertos.",
    )


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/informe — el informe para el cliente (Ola 6.2,
# decision 138). Junta lo que ya calculan los demas endpoints; no mide nada
# nuevo. La interfaz lo pinta en una pagina imprimible (`#/rastreos/<id>/informe-cliente`)
# con las fichas de `incidencias.js`, que viven en el frontend.
# ---------------------------------------------------------------------------
_TEXTO_TRUNCADO = {
    "max_urls_reached": "se detuvo al llegar al máximo de URLs",
    "max_runtime_reached": "se detuvo al agotar el tiempo máximo",
    "stalled": "se quedó parado y se cerró",
    "cancelled": "se canceló a medias",
    "tope_por_carpeta": "dejó partes del sitio sin rastrear por los topes por carpeta",
    "frontera_sin_disco": "se quedó sin disco para la cola y perdió URLs por rastrear",
}


def _trafico_del_informe(db: Session, job: Job) -> dict | None:
    """Search Console en el informe (decision 142): lo que el cliente entiende
    sin explicacion, el trafico que se pierde y el que nadie enlaza."""
    r = job.gsc_resumen if isinstance(getattr(job, "gsc_resumen", None), dict) else None
    if not r:
        return None
    salida = {k: r.get(k) for k in ("desde", "hasta", "clics", "impresiones", "clics_en_urls_del_censo",
                                     "clics_en_variantes", "urls_fuera_del_censo", "clics_fuera_del_censo",
                                     "cubre_la_ventana")}
    salida["fuera_del_censo"] = (r.get("fuera_del_censo") or [])[:5]
    salida["inspeccion"] = r.get("inspeccion")
    for tipo in ("trafico_en_pagina_perdida", "huerfana_con_trafico", "trafico_en_variante_con_parametros"):
        filas = (db.query(Url.url, Issue.details).join(Url, Url.id == Issue.url_id)
                 .filter(Issue.job_id == job.id, Issue.issue_type == tipo).all())
        clave = "clics_variantes" if tipo == "trafico_en_variante_con_parametros" else "clics"
        filas = sorted(((int((d or {}).get(clave) or 0), u) for u, d in filas), reverse=True)
        salida[tipo] = {"paginas": len(filas), "clics": sum(c for c, _ in filas),
                        "ejemplos": [{"url": u, "clics": c} for c, u in filas[:5]]}
    return salida


def _ia_del_informe(db: Session, job: Job) -> dict | None:
    """Buscadores de IA en el informe (decisiones 129, 137 y 140): si pueden
    entrar segun el robots.txt, que paginas se les niegan con `nosnippet` y
    que contenido solo existe con JavaScript (no lo ejecutan). None si el
    censo no tiene nada de eso medido: no se afirma «todo bien» sin mirar."""
    from urllib.parse import urlsplit

    from shared.robots_txt import BOTS_INFO

    salida: dict[str, Any] = {"bots": [], "nosnippet": 0, "max_snippet": 0,
                              "data_nosnippet": 0,
                              "solo_con_js": {"paginas": 0, "plantillas": 0, "muestreadas": 0}}
    sitio = urlsplit(_raiz_del_sitio((job.seeds or [None])[0]) or "").hostname or ""
    try:
        filas = _filas_robots(db, job.id, con_cuerpo=False)
    except Exception:  # noqa: BLE001 — sin tabla, sin la parte de robots
        db.rollback()
        filas = {}
    ev = None
    for _o, fila in sorted(filas.items()):
        e = fila.evaluacion if isinstance(fila.evaluacion, dict) else {}
        if e.get("bots") and (ev is None or (fila.host or "") == sitio):
            ev = e["bots"]
    if ev:
        for b in BOTS_INFO:
            if b["tipo"] in ("busqueda_ia", "entrenamiento") and b["bot"] in ev:
                salida["bots"].append({"token": b["token"], "proveedor": b["proveedor"], "tipo": b["tipo"],
                                       "alcance": (ev.get(b["bot"]) or {}).get("alcance")})
    cuentas = dict(db.query(Issue.issue_type, func.count(func.distinct(Issue.url_id)))
                   .filter(Issue.job_id == job.id,
                           Issue.issue_type.in_(("nosnippet_en_indexable", "max_snippet_restrictivo")))
                   .group_by(Issue.issue_type).all())
    salida["nosnippet"] = int(cuentas.get("nosnippet_en_indexable", 0))
    salida["max_snippet"] = int(cuentas.get("max_snippet_restrictivo", 0))
    for (d,) in db.query(Issue.details).filter(Issue.job_id == job.id,
                                               Issue.issue_type == "contenido_solo_con_js"):
        d = d or {}
        salida["solo_con_js"]["paginas"] += int(d.get("paginas_afectadas") or 0)
        salida["solo_con_js"]["muestreadas"] += int(d.get("paginas_muestreadas") or 0)
        salida["solo_con_js"]["plantillas"] += 1
    # Decision 170: agrupado por plantilla, se suman sus paginas afectadas.
    for (d,) in db.query(Issue.details).filter(
            Issue.job_id == job.id, Issue.issue_type == "data_nosnippet_contenido_principal"):
        salida["data_nosnippet"] += int((d or {}).get("paginas_afectadas") or 0)
    if not (salida["bots"] or salida["nosnippet"] or salida["max_snippet"] or salida["data_nosnippet"]
            or salida["solo_con_js"]["plantillas"]):
        return None
    return salida


def _backlinks_del_informe(db: Session, job: Job) -> dict | None:
    """Backlinks en el informe (decision 212): cuantos llegan, cuantos son
    nofollow y cuantos spam segun el proveedor (ni unos ni otros aportan
    autoridad), las paginas que mas reciben y lo que cae en errores. None sin
    CSV subido para el cliente."""
    r = job.pagerank_resumen if isinstance(getattr(job, "pagerank_resumen", None), dict) else None
    e = (r or {}).get("externo")
    if not isinstance(e, dict) or not e.get("backlinks"):
        return None
    entra = e.get("entra_en") or {}
    salida = {k: e.get(k) for k in ("fuente", "fecha_dato", "backlinks", "nofollow", "spam", "casados",
                                     "paginas_con_backlinks")}
    salida["perdida"] = round(float(entra.get("error") or 0) + float(entra.get("sin_respuesta") or 0), 4)
    nofollow = func.coalesce(Url.backlinks_nofollow, 0)
    todos = Url.backlinks_externos + nofollow
    filas = (db.query(Url.url, todos, nofollow, Url.backlinks_spam)
             .filter(Url.job_id == job.id, todos > 0)
             .order_by(todos.desc(), Url.id).limit(5).all())
    salida["paginas"] = [{"url": u, "backlinks": b, "nofollow": nf, "spam": s} for u, b, nf, s in filas]
    salida["a_error"] = (db.query(func.count(Issue.id))
                         .filter(Issue.job_id == job.id, Issue.issue_type == "backlinks_a_error").scalar() or 0)
    return salida


def _raiz_del_sitio(semilla: str | None) -> str | None:
    """`https://host`: la primera semilla de una lista puede ser `/blog/`, y la
    cabecera de un informe del sitio entero no puede decir eso."""
    from urllib.parse import urlsplit

    if not semilla:
        return None
    p = urlsplit(semilla)
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else semilla


@router.get("/informe")
def get_informe(
    job_id: uuid.UUID,
    prioridades: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_session),
):
    """Lo que se le entrega al cliente de UN censo, en este orden: la nota y por
    que, las cifras, lo que ha cambiado frente al anterior, que arreglar primero
    y con que fiabilidad se puede leer todo lo anterior.

    La fiabilidad va en el informe y no en una nota aparte: un informe que
    parece completo y no lo es (un censo truncado, un grafo sin los enlaces de
    JavaScript, un muro) es peor que no entregarlo (decisiones 35, 67 y 103)."""
    from shared.comparacion import MOTIVOS_TRUNCADO
    from shared.models import Client
    from shared.resumen_semanal import _resumen_de_rastreo

    job = _get_job_or_404(job_id, db)
    insights = get_insights(job_id, db)
    stats = get_stats(job_id, db)
    # `por_segmento` para tener `agregadas`: un hallazgo de plantilla dice
    # «1 pagina» y afecta a todo el sitio; el informe lo tiene que decir.
    filas = resumen_issues(job_id, ejemplos=3, segmento=None, por_segmento=True,
                           segmentos_max=1, orden="prioridad", db=db)
    for r in filas:
        r.por_segmento = None
    cliente = (db.query(Client).filter(Client.id == job.cliente_id).one_or_none()
               if getattr(job, "cliente_id", None) else None)
    config = job.config if isinstance(job.config, dict) else {}
    lista = config.get("max_depth") in (0, "0")

    fiabilidad: list[str] = []
    motivo = job.finish_reason or ""
    if job.status != "completed":
        fiabilidad.append(f"El rastreo no terminó bien (estado «{job.status}»): las cifras son parciales.")
    elif motivo in MOTIVOS_TRUNCADO and not lista and motivo != "tope_por_carpeta":
        fiabilidad.append(f"El rastreo {_TEXTO_TRUNCADO.get(motivo, motivo)}: el informe no cubre el "
                          "sitio entero, y lo que no se rastreó no se puede dar por bueno ni por malo.")
    # Los topes por carpeta (decision 172), con las partes concretas: tambien
    # junto a otro corte, que no dice cuales se quedaron a medias.
    from shared.topes_carpeta import describir

    topes = describir(getattr(job, "topes_carpeta", None))
    if topes:
        fiabilidad.append(f"{topes}: el censo no está entero y, como lo que no se pidió también enlaza al resto del sitio, no se afirman páginas huérfanas ni sin camino desde la home.")
    if motivo == "bloqueado_por_waf":
        fiabilidad.append("Un cortafuegos (WAF) bloqueó parte del rastreo: las páginas detrás del muro "
                          "no se han auditado.")
    if _pagerank_fiable(db, job_id) is False:
        fiabilidad.append("Algunas plantillas montan sus enlaces con JavaScript y el rastreo no los ve: "
                          "las cifras de enlazado interno y PageRank están incompletas.")

    comparacion = None
    try:
        comparacion = _resumen_de_rastreo(db, job)
    except Exception:  # noqa: BLE001 — el informe sale sin la comparacion
        logger.warning("Informe del job %s sin comparacion", job_id, exc_info=True)

    return {
        "job": {
            "id": str(job.id), "nombre": job.name, "estado": job.status, "motivo": job.finish_reason,
            "sitio": _raiz_del_sitio((job.seeds or [None])[0]), "semillas": len(job.seeds or []),
            "fecha": (job.completed_at or job.started_at or job.created_at),
            "modo_lista": lista, "render_js": bool(config.get("render_js")),
            "crawler_version": getattr(job, "crawler_version", None),
            "analisis_version": getattr(job, "analisis_version", None),
        },
        "cliente": {"id": str(cliente.id), "nombre": cliente.nombre, "slug": cliente.slug} if cliente else None,
        "nota": {
            "global": insights.overall_score,
            "sin_tope": insights.overall_score_sin_tope,
            "tope": insights.tope.model_dump() if insights.tope else None,
            "categorias": [{"key": c.key, "nombre": c.name, "nota": c.score} for c in insights.categories],
        },
        "cifras": {
            "urls": stats.total_urls, "paginas_html": stats.paginas_html,
            "indexables": stats.indexables, "no_indexables": stats.no_indexables,
            "por_estado": {g.status_group: g.count for g in stats.urls_by_status_group},
            "incidencias": sum(t.count for t in stats.issues_by_type),
        },
        "prioridades": [r.model_dump() for r in filas[:prioridades]],
        "tipos_de_incidencia": len(filas),
        "comparacion": comparacion,
        "fiabilidad": fiabilidad,
        "trafico": _trafico_del_informe(db, job),
        "ia": _ia_del_informe(db, job),
        "backlinks": _backlinks_del_informe(db, job),
        "generado": datetime.now(timezone.utc),
    }


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/export.xlsx — el censo en Excel con varias hojas
# (Ola 6.3, decision 145)
# ---------------------------------------------------------------------------
@router.get("/export.xlsx")
def export_excel(job_id: uuid.UUID, db: Session = Depends(get_session)):
    """Resumen, que arreglar (con la ficha de cada incidencia), URLs,
    incidencias y lo de Google que el rastreo no encontro (`api/excel.py`).
    Se escribe en un temporal con openpyxl en solo escritura y se borra al
    terminar de servirlo."""
    import os
    import tempfile

    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    from api.excel import escribir

    job = _get_job_or_404(job_id, db)
    fd, ruta = tempfile.mkstemp(suffix=".xlsx", prefix="censo-")
    os.close(fd)
    try:
        escribir(ruta, db, job_id)
    except Exception:
        os.unlink(ruta)
        raise
    host = (_raiz_del_sitio((job.seeds or [None])[0]) or "censo").split("//")[-1]
    fecha = (job.completed_at or job.created_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return FileResponse(
        ruta, filename=f"{host}-{fecha}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(os.unlink, ruta))
