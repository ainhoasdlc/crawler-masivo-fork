"""Arrastre de un job incremental: lo no pedido, copiado del censo anterior
(#36 F4, decision 220).

Corre en el worker despues del rastreo y ANTES del analisis, con el job en
`analyzing`, y solo si `jobs.incremental.modo == "incremental"`. Deja el job
como una foto completa del sitio, asi que el analizador, el PageRank, la
comparacion y las decisiones funcionan sin saber que hubo arrastre:

1. Completa los 304 (`fetch_mode='not_modified'`) con la fila del anterior.
2. Copia a `urls` lo del anterior que no esta en este job (`carried`), con su
   `last_crawled_at` de entonces. Las columnas que calcula el analisis van a
   sus valores por defecto, como en una fila recien rastreada.
3. Copia sus hijos (y los de los 304): metadatos, encabezados, hreflang, datos
   estructurados, recursos, contenido, cabeceras, extraccion a medida,
   enlaces no rastreables y `links`, estos del Parquet si el anterior esta
   archivado (decision 150). No se copian incidencias, Search Console ni
   nada del analisis: lo recalcula el analisis de este job.
4. Aplica la membresia del sitemap de ESTE rastreo a lo copiado.
5. Poda lo copiado que ya no enlaza nadie: un completo no lo habria encontrado.

Una sola transaccion: si se corta, no queda nada a medias y se repite entera.
Con `jobs.incremental.arrastre.hecho` no se repite (el re-analisis de un
incremental ya arrastrado no duplica filas).

Solo Postgres: `UPDATE ... FROM`, tablas temporales y `COPY`.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class OrigenBorrado(RuntimeError):
    """El censo del que se copia ya no existe: sin el, la foto saldria
    incompleta (decision 20)."""


# ---------------------------------------------------------------------------
# Columnas de `urls`
# ---------------------------------------------------------------------------
# Las que escribe el rastreo (`pipelines._handle_page`) y se copian tal cual.
COPIADAS = (
    "url", "url_hash", "host", "path", "scheme", "is_internal", "crawl_depth",
    "content_type", "content_length", "status_code", "status_group",
    "response_time_ms", "ttfb_ms", "content_encoding", "is_html", "resource_type",
    "redirect_url", "body_hash", "url_length", "folder_depth", "word_count",
    "content_word_count", "content_hash", "html_bytes_servidos", "text_ratio",
    "redirect_type", "status_text", "last_modified", "http_version",
    "transfer_size", "indexability_status", "blocked_by_robots", "response_class",
    "first_seen_at", "last_crawled_at", "etag",
)
# De la fila de ESTE job en un 304: lo que se pidio de verdad (la URL, cuando
# y a que profundidad se llego) y lo que dijo el servidor.
PROPIAS_DEL_304 = ("url", "url_hash", "host", "path", "scheme", "is_internal",
                   "crawl_depth", "last_crawled_at", "etag", "last_modified")
# Las de la propia fila: ni se copian ni se reinician.
DE_LA_FILA = ("id", "job_id", "fetch_mode")
# Las que calcula el analisis (o el cierre del spider, `in_sitemap`): en una
# fila copiada empiezan en su valor por defecto, como una recien rastreada.
CALCULADAS = (
    "click_depth", "gsc_clics", "gsc_impresiones", "gsc_posicion", "indexable",
    "noindex", "bloqueada_googlebot", "inlinks_count", "outlinks_count",
    "external_outlinks_count", "unique_inlinks_count", "pagerank", "pagerank_raw",
    "pagerank_score", "pagerank_externo_score", "backlinks_externos", "backlinks_spam",
    "autoridad_externa", "googlebot_visitas", "googlebot_ultima",
    "near_duplicate_count", "closest_similarity", "in_sitemap", "segmento",
)

# Hijos por `url_id` que se copian: (tabla, si llevan `job_id`, columnas que
# se reinician o se reescriben -> expresion SQL sobre la fila `c` de origen).
HIJOS: tuple[tuple[str, bool, dict[str, str]], ...] = (
    ("html_meta", False, {}),
    ("headings", False, {}),
    # El retorno y la validez del idioma los decide el analisis.
    ("hreflang", False, {"return_tag_ok": "NULL", "lang_valid": "NULL"}),
    ("structured_data", False, {"validation_status": "NULL", "validation_issues": "NULL"}),
    ("resources", False, {}),
    # La limpieza es por job (`cleaning_rulesets`): se copia el original.
    ("page_content", False, {
        "content_text": "COALESCE(c.content_text_original, c.content_text)",
        "content_markdown": "COALESCE(c.content_markdown_original, c.content_markdown)",
        "content_text_original": "NULL", "content_markdown_original": "NULL",
        "cleaned_at": "NULL",
    }),
    ("security_headers", False, {}),
    ("custom_extraction", True, {}),
)


def _defecto(columna) -> Any:
    d = columna.default
    if d is not None and getattr(d, "is_scalar", False):
        return d.arg
    return None


def _columnas_de(tabla: str) -> list[str]:
    from shared.models import Base

    return [c.name for c in Base.metadata.tables[tabla].columns]


# ---------------------------------------------------------------------------
# El arrastre
# ---------------------------------------------------------------------------
def arrastrar(db, job_id) -> dict[str, Any] | None:
    """Arrastra el job. Devuelve el resumen (`jobs.incremental.arrastre`), o
    None si el job no es incremental. Lanza `OrigenBorrado` si falta el censo
    del que copiar. Con commit."""
    from sqlalchemy import text

    from shared.candados import clave_de_job
    from shared.incremental import es_incremental
    from shared.models import Job

    job = db.get(Job, job_id)
    if job is None or not es_incremental(job):
        return None
    inc = dict(job.incremental)
    hecho = inc.get("arrastre") or {}
    if hecho.get("hecho"):
        logger.info("Job %s: arrastre ya hecho, no se repite", job_id)
        return hecho
    prev_id = inc.get("prev_job_id")
    prev = db.get(Job, prev_id) if prev_id else None
    if prev is None or not db.execute(
            text("SELECT EXISTS (SELECT 1 FROM urls WHERE job_id = :p)"),
            {"p": str(prev.id)}).scalar():
        raise OrigenBorrado(f"el censo {prev_id} del que se arrastra ya no existe")

    t0 = time.monotonic()
    cur, ant = str(job.id), str(prev.id)
    # El candado del ANTERIOR: un re-analisis suyo restaura sus enlaces a
    # `links` y borra el Parquet (decision 150), y leerlo a la vez daria uno
    # de los dos a medias.
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": clave_de_job(prev.id)})
    # Releido CON el candado: si se estaba re-analizando, al soltarlo sus
    # enlaces han vuelto al Parquet, y la marca leida antes diria que estan
    # en `links` (donde ya no hay nada).
    db.refresh(prev)

    r: dict[str, Any] = {}
    r["no_modificadas"] = _completar_304(db, cur, ant)
    r["arrastradas"] = _copiar_urls(db, cur, ant)
    _crear_remap(db, cur, ant)
    r["hijos"] = {t: _copiar_hijo(db, cur, t, con_job, reescribir)
                  for t, con_job, reescribir in HIJOS}
    r["hijos"]["enlaces_no_rastreables"] = _copiar_no_rastreables(db, cur)
    r["enlaces"] = _copiar_links(db, cur, prev)
    r["respuestas_sondeadas"] = _copiar_sondeadas(db, cur, str(prev.id))
    _membresia_de_sitemap(db, job)
    r["podadas"] = _podar(db, job)

    total, arrastradas, mas_vieja = db.execute(text("""
        SELECT count(*), count(*) FILTER (WHERE fetch_mode = 'carried'),
               min(last_crawled_at) FILTER (WHERE fetch_mode = 'carried')
          FROM urls WHERE job_id = :j
    """), {"j": cur}).one()
    r["total"] = int(total)
    r["arrastradas_final"] = int(arrastradas)
    r["pct_arrastrado"] = round(100.0 * arrastradas / total, 1) if total else 0.0
    r["mas_antigua"] = mas_vieja.isoformat() if mas_vieja is not None else None
    r["segundos"] = round(time.monotonic() - t0, 1)
    r["hecho"] = True
    inc["arrastre"] = r
    job.incremental = inc
    db.commit()
    logger.info("Job %s: arrastre de %s hecho: %s", cur, ant, r)
    return r


def _completar_304(db, cur: str, ant: str) -> int:
    from sqlalchemy import text

    columnas = [c for c in COPIADAS if c not in PROPIAS_DEL_304]
    asignaciones = ", ".join(f"{c} = o.{c}" for c in columnas)
    n = db.execute(text(f"""
        UPDATE urls n SET {asignaciones}, etag = COALESCE(n.etag, o.etag),
               last_modified = COALESCE(n.last_modified, o.last_modified)
          FROM urls o
         WHERE n.job_id = :cur AND n.fetch_mode = 'not_modified'
           AND o.job_id = :ant AND o.url_hash = n.url_hash
    """), {"cur": cur, "ant": ant}).rowcount
    # Un 304 de una URL que el anterior no tiene no deberia existir (solo se
    # pide condicional lo que estaba): sin nada con que completarlo, se pide
    # en el siguiente ciclo. Se borra para no dejar un «304» en el censo.
    db.execute(text("""
        DELETE FROM urls n
         WHERE n.job_id = :cur AND n.fetch_mode = 'not_modified'
           AND NOT EXISTS (SELECT 1 FROM urls o WHERE o.job_id = :ant
                            AND o.url_hash = n.url_hash)
    """), {"cur": cur, "ant": ant})
    return int(n or 0)


def _copiar_urls(db, cur: str, ant: str) -> int:
    from sqlalchemy import bindparam, text

    from shared.models import Url

    por_nombre = {c.name: c for c in Url.__table__.columns}
    calculadas = [c for c in CALCULADAS]
    destino = ["job_id", "fetch_mode", *COPIADAS, *calculadas]
    origen = [":cur", "'carried'", *(f"o.{c}" for c in COPIADAS),
              *(f":d_{c}" for c in calculadas)]
    params: dict[str, Any] = {"cur": cur, "ant": ant}
    params.update({f"d_{c}": _defecto(por_nombre[c]) for c in calculadas})
    sentencia = text(f"""
        INSERT INTO urls ({", ".join(destino)})
        SELECT {", ".join(origen)}
          FROM urls o
         WHERE o.job_id = :ant
           AND NOT EXISTS (SELECT 1 FROM urls n WHERE n.job_id = :cur
                            AND n.url_hash = o.url_hash)
        ON CONFLICT ON CONSTRAINT uq_job_url DO NOTHING
    """)
    tipos = [bindparam(f"d_{c}", type_=por_nombre[c].type) for c in calculadas]
    return int(db.execute(sentencia.bindparams(*tipos), params).rowcount or 0)


def _crear_remap(db, cur: str, ant: str) -> None:
    from sqlalchemy import text

    db.execute(text("DROP TABLE IF EXISTS arrastre_remap"))
    db.execute(text("""
        CREATE TEMP TABLE arrastre_remap ON COMMIT DROP AS
        SELECT o.id AS old_id, n.id AS new_id
          FROM urls n
          JOIN urls o ON o.job_id = :ant AND o.url_hash = n.url_hash
         WHERE n.job_id = :cur AND n.fetch_mode IN ('carried', 'not_modified')
    """), {"cur": cur, "ant": ant})
    db.execute(text("CREATE UNIQUE INDEX ON arrastre_remap (old_id)"))
    # Sin estadisticas el planificador cree que tiene una fila (decision 21).
    db.execute(text("ANALYZE arrastre_remap"))


def _copiar_hijo(db, cur: str, tabla: str, con_job: bool, reescribir: dict[str, str]) -> int:
    from sqlalchemy import text

    # Sin `id`: las que lo tienen lo sacan de su secuencia.
    columnas = [c for c in _columnas_de(tabla) if c not in ("id", "url_id", "job_id")]
    destino = ["url_id", *(["job_id"] if con_job else []), *columnas]
    origen = ["r.new_id", *([":cur"] if con_job else []),
              *(reescribir.get(c, f"c.{c}") for c in columnas)]
    n = db.execute(text(f"""
        INSERT INTO {tabla} ({", ".join(destino)})
        SELECT {", ".join(origen)}
          FROM {tabla} c
          JOIN arrastre_remap r ON r.old_id = c.url_id
    """), {"cur": cur}).rowcount
    return int(n or 0)


def _copiar_no_rastreables(db, cur: str) -> int:
    from sqlalchemy import text

    columnas = [c for c in _columnas_de("enlaces_no_rastreables")
                if c not in ("id", "job_id", "from_url_id")]
    n = db.execute(text(f"""
        INSERT INTO enlaces_no_rastreables (job_id, from_url_id, {", ".join(columnas)})
        SELECT :cur, r.new_id, {", ".join("c." + c for c in columnas)}
          FROM enlaces_no_rastreables c
          JOIN arrastre_remap r ON r.old_id = c.from_url_id
    """), {"cur": cur}).rowcount
    return int(n or 0)


def _copiar_links(db, cur: str, prev) -> int:
    """Los enlaces salientes de lo copiado, de `links` o del Parquet."""
    from sqlalchemy import text

    from shared import archivo_enlaces

    columnas = [c for c in archivo_enlaces.COLUMNAS if c not in ("id", "from_url_id")]
    if not archivo_enlaces.esta_archivado(prev):
        n = db.execute(text(f"""
            INSERT INTO links (job_id, from_url_id, {", ".join(columnas)})
            SELECT :cur, r.new_id, {", ".join("l." + c for c in columnas)}
              FROM links l
              JOIN arrastre_remap r ON r.old_id = l.from_url_id
             WHERE l.job_id = :ant
        """), {"cur": cur, "ant": str(prev.id)}).rowcount
        return int(n or 0)

    import io

    import pyarrow.parquet as pq

    remap = dict(db.execute(text("SELECT old_id, new_id FROM arrastre_remap")).all())
    if not remap:
        return 0
    cursor = db.connection().connection.cursor()
    sentencia = f"COPY links (job_id, from_url_id, {', '.join(columnas)}) FROM STDIN"
    fichero = pq.ParquetFile(archivo_enlaces.ruta(prev.id))
    n = 0
    for lote in fichero.iter_batches(batch_size=50_000,
                                     columns=["from_url_id", *columnas]):
        origenes = lote.column("from_url_id").to_pylist()
        valores = [lote.column(c).to_pylist() for c in columnas]
        buf = io.StringIO()
        for i, viejo in enumerate(origenes):
            nuevo = remap.get(viejo)
            if nuevo is None:
                continue
            buf.write(cur)
            buf.write("\t")
            buf.write(str(nuevo))
            for col in valores:
                buf.write("\t")
                buf.write(archivo_enlaces._valor_copy(col[i]))
            buf.write("\n")
            n += 1
        if buf.tell():
            buf.seek(0)
            cursor.copy_expert(sentencia, buf)
    return n


def _copiar_sondeadas(db, cur: str, ant: str) -> int:
    """Lo que respondieron los enlaces externos y recursos del anterior que
    este rastreo no ha vuelto a sondear (decisiones 123 y 124).

    Las sondas salen de las paginas pedidas: sin esto, un enlace a un dominio
    muerto en una pagina copiada dejaria de avisarse y la comparacion lo daria
    por resuelto. Va con su `fecha` de entonces.
    """
    from sqlalchemy import text

    columnas = [c for c in _columnas_de("respuestas_sondeadas") if c not in ("id", "job_id")]
    n = db.execute(text(f"""
        INSERT INTO respuestas_sondeadas (job_id, {", ".join(columnas)})
        SELECT :cur, {", ".join("c." + c for c in columnas)}
          FROM respuestas_sondeadas c
         WHERE c.job_id = :ant
        ON CONFLICT ON CONSTRAINT uq_rsond_job_hash DO NOTHING
    """), {"cur": cur, "ant": ant}).rowcount
    return int(n or 0)


def _membresia_de_sitemap(db, job) -> None:
    """`in_sitemap` de lo copiado, con el sitemap de ESTE rastreo.

    La misma regla que `SeoSpider._persist_sitemap_membership`: True si esta;
    False si no esta y el sitemap se leyo entero; NULL si no hubo sitemap o se
    leyo a medias (no se afirma lo que no se ha visto). Si hubo datos de
    sitemap se sabe por las filas pedidas: el spider las marco al cerrar.
    """
    from sqlalchemy import text

    cur = str(job.id)
    con_datos = db.execute(text("""
        SELECT EXISTS (SELECT 1 FROM urls WHERE job_id = :j AND in_sitemap IS NOT NULL
                          AND fetch_mode IS DISTINCT FROM 'carried')
            OR EXISTS (SELECT 1 FROM sitemap_arrastre WHERE job_id = :j)
    """), {"j": cur}).scalar()
    if not con_datos:
        return
    db.execute(text("""
        UPDATE urls u SET in_sitemap = TRUE
          FROM sitemap_arrastre s
         WHERE u.job_id = :j AND u.fetch_mode IN ('carried', 'not_modified')
           AND s.job_id = :j AND s.url_hash = u.url_hash
    """), {"j": cur})
    parcial = bool((job.sitemaps or {}).get("parcial"))
    if not parcial:
        db.execute(text("""
            UPDATE urls SET in_sitemap = FALSE
             WHERE job_id = :j AND fetch_mode = 'carried' AND in_sitemap IS NULL
        """), {"j": cur})


def _podar(db, job) -> int:
    """Borra lo copiado que ya no se alcanza desde las semillas, el sitemap o
    el destino de una redireccion de este job.

    Por TODOS los enlaces, no solo los `is_internal`: con `crawl_subdomains`
    el spider sigue los de un subdominio aunque la fila diga externo, y con
    `follow_external` los de fuera. Recorrer de mas solo poda de menos.

    Una pagina pedida que quita su enlace a una que no tocaba: copiada sin
    mas, saldria con 0 entrantes como huerfana nueva y en la comparacion nunca
    «desapareceria»; un completo no la habria encontrado. Solo se poda HTML
    2xx copiado: una redireccion o un error copiados no cuelgan de nada que
    se pueda comprobar aqui, y quedarse corto es dejar una fila que el
    siguiente completo confirma.
    """
    from sqlalchemy import text

    from shared.incremental import _hashes_de_semillas

    cur = str(job.id)
    raices = set(_hashes_de_semillas(job.seeds))
    try:
        from seo_crawler.extractors import compute_url_hash, normalize_url
    except ImportError:
        from crawler.seo_crawler.extractors import compute_url_hash, normalize_url
    for (destino,) in db.execute(text(
            "SELECT redirect_url FROM urls WHERE job_id = :j AND redirect_url IS NOT NULL"),
            {"j": cur}):
        try:
            raices.add(compute_url_hash(normalize_url(destino)))
        except Exception:
            continue
    raices.update(h for (h,) in db.execute(text(
        "SELECT url_hash FROM urls WHERE job_id = :j AND in_sitemap IS TRUE"), {"j": cur}))
    db.execute(text("DROP TABLE IF EXISTS arrastre_raices"))
    db.execute(text("CREATE TEMP TABLE arrastre_raices (h text PRIMARY KEY) ON COMMIT DROP"))
    lista = sorted(raices)
    for i in range(0, len(lista), 5000):
        db.execute(text("INSERT INTO arrastre_raices (h) SELECT unnest(CAST(:l AS text[])) "
                        "ON CONFLICT DO NOTHING"), {"l": lista[i:i + 5000]})
    n = db.execute(text("""
        WITH RECURSIVE alcanzadas(h) AS (
            SELECT h FROM arrastre_raices
            UNION
            SELECT l.to_url_hash
              FROM alcanzadas a
              JOIN urls u ON u.job_id = :j AND u.url_hash = a.h
              JOIN links l ON l.job_id = :j AND l.from_url_id = u.id
        )
        DELETE FROM urls u
         WHERE u.job_id = :j AND u.fetch_mode = 'carried'
           AND u.is_html AND u.status_code BETWEEN 200 AND 299
           AND NOT EXISTS (SELECT 1 FROM alcanzadas a WHERE a.h = u.url_hash)
    """), {"j": cur}).rowcount
    return int(n or 0)


def main() -> None:
    import argparse
    import sys

    from shared.database import SessionLocal

    p = argparse.ArgumentParser(description="Arrastra un job incremental (decision 220)")
    p.add_argument("job_id")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    db = SessionLocal()
    try:
        print(arrastrar(db, args.job_id))
    except OrigenBorrado as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)
    finally:
        db.close()


if __name__ == "__main__":
    main()
