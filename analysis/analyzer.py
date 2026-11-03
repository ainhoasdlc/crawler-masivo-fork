"""
SEO Analysis Engine
~~~~~~~~~~~~~~~~~~~

Post-crawl analysis that inspects every URL collected by a crawl job
and populates the ``issues`` table with actionable SEO findings.

Usage::

    from analysis.analyzer import run_analysis
    run_analysis(job_id="some-uuid-string")
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import time
import uuid
from contextlib import contextmanager
import re
import sys
from array import array
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Sequence
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlsplit

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session, aliased

from shared.config import (
    DESCRIPTION_MAX_LEN,
    DESCRIPTION_MAX_PIXELS,
    DESCRIPTION_MIN_LEN,
    GOOGLEBOT_HTML_MAX_BYTES,
    TITLE_MAX_LEN,
    TITLE_MAX_PIXELS,
    TITLE_MIN_LEN,
)
from analysis.sd_validation import problemas_structured_data
from analysis import near_duplicates as nd
from analysis import pagerank as prk
from analysis import avisos_de_enlaces, avisos_de_sondas
from analysis import avisos_de_paginacion
from analysis import avisos_de_gsc, avisos_de_render, avisos_de_servidor, oportunidades_gsc
from analysis import avisos_de_accesibilidad
from analysis import avisos_de_sitemaps
from analysis import avisos_de_html
from analysis import avisos_de_medios
from analysis import avisos_de_nosnippet
from analysis import avisos_de_entidad
from analysis import avisos_de_nofollow
from analysis import avisos_de_wordpress
from analysis import avisos_de_backlinks
from analysis import avisos_de_logs
from analysis import avisos_de_trampas
from shared.rel_de_enlace import sql_nofollow_por_rel
from shared.indexabilidad import (
    BOT_POR_DEFECTO, clave_url, es_noindex, estado_indexabilidad, limite_de_fragmento, misma_url,
    x_robots_para_bot,
)
from shared.meta_refresh import retardo_meta_refresh
from shared.plantillas import firma_de_ruta
from shared.titulos import description_igual_title, es_title_generico, marcas_del_host
from shared.respuestas import NO_VALIDAS
from shared.robots import robots_bad_separators
from shared.database import SessionLocal
from shared.dominios import dominio_registrable
from shared.models import (
    Heading,
    HtmlMeta,
    Hreflang,
    Issue,
    Link,
    PageContent,
    Resource,
    SecurityHeaders,
    StructuredData,
    Url,
)

# Decision 137: por debajo de esto el fragmento queda mas corto que el que
# Google suele ensenar (unos 150-160 caracteres) y las funciones de IA solo
# pueden citar ese trozo. Un juicio, como el resto de umbrales de longitud.
MAX_SNIPPET_CORTO = 160

logger = logging.getLogger(__name__)


def _ejemplos_por_url(paginas: list[tuple[str, int]], n: int = 5) -> list[str]:
    """Las `n` primeras URLs distintas de unos pares (url, id) ya ordenados.

    Por URL y no por id, como el ancla: si no, la muestra de un aviso agregado
    cambia entre dos censos iguales rastreados en otro orden (decision 88).
    """
    vistas: list[str] = []
    for url, _ in paginas:
        if not vistas or vistas[-1] != url:
            vistas.append(url)
            if len(vistas) >= n:
                break
    return vistas


# Parametros de version que un CMS anade a la URL de un recurso y cambian sin
# que cambie el recurso (Liferay: `?t=<marca de tiempo>&version=3.3`).
_PARAMS_DE_VERSION = frozenset({"t", "v", "ver", "version", "cb", "_", "ts", "timestamp"})


def _url_sin_version(url: str) -> str:
    """La URL de un recurso sin sus parametros de version, para que la misma
    imagen sea el mismo hallazgo aunque el CMS cambie el `?t=`."""
    p = urlsplit(url or "")
    if not p.query:
        return url
    resto = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if k.lower() not in _PARAMS_DE_VERSION]
    return p._replace(query=urlencode(resto)).geturl()


def _clave_de_grupo(valor: str | None) -> str | None:
    """La clave estable de un hallazgo dentro de su tipo y su URL (#32).

    Se guarda un **hash**, no el valor: una description duplicada puede tener
    1.000 caracteres y la clave se repite en cada fila del grupo. Con SHA-256
    truncado a 16 hexadecimales la colision es despreciable para lo que se usa
    —comparar dos censos del mismo sitio— y la columna no engorda la tabla.

    Se normaliza la caja y los espacios por la misma razon que el
    `content_hash` de la decision 47: dos valores que solo se diferencian en
    eso son el MISMO hallazgo, y tratarlos como distintos diria que uno se
    resolvio y apareció otro.
    """
    if valor is None:
        return None
    texto = " ".join(str(valor).split()).casefold()
    if not texto:
        return None
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def _misma_ruta(a: tuple[str, str, str, str], b: tuple[str, str, str, str]) -> bool:
    """Si dos claves de :func:`_clave` son la misma ruta salvo parametros o la
    barra final: la forma de una variante de la misma pagina."""
    return a[:2] == b[:2] and (a[2].rstrip("/") or "/") == (b[2].rstrip("/") or "/")


def _url_de_clave(clave: tuple[str, str, str, str]) -> str:
    """La URL que representa una clave de :func:`_clave`, para escribirla."""
    esquema, host, ruta, query = clave
    return f"{esquema}://{host}{ruta}" + (f"?{query}" if query else "")


def _fuera_del_head(valor: str | None) -> list[str]:
    """La lista guardada en `html_meta.fuera_del_head`."""
    return [t for t in (valor or "").split(",") if t]


def _lo_saca_el_corte(cortado_por: str | None, fuera: str | None, nombre: str) -> bool:
    """Si *nombre* esta fuera del head porque algo corto el head antes."""
    return bool(cortado_por) and nombre in _fuera_del_head(fuera)


def _nivel_de_encabezado(tag: str | None) -> int | None:
    """1-6 para `h1`...`h6`; None para lo demas."""
    t = (tag or "").strip().lower()
    if len(t) == 2 and t[0] == "h" and t[1] in "123456":
        return int(t[1])
    return None


def _respuesta_valida():
    """La fila es la respuesta del sitio, no un muro delante (decision 103).

    NULL vale: rastreos anteriores a la columna, saltos y filas sin respuesta.
    Una pagina de muro no lleva incidencias de pagina —saldrian un `h1_missing`
    y un `4xx_error` de una pagina que no se ha llegado a ver—; lleva
    `respuesta_no_valida`, agrupada por host y clase.
    """
    return or_(Url.response_class.is_(None),
               Url.response_class.notin_(sorted(NO_VALIDAS)))


# Fuentes de una anotacion hreflang, como bits (decision 167): `Hreflang.origen`
# (NULL es el `<head>`) y el sitemap, que no tiene fila.
_BIT_FUENTE = {"html": 1, "cabecera": 2, "sitemap": 4}


def _clave(url: str | None):
    """Clave para buscar una URL entre las rastreadas, o None si no se puede.

    Es la de :func:`shared.indexabilidad.misma_url`, y no otra. Aqui habia un
    segundo normalizador (w3lib a secas) cuyo docstring prometia igualar la
    barra final —no lo hacia, y no debe: `/a` y `/a/` son dos URLs— y que no
    quitaba el puerto por defecto. Con dos criterios, un canonical a
    `https://x.com:443/b` era la misma URL que `/b` para la indexabilidad y otra
    para `canonical_broken`, que no encontraba el 404 (#26, decision 39).
    Tolerante a URLs que no se pueden partir (un puerto no numerico): esas no
    casan con nada, igual que antes.
    """
    if not url or not url.strip():
        return None
    try:
        return clave_url(url)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BATCH_SIZE = 1000

LOW_WORD_COUNT_THRESHOLD = 200
# El ratio texto/HTML se sigue midiendo y exportando, pero ya no genera issue:
# ver analyze_content. No queda umbral porque no hay decision que tomar con el.
URL_MAX_LENGTH = 115
HIGH_OUTLINK_THRESHOLD = 100

# BCP 47 language tag pattern (simplified but covers common cases).
# Matches things like "en", "en-US", "zh-Hant-TW", "x-default".
#
# IGNORECASE porque hreflang no distingue mayusculas: `X-Default` es valido y
# se marcaba como idioma invalido, que es el valor que escriben media docena de
# plugins de WordPress.
_LANG_TAG_RE = re.compile(
    r"^(?:x-default|[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{1,8})*)$", re.I
)

# Idiomas ISO 639-1, que es lo que Google acepta en hreflang ("the language, in
# ISO 639-1 format"). La regex de arriba solo mira la FORMA, asi que `eng`, `xx`
# o `sp` pasaban por validos y Google ignora esas anotaciones enteras: ese
# idioma se queda sin hreflang y el informe decia que estaba bien (#26). Con
# los codigos retirados que Google sigue usando (`iw`, `in`, `ji`, `jw`, `mo`)
# para no marcar como error lo que funciona.
_ISO_639_1 = frozenset("""
aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co
cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl
gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg
ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk
ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps
pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta
te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za
zh zu iw in ji jw mo
""".split())

# Regiones que la gente escribe y no existen en ISO 3166-1. `en-UK` es el error
# clasico —el codigo de Reino Unido es GB— y Google ignora el hreflang entero,
# asi que ese idioma queda sin anotacion y nadie se entera. `uk` SOLO es error
# como REGION: como idioma es ucraniano y es valido.
_REGIONES_INVENTADAS: dict[str, str] = {
    "uk": "GB",   # Reino Unido
    "eu": "",     # la UE no es un pais; para idioma se usa `eu` = euskera
    "ue": "",
    "la": "",     # Latinoamerica no es un pais (Google usa `es-419`)
    "sa": "",     # (South America; SA es Arabia Saudi)
    "en": "",     # `xx-EN` no existe: EN es un idioma, no una region
    "sp": "ES",
    "po": "PT",
}

# ISO 3166-1 alfa-2, los 249 codigos ASIGNADOS: es lo que Google acepta como
# region («the region, in ISO 3166-1 Alpha 2 format»). Con solo la lista de
# errores conocidos de arriba, `es-XX` o `fr-ZZ` pasaban por validos (#107).
# Los reservados (`UK`, `EU`) no estan: Google no los acepta como region.
_ISO_3166_1 = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR
GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO
JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR
MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO
RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV
TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".lower().split())

def _lang_hreflang_valido(lang: str | None) -> tuple[bool, str | None, str | None]:
    """(valido, idioma que no es ISO 639-1, region inventada) de un codigo.

    Una sola regla para el aviso de idioma invalido y para los checks de
    cluster de la decision 99, que no deben contar una anotacion que Google
    ignora.
    """
    valido = bool(lang) and bool(_LANG_TAG_RE.match(lang))
    idioma_malo = region_mala = None
    if valido and lang.lower() != "x-default":
        idioma = lang.split("-")[0].lower()
        if idioma not in _ISO_639_1:
            idioma_malo = idioma
            valido = False
    if valido and "-" in lang:
        region = lang.split("-")[-1].lower()
        # Solo regiones de dos letras: un `es-419` (UN M.49) o un `zh-Hant`
        # (escritura) no se juzgan aqui, no se puede afirmar que Google los
        # ignore.
        if len(region) == 2 and region.isalpha() and region not in _ISO_3166_1:
            region_mala = region
            valido = False
    return valido, idioma_malo, region_mala


# Regex to detect non-ASCII characters in a URL.
_NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")

# Regex to detect multiple consecutive slashes in a path (not the scheme://).
_MULTIPLE_SLASHES_RE = re.compile(r"(?<!:)//+")

# Patterns that indicate non-SEO-friendly URLs exposed to crawlers.
# These waste crawl budget and pollute the index when discoverable.
_NON_SEO_FRIENDLY_RE = re.compile(
    r";jsessionid="                 # Java session IDs leaked into URLs
    # Escapes unicode de JavaScript sin decodificar. Pedia \d{4} —solo
    # digitos— asi que el ejemplo del propio comentario, %5Cu002F, NO casaba:
    # la letra final lo tumbaba. Son hexadecimales.
    r"|%5Cu[0-9a-fA-F]{4}"
    r"|\\u[0-9a-fA-F]{4}"          # raw JS unicode escapes
    r"|%00"                         # null bytes in URL
    , re.IGNORECASE,
)

# Heuristic: path segments that look like CMS internal/faceted navigation.
# Matches paths containing encoded semicolons, pipe chars, or long
# percent-encoded sequences typical of filter/tag pages.
# `/-/` es el prefijo que Liferay pone a sus rutas de "friendly URL" de
# portlet, y `/-/categories/123` es la faceta de verdad: no la cazaba ninguna de
# las alternativas de abajo. En cambio `/elem_entry_list/` si la cazaba por
# `/ELEM_ENTRY` con IGNORECASE, y un listado no es una faceta: se exige el
# limite de palabra para que solo case el nombre exacto del portlet.
_CMS_FACETED_RE = re.compile(
    r"[.;|](?:categorias|categories|tags|labels|filters?|facets?|taxonomy)/"
    r"|/-/(?:categories|categorias|tags|labels)(?:/|$)"   # faceta de Liferay
    r"|/ELEM_ENTRY\b|/BP_Categories/"
    , re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------
class SEOAnalyzer:
    """Runs all SEO analysis checks for a single crawl job.

    Parameters
    ----------
    session:
        An active SQLAlchemy ``Session`` bound to the crawler database.
    job_id:
        UUID (as string or ``uuid.UUID``) of the crawl job to analyse.
    """

    def __init__(self, session: Session, job_id: str) -> None:
        self.session = session
        self.job_id = job_id
        self._pending_issues: list[dict[str, Any]] = []
        # (fase, segundos) de `run_all`, para `jobs.analisis_fases` (decision 226).
        self._fases: list[tuple[str, float]] = []
        # Sondas de respuesta (decisiones 123 y 124): lo ya avisado como enlace
        # externo o dominio muerto (para no repetirlo como recurso) y el resumen
        # que va a `jobs.sondas_resumen`.
        self.sondas_avisadas: set[str] = set()
        self.sondas_resumen: dict[str, Any] = {}
        self._con_sondas: bool | None = None

        # Per-job thresholds (fallback to module-level constants)
        from shared.models import Job

        job = session.query(Job).filter(Job.id == job_id).one_or_none()
        t = (job.config or {}).get("analysis_thresholds", {}) if job else {}
        self._enlaces_archivados = getattr(job, "enlaces_archivados", None)
        self._render_js = bool((job.config or {}).get("render_js")) if job else False
        self.title_min_len = t.get("title_min_length", TITLE_MIN_LEN)
        self.title_max_len = t.get("title_max_length", TITLE_MAX_LEN)
        self.desc_min_len = t.get("description_min_length", DESCRIPTION_MIN_LEN)
        self.desc_max_len = t.get("description_max_length", DESCRIPTION_MAX_LEN)
        self.title_max_px = t.get("title_max_pixels", TITLE_MAX_PIXELS)
        self.desc_max_px = t.get("description_max_pixels", DESCRIPTION_MAX_PIXELS)
        self.min_word_count = t.get("min_word_count", LOW_WORD_COUNT_THRESHOLD)
        # Cadena a partir de DOS saltos (A->B->C). Estaba en 2 con la
        # comparacion `hops > 2`, asi que hacian falta TRES saltos para que
        # saltara y A->B->C —la cadena mas comun, y la que Google pide evitar—
        # no se reportaba nunca. Un salto solo es una redireccion normal.
        self.max_redirect_chain = t.get("max_redirect_chain_length", 1)
        self.max_outlinks = t.get("max_outlinks", HIGH_OUTLINK_THRESHOLD)
        # PageRank con autoridad externa (decision 212): la parte del salto
        # que sigue repartida por igual entre las indexables.
        self.pagerank_externo_beta = float(t.get("pagerank_externo_beta", 0.5))
        self._cliente_id = getattr(job, "cliente_id", None)
        # Lo que el CSV de backlinks del cliente deja en este censo; lo rellena
        # `compute_pagerank` y lo leen los avisos (avisos_de_backlinks).
        self._backlinks = None
        # Las que llevan `solo_enlazada_con_nofollow` (decision 183): lo escribe
        # la profundidad de clic y lo lee el aviso por destino.
        self._solo_con_nofollow: set[int] = set()
        self.enlaces_plantilla_min_paginas = t.get("enlaces_plantilla_min_paginas", 10)  # d106
        # Avisos del servidor (decisiones 109 y 110, `avisos_de_servidor.py`).
        self.respuesta_lenta_ms = t.get("respuesta_lenta_ms", 1000)
        self.respuesta_lenta_grave_ms = t.get("respuesta_lenta_grave_ms", 3000)
        self.respuesta_lenta_min_paginas = t.get("respuesta_lenta_min_paginas", 20)
        self.tls_dias_aviso = t.get("tls_dias_aviso", 7)
        self.wp_taxonomia_anemica_max = t.get("wp_taxonomia_anemica_max", 1)  # d161
        self._job_config = (job.config or {}) if job else {}
        self._job_tls = getattr(job, "tls", None) if job else None
        # Lo que dejaron sin rastrear los topes por carpeta (decision 172).
        self._topes_carpeta = getattr(job, "topes_carpeta", None) if job else None
        self.near_duplicate_similarity = t.get(
            "near_duplicate_similarity", nd.UMBRAL_SIMILITUD
        )

    # -- public interface ---------------------------------------------------

    def run_all(self) -> None:
        """Run every analysis check and persist results to the issues table."""
        logger.info("Starting SEO analysis for job %s", self.job_id)

        # Sin sus enlaces, el analisis pondria a cero los entrantes, el
        # PageRank y la profundidad, y llenaria el censo de huerfanas falsas
        # (decision 95). `run_analysis` restaura, analiza y vuelve a archivar
        # (decision 150); quien llama a `run_all` directamente, restaura antes.
        if self._enlaces_archivados:
            raise EnlacesArchivados(
                f"los enlaces del job {self.job_id} estan archivados en Parquet; "
                f"analizalo con `python -m analysis.analyzer {self.job_id}`, que "
                f"los restaura y los vuelve a archivar, o restauralos antes: "
                f"python scripts/archivar_enlaces.py --restaurar {self.job_id}"
            )

        self._fase("actualizar_estadisticas", self.actualizar_estadisticas)
        self._fase("clear_existing_issues", self.clear_existing_issues)

        self._fase("analyze_status_codes", self.analyze_status_codes)
        # robots.txt de cada host (decisiones 112 y 113): antes de la
        # indexabilidad, que lo usa para saber que puede pedir Googlebot.
        self._fase("analyze_robots_txt", self.analyze_robots_txt)
        # La indexabilidad va ANTES que los titulos, las descripciones y los
        # duplicados: los tres agrupan solo paginas indexables y necesitan
        # `Url.indexable` escrito. Estaba despues, asi que la columna era NULL y
        # el filtro no habria hecho nada.
        self._fase("analyze_indexability", self.analyze_indexability)
        self._fase("analyze_titles", self.analyze_titles)
        self._fase("analyze_descriptions", self.analyze_descriptions)
        self._fase("analyze_headings", self.analyze_headings)
        self._fase("analyze_saltos_de_encabezado", self.analyze_saltos_de_encabezado)  # decision 153
        self._fase("analyze_canonicals", self.analyze_canonicals)
        self._fase("analyze_hreflang", self.analyze_hreflang)
        self._fase("analyze_structured_data", self.analyze_structured_data)
        self._fase("avisos_de_entidad.avisar", avisos_de_entidad.avisar, self)  # decision 229
        self._fase("analyze_html_ignorado", self.analyze_html_ignorado)
        self._fase("avisos_de_html.avisar_declaraciones_html", avisos_de_html.avisar_declaraciones_html, self)  # decision 108
        self._fase("avisos_de_medios.avisar", avisos_de_medios.avisar, self)  # decisiones 154, 155 y 156
        self._fase("avisos_de_nosnippet.avisar", avisos_de_nosnippet.avisar, self)  # decision 170
        self._fase("analyze_robots_syntax", self.analyze_robots_syntax)
        self._fase("avisos_de_nofollow.avisar_paginas_nofollow", avisos_de_nofollow.avisar_paginas_nofollow, self)  # decision 183
        self._fase("analyze_duplicates", self.analyze_duplicates)
        self._fase("analyze_near_duplicates", self.analyze_near_duplicates)
        self._fase("analyze_redirect_chains", self.analyze_redirect_chains)
        self._fase("analyze_images", self.analyze_images)
        self._fase("analyze_security", self.analyze_security)
        self._fase("avisos_de_servidor.avisar", avisos_de_servidor.avisar, self)  # decisiones 109 y 110
        self._fase("analyze_content", self.analyze_content)
        self._fase("analyze_soft_404", self.analyze_soft_404)
        self._fase("analyze_paridad_movil", self.analyze_paridad_movil)
        self._fase("avisos_de_render.avisar", avisos_de_render.avisar, self)  # decision 140
        self._fase("avisos_de_accesibilidad.avisar", avisos_de_accesibilidad.avisar, self)  # decision 174
        self._fase("analyze_url_issues", self.analyze_url_issues)
        # Despues de la indexabilidad (necesita `Url.noindex`) y antes de los
        # conteos: deja marcadas las paginas que la lectura de `links` de
        # `compute_link_counts` tiene que distinguir (decision 122).
        self._fase("avisos_de_paginacion.analizar_paginacion", avisos_de_paginacion.analizar_paginacion, self)
        self._fase("compute_link_counts", self.compute_link_counts)
        self._fase("compute_pagerank", self.compute_pagerank)
        self._fase("analyze_links", self.analyze_links)
        self._fase("avisos_de_enlaces.avisar_enlaces_no_rastreables", avisos_de_enlaces.avisar_enlaces_no_rastreables, self)  # decision 106
        self._fase("avisos_de_sondas.avisar_recursos_rotos", avisos_de_sondas.avisar_recursos_rotos, self)  # decision 124
        self._fase("analyze_sitemap", self.analyze_sitemap)
        self._fase("avisos_de_sitemaps.avisar", avisos_de_sitemaps.avisar, self)  # decision 126
        # WordPress por su REST API (decision 161): despues de la
        # indexabilidad, los enlaces y el sitemap, que es con lo que se cruza.
        self._fase("avisos_de_wordpress.avisar_sin_tumbar", avisos_de_wordpress.avisar_sin_tumbar, self)
        # Search Console (decision 142): despues de la indexabilidad y de los
        # entrantes, que es con lo que se cruza.
        self._fase("avisos_de_gsc.avisar", avisos_de_gsc.avisar, self)
        self._fase("oportunidades_gsc.avisar_sin_tumbar", oportunidades_gsc.avisar_sin_tumbar, self)  # decision 157
        # Backlinks del cliente (decision 212): despues de Search Console, que
        # ya cambio las huerfanas con trafico por su propio aviso.
        self._fase("avisos_de_backlinks.avisar_sin_tumbar", avisos_de_backlinks.avisar_sin_tumbar, self)
        # Logs del servidor (decision 213): despues del PageRank, que es con
        # lo que se elige que paginas importantes no visita Googlebot.
        self._fase("avisos_de_logs.avisar_sin_tumbar", avisos_de_logs.avisar_sin_tumbar, self)
        # Trampas de rastreo (decision 214): sobre todas las URLs del censo.
        self._fase("avisos_de_trampas.avisar_sin_tumbar", avisos_de_trampas.avisar_sin_tumbar, self)
        # Al final: sus condiciones pueden leer lo que acaba de escribir el
        # analisis (indexable, click_depth, in_sitemap...). No emite incidencias.
        self._fase("segmentar", self.segmentar)

        # Flush any remaining buffered issues.
        self._fase("_flush_issues", self._flush_issues)
        self._sellar_version()
        self.session.commit()

        caras = sorted(self._fases, key=lambda f: -f[1])[:5]
        logger.info("SEO analysis completed for job %s en %.0f s; lo mas caro: %s", self.job_id,
                    sum(t for _, t in self._fases), ", ".join(f"{n} {t:.1f} s" for n, t in caras))

    def _fase(self, nombre: str, fn, *args):
        """Llama a una fase del analisis y apunta lo que tarda (#281, decision
        226): se guarda en `jobs.analisis_fases` para saber donde se va el
        tiempo en los censos grandes de verdad. Si la fase revienta, se apunta
        igual y la excepcion sigue."""
        inicio = time.perf_counter()
        try:
            return fn(*args)
        finally:
            self._fases.append((nombre, round(time.perf_counter() - inicio, 2)))

    def segmentar(self) -> dict:
        """Materializa `urls.segmento` con las reglas de `config.segmentos`
        (decision 125). Es lo mismo que hace `POST /segmentos` sin el analisis
        entero: re-analizar un censo viejo con reglas nuevas lo segmenta sin
        re-rastrear."""
        from shared.segmentos import segmentar

        resumen = segmentar(self.session, self.job_id)
        logger.info("Segmentos: %d URLs en %d segmentos (%d por regla) en %.1f s",
                    resumen["urls"], resumen["segmentos_distintos"],
                    sum(r["urls"] for r in resumen["por_regla"]), resumen["segundos"])
        return resumen

    def _sellar_version(self) -> None:
        """Con que version del codigo se calcularon estas cifras.

        `jobs.crawler_version` dice con que se RASTREO; esto, con que se
        ANALIZO, que es otra pregunta y hace falta igual: un re-analisis cambia
        las cifras de un censo sin que cambie el sitio ni el rastreo. Medido en
        penguin, un censo de julio: 959.633 incidencias antes de re-analizarlo
        con el codigo de octubre. Comparar dos censos analizados con codigo
        distinto sin decirlo atribuye al cliente un cambio que es nuestro.
        """
        from shared.models import Job
        from shared.version import VERSION

        self.session.execute(
            update(Job).where(Job.id == self.job_id).values(
                analisis_version=VERSION,
                # NULL si el censo no tiene sondas: no un resumen de ceros.
                sondas_resumen=self.sondas_resumen or None,
                # Segundos por fase, en el orden en que corren (decision 226).
                analisis_fases={"fases": [[n, t] for n, t in self._fases],
                                "total": round(sum(t for _, t in self._fases), 1)},
            )
        )

    # -- helpers ------------------------------------------------------------

    def actualizar_estadisticas(self) -> None:
        """Dice a Postgres cuantas filas acaba de insertar el rastreo.

        El rastreo mete millones de enlaces y el planificador no se entera
        hasta que el autovacuum pasa por ahi. Como las filas nuevas son de un
        `job_id` que no existia cuando se tomaron las ultimas estadisticas, la
        estimacion para ese job es **1 fila** — y con eso Postgres elige planes
        de bucle anidado para agregaciones de millones.

        Medido en produccion el 2026-10-13 con el censo semanal de Lopesan
        (5.276 URLs, 1.431.667 enlaces): la materializacion de aristas llevaba
        **1 h 3 min sin terminar** y hubo que cancelarla. El `EXPLAIN` de
        `count(*) FROM links WHERE job_id=...` estimaba **1 fila** (coste 8,58);
        tras un `ANALYZE`, 1,43 M de filas (coste 342.082). Relanzado con las
        estadisticas frescas, el analisis ENTERO del mismo censo tarda
        **107 segundos**.

        Y llevaba funcionando por suerte: el censo del mismo sitio del 8 de
        octubre salio en 2 h porque el `autoanalyze` de Postgres salto a las
        16:31, en mitad de aquel rastreo. El umbral por defecto para una tabla
        de 20 M de filas son ~2 M de modificaciones, y entre censo y censo no
        siempre se llega.

        No es best-effort por capricho: si el motor no es Postgres (los tests
        corren contra SQLite) o el usuario no puede analizar la tabla, el
        analisis tiene que seguir. Lo unico que se pierde es velocidad.
        """
        from sqlalchemy import text

        if self.session.bind is None or self.session.bind.dialect.name != "postgresql":
            return
        for tabla in ("links", "urls"):
            try:
                inicio = time.time()
                # `ANALYZE` a secas, sin transaccion larga: no bloquea lecturas
                # ni escrituras, solo conflige con otro ANALYZE o VACUUM.
                self.session.execute(text(f"ANALYZE {tabla}"))
                self.session.commit()
                logger.info("Estadisticas de `%s` actualizadas en %.1f s",
                            tabla, time.time() - inicio)
            except Exception:
                self.session.rollback()
                logger.warning(
                    "No se pudieron actualizar las estadisticas de `%s`; el "
                    "analisis sigue, pero puede ir MUCHO mas lento", tabla,
                    exc_info=True)

    def clear_existing_issues(self) -> None:
        """Remove all issues previously generated for this job."""
        self.session.execute(
            delete(Issue).where(Issue.job_id == self.job_id)
        )
        self.session.flush()

    # Cuantas URLs del grupo se guardan en los detalles. El grupo entero no:
    # cada fila llevaba la lista de TODAS las demas, asi que un grupo de N
    # paginas gastaba N x N identificadores. Medido en el censo de CST, donde
    # 7.511 paginas comparten la misma description: esa sola clase de
    # incidencia ocupaba **431 MB** de la columna `details` (9 kB por fila, la
    # mayor de 59 kB), frente a 8 MB, 7 MB y 0,8 MB en los censos sin un grupo
    # gigante. Y no lo lee nadie: cuatro sitios lo escriben y ninguno lo
    # consume. Con la cuenta y una muestra se responde lo mismo —"esta
    # description la comparten 7.511 paginas, por ejemplo estas"— y el resto
    # se saca con una consulta por el valor compartido.
    _MUESTRA_DUPLICADOS = 20

    def _detalle_duplicados(self, otros: list[int], **extra) -> dict[str, Any]:
        detalle: dict[str, Any] = {
            "duplicate_count": len(otros),
            "duplicate_urls": otros[: self._MUESTRA_DUPLICADOS],
        }
        if len(otros) > self._MUESTRA_DUPLICADOS:
            detalle["duplicate_urls_truncada"] = True
        detalle.update(extra)
        return detalle

    def _add_issue(
        self,
        url_id: int,
        issue_type: str,
        severity: str,
        details: dict[str, Any] | None = None,
        group_key: str | None = None,
    ) -> None:
        """Buffer an issue for bulk insertion.

        `group_key` distingue dos hallazgos del MISMO tipo en la MISMA URL, que
        es lo que hace falta para poder decir «esto se arregló» entre dos
        censos (#32). Con tipo y URL no basta: un hreflang mal escrito emite
        una incidencia por código de idioma, y un título duplicado pertenece a
        un grupo que puede cambiar de miembros sin dejar de existir.

        Va a NULL en las reglas que emiten como mucho una incidencia por URL
        —un 404, un título largo, una URL con mayúsculas—: ahí el par
        (tipo, URL) ya identifica el hallazgo y una clave inventada solo sería
        ruido que puede cambiar entre versiones del código y fingir que el
        problema se resolvió.
        """
        self._pending_issues.append(
            {
                "job_id": self.job_id,
                "url_id": url_id,
                "issue_type": issue_type,
                "severity": severity,
                "details": details,
                "group_key": group_key,
                "detected_at": datetime.now(timezone.utc),
            }
        )
        if len(self._pending_issues) >= BATCH_SIZE:
            self._flush_issues()

    def _flush_issues(self) -> None:
        """Perform a bulk insert of all buffered issues."""
        if not self._pending_issues:
            return
        self.session.bulk_insert_mappings(Issue, self._pending_issues)
        self.session.flush()
        logger.debug("Flushed %d issues", len(self._pending_issues))
        self._pending_issues.clear()

    def _iter_urls(
        self,
        *extra_filters,
        columns: Sequence | None = None,
    ):
        """Yield URL rows in batches of ``BATCH_SIZE``.

        Parameters
        ----------
        *extra_filters:
            Additional SQLAlchemy filter expressions applied on top of
            the job_id filter.
        columns:
            If provided, select only these columns (returns ``Row``
            objects instead of full ORM instances).
        """
        base_filter = Url.job_id == self.job_id
        if columns is not None:
            stmt = select(*columns).where(base_filter, *extra_filters)
        else:
            stmt = select(Url).where(base_filter, *extra_filters)

        result = self.session.execute(
            stmt.execution_options(yield_per=BATCH_SIZE)
        )
        yield from result

    # ======================================================================
    # Analysis checks
    # ======================================================================

    # -- Status codes -------------------------------------------------------

    def analyze_status_codes(self) -> None:
        """Flag 4xx, 5xx, and connection-level errors."""
        logger.debug("Analyzing status codes ...")

        self._respuestas_no_validas()

        # 4xx errors
        rows = self.session.execute(
            select(Url.id, Url.status_code).where(
                Url.job_id == self.job_id,
                Url.status_group == "4xx",
                _respuesta_valida(),
            )
        ).all()
        for url_id, status_code in rows:
            self._add_issue(
                url_id,
                "4xx_error",
                "error",
                {"status_code": status_code},
            )

        # 5xx errors
        rows = self.session.execute(
            select(Url.id, Url.status_code).where(
                Url.job_id == self.job_id,
                Url.status_group == "5xx",
                _respuesta_valida(),
            )
        ).all()
        for url_id, status_code in rows:
            self._add_issue(
                url_id,
                "5xx_error",
                "error",
                {"status_code": status_code},
            )

        # Connection-level errors (timeouts, DNS failures, connection refused, etc.)
        rows = self.session.execute(
            select(Url.id, Url.status_group).where(
                Url.job_id == self.job_id,
                Url.status_group.in_(["timeout", "dns_error", "conn_refused", "tls_error",
                                      "error", "unknown"]),
            )
        ).all()
        # Una pagina que falla por el certificado de su host no lleva ademas
        # su `connection_error` cuando la sonda lo confirma: lo dice una vez
        # `tls_certificado_invalido`, con las paginas afectadas (36, 110).
        ya_contadas = avisos_de_servidor.ids_tls_de_hosts_invalidos(self)
        for url_id, status_group in rows:
            if url_id in ya_contadas:
                continue
            self._add_issue(
                url_id,
                "connection_error",
                "error",
                {"error_type": status_group},
            )

        self._flush_issues()

    # Cuantas URLs de ejemplo lleva una incidencia agrupada.
    _MUESTRA_EJEMPLOS = 5

    def _respuestas_no_validas(self) -> None:
        """Una incidencia por host y clase de respuesta no valida.

        Un desafio de un WAF, un captcha, un 429 o un cuerpo binario no son la
        pagina: no se puede decir nada de su titulo ni de su h1, y emitir un
        `4xx_error` por cada desafio de Cloudflare era contar como roto lo que
        no se llego a ver (medido en penguin: 270 paginas con 429 y un
        `4xx_error` cada una). Es un hallazgo del RASTREO por host, como las
        cabeceras de seguridad (decision 53): una fila por (host, clase) con
        las paginas afectadas y unos ejemplos.
        """
        filas = self.session.execute(
            select(Url.id, Url.host, Url.url, Url.response_class, Url.status_code)
            .where(Url.job_id == self.job_id,
                   Url.response_class.in_(sorted(NO_VALIDAS)))
            # Por URL, no por id: el ancla y los ejemplos no pueden depender
            # del orden de rastreo (decision 88).
            .order_by(Url.url, Url.id)
        ).all()
        grupos: dict[tuple[str, str], dict[str, Any]] = {}
        for url_id, host, url, clase, status in filas:
            g = grupos.setdefault((host or "", clase), {
                "url_id": url_id, "paginas": 0, "ejemplos": [], "codigos": defaultdict(int)})
            g["paginas"] += 1
            g["codigos"][str(status)] += 1
            if len(g["ejemplos"]) < self._MUESTRA_EJEMPLOS:
                g["ejemplos"].append(url)
        for (host, clase), g in grupos.items():
            self._add_issue(
                g["url_id"], "respuesta_no_valida", "warning",
                {"host": host, "clase": clase, "paginas_afectadas": g["paginas"],
                 "codigos": dict(g["codigos"]), "ejemplos": g["ejemplos"]},
                group_key=_clave_de_grupo(f"{host}|{clase}"),
            )

    # -- Titles -------------------------------------------------------------

    def analyze_titles(self) -> None:
        """Check for missing, short, long, and duplicate page titles."""
        logger.debug("Analyzing titles ...")

        # Join Url with HtmlMeta for all HTML pages in the job.
        stmt = (
            select(Url.id, HtmlMeta.title, HtmlMeta.title_len,
                   HtmlMeta.title_pixel_width, Url.status_code,
                   Url.is_internal, Url.indexable, HtmlMeta.title_count,
                   Url.host, Url.url)
            .join(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(Url.job_id == self.job_id, Url.is_html.is_(True))
        )
        rows = self.session.execute(stmt).all()

        # Track titles for duplicate detection.
        title_to_url_ids: dict[str, list[int]] = defaultdict(list)
        genericos = self._titulos_genericos(rows)

        for (url_id, title, title_len, title_px, status_code, is_internal,
             indexable, title_count, _host, _url) in rows:
            # Con dos `<title>` no se sabe cual usa Google, y el caso tipico es
            # uno VACIO delante del bueno (dos plugins escribiendo la cabecera):
            # se cogia el vacio y salia `title_missing` sin decir que habia otro.
            # El aviso dice si el primero esta vacio, que es la pista de por que.
            if (title_count or 0) > 1:
                self._add_issue(
                    url_id, "title_multiple", "warning",
                    {"cuantos": title_count,
                     "primero_vacio": not (title or "").strip()},
                )
            if not title or not title.strip():
                self._add_issue(url_id, "title_missing", "warning")
                continue

            clean_title = title.strip()
            effective_len = title_len if title_len is not None else len(clean_title)

            # Un placeholder corto («Página») ya lo dice `title_generico`, con
            # el mismo arreglo: rellenar el titulo (36).
            if url_id in genericos:
                pass
            elif effective_len < self.title_min_len:
                self._add_issue(
                    url_id,
                    "title_too_short",
                    "warning",
                    {"length": effective_len, "min": self.title_min_len},
                )
            # Demasiado largo = SE TRUNCA en el resultado, y Google trunca por
            # pixeles: un titulo de 65 letras estrechas cabe y uno de 55 en
            # mayusculas no. Medido en tres censos, 8.801 titulos pasaban de 60
            # caracteres sin pasar del ancho de pixeles —o sea sin truncarse—,
            # el 29% de los avisos. Si el ancho no esta medido (rastreos
            # antiguos) se cae a los caracteres, que es lo que habia.
            elif title_px is not None:
                if title_px > self.title_max_px:
                    self._add_issue(
                        url_id,
                        "title_too_long",
                        "warning",
                        {"pixels": title_px, "max_pixels": self.title_max_px,
                         "length": effective_len},
                    )
            elif effective_len > self.title_max_len:
                self._add_issue(
                    url_id,
                    "title_too_long",
                    "warning",
                    {"length": effective_len, "max": self.title_max_len},
                )

            # Only real, served internal pages count toward duplicate groups;
            # otherwise 404/redirect/external pages sharing a boilerplate
            # title bury the genuine duplicates.
            # Los grupos de duplicados solo miran paginas INDEXABLES, y es
            # la unica forma de que el aviso signifique algo: dos variantes
            # `?utm`, dos ordenaciones de un listado o un `/page/2` comparten
            # titulo a proposito y estan canonicalizadas o en noindex, asi que
            # no compiten con nadie. Lo que importa es que dos paginas que
            # Google SI puede posicionar se pisen entre ellas. Por eso
            # `analyze_indexability` corre antes en `run_all`: aqui se necesita
            # `Url.indexable` ya escrito.
            if status_code == 200 and is_internal and indexable:
                title_to_url_ids[clean_title.lower()].append(url_id)

        # Duplicate titles: only flag groups with 2+ pages sharing the same title.
        for title_text, url_ids in title_to_url_ids.items():
            # «Sin título | Marca» en 12 paginas son 12 duplicados de un
            # placeholder: el hallazgo es el placeholder, y lo dice
            # `title_generico` en una fila (36, como las TAPADAS del soft 404).
            url_ids = [u for u in url_ids if u not in genericos]
            if len(url_ids) < 2:
                continue
            for uid in url_ids:
                other_ids = [x for x in url_ids if x != uid]
                self._add_issue(
                    uid,
                    "title_duplicate",
                    "warning",
                    self._detalle_duplicados(other_ids),
                    group_key=_clave_de_grupo(title_text),
                )

        self._flush_issues()

    def _titulos_genericos(self, rows) -> set[int]:
        """`title_generico` (decision 121): una fila por valor, y los ids que
        tapa (su `title_too_short` y su `title_duplicate`).

        Solo indexables, como los duplicados: un placeholder en una pagina en
        noindex o canonicalizada no compite en el indice. La marca de cada host
        sale de los titulos de sus indexables (`shared/titulos.py`).
        """
        por_host: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
        for (url_id, title, _l, _px, status_code, is_internal, indexable,
             _c, host, url) in rows:
            if status_code == 200 and is_internal and indexable and (title or "").strip():
                por_host[host or ""].append((url_id, title.strip(), url))
        grupos: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
        for host, filas in por_host.items():
            marcas = marcas_del_host(t for _, t, _ in filas)
            for url_id, title, url in filas:
                if es_title_generico(title, marcas):
                    grupos[title.lower()].append((url, url_id, title))
        tapados: set[int] = set()
        for valor, miembros in grupos.items():
            # Anclada en la URL menor: el id depende del orden de rastreo (88).
            miembros.sort()
            self._add_issue(
                miembros[0][1], "title_generico", "warning",
                {"title": miembros[0][2], "paginas_afectadas": len(miembros),
                 "paginas_ejemplo": [m[0] for m in miembros[: self._MUESTRA_EJEMPLOS]]},
                group_key=_clave_de_grupo(valor),
            )
            tapados.update(m[1] for m in miembros)
        return tapados

    # -- Descriptions -------------------------------------------------------

    def analyze_descriptions(self) -> None:
        """Check for missing, short, long, and duplicate meta descriptions."""
        logger.debug("Analyzing meta descriptions ...")

        stmt = (
            select(Url.id, HtmlMeta.meta_description, HtmlMeta.meta_description_len,
                   HtmlMeta.meta_description_pixel_width,
                   Url.status_code, Url.is_internal, Url.indexable,
                   HtmlMeta.meta_description_count, HtmlMeta.title, Url.host,
                   Url.path, Url.url)
            .join(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(Url.job_id == self.job_id, Url.is_html.is_(True))
        )
        rows = self.session.execute(stmt).all()

        desc_to_url_ids: dict[str, list[int]] = defaultdict(list)
        # (host, plantilla) -> [(url, url_id)] de las que repiten el titulo.
        igual_title: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)

        for (url_id, description, desc_len, desc_px, status_code, is_internal,
             indexable, desc_count, title, host, path, url) in rows:
            # Igual que el titulo: con dos descriptions no se sabe cual usa
            # Google. La vacia se salta al coger el valor, pero sigue ahi.
            if (desc_count or 0) > 1:
                self._add_issue(
                    url_id, "description_multiple", "warning",
                    {"cuantos": desc_count},
                )
            if not description or not description.strip():
                self._add_issue(url_id, "description_missing", "warning")
                continue

            clean_desc = description.strip()
            effective_len = desc_len if desc_len is not None else len(clean_desc)

            if effective_len < self.desc_min_len:
                self._add_issue(
                    url_id,
                    "description_too_short",
                    "warning",
                    {"length": effective_len, "min": self.desc_min_len},
                )
            # Por pixeles, como el titulo: es lo que decide si el fragmento se
            # corta en el resultado.
            elif desc_px is not None:
                if desc_px > self.desc_max_px:
                    self._add_issue(
                        url_id,
                        "description_too_long",
                        "warning",
                        {"pixels": desc_px, "max_pixels": self.desc_max_px,
                         "length": effective_len},
                    )
            elif effective_len > self.desc_max_len:
                self._add_issue(
                    url_id,
                    "description_too_long",
                    "warning",
                    {"length": effective_len, "max": self.desc_max_len},
                )

            # Restrict duplicate grouping to real, served internal pages,
            # and solo indexables: ver la nota en `analyze_titles`.
            if status_code == 200 and is_internal and indexable:
                desc_to_url_ids[clean_desc.lower()].append(url_id)
                if description_igual_title(clean_desc, title):
                    igual_title[(host or "", firma_de_ruta(path or "/"))].append((url, url_id))

        # La description que repite el titulo es el valor por defecto del CMS
        # o del plugin: una fila por (host, plantilla) (decision 121, 64).
        for (host, plantilla), miembros in igual_title.items():
            miembros.sort()
            self._add_issue(
                miembros[0][1], "description_igual_title", "info",
                {"host": host, "plantilla": plantilla, "paginas_afectadas": len(miembros),
                 "paginas_ejemplo": [u for u, _ in miembros[: self._MUESTRA_EJEMPLOS]]},
                group_key=_clave_de_grupo(f"{host}|{plantilla}"),
            )

        for desc_text, url_ids in desc_to_url_ids.items():
            if len(url_ids) < 2:
                continue
            for uid in url_ids:
                other_ids = [x for x in url_ids if x != uid]
                self._add_issue(
                    uid,
                    "description_duplicate",
                    "warning",
                    self._detalle_duplicados(other_ids),
                    group_key=_clave_de_grupo(desc_text),
                )

        self._flush_issues()

    # -- Headings -----------------------------------------------------------

    def analyze_headings(self) -> None:
        """Check H1 presence, multiplicity, and duplication."""
        logger.debug("Analyzing headings ...")

        # Get all H1 headings for HTML pages in this job.
        stmt = (
            select(Url.id, Heading.text, Url.indexable)
            .join(Heading, Heading.url_id == Url.id)
            .where(
                Url.job_id == self.job_id,
                Url.is_html.is_(True),
                Heading.tag == "h1",
                # Los que no se pintan no cuentan: el clon movil y el de
                # escritorio del mismo titular daban 3 h1 donde hay 1, con un
                # `h1_multiple` falso. Siguen guardados, marcados.
                Heading.oculto.isnot(True),
            )
            .order_by(Url.id)
        )
        rows = self.session.execute(stmt).all()

        # Group H1s per URL.
        h1_by_url: dict[int, list[str]] = defaultdict(list)
        indexable_por_url: dict[int, bool] = {}
        for url_id, text, indexable in rows:
            h1_by_url[url_id].append(text or "")
            indexable_por_url[url_id] = bool(indexable)

        # Get the full set of HTML URL ids so we can detect missing H1s. Solo
        # 2xx: los headings solo se extraen de respuestas correctas, y sin este
        # filtro cada 404 HTML salia "sin H1" (55 de 656 en Lopesan).
        html_url_ids_stmt = select(Url.id).where(
            Url.job_id == self.job_id, Url.is_html.is_(True),
            Url.status_code >= 200, Url.status_code < 300,
            _respuesta_valida(),
        )
        all_html_url_ids = {
            row[0] for row in self.session.execute(html_url_ids_stmt).all()
        }

        # Missing H1
        for url_id in all_html_url_ids:
            if url_id not in h1_by_url:
                self._add_issue(url_id, "h1_missing", "warning")

        # H1 presente pero vacio (decision 121): un `<h1><img src=logo></h1>`
        # sin alt deja la pagina sin titular igual que no tenerlo, y contaba
        # como h1 presente. En un censo anterior a la decision 46 el alt no se
        # leia y el logo CON alt tambien se guardo vacio: ahi no se afirma.
        evaluar_vacios = not self._censo_anterior_a_d46()
        if not evaluar_vacios:
            logger.warning(
                "Job %s: headings.oculto NULL en todo el censo (anterior a la "
                "decision 46); h1_vacio no se evalua", self.job_id)
        for url_id, h1_texts in h1_by_url.items():
            con_texto = [t for t in h1_texts if t.strip()]
            if not con_texto and evaluar_vacios and url_id in all_html_url_ids:
                self._add_issue(url_id, "h1_vacio", "warning",
                                {"h1_vacios": len(h1_texts)})

        # Multiple H1s. Solo los que tienen texto: uno bueno y uno vacio es UN
        # titular, y solo vacios ya es `h1_vacio` (36).
        for url_id, h1_texts in h1_by_url.items():
            con_texto = [t for t in h1_texts if t.strip()]
            if len(con_texto) > 1:
                self._add_issue(
                    url_id,
                    "h1_multiple",
                    "warning",
                    {"count": len(con_texto)},
                )

        # Duplicate H1 text across different URLs.
        h1_text_to_url_ids: dict[str, list[int]] = defaultdict(list)
        for url_id, h1_texts in h1_by_url.items():
            # Solo indexables: ver la nota en `analyze_titles`.
            if not indexable_por_url.get(url_id):
                continue
            for text in h1_texts:
                if text.strip():
                    h1_text_to_url_ids[text.strip().lower()].append(url_id)

        for h1_text, url_ids in h1_text_to_url_ids.items():
            # Deduplicate URL ids (a URL with two identical H1s should not
            # appear twice in the duplicate group).
            unique_ids = list(dict.fromkeys(url_ids))
            if len(unique_ids) < 2:
                continue
            for uid in unique_ids:
                other_ids = [x for x in unique_ids if x != uid]
                self._add_issue(
                    uid,
                    "h1_duplicate",
                    "info",
                    self._detalle_duplicados(other_ids),
                    group_key=_clave_de_grupo(h1_text),
                )

        self._flush_issues()

    def analyze_saltos_de_encabezado(self) -> None:
        """``encabezado_salta_nivel`` (decision 153): un titular baja mas de un
        nivel respecto al anterior (un H2 seguido de un H4).

        Google no lo penaliza; Screaming Frog y Sitebulb lo marcan y es un fallo
        de accesibilidad (WCAG 1.3.1: el lector de pantalla navega por niveles).
        Por eso es ``info`` y va **por plantilla** (36, 53, 64, 73): el salto lo
        pone casi siempre el tema (el H4 del pie, el H5 de la barra lateral), y
        una fila por (host, forma de la ruta) con `paginas_afectadas` dice lo
        mismo que 3.000 filas.

        - Solo titulares que se pintan y tienen texto: el oculto y el vacio no
          los oye nadie (46, 121). En un censo anterior a la decision 46 no se
          sabe cuales se pintaban y no se afirma, como ``h1_vacio``.
        - Subir de nivel (H4 -> H2) no es un salto, y el primer titular no se
          compara con nada: que falte el H1 ya es ``h1_missing``.
        - Solo HTML interno 2xx, respuesta valida e indexable (47).

        Lee `headings` de las paginas del job por `url_id` (sin `links`), en
        orden de documento y por lotes.
        """
        if self._censo_anterior_a_d46():
            logger.warning("Job %s: headings.oculto NULL en todo el censo; "
                           "encabezado_salta_nivel no se evalua", self.job_id)
            return
        stmt = (
            select(Url.id, Url.url, Url.host, Heading.tag)
            .join(Heading, Heading.url_id == Url.id)
            .where(
                Url.job_id == self.job_id, Url.is_html.is_(True),
                Url.is_internal.is_(True),
                Url.status_code >= 200, Url.status_code < 300,
                _respuesta_valida(), Url.indexable.is_(True),
                Heading.oculto.isnot(True),
                func.length(func.trim(func.coalesce(Heading.text, ""))) > 0,
            )
            .order_by(Url.id, Heading.position)
        )
        # (host, plantilla) -> {"paginas": [(url, id)], "saltos": Counter del
        # primer salto de cada pagina}
        grupos: dict[tuple, dict[str, Any]] = {}
        actual: int | None = None
        anterior = 0
        primero: str | None = None
        datos_pagina: tuple | None = None

        def _cerrar() -> None:
            if datos_pagina is None or not primero:
                return
            url, url_id, host = datos_pagina
            try:
                plantilla = firma_de_ruta(urlparse(url).path)
            except ValueError:
                plantilla = firma_de_ruta("")
            g = grupos.setdefault(((host or "").lower(), plantilla),
                                  {"paginas": [], "saltos": Counter()})
            g["paginas"].append((url, url_id))
            g["saltos"][primero] += 1

        for url_id, url, host, tag in self.session.execute(
                stmt.execution_options(yield_per=BATCH_SIZE)):
            if url_id != actual:
                _cerrar()
                actual, anterior, primero = url_id, 0, None
                datos_pagina = (url, url_id, host)
            nivel = _nivel_de_encabezado(tag)
            if nivel is None:
                continue
            if anterior and nivel > anterior + 1 and primero is None:
                primero = f"h{anterior}>h{nivel}"
            anterior = nivel
        _cerrar()

        for (host, plantilla), g in grupos.items():
            paginas = sorted(g["paginas"])
            salto, _ = g["saltos"].most_common(1)[0]
            self._add_issue(
                paginas[0][1], "encabezado_salta_nivel", "info",
                {"plantilla": plantilla, "salto": salto,
                 "saltos_distintos": sorted(g["saltos"]),
                 "paginas_afectadas": len(paginas),
                 "paginas_ejemplo": [u for u, _ in paginas[:5]]},
                group_key=_clave_de_grupo(f"{host}|{plantilla}"),
            )
        self._flush_issues()

    def _censo_anterior_a_d46(self) -> bool:
        """¿Ningun titular del job tiene `oculto` escrito? Entonces el censo es
        anterior a la decision 46 (alt de la imagen y `aria-label` como texto,
        y la columna `oculto`, en el mismo commit): lo que entonces se guardo
        vacio puede no estarlo. Un job sin titulares no es «anterior»."""
        if getattr(self, "_anterior_d46", None) is None:
            from sqlalchemy import inspect

            # Los tests de enlaces montan SQLite sin `headings`: sin tabla no
            # hay titulares que digan de que epoca es el censo.
            if not inspect(self.session.connection()).has_table(Heading.__tablename__):
                self._anterior_d46 = False
                return False
            hay = self.session.execute(
                select(Heading.id).join(Url, Url.id == Heading.url_id)
                .where(Url.job_id == self.job_id).limit(1)
            ).first()
            medido = self.session.execute(
                select(Heading.id).join(Url, Url.id == Heading.url_id)
                .where(Url.job_id == self.job_id, Heading.oculto.isnot(None)).limit(1)
            ).first()
            self._anterior_d46 = hay is not None and medido is None
        return self._anterior_d46

    # -- Canonicals ---------------------------------------------------------

    def analyze_canonicals(self) -> None:
        """Validate canonical link declarations."""
        logger.debug("Analyzing canonicals ...")

        # Todas las URLs del job, por la URL tal cual y por la clave de
        # `misma_url`: un canonical que solo difiere en el orden de los
        # parametros, el escapado o el puerto por defecto encuentra su destino.
        # Con lo que hace falta para seguir el destino (decision 101): su
        # codigo, a donde redirige, si es noindex y su propio canonical.
        fichas = _Fichas(self.session, self.job_id)
        # Lo reutiliza `avisos_de_medios` (decision 156), que lo suelta al
        # empezar: entre los dos no cambia nada de lo que lleva una ficha.
        self._fichas_canonicals = fichas

        # Iterate HTML pages with their canonical information.
        # Una meta refresh no es la pagina: es un salto (decision 120). Sus
        # senales no se evaluan como las de la pagina final —salia
        # `canonical_missing` en el puente—; lo que tiene de malo lo dice
        # `meta_refresh_redireccion`. Un muro tampoco (103).
        stmt = (
            select(Url.id, Url.url, Url.host, Url.status_code, HtmlMeta.canonical_href,
                   HtmlMeta.canonical_count, HtmlMeta.canonical_in_body,
                   HtmlMeta.head_cortado_por, HtmlMeta.fuera_del_head,
                   HtmlMeta.canonical_distintos, HtmlMeta.canonical_header,
                   Url.noindex, Url.path)
            .join(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(Url.job_id == self.job_id, Url.is_html.is_(True),
                   _respuesta_valida(),
                   or_(Url.indexability_status.is_(None),
                       Url.indexability_status != ESTADO_META_REFRESH))
        )
        rows = self.session.execute(stmt).all()

        # (host, plantilla) -> paginas con `noindex` y canonical a otra (4b).
        noindex_y_canonical: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        # host -> paginas con el canonical del HTML distinto del de la cabecera.
        html_y_cabecera: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for (url_id, page_url, page_host, page_status, canonical_href,
             canonical_count, canonical_in_body, head_cortado_por,
             fuera_del_head, canonical_distintos, canonical_header,
             page_noindex, page_path) in rows:
            # Con VARIOS canonicals DISTINTOS Google los ignora todos y elige el
            # por su cuenta: la pagina esta sin canonicalizar (decision 115).
            # El mismo destino escrito dos veces —relativo y absoluto, dos
            # plugins— es un canonical, y uno en el head mas el mismo en el
            # body ya es `canonical_in_body`. Un censo anterior a la columna
            # (NULL) sigue con el conteo de etiquetas, con `distintos` a None:
            # lo que no se sabe no se calla ni se inventa.
            if canonical_distintos is None:
                multiple = (canonical_count or 0) > 1
            else:
                multiple = canonical_distintos > 1
            if multiple:
                self._add_issue(
                    url_id, "canonical_multiple", "warning",
                    {"cuantos": canonical_count, "distintos": canonical_distintos},
                )
            # Un canonical en el `<body>` Google lo ignora SIEMPRE: solo cuenta
            # en el `<head>`.
            # Si esta en el body porque algo corto el head, el hallazgo es el
            # corte y lo dice `head_cortado` (decision 102): un aviso por
            # hallazgo (36).
            cortado = _lo_saca_el_corte(head_cortado_por, fuera_del_head, "canonical")
            if canonical_in_body and not cortado:
                self._add_issue(url_id, "canonical_in_body", "warning")

            # El canonical que vale es el del HTML y, si no hay, el de la
            # cabecera `Link`: el mismo criterio que la indexabilidad y que
            # `_Fichas`. Solo se leia el del HTML, asi que una pagina
            # «Canonicalised» por cabecera salia ademas con `canonical_missing`
            # y su destino no se comprobaba (B1 de #150, decision 120).
            del_html = (canonical_href or "").strip()
            de_cabecera = (canonical_header or "").strip()
            if not del_html and not de_cabecera:
                # El extractor solo toma el canonical del head tal como lo
                # parsea lxml, asi que con el head cortado antes del canonical
                # `canonical_href` llega vacio: la pagina SI lo declara, y el
                # hallazgo es el corte (`head_cortado`, error). Decir ademas
                # que falta era el mismo hallazgo dos veces (decision 36).
                if not cortado:
                    self._add_issue(url_id, "canonical_missing", "info")
                continue

            canonical = del_html or de_cabecera
            fuente = {} if del_html else {"fuente": "cabecera"}

            # Google ignora ese canonical: avisar de a donde va (otro dominio,
            # http, un destino roto) seria tratarlo como si valiera. El aviso
            # es `canonical_multiple`, uno por hallazgo (36).
            if canonical_distintos is not None and canonical_distintos > 1:
                continue

            # Dos canonicals que se contradicen, uno en el HTML y otro en la
            # cabecera (4a): manda el del HTML para la indexabilidad, pero
            # Google recibe dos senales y puede no fiarse de ninguna. Con la
            # regla de `misma_url`: la barra final SI cuenta, el orden de los
            # parametros no. Solo en paginas que responden 200, como el destino.
            if (page_status == 200 and del_html and de_cabecera
                    and not misma_url(del_html, de_cabecera)):
                html_y_cabecera[page_host or ""].append({
                    "url_id": url_id, "url": page_url,
                    "canonical_html": del_html, "canonical_cabecera": de_cabecera,
                })

            # `noindex` con un canonical a otra URL (4b): dos senales que piden
            # cosas distintas. Se decide abajo, con el destino a la vista.
            if (page_status == 200 and page_noindex
                    and not misma_url(canonical, page_url)):
                noindex_y_canonical[(page_host or "", firma_de_ruta(page_path or "/"))].append(
                    {"url_id": url_id, "url": page_url, "canonical": canonical})

            # Autocanonico: nada que avisar. Con la MISMA regla que la
            # indexabilidad (`misma_url`): el puerto por defecto, la caja del
            # host, el escapado y el orden de los parametros no cuentan; la
            # barra final, el `www` y el esquema SI, porque ahi hay una
            # canonicalizacion de verdad (decision 39).
            if misma_url(canonical, page_url):
                continue

            # Cross-domain canonical.
            try:
                canonical_parsed = urlparse(canonical)
                canonical_host = canonical_parsed.hostname or ""
            except Exception:
                canonical_parsed = None
                canonical_host = ""

            # `www.x.com` y `x.com` no son otro dominio: son el mismo sitio
            # resolviendo su propia variante, que es justo para lo que existe el
            # canonical. Marcarlo como "canonical a otro dominio" convertia la
            # solucion en un problema en el informe.
            #
            # Y la SEVERIDAD depende de a donde va, que es lo que decide lo que
            # se pierde (mismo criterio que la decision 22):
            #
            # - A otro subdominio de la misma casa (`comein.uoc.edu` desde
            #   `www.uoc.edu`) es consolidacion de contenido: una decision que
            #   conviene ver, no una alarma. Se queda en `info`.
            # - A otro dominio REGISTRABLE la pagina se esta sacando del indice
            #   en favor de un sitio que no es el suyo. Eso es un error.
            #
            # Medido: en www.uoc.edu hay 3.551 canonicals a otro host y **3.550
            # se quedan dentro de uoc.edu**; con el criterio de host eran 3.411
            # lineas de ruido. En Lopesan, 2.367 apuntaban al servidor de origen
            # de Liferay (`*.lfr.cloud`, otro dominio registrable) y eran el
            # 99,5% de la seccion de hoteles: el hallazgo mas grave del informe,
            # archivado como "informativo".
            if (
                canonical_host
                and page_host
                and canonical_host.removeprefix("www.") != page_host.removeprefix("www.")
            ):
                fuera = (
                    dominio_registrable(canonical_host)
                    != dominio_registrable(page_host)
                )
                self._add_issue(
                    url_id,
                    "canonical_cross_domain",
                    "error" if fuera else "info",
                    {
                        "canonical": canonical,
                        "canonical_host": canonical_host,
                        "otro_dominio_registrable": fuera,
                        **fuente,
                    },
                    group_key=_clave_de_grupo(canonical_host),
                )

            # Un canonical a http desde una pagina https manda a Google a la
            # version sin cifrar: o se indexa la http (perdiendo la senal de
            # HTTPS) o se ignora el canonical. Pasa al migrar a https y dejar la
            # plantilla con la URL vieja escrita a mano.
            a_http = (
                canonical_parsed is not None
                and canonical_parsed.scheme == "http"
                and urlparse(page_url).scheme == "https"
            )
            if a_http:
                self._add_issue(
                    url_id, "canonical_a_http", "warning",
                    {"canonical": canonical, **fuente},
                )

            # Lo que encuentra Google al llegar al destino (decision 101).
            # Solo desde una pagina que responde 200: el canonical de un 404 o
            # de un 500 Google no lo procesa, porque esa pagina sale del indice
            # por su codigo antes de que importe a donde apunte.
            if page_status == 200:
                self._avisar_destino_del_canonical(
                    url_id, page_url, canonical, fichas, a_http=a_http,
                    extra=fuente,
                )

        self._avisar_html_y_cabecera(html_y_cabecera)
        self._avisar_noindex_y_canonical(noindex_y_canonical, fichas)
        self._flush_issues()

    def _avisar_html_y_cabecera(self, por_host: dict[str, list[dict[str, Any]]]) -> None:
        """`canonical_html_y_cabecera_distintos` (decision 120): por pagina, o
        una fila por host si son `enlaces_plantilla_min_paginas` o mas —un CDN
        o un plugin que pone la cabecera en todo el sitio es UN arreglo (53)—.
        """
        for host, paginas in por_host.items():
            paginas.sort(key=lambda p: p["url"])
            if len(paginas) >= self.enlaces_plantilla_min_paginas:
                p = paginas[0]
                self._add_issue(
                    p["url_id"], "canonical_html_y_cabecera_distintos", "warning",
                    {"alcance": "host", "host": host, "paginas_afectadas": len(paginas),
                     "canonical_html": p["canonical_html"],
                     "canonical_cabecera": p["canonical_cabecera"],
                     "paginas_ejemplo": [x["url"] for x in paginas[: self._MUESTRA_EJEMPLOS]]},
                    group_key=_clave_de_grupo(host),
                )
                continue
            for p in paginas:
                self._add_issue(
                    p["url_id"], "canonical_html_y_cabecera_distintos", "warning",
                    {"alcance": "pagina", "canonical_html": p["canonical_html"],
                     "canonical_cabecera": p["canonical_cabecera"]},
                )

    def _avisar_noindex_y_canonical(
        self, grupos: dict[tuple[str, str], list[dict[str, Any]]], fichas: "_Fichas",
    ) -> None:
        """`noindex_y_canonical_a_otra` (decision 120), una fila por (host,
        plantilla), y fuera el `noindex_page` de esas paginas: es el mismo
        hallazgo dicho con mas (36), como `canonical_sin_enlazar` con
        `orphan_page`.

        Google suele obedecer el `noindex` y la consolidacion no se produce;
        quitar una de las dos senales da claridad, no indice. Por eso `info` y
        agrupado: «faceta en noindex con canonical a la categoria» es deliberado
        y masivo (decision 38: 9.771 noindex en Druni). Con un destino que es a
        su vez noindex no hay contradiccion util (101): la pagina se queda con
        su `noindex_page` y nada mas.
        """
        sustituidas: list[int] = []
        for (host, plantilla), paginas in grupos.items():
            validas = []
            for p in paginas:
                destino = fichas.buscar(p["canonical"])
                if destino is not None and destino.status_code == 200 and destino.noindex:
                    continue
                # Lo que no se ha visto no se afirma: sin rastrear, None.
                p["destino_indexable"] = (
                    None if destino is None
                    else bool(destino.status_code == 200 and not destino.noindex))
                validas.append(p)
            if not validas:
                continue
            validas.sort(key=lambda p: p["url"])
            p = validas[0]
            self._add_issue(
                p["url_id"], "noindex_y_canonical_a_otra", "info",
                {"host": host, "plantilla": plantilla, "paginas_afectadas": len(validas),
                 "canonical": p["canonical"], "destino_indexable": p["destino_indexable"],
                 "paginas_ejemplo": [x["url"] for x in validas[: self._MUESTRA_EJEMPLOS]]},
                group_key=_clave_de_grupo(f"{host}|{plantilla}"),
            )
            sustituidas.extend(x["url_id"] for x in validas)
        if not sustituidas:
            return
        self._flush_issues()
        for i in range(0, len(sustituidas), BATCH_SIZE):
            self.session.execute(
                delete(Issue).where(
                    Issue.job_id == self.job_id,
                    Issue.issue_type == "noindex_page",
                    Issue.url_id.in_(sustituidas[i:i + BATCH_SIZE]),
                ).execution_options(synchronize_session=False)
            )

    def _avisar_destino_del_canonical(
        self, url_id: int, page_url: str, canonical: str, fichas: "_Fichas",
        *, a_http: bool, extra: dict[str, Any] | None = None,
    ) -> None:
        """Que encuentra Google en el destino del canonical (decision 101).

        Antes era UN tipo, `canonical_broken`, para «no responde 200» — un 301
        y un 404 son hallazgos distintos con arreglos distintos, y un destino
        200 en `noindex` o canonicalizado a su vez a otro no avisaba de nada.
        Un aviso por hallazgo, el que dice que hay que arreglar:

        - destino que es un error, directamente o al final de sus
          redirecciones → `canonical_a_error` (error): el contenido no tiene
          ninguna URL que Google pueda indexar.
        - destino que redirige a una pagina buena → `canonical_a_redireccion`
          (warning): Google suele quedarse con la final, pero la senal
          contradice al canonical. Si la redireccion vuelve a la propia pagina
          y ya salio `canonical_a_http`, ese es el aviso: no se repite.
        - destino 200 en `noindex` → `canonical_a_no_indexable` (warning): la
          variante se declara copia de una pagina que pide no estar en el
          indice, y Google recibe dos senales que se contradicen. No es error
          porque lo que saca el contenido del indice es el `noindex` del
          destino, que ya avisa en su URL y muchas veces es deliberado (en
          Druni, 52 variantes con `gclid` de paginaciones `?p=N` en noindex).
        - destino 200 canonicalizado a otro → `canonical_encadenado`
          (A → B → C). Error si la cadena acaba en un 4xx o 5xx —el contenido
          se queda sin URL buena—; warning en lo demas.

        Lo que no se sabe no se afirma: un destino no rastreado, bloqueado por
        robots.txt, sin respuesta o con 429 —el sitio frenando al rastreador,
        no su codigo real— no emite nada.
        """
        destino = fichas.buscar(canonical)
        if destino is None:
            return
        base = {"canonical": canonical, "target_status": destino.status_code,
                **(extra or {})}

        if destino.redirige:
            final, cadena, bucle = fichas.seguir_redirecciones(destino)
            if final is not None and _es_error(final.status_code):
                self._add_issue(url_id, "canonical_a_error", "error", {
                    **base, "via_redireccion": True, "cadena": cadena,
                    "final_status": final.status_code,
                })
            elif bucle:
                self._add_issue(url_id, "canonical_a_error", "error", {
                    **base, "via_redireccion": True, "cadena": cadena,
                    "bucle_de_redireccion": True,
                })
            else:
                # Que el destino redirige es un hecho aunque no se sepa donde
                # acaba (sale de lo rastreado, o un 429): entonces
                # `destino_final` va vacio.
                bueno = final is not None and final.status_code == 200
                vuelve = bueno and misma_url(final.url, page_url)
                # Con `canonical_a_http` ya avisado, una redireccion que solo
                # sube a https (a la propia pagina o a la version https del
                # canonical) es el mismo hallazgo con el mismo arreglo.
                if a_http and bueno and (
                        vuelve or misma_url(final.url, _a_https(canonical))):
                    return
                self._add_issue(url_id, "canonical_a_redireccion", "warning", {
                    **base, "destino_final": final.url if bueno else None,
                    "cadena": cadena, "vuelve_a_la_pagina": vuelve,
                })
            return
        if destino.status_code is not None and 300 <= destino.status_code < 400:
            # Un 3xx sin destino guardado: redirige, no se sabe a donde.
            self._add_issue(url_id, "canonical_a_redireccion", "warning", {
                **base, "destino_final": None, "vuelve_a_la_pagina": False,
            })
            return

        if _es_error(destino.status_code):
            self._add_issue(url_id, "canonical_a_error", "error", base)
            return
        if destino.status_code != 200:
            return

        if destino.noindex:
            # Si la propia pagina tambien es noindex no hay senales que se
            # contradigan: no entra en el indice pase lo que pase, y lo que
            # quede por revisar es el noindex del destino, que avisa en su URL.
            origen = fichas.buscar(page_url)
            if origen is not None and origen.noindex:
                return
            self._add_issue(url_id, "canonical_a_no_indexable", "warning", {
                **base, "motivo": "noindex",
            })
            return

        if destino.canonical and not misma_url(destino.canonical, destino.url):
            cadena, final, bucle = fichas.seguir_canonicals(page_url, destino)
            if final is destino:
                # El canonical del destino vuelve a el por una redireccion: el
                # de A es correcto, de un salto.
                return
            final_malo = final is not None and _es_error(final.status_code)
            detalle = {**base, "cadena": cadena, "bucle": bucle}
            if final is not None:
                detalle["final_status"] = final.status_code
                detalle["final_noindex"] = bool(final.noindex)
            self._add_issue(
                url_id, "canonical_encadenado",
                "error" if final_malo else "warning", detalle,
            )

    # -- Hreflang -----------------------------------------------------------

    def analyze_hreflang(self) -> None:
        """Validate hreflang annotations, including reciprocal return tags.

        Computes and persists ``lang_valid`` and ``return_tag_ok`` on each
        Hreflang row (nothing else populates them), then flags invalid
        language codes, missing reciprocal return tags, and hreflang targets
        that do not return 200. Reciprocity is confirmed only when the target
        page was crawled and carries its own hreflang cluster; otherwise the
        return tag is left unknown to avoid false positives.

        Y los cinco de la decision 99, que solo miran paginas INDEXABLES
        (Google no usa el hreflang de una pagina canonicalizada o noindex: una
        variante `?utm` que repite el cluster de su canonica no tiene nada que
        arreglar): `hreflang_sin_autorreferencia` (por pagina),
        `hreflang_sin_x_default` (por host), `hreflang_idioma_repetido`
        (por cluster e idioma), `hreflang_destino_no_indexable` (por anotacion) y
        `hreflang_retorno_incoherente` (por anotacion). Todo sale de diccionarios
        montados con UNA consulta de URLs y una de anotaciones: nada por
        anotacion y nada por pareja de paginas.

        Las anotaciones de una pagina son la UNION de sus tres fuentes: el
        `<head>`, la cabecera `Link` y el sitemap (decision 167), y dos fuentes
        que dan URLs distintas para el mismo idioma son
        `hreflang_fuentes_discrepan` (uno por host y combinacion de fuentes).
        """
        logger.debug("Analyzing hreflang ...")

        # Precarga, una sola consulta para todo el censo: estado, indexable,
        # motivo (`Noindex`, `Canonicalised`, robots...), redireccion y
        # canonical de cada URL (decision 99). El canonical solo va
        # al detalle —«este destino esta canonicalizado a X»—; quien decide si
        # la pagina es indexable es `analyze_indexability`, que corre antes.
        url_status: dict[str, int | None] = {}
        url_id_by_norm: dict[str, int] = {}
        norm_by_id: dict[int, str] = {}
        url_by_id: dict[int, str] = {}
        info_url: dict[int, tuple] = {}
        # Interna y tipo de recurso, para dos cosas: una pagina EXTERNA no es
        # fuente (no es del sitio auditado y la pestana Hreflang del Explorador
        # no la ensena), y el x-default se ancla en una pagina HTML interna.
        internas: set[int] = set()
        html_200: set[int] = set()
        # Lo que se sabe que no es HTML (un PDF con hreflang en la cabecera
        # `Link`): sus anotaciones cuentan como destino y como retorno, pero no
        # es fuente de avisos, porque la pestana Hreflang filtra por HTML
        # interno y el chip diria N con la lista en N-k (decision 116).
        no_html: set[int] = set()
        # URL -> a donde salta, SOLO por redireccion (para anclar el x-default
        # en la pagina a la que lleva la raiz, no en el 301).
        salta_a: dict[tuple, tuple] = {}
        consulta = (
            select(Url.id, Url.url, Url.status_code, Url.indexable,
                   Url.indexability_status, Url.redirect_url,
                   HtmlMeta.canonical_href, Url.is_internal, Url.resource_type,
                   Url.response_class)
            .outerjoin(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(Url.job_id == self.job_id)
        )
        # URL -> a donde la manda su redireccion o su canonical: una pagina
        # que se anota a si misma por una variante que salta a ella no carece
        # de autorreferencia; lo que tiene es un destino roto o no indexable,
        # y ese es el aviso (uno por hallazgo).
        alias_de: dict[str, str] = {}
        for (uid, row_url, sc, indexable, estado_idx, redirige, canonical,
             interna, tipo_recurso, clase) in self.session.execute(
            consulta.execution_options(yield_per=BATCH_SIZE)
        ):
            # Un destino que es un muro no se ha visto: ni roto ni sin retorno
            # (decision 103). Como si no se hubiera rastreado.
            if clase in NO_VALIDAS:
                continue
            url_status[row_url] = sc
            url_by_id[uid] = row_url
            info_url[uid] = (sc, indexable, estado_idx, canonical)
            if interna:
                internas.add(uid)
                if sc == 200 and tipo_recurso == "html":
                    html_200.add(uid)
            if tipo_recurso is not None and tipo_recurso != "html":
                no_html.add(uid)
            norm = _clave(row_url)
            if norm:
                if redirige and _clave(redirige):
                    salta_a[norm] = _clave(redirige)
                url_status.setdefault(norm, sc)
                url_id_by_norm[norm] = uid
                norm_by_id[uid] = norm
                otra = redirige if redirige else (
                    canonical if estado_idx == "Canonicalised" else None)
                otra = _clave(otra)
                if otra and otra != norm:
                    alias_de[norm] = otra

        def indexable(uid: int | None) -> bool:
            """Si la pagina cuenta como FUENTE de hreflang.

            Google no usa el hreflang de una pagina que no es indexable: la
            variante `/es` canonicalizada a `/es/` repite el cluster de su
            canonica y nadie le devuelve el enlace, porque el retorno apunta,
            bien, a `/es/`. Medido: de las 296 `hreflang_missing_return` de
            Lopesan, las 296 venian de paginas canonicalizadas (decision 99).
            NULL —un censo sin indexabilidad calculada— cuenta: no se descarta
            por desconocimiento.
            """
            return uid is not None and info_url.get(uid, (None, None))[1] is not False

        def fuente(uid: int | None) -> bool:
            """Indexable y del sitio: una pagina externa que el rastreo leyo
            (otro subdominio fuera del alcance) no es lo que se audita, y sus
            avisos no se verian en la pestana Hreflang, que filtra por HTML
            interno."""
            return indexable(uid) and uid in internas and uid not in no_html

        stmt = (
            select(Hreflang.id, Hreflang.url_id, Hreflang.lang, Hreflang.href,
                   Hreflang.en_body, Hreflang.origen)
            .join(Url, Url.id == Hreflang.url_id)
            .where(Url.job_id == self.job_id)
        )
        # La tercera fuente: el `<xhtml:link>` del sitemap (decision 167).
        # Google trata las tres igual, asi que las anotaciones de una URL son
        # la UNION de las tres. Las del sitemap no tienen fila en `hreflang`:
        # entran aqui con un id negativo, que nunca se escribe.
        sm = self._hreflang_del_sitemap()
        # La misma anotacion repetida —dos plugins escribiendo el mismo
        # `en-GB`, el head y la cabecera `Link`, `/en/` y `/en/#top`— es UNA
        # (decision 116): salian dos `hreflang_broken_target` identicos. Se analiza la
        # primera, o la primera del head si la otra esta en el body (Google lee
        # esa), y las repetidas reciben su mismo veredicto al final, para que
        # no queden a NULL en la nota de /insights. Asi re-analizar arregla los
        # censos ya guardados, que el extractor no deduplicaba.
        #
        # Memoria: todo lo de aqui es por anotacion, y un sitemap con 20
        # idiomas son millones (revision de la PR #231: ~1,7 KB por anotacion
        # del sitemap con una estructura por fuente). Por eso las dos
        # consultas se leen por lotes, cada href y su clave se guardan UNA vez
        # (una URL de un cluster de N idiomas aparece en N paginas), y las
        # fuentes de cada anotacion son bits en `mascaras`, alineada con
        # `rows`, no un set por anotacion.
        rows: list[tuple] = []
        mascaras: list[int] = []
        representante: dict[tuple, int] = {}
        repetidas: dict[int, list[int]] = defaultdict(list)
        # Pagina -> fuentes con alguna anotacion (bits): solo las que tienen
        # dos o mas pueden discrepar (decision 167).
        mascara_pagina: dict[int, int] = defaultdict(int)
        # href -> (el mismo href, su clave): el primero que se vio se reutiliza.
        canon: dict[str | None, tuple] = {}
        minusculas: dict[str, str] = {}

        def _cf(lang: str | None) -> str:
            c = minusculas.get(lang or "")
            if c is None:
                c = minusculas[lang or ""] = sys.intern((lang or "").casefold())
            return c

        def _filas():
            yield from self.session.execute(
                stmt.order_by(Hreflang.id).execution_options(yield_per=BATCH_SIZE))
            yield from sm["filas"]

        for hid, uid, lang, href, en_body, origen in _filas():
            par = canon.get(href)
            if par is None:
                par = canon[href] = (href, _clave(href))
            href, nh = par
            if lang:
                lang = sys.intern(lang)
            clave = (uid, _cf(lang), nh or href)
            bit = 0 if en_body else _BIT_FUENTE.get(origen or "html", 1)
            if bit:
                mascara_pagina[uid] |= bit
            fila = (hid, uid, lang, href, en_body)
            i = representante.get(clave)
            if i is None:
                representante[clave] = len(rows)
                rows.append(fila)
                mascaras.append(bit)
                continue
            mascaras[i] |= bit
            if rows[i][4] and not en_body:
                repetidas[hid].append(rows[i][0])
                repetidas[hid].extend(repetidas.pop(rows[i][0], []))
                rows[i] = fila
            elif hid > 0:
                # Una del sitemap repetida (id negativo) no tiene fila que
                # escribir: no se apunta.
                repetidas[rows[i][0]].append(hid)
        del representante

        # Map each crawled page to the set of hreflang targets it declares,
        # so we can check whether a target links back (reciprocal return tag).
        # Los del `<body>` no: Google los ignora, asi que no son el retorno de
        # nadie.
        targets_by_page: dict[int, set[str]] = defaultdict(set)
        # Pagina -> destino -> codigos VALIDOS con que lo anota (casefold).
        # Un codigo invalido ya tiene su aviso y Google ignora esa anotacion:
        # contarlo aqui seria avisar dos veces de lo mismo.
        codigos: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        # Pagina -> destinos a los que apunta con cualquier codigo, valido o no:
        # para la autorreferencia basta con que exista (si su codigo esta mal,
        # el aviso es `hreflang_invalid_lang`, no este).
        for _hid, page_id, lang, href, en_body in rows:
            nh = canon[href][1]
            if nh and not en_body:
                targets_by_page[page_id].add(nh)
                if _lang_hreflang_valido(lang)[0]:
                    codigos[page_id][nh].add(_cf(lang))

        # Anotaciones agrupadas por veredicto, para escribirlas por lotes.
        por_veredicto: dict[tuple[bool, bool | None], list[int]] = {}

        def apuntar(veredicto: tuple, hid: int) -> None:
            # Las del sitemap (id negativo) no tienen fila que escribir.
            if hid > 0:
                por_veredicto.setdefault(veredicto, []).append(hid)

        # Pagina -> idiomas anotados en el `<body>`.
        en_body_por_pagina: dict[int, list[str]] = defaultdict(list)
        # Destino no indexable -> pagina indexable que lo anota -> idiomas.
        no_indexable: dict[int, dict[int, set[str]]] = {}
        # Anotaciones sin retorno, pendientes de saber si son la autorreferencia.
        sin_retorno: list[tuple] = []

        # Paginas cuyo hreflang del sitemap no se conoce (se leyo a medias y su
        # entrada no se guardo): lo que falte en ellas puede estar en lo que no
        # se leyo, y esa ausencia no se afirma (decision 167).
        def sitemap_desconocido(uid: int | None) -> bool:
            return (sm["en_uso"] and not sm["completo"]
                    and uid not in sm["conocidas"])

        # Mismo codigo hacia URLs distintas segun la fuente (decision 167).
        def por_fuente():
            """(pagina, codigo -> fuente -> destinos) de las paginas fuente con
            dos fuentes o mas, una a una: solo lo que Google lee (no el body).
            Sale de las representantes, cuya mascara junta las fuentes de todas
            sus repetidas."""
            varias = {p for p, m in mascara_pagina.items() if m & (m - 1) and fuente(p)}
            if not varias:
                return
            filas_de: dict[int, array] = defaultdict(lambda: array("q"))
            for i, f in enumerate(rows):
                if mascaras[i] and f[1] in varias:
                    filas_de[f[1]].append(i)
            for page_id, indices in filas_de.items():
                por_codigo: dict[str, dict[str, set]] = defaultdict(
                    lambda: defaultdict(set))
                for i in indices:
                    _h, _p, lang, href, _b = rows[i]
                    destino = canon[href][1] or href
                    for nombre, bit in _BIT_FUENTE.items():
                        if mascaras[i] & bit:
                            por_codigo[_cf(lang)][nombre].add(destino)
                yield page_id, por_codigo

        discrepantes, entre_fuentes = self._hreflang_discrepancias(
            por_fuente(), fuente, url_status, url_id_by_norm, info_url)

        for n_fila, (hreflang_id, url_id, lang, href, en_body) in enumerate(rows):
            norm_href = canon[href][1]

            lang_is_valid, idioma_malo, region_mala = _lang_hreflang_valido(lang)

            # Una pagina no indexable no es fuente: se guarda si su codigo es
            # valido, que sigue siendo verdad, y nada mas. Lo que tenga mal lo
            # tendra tambien su canonica, y ahi es donde se avisa.
            if not fuente(url_id):
                apuntar((lang_is_valid, None), hreflang_id)
                continue

            # Un hreflang en el `<body>` Google lo ignora: esa anotacion no
            # existe para el, asi que no tiene sentido decir que le falta el
            # retorno o que su destino esta roto. Un aviso por hallazgo
            # (decision 36): `hreflang_in_body`, una vez por pagina, y lo que
            # hay que hacer es moverlo al `<head>`. Se guarda igualmente si el
            # idioma es valido, que sigue siendo verdad.
            if en_body:
                en_body_por_pagina[url_id].append(lang)
                apuntar((lang_is_valid, None), hreflang_id)
                continue

            # Reciprocal return tag. Only decidable when the target page was
            # crawled; x-default entries need no reciprocal.
            page_norm = norm_by_id.get(url_id)
            target_uid = url_id_by_norm.get(norm_href)
            if lang and lang.lower() == "x-default":
                return_ok = None
            elif target_uid is None or target_uid == url_id:
                return_ok = None  # target not crawled or self-reference
            else:
                return_ok = page_norm in targets_by_page.get(target_uid, set())
                if not return_ok and sitemap_desconocido(target_uid):
                    return_ok = None
            # Una de las URLs de un idioma en el que las fuentes discrepan: el
            # hallazgo es la discrepancia, y arreglarla decide cual se queda.
            if return_ok is False and (url_id, (lang or "").casefold()) in discrepantes:
                return_ok = None

            # Si el destino no responde 200 no se puede saber si devuelve el
            # enlace: reportar las dos cosas a la vez (destino roto Y sin
            # retorno) es contar el mismo hallazgo dos veces, y lo que hay que
            # arreglar es el destino. El docstring ya decia que en ese caso se
            # deja "unknown"; el codigo no lo hacia.
            estado_destino = url_status.get(href)
            if estado_destino is None:
                estado_destino = url_status.get(norm_href)
            destino_roto = estado_destino is not None and estado_destino != 200
            if destino_roto:
                return_ok = None

            # Lo mismo con un destino que responde pero no es indexable
            # (canonicalizado, noindex, bloqueado por robots): Google no lo usa
            # como alternativa, asi que su retorno tampoco cuenta. Un aviso, por
            # DESTINO, con las paginas que lo anotan (decision 99).
            # Sin respuesta (timeout, DNS) es otra cosa: no se sabe que veria
            # Google, asi que ni se avisa del destino ni se afirma que falte su
            # retorno —un destino sin respuesta no tiene hreflang guardado y
            # salia como `hreflang_missing_return`—.
            sin_respuesta = (
                target_uid is not None and estado_destino is None
                and not (info_url[target_uid][2] or "").startswith("Blocked by robots")
            )
            destino_no_indexable = (
                not destino_roto and not sin_respuesta
                and target_uid is not None and target_uid != url_id
                and info_url[target_uid][1] is False
            )
            if sin_respuesta and target_uid != url_id:
                return_ok = None
            if destino_no_indexable:
                return_ok = None
                no_indexable.setdefault(target_uid, {}).setdefault(
                    url_id, set()).add(lang)

            # El veredicto se apunta y se escribe al final, por lotes. Se
            # escribia con un UPDATE POR ANOTACION —y con DOS cuando el destino
            # estaba roto, porque el segundo pisaba al primero—, y de ahi solo
            # salen SEIS combinaciones distintas: valido o no, por devuelve el
            # enlace / no lo devuelve / no se sabe. En el censo de penguin eso
            # son 438.957 sentencias para escribir seis valores.
            # La falta de retorno se decide DESPUES de la autorreferencia: si el
            # destino es la variante con la que la pagina se anota a si misma
            # (`?p=2` que se llama `es-es` con la URL de la pagina 1), el
            # hallazgo es `hreflang_sin_autorreferencia` y su arreglo cierra
            # los dos; avisar tambien de que la pagina 1 no devuelve el enlace
            # era el mismo hallazgo dos veces (decision 36). Medido en progym:
            # 139 de las 140 `hreflang_missing_return` eran esto.
            # Lo que solo declara el sitemap se dice: el arreglo va alli.
            de_sitemap = mascaras[n_fila] == _BIT_FUENTE["sitemap"]
            if return_ok is False:
                sin_retorno.append((hreflang_id, lang_is_valid, url_id, lang,
                                    href, norm_href, de_sitemap))
            else:
                apuntar((lang_is_valid, return_ok), hreflang_id)

            if not lang_is_valid:
                detalle = {"lang": lang}
                if idioma_malo:
                    detalle["motivo"] = (
                        f"'{idioma_malo}' no es un codigo de idioma ISO 639-1"
                        " (Google solo acepta los de dos letras)"
                    )
                elif region_mala:
                    sugerida = _REGIONES_INVENTADAS.get(region_mala) or None
                    detalle["motivo"] = (
                        f"'{region_mala.upper()}' no es un codigo de pais ISO 3166-1"
                        + (f"; el de ese pais es '{sugerida}'" if sugerida else "")
                    )
                if de_sitemap:
                    detalle["origen"] = "sitemap"
                self._add_issue(url_id, "hreflang_invalid_lang", "warning",
                                detalle, group_key=_clave_de_grupo(lang))

            # Target URL not returning 200.
            if destino_roto:
                detalle = {"href": href, "target_status": estado_destino}
                if de_sitemap:
                    detalle["origen"] = "sitemap"
                self._add_issue(
                    url_id,
                    "hreflang_broken_target",
                    "error",
                    detalle,
                    group_key=_clave_de_grupo(lang),
                )

        # Las que estan en el body porque algo corto el head van en
        # `head_cortado` (decision 102), no aqui tambien.
        cortadas = {
            uid for uid, cortado, fuera in self.session.execute(
                select(HtmlMeta.url_id, HtmlMeta.head_cortado_por,
                       HtmlMeta.fuera_del_head)
                .join(Url, Url.id == HtmlMeta.url_id)
                .where(Url.job_id == self.job_id,
                       HtmlMeta.head_cortado_por.isnot(None))
            ).all()
            if _lo_saca_el_corte(cortado, fuera, "hreflang")
        } if en_body_por_pagina else set()
        for url_id, langs in en_body_por_pagina.items():
            if url_id in cortadas:
                continue
            self._add_issue(
                url_id, "hreflang_in_body", "warning",
                {"cuantos": len(langs), "langs": sorted(set(langs))[:20]},
            )

        variante_de = self._hreflang_completo(
            targets_by_page, codigos, no_indexable, info_url, norm_by_id,
            url_id_by_norm, url_by_id, fuente, alias_de, salta_a, html_200,
            discrepantes=entre_fuentes, desconocida=sitemap_desconocido,
        )
        self._avisar_hreflang_discrepante(
            discrepantes, norm_by_id, url_by_id, url_id_by_norm, salta_a, html_200)

        for (hreflang_id, lang_valid, url_id, lang, href, norm_href,
             de_sitemap) in sin_retorno:
            if norm_href is not None and variante_de.get(url_id) == norm_href:
                # La autorreferencia escrita con otra URL: no se afirma que
                # falte el retorno (ni en la nota de /insights).
                apuntar((lang_valid, None), hreflang_id)
                continue
            apuntar((lang_valid, False), hreflang_id)
            detalle = {"lang": lang, "href": href}
            if de_sitemap:
                detalle["origen"] = "sitemap"
            self._add_issue(
                url_id,
                "hreflang_missing_return",
                "warning",
                detalle,
                group_key=_clave_de_grupo(lang),
            )

        for (lang_valid, return_ok), ids in por_veredicto.items():
            ids = ids + [r for hid in ids for r in repetidas.get(hid, ()) if r > 0]
            for i in range(0, len(ids), 5000):
                self.session.execute(
                    update(Hreflang)
                    .where(Hreflang.id.in_(ids[i:i + 5000]))
                    .values(lang_valid=lang_valid, return_tag_ok=return_ok)
                )

        self.session.flush()
        self._flush_issues()

    # Cuantas URLs de ejemplo lleva una incidencia agrupada (decision 73).
    _EJEMPLOS_HREFLANG = 5

    def _hreflang_del_sitemap(self) -> dict:
        """El hreflang del sitemap de las URLs rastreadas (decision 167).

        Devuelve ``filas``, un generador de ``(id < 0, url_id, lang, href,
        False, "sitemap")`` que se lee por lotes, y tres datos que se completan
        al recorrerlo: ``conocidas`` (las URLs con su entrada leida, aunque no
        declare nada), ``en_uso`` (el sitio declara hreflang en el sitemap) y
        ``completo`` (`shared.sitemaps.estado_hreflang_sitemap`). Un censo
        anterior a la columna, o una base sin migrar, sale vacio y completo:
        el analisis queda como antes, solo con el HTML y la cabecera.

        ``en_uso`` sale de lo que el spider GUARDO (`hreflang_guardadas` o el
        tope de `jobs.sitemaps`), no solo de las entradas que casan con una
        URL rastreada: un sitemap leido a medias que declara hreflang de URLs
        que no se rastrearon tambien dice que el sitio lo usa, y entonces lo
        que falte en una pagina sin entrada leida no se afirma.

        `sitemap_entries` se une con `urls` por su indice unico
        ``(job_id, url_hash)``: una entrada de una URL que no se rastreo no es
        fuente de nada, y asi no se cargan en memoria. Las filas no se juntan
        en una lista: el sitemap de un sitio grande son millones de
        anotaciones (revision de la PR #231).

        Best-effort entero: si algo falla, el hreflang se analiza sin el
        sitemap en vez de tumbar el analisis (y si falla a medias de leerlo,
        lo leido vale y lo demas no se conoce).
        """
        def vacio() -> dict:
            return {"filas": iter(()), "conocidas": set(), "en_uso": False,
                    "completo": True}
        try:
            from shared.models import Job

            from shared.sitemaps import estado_hreflang_sitemap

            job = self.session.get(Job, self.job_id)
            resumen = getattr(job, "sitemaps", None) if job is not None else None
            guardado, completo = estado_hreflang_sitemap(resumen)
            if not guardado:
                return vacio()
            estado = {"conocidas": set(), "completo": completo,
                      "en_uso": bool(resumen.get("hreflang_guardadas")
                                     or resumen.get("hreflang_recortado"))}
            estado["filas"] = self._filas_hreflang_sitemap(estado)
            return estado
        except Exception:  # noqa: BLE001 -- best-effort (decision 40)
            logger.warning("No se pudo leer el hreflang del sitemap; se analiza "
                           "sin el (decision 167)", exc_info=True)
            return vacio()

    def _filas_hreflang_sitemap(self, estado: dict):
        """Las anotaciones de :meth:`_hreflang_del_sitemap`, por lotes.

        Best-effort: si falla, lo leido vale, y si el sitio usa hreflang en el
        sitemap lo demas no se conoce (no se afirman ausencias); si no consta
        que lo use, el analisis queda como antes, con el HTML y la cabecera.
        """
        n = 0
        try:
            from shared.models import SitemapEntry
            from shared.sitemaps import expandir_hreflang

            with self.session.begin_nested():
                consulta = (
                    select(Url.id, SitemapEntry.url, SitemapEntry.hreflang)
                    .join(Url, and_(Url.job_id == SitemapEntry.job_id,
                                    Url.url_hash == SitemapEntry.url_hash))
                    .where(SitemapEntry.job_id == self.job_id,
                           SitemapEntry.hreflang.isnot(None))
                    .execution_options(yield_per=BATCH_SIZE)
                )
                for uid, url, guardado_json in self.session.execute(consulta):
                    pares = expandir_hreflang(url, guardado_json)
                    if pares is None:
                        continue
                    estado["conocidas"].add(uid)
                    for lang, href in pares:
                        n += 1
                        estado["en_uso"] = True
                        yield (-n, uid, lang, href, False, "sitemap")
        except Exception:  # noqa: BLE001 -- best-effort (decision 40)
            logger.warning("No se pudo leer el hreflang del sitemap; se analiza "
                           "sin el (decision 167)", exc_info=True)
            # Si se sabe que el sitio lo usa (lo guardado o lo ya leido), lo que
            # no se pudo leer no se conoce; si no, queda como antes.
            estado["completo"] = not estado["en_uso"]

    @staticmethod
    def _hreflang_discrepancias(por_fuente, fuente, url_status, url_id_by_norm,
                                info_url) -> tuple[dict, set]:
        """Idiomas en los que las fuentes de una pagina dan URLs distintas.

        Google suma las tres fuentes (`<head>`, cabecera `Link`, sitemap): si
        el HTML dice `fr -> /fr/a` y el sitemap `fr -> /fr/b`, para el la
        pagina declara dos URLs para el frances, una senal contradictoria de
        la que puede descartar una o las dos (decision 167).

        *por_fuente*: iterable de ``(pagina, {codigo: {fuente: destinos}})``.

        Devuelve ``(discrepantes, entre_fuentes)``:

        - *entre_fuentes*: todos los ``(pagina, codigo)`` en que cada fuente da
          UNA URL y no coinciden. No son `hreflang_idioma_repetido`, que es el
          mismo codigo hacia dos URLs dentro de UNA fuente.
        - *discrepantes*: los de *entre_fuentes* en que todos los destinos
          estan vivos e indexables (o no se rastrearon), con ``{fuente: url}``.
          Si uno esta roto o no es indexable, ese es el hallazgo (su aviso
          propio dice cual sobra) y no se avisa ademas de la discrepancia.
        """
        discrepantes: dict[tuple, dict[str, tuple]] = {}
        entre_fuentes: set[tuple] = set()
        for page_id, por_codigo in por_fuente:
            if not fuente(page_id):
                continue
            for codigo, fuentes in por_codigo.items():
                if len(fuentes) < 2 or not _lang_hreflang_valido(codigo)[0]:
                    continue
                if any(len(d) != 1 for d in fuentes.values()):
                    continue  # repetido dentro de una fuente: otro aviso
                destinos = {next(iter(d)) for d in fuentes.values()}
                if len(destinos) < 2:
                    continue
                entre_fuentes.add((page_id, codigo))
                malo = False
                for d in destinos:
                    estado = url_status.get(d) if d in url_status else None
                    uid = url_id_by_norm.get(d)
                    if (estado is not None and estado != 200) or (
                            uid is not None and info_url[uid][1] is False):
                        malo = True
                        break
                if not malo:
                    discrepantes[(page_id, codigo)] = {
                        f: next(iter(d)) for f, d in fuentes.items()}
        return discrepantes, entre_fuentes

    def _avisar_hreflang_discrepante(self, discrepantes, norm_by_id, url_by_id,
                                     url_id_by_norm, salta_a, html_200) -> None:
        """`hreflang_fuentes_discrepan`: UNO por host y combinacion de fuentes.

        Casi siempre es de plantilla —el sitemap lo genera un plugin y el
        `<head>` otro, y uno escribe la barra final, el `http` o la ruta
        traducida de otra forma—, asi que va agrupado como el x-default
        (decisiones 64 y 73): una fila con `paginas_afectadas`, los idiomas y
        ejemplos, anclada en la raiz del host (o en la pagina a la que salta).
        """
        n_ej = self._EJEMPLOS_HREFLANG
        grupos: dict[tuple, dict] = {}
        for (page_id, codigo), urls in discrepantes.items():
            norm = norm_by_id.get(page_id)
            if not norm:
                continue
            clave = (norm[1], norm[0], tuple(sorted(urls)))
            g = grupos.setdefault(clave, {"paginas": set(), "idiomas": set(),
                                          "ejemplos": []})
            g["paginas"].add(page_id)
            g["idiomas"].add(codigo)
            g["ejemplos"].append({"url": url_by_id[page_id], "lang": codigo,
                                  **{f: (_url_de_clave(d) if isinstance(d, tuple) else d)
                                     for f, d in sorted(urls.items())}})
        for (host, esquema, fuentes), g in sorted(grupos.items()):
            clave_raiz = _clave(f"{esquema}://{host}/")
            vistas = {clave_raiz}
            while clave_raiz in salta_a and salta_a[clave_raiz] not in vistas:
                clave_raiz = salta_a[clave_raiz]
                vistas.add(clave_raiz)
            raiz = url_id_by_norm.get(clave_raiz)
            if raiz not in html_200 or raiz is None:
                raiz = min(g["paginas"], key=lambda i: url_by_id[i])
            ejemplos = sorted(g["ejemplos"], key=lambda e: (e["url"], e["lang"]))[:n_ej]
            self._add_issue(
                raiz, "hreflang_fuentes_discrepan", "warning",
                {"host": host, "fuentes": list(fuentes),
                 "paginas_afectadas": len(g["paginas"]),
                 "idiomas": sorted(g["idiomas"])[:20],
                 "ejemplos": ejemplos},
                group_key=_clave_de_grupo(f"{host}|{'+'.join(fuentes)}"),
            )

    def _hreflang_completo(self, targets_by_page, codigos, no_indexable,
                           info_url, norm_by_id, url_id_by_norm, url_by_id,
                           indexable, alias_de, salta_a, html_200,
                           discrepantes=frozenset(), desconocida=None) -> dict:
        """Los cinco tipos de la decision 99, sobre lo ya precargado.

        El CLUSTER de una pagina es el conjunto de URLs que anota mas ella
        misma. En un cluster bien hecho todas sus paginas declaran el mismo
        conjunto, asi que les sale la misma clave sin unir nada con nada: no
        hay componentes conexas que un enlace de «idioma no disponible -> la
        home» convierta en un cluster de medio sitio.

        *indexable* es el criterio de FUENTE (indexable e interna). Devuelve,
        por pagina sin autorreferencia, la clave de la variante con la que se
        anota a si misma, para no afirmar ademas que esa variante no le
        devuelve el enlace.

        *discrepantes*: ``(pagina, codigo)`` en los que las fuentes dan URLs
        distintas; eso es `hreflang_fuentes_discrepan` y no
        `hreflang_idioma_repetido`. *desconocida(pagina)*: su hreflang del
        sitemap no se leyo, y lo que le falte no se afirma (decision 167).
        """
        if desconocida is None:
            def desconocida(_uid):
                return False
        n_ej = self._EJEMPLOS_HREFLANG
        clusters: dict[str, list[int]] = defaultdict(list)
        cluster_de: dict[int, str] = {}
        sin_auto: list[tuple[int, tuple | None]] = []
        variante_de: dict[int, tuple] = {}

        for page_id, destinos in targets_by_page.items():
            if not indexable(page_id):
                continue
            yo = norm_by_id.get(page_id)
            if not yo:
                continue
            otros = destinos - {yo}
            if not otros:
                continue  # solo se anota a si misma: no hay cluster
            miembros = sorted(_url_de_clave(m) for m in destinos | {yo})
            clave = _clave_de_grupo("\n".join(miembros))
            clusters[clave].append(page_id)
            cluster_de[page_id] = clave

            # Autorreferencia: con cualquier codigo que no sea x-default. Si el
            # unico que apunta a ella es x-default, la pagina no dice en que
            # idioma esta.
            propios = codigos.get(page_id, {}).get(yo)
            autoref = yo in destinos and (
                propios is None or bool(propios - {"x-default"})
                # `propios is None`: se anota con un codigo invalido, que ya
                # tiene su aviso.
            )
            if autoref:
                continue
            # Se anota con una VARIANTE de si misma —la misma ruta con un
            # parametro, o con/sin barra final— que se canonicaliza a ella:
            # es su autorreferencia escrita con una URL no canonica, y ningun
            # mercado pierde su version (la pagina es indexable). El aviso es
            # este, no `hreflang_destino_no_indexable`, que diria con un
            # `error` que esa version desaparece (decision 99; medido: las 196
            # de penguin 30-jul eran esto). Una variante con OTRA ruta —`/de/`
            # canonicalizada a `/es/`— si es un mercado sin version, y sigue
            # siendo el error del destino.
            propias = sorted(
                d for d in otros
                if alias_de.get(d) == yo and _misma_ruta(d, yo)
                and (info_url[url_id_by_norm[d]][2] if d in url_id_by_norm
                     else None) == "Canonicalised"
                and (codigos.get(page_id, {}).get(d) is None
                     or bool(codigos[page_id][d] - {"x-default"}))
            )
            if propias:
                for d in propias:
                    fuentes = no_indexable.get(url_id_by_norm[d])
                    if fuentes is not None:
                        fuentes.pop(page_id, None)
                        if not fuentes:
                            del no_indexable[url_id_by_norm[d]]
                sin_auto.append((page_id, propias[0]))
            elif any(alias_de.get(d) == yo for d in otros):
                continue  # por otra URL que es ella: el aviso es el del destino
            else:
                sin_auto.append((page_id, None))

        for page_id, propia in sin_auto:
            if desconocida(page_id):
                continue
            yo = norm_by_id[page_id]
            otros = targets_by_page[page_id] - {yo}
            detalle = {"cluster": cluster_de[page_id], "alternativas": len(otros)}
            # Lo mas comun en los censos medidos: la pagina SI se anota, pero
            # con otra URL —la misma ruta con un parametro de tienda o de
            # pagina—, que para Google es otra URL. Se dice cual, porque el
            # arreglo es ese.
            variante = [propia] if propia else sorted(
                (d for d in otros if d[:3] == yo[:3]), key=_url_de_clave)
            if variante:
                detalle["variante_propia"] = _url_de_clave(variante[0])
                variante_de[page_id] = variante[0]
            self._add_issue(page_id, "hreflang_sin_autorreferencia", "warning",
                            detalle)

        def ejemplos(ids) -> list[str]:
            return sorted(url_by_id[i] for i in ids)[:n_ej]

        def ancla(ids) -> int:
            return min(ids, key=lambda i: url_by_id[i])

        # x-default: se decide por cluster —basta con que una de sus paginas
        # lo declare para no afirmar que falta— y se AVISA por host. Es una
        # decision de plantilla y casi siempre de todo el sitio: medido en el
        # censo de penguin del 30-jul, una fila por cluster eran 20.557 avisos
        # `info` diciendo una sola cosa (decision 64).
        sin_xd_por_host: dict[str, list[list[int]]] = defaultdict(list)
        clusters_por_host: dict[str, int] = defaultdict(int)
        esquema_de_host: dict[str, str] = {}
        for clave, paginas in clusters.items():
            # El host del cluster, elegido sin depender del orden de las filas
            # (la consulta no lleva ORDER BY y el UPDATE por lotes reescribe las
            # tuplas): con `paginas[0]`, un cluster que cruza hosts caia en uno
            # u otro segun el analisis, y la comparacion entre censos lo daba
            # por resuelto en uno y nuevo en el otro (decision 88).
            host, esquema = min((norm_by_id[p][1], norm_by_id[p][0]) for p in paginas)
            esquema_de_host.setdefault(host, esquema)
            clusters_por_host[host] += 1
            if any(desconocida(p) for p in paginas):
                continue  # el x-default puede estar en lo que no se leyo
            if not any("x-default" in cods
                       for p in paginas
                       for cods in codigos.get(p, {}).values()):
                sin_xd_por_host[host].append(paginas)
        for host, grupos in sorted(sin_xd_por_host.items()):
            todas = [p for g in grupos for p in g]
            # Anclado en la raiz del host si se rastreo: con la URL minima de
            # las afectadas, el hallazgo cambiaba de URL en cuanto se arreglaba
            # ese cluster o aparecia otro con una URL menor, y el diff lo
            # contaba como uno resuelto y uno nuevo estando abierto.
            # Si la raiz redirige (Lopesan: 302 a `/es/`; penguin: 301 a la
            # https), se ancla en la pagina a la que lleva: el 302 no es una
            # pagina HTML y la pestana Hreflang no lo ensenaba («1 pagina» en
            # el chip y la lista vacia).
            clave_raiz = _clave(f"{esquema_de_host[host]}://{host}/")
            vistas = {clave_raiz}
            while clave_raiz in salta_a and salta_a[clave_raiz] not in vistas:
                clave_raiz = salta_a[clave_raiz]
                vistas.add(clave_raiz)
            raiz = url_id_by_norm.get(clave_raiz)
            if raiz not in html_200:
                raiz = None
            self._add_issue(
                raiz if raiz is not None else ancla(todas),
                "hreflang_sin_x_default", "info",
                {"host": host,
                 "clusters_afectados": len(grupos),
                 "clusters_del_host": clusters_por_host[host],
                 "paginas_afectadas": len(todas),
                 "ejemplos": sorted(url_by_id[ancla(g)] for g in grupos)[:n_ej]},
                group_key=_clave_de_grupo(host),
            )

        for clave, paginas in clusters.items():
            # Mismo codigo -> varias URLs dentro del cluster.
            repetidos: dict[str, tuple[set[str], list[int]]] = {}
            for p in paginas:
                por_codigo: dict[str, set[str]] = defaultdict(set)
                for destino, cods in codigos.get(p, {}).items():
                    for c in cods:
                        if (p, c) not in discrepantes:
                            por_codigo[c].add(destino)
                for c, urls_c in por_codigo.items():
                    if len(urls_c) > 1:
                        urls_r, pags = repetidos.setdefault(c, (set(), []))
                        urls_r |= urls_c
                        pags.append(p)
            for c, (urls_r, pags) in sorted(repetidos.items()):
                self._add_issue(
                    ancla(pags), "hreflang_idioma_repetido", "warning",
                    {"lang": c, "urls": sorted(_url_de_clave(u) for u in urls_r)[:10],
                     "cuantas_urls": len(urls_r),
                     "paginas_afectadas": len(pags), "ejemplos": ejemplos(pags)},
                    group_key=_clave_de_grupo(f"{clave}|{c}"),
                )

        # Por ANOTACION y en la pagina que la escribe, como el destino roto
        # (`hreflang_broken_target`): `error` por lo mismo —Google descarta esa
        # alternativa y ese mercado se queda sin su version—, y la fila tiene
        # que estar en una pagina del sitio. Anclada en el destino, en
        # www.uoc.edu 9 de las 19 caian en URLs externas (`blogs.uoc.edu`,
        # `recerca.uoc.edu`) que la pestana Hreflang no ensena, y el arreglo
        # —apuntar el hreflang a la canonica, o quitar la canonicalizacion—
        # se decide mirando la pagina que anota.
        for destino_id, por_fuente in no_indexable.items():
            _sc, _idx, estado_idx, canonical = info_url[destino_id]
            for fuente_id, langs in por_fuente.items():
                for lang in sorted(langs):
                    detalle = {"href": url_by_id[destino_id], "lang": lang,
                               "motivo": estado_idx}
                    if canonical and estado_idx == "Canonicalised":
                        detalle["canonical"] = canonical
                    self._add_issue(
                        fuente_id, "hreflang_destino_no_indexable", "error",
                        detalle, group_key=_clave_de_grupo(lang),
                    )

        # Retorno incoherente: S anota D con un codigo, D devuelve el enlace a
        # S, pero D se declara a si misma con OTRO. Una vez por anotacion de S;
        # el caso simetrico (lo que D dice de S frente a lo que S dice de si
        # misma) sale cuando D es la fuente.
        for page_id in cluster_de:
            yo = norm_by_id[page_id]
            for destino, cods_s in codigos.get(page_id, {}).items():
                if destino == yo:
                    continue
                cods_s = cods_s - {"x-default"}
                if not cods_s:
                    continue
                d_id = url_id_by_norm.get(destino)
                if d_id is None or not indexable(d_id) or desconocida(d_id):
                    continue
                if yo not in targets_by_page.get(d_id, ()):
                    continue  # sin retorno: eso es `hreflang_missing_return`
                cods_d = codigos.get(d_id, {}).get(destino, set()) - {"x-default"}
                if not cods_d or cods_s & cods_d:
                    continue
                lang = ", ".join(sorted(cods_s))
                self._add_issue(
                    page_id, "hreflang_retorno_incoherente", "warning",
                    {"href": url_by_id[d_id], "lang": lang,
                     "lang_del_destino": sorted(cods_d)},
                    group_key=_clave_de_grupo(lang),
                )

        return variante_de

    # -- Structured Data ----------------------------------------------------

    def analyze_structured_data(self) -> None:
        """Validate structured data and surface errors/warnings.

        Nothing else populates ``validation_status``/``validation_issues``,
        so this computes them from each block's raw JSON (missing ``@type``
        or missing required properties for common rich-result types),
        persists the result, and raises the corresponding issues. Validation
        is deliberately conservative to avoid false positives.
        """
        logger.debug("Analyzing structured data ...")

        stmt = (
            select(
                StructuredData.id,
                StructuredData.url_id,
                StructuredData.schema_type,
                StructuredData.raw,
                StructuredData.json_invalido,
                Url.url,
            )
            .join(Url, Url.id == StructuredData.url_id)
            .where(Url.job_id == self.job_id)
        )
        rows = self.session.execute(stmt).all()

        # UNA incidencia por HALLAZGO, no por bloque. La misma cura que la
        # decision 64b aplico a las imagenes y la 53 a las cabeceras: un aviso
        # que sale en todas las paginas deja de ser un aviso.
        #
        # Un bloque de plantilla —el `Organization` del pie, la miga de pan— es
        # el MISMO en todo el sitio y se arregla una vez. Medido en tres
        # censos: penguin tiene **226.651 filas para 4 hallazgos distintos**,
        # Lopesan 11.186 para 13 y Saunier 288 para 7. En penguin eso es el 39%
        # de las incidencias del censo entero diciendo cuatro cosas.
        #
        # No se pierde nada: cada fila lleva cuantas paginas la llevan y hasta
        # cinco ejemplos, y `structured_data` conserva TODOS los bloques con su
        # validacion.
        # (url, url_id) de cada bloque: el ancla es la URL menor, no el id menor,
        # que depende del orden de rastreo (decision 88).
        por_hallazgo: dict[tuple, list[tuple[str, int]]] = {}
        # Los ids de bloque agrupados por veredicto, para no hacer un UPDATE
        # por bloque: en penguin eran 226.651 sentencias para escribir cuatro
        # valores distintos.
        por_veredicto: dict[tuple, list[int]] = {}

        for sd_id, url_id, schema_type, raw, json_invalido, page_url in rows:
            problemas = problemas_structured_data(raw, json_invalido=json_invalido)
            niveles = {n for n, _ in problemas}
            status = next(
                (n for n in ("error", "warning", "info") if n in niveles), "ok"
            )
            issues = [m for _, m in problemas]
            clave = (status, json.dumps(issues or None, sort_keys=True))
            por_veredicto.setdefault(clave, []).append(sd_id)
            # El bloque se queda con el PEOR nivel, pero el aviso de «resultado
            # retirado» (decision 97) es su propio hallazgo. Si no, un FAQPage
            # anidado en un bloque al que le falta una recomendada se emitia
            # como `structured_data_warning` con el aviso dentro, sin ninguna
            # `structured_data_info` para esa pagina; y el «falta tal
            # recomendada» se partia en dos grupos segun la pagina llevara FAQ
            # o no (decision 73: un aviso por hallazgo). Errores y warnings del
            # mismo bloque siguen juntos, como siempre: son el mismo marcado
            # que arreglar.
            resto = tuple(m for n, m in problemas if n != "info")
            retirados = tuple(m for n, m in problemas if n == "info")
            if resto:
                nivel = "error" if "error" in niveles else "warning"
                por_hallazgo.setdefault((nivel, schema_type, resto), []).append((page_url, url_id))
            if retirados:
                por_hallazgo.setdefault(("info", schema_type, retirados), []).append(
                    (page_url, url_id))

        for (status, issues_json), ids in por_veredicto.items():
            valores = {"validation_status": status,
                       "validation_issues": json.loads(issues_json)}
            for i in range(0, len(ids), 5000):
                self.session.execute(
                    update(StructuredData)
                    .where(StructuredData.id.in_(ids[i:i + 5000]))
                    .values(**valores)
                )

        for (status, schema_type, issues), paginas in por_hallazgo.items():
            paginas.sort()
            self._add_issue(
                paginas[0][1],
                f"structured_data_{status}",
                status,
                group_key=_clave_de_grupo(f"{schema_type}|" + "|".join(issues)),
                details={
                    "schema_type": schema_type,
                    "validation_issues": list(issues),
                    "paginas_afectadas": len(paginas),
                    "paginas_ejemplo": _ejemplos_por_url(paginas),
                },
            )

        self.session.flush()
        self._flush_issues()

    # -- HTML que Google trunca o ignora (decision 102) ---------------------

    # Los que tienen su propio aviso cuando estan en el body sin que se haya
    # cortado el head (`canonical_in_body`, `hreflang_in_body`).
    _CON_AVISO_PROPIO = frozenset({"canonical", "hreflang"})
    # Lo que, quedando detras del corte, decide si la pagina entra en el
    # indice o cual de sus variantes (decision 64: la severidad es la
    # consecuencia).
    _PERDIDA_GRAVE = frozenset({"robots", "googlebot", "canonical"})

    def analyze_html_ignorado(self) -> None:
        """HTML que Googlebot no llega a leer: mas de 2 MB o un head cortado.

        Tres tipos, todos sobre paginas HTML internas que responden 2xx:

        - ``html_supera_2mb`` (por pagina, solo indexables): Googlebot corta la
          descarga en los 2 MB del HTML descomprimido e indexa lo que tenga.
          El tamano sale de ``html_bytes_servidos``; en un censo anterior a la
          columna y SIN render, del mayor de ``content_length`` y
          ``transfer_size`` (la decision 50 los cambio de sitio el 2026-10-07 y
          el mayor es el descomprimido en las dos epocas). Con render y sin la
          columna no se sabe —``content_length`` es el DOM montado— y no se
          afirma nada.
        - ``head_cortado`` (agrupado): un elemento que no va en el head lo
          cerro antes de tiempo y algun metadato quedo detras, en el body.
          Google: "it assumes the end of the <head> element and stops reading".
          Severidad por lo que se pierde (decision 64): ``error`` si queda
          detras el robots, el googlebot o el canonical —la pagina puede
          acabar dentro o fuera del indice al reves de lo que pide—, y
          ``warning`` si solo titulo, description o hreflang.
        - ``meta_fuera_del_head`` (agrupado, ``info``): titulo, description o
          robots en el body sin que nada cortara el head. Google documenta que
          van en el head y no dice que hace con ellos fuera, y hay frameworks
          que los sirven ahi a proposito (Next.js 15.2+ con streaming metadata
          los sube al head con JavaScript, y documenta que Googlebot los lee):
          un dato que mirar, no un fallo afirmado.

        Los dos ultimos necesitan las columnas de la decision 102, que solo
        rellena un rastreo SIN render (con render el DOM serializado ya no
        conserva el corte; el spider las deja a NULL). En un censo anterior, o
        con render, no se emiten.
        """
        logger.debug("Analyzing HTML que Google trunca o ignora ...")
        base = (
            Url.job_id == self.job_id,
            Url.is_html.is_(True),
            Url.is_internal.is_(True),
            Url.status_code >= 200,
            Url.status_code < 300,
            # El HTML de un muro no es el de la pagina (decision 103).
            _respuesta_valida(),
        )

        # -- Mas de 2 MB --------------------------------------------------
        limite = GOOGLEBOT_HTML_MAX_BYTES
        sin_medir = 0
        for url_id, servidos, content_length, transfer_size in self.session.execute(
            select(Url.id, Url.html_bytes_servidos, Url.content_length,
                   Url.transfer_size)
            .where(*base, Url.indexable.is_(True))
        ):
            if servidos is not None:
                tamano, fuente = servidos, "html_bytes_servidos"
            elif not self._render_js:
                tamano = max(content_length or 0, transfer_size or 0) or None
                fuente = "cuerpo_descargado"
            else:
                tamano = None
            if tamano is None:
                sin_medir += 1
                continue
            if tamano > limite:
                self._add_issue(
                    url_id, "html_supera_2mb", "warning",
                    {"bytes": tamano, "limite_bytes": limite,
                     "bytes_sin_leer": tamano - limite,
                     "pct_sin_leer": round(100 * (tamano - limite) / tamano, 1),
                     "fuente": fuente},
                )
        if sin_medir:
            logger.warning(
                "html_supera_2mb: %d paginas indexables sin el tamano del HTML "
                "servido (rastreo con render anterior a la decision 102); no se "
                "afirma nada de ellas. Hay que re-rastrear.", sin_medir)

        # -- Head cortado y metadatos en el body ----------------------------
        if self._render_js:
            # El DOM montado no dice si el head se corto: lo que el navegador
            # movio al body pareceria «fuera del head sin corte» (102).
            self._flush_issues()
            return
        filas = self.session.execute(
            select(Url.id, HtmlMeta.head_cortado_por, HtmlMeta.fuera_del_head,
                   HtmlMeta.title_count, HtmlMeta.meta_description_count, Url.url)
            .join(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(*base, HtmlMeta.fuera_del_head.isnot(None),
                   HtmlMeta.fuera_del_head != "")
        ).all()
        # (url, url_id): anclados en la URL menor, no en el id menor (88).
        cortados: dict[tuple, list[tuple[str, int]]] = {}
        en_body: dict[tuple, list[tuple[str, int]]] = {}
        for url_id, cortado_por, fuera, n_titulos, n_descripciones, page_url in filas:
            perdidos = tuple(_fuera_del_head(fuera))
            if cortado_por:
                cortados.setdefault((cortado_por, perdidos), []).append((page_url, url_id))
                continue
            # Un segundo <title> o una segunda description en el body, con el
            # bueno en el head, ya es `title_multiple` / `description_multiple`:
            # un aviso por hallazgo (36). Medido en penguin: las 552 paginas
            # `/fragmento` incrustan un capitulo EPUB entero, con su propio
            # `<head><title>cap-2</title>`, dentro del body.
            ya_dicho = set(self._CON_AVISO_PROPIO)
            if (n_titulos or 0) > 1:
                ya_dicho.add("title")
            if (n_descripciones or 0) > 1:
                ya_dicho.add("description")
            propios = tuple(p for p in perdidos if p not in ya_dicho)
            if propios:
                en_body.setdefault(propios, []).append((page_url, url_id))

        for (cortado_por, perdidos), paginas in cortados.items():
            grave = bool(self._PERDIDA_GRAVE.intersection(perdidos))
            paginas.sort()
            self._add_issue(
                paginas[0][1], "head_cortado", "error" if grave else "warning",
                {"cortado_por": cortado_por,
                 "fuera_del_head": list(perdidos),
                 # El estado de indexabilidad del crawler sigue leyendo el
                 # robots que quedo en el body como si contara: no esta
                 # comprobado que Google lo ignore ahi, y cambiarlo sin medir
                 # sacaria o meteria paginas del indice. Lo que se afirma es
                 # que la directiva esta donde Google deja de leer.
                 "directiva_en_duda": grave,
                 "paginas_afectadas": len(paginas),
                 "paginas_ejemplo": _ejemplos_por_url(paginas)},
                group_key=_clave_de_grupo(f"{cortado_por}|" + ",".join(perdidos)),
            )
        for perdidos, paginas in en_body.items():
            paginas.sort()
            self._add_issue(
                paginas[0][1], "meta_fuera_del_head", "info",
                {"fuera_del_head": list(perdidos),
                 "paginas_afectadas": len(paginas),
                 "paginas_ejemplo": _ejemplos_por_url(paginas)},
                group_key=_clave_de_grupo(",".join(perdidos)),
            )
        self._flush_issues()

    # -- Indexability --------------------------------------------------------

    def analyze_indexability(self) -> None:
        """Determine indexability and flag noindex pages.

        A URL is considered indexable when all of the following hold:

        1. HTTP status is 200.
        2. Neither ``meta_robots`` nor ``x_robots_tag`` contain "noindex".
        3. The canonical is either absent or self-referencing.
        """
        logger.debug("Analyzing indexability ...")

        # LEFT JOIN y sin filtrar por is_html a proposito: con INNER JOIN solo
        # entraban las paginas HTML que llegaron a tener metadatos, y todo lo
        # demas —404, redirecciones, PDFs, imagenes— se quedaba en NULL en vez
        # de en False. Medido: 4.899 de 34.704 filas de un rastreo sin valor,
        # con `indexability_status` diciendo "Client Error (404)" al lado. El
        # filtro ?indexable=false de la API las perdia y el CSV las dejaba en
        # blanco, que se lee como "no se sabe".
        stmt = (
            select(
                Url.id,
                Url.url,
                Url.status_code,
                Url.indexability_status,
                Url.blocked_by_robots,
                Url.response_class,
                HtmlMeta.meta_robots,
                HtmlMeta.meta_robots_googlebot,
                HtmlMeta.x_robots_tag,
                HtmlMeta.canonical_href,
                HtmlMeta.canonical_header,
                HtmlMeta.canonical_distintos,
            )
            .outerjoin(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(Url.job_id == self.job_id)
        )
        rows = self.session.execute(stmt).all()

        indexable_ids: list[int] = []
        non_indexable_ids: list[int] = []
        # Se materializa el `noindex` aparte: de el depende si los enlaces de
        # esa pagina cuentan como entrantes (C3 de #24), y no se puede deducir
        # en SQL sin tokenizar la directiva (decision 23: `noindex/nofollow`
        # separado por barra NO es noindex, y buscar la subcadena lo seria).
        noindex_ids: list[int] = []
        con_indice_ids: list[int] = []

        # Motivos que decide esta funcion. Los demas ("Redirect (301)",
        # "Client Error (404)"...) los escribe el rastreo con el codigo exacto
        # y se respetan tal cual: aqui solo se corrigen los de una pagina 200.
        _MOTIVOS_PROPIOS = {"Indexable", "Canonicalised", "Noindex"}
        estados_por_motivo: dict[str, list[int]] = {}

        robots = getattr(self, "_robots", None)
        for (
            url_id,
            page_url,
            status_code,
            estado_actual,
            bloqueada_robots,
            clase_respuesta,
            meta_robots_generico,
            meta_robots_googlebot,
            x_robots,
            canonical_href,
            canonical_header,
            canonical_distintos,
        ) in rows:
            # Lo que hizo el rastreo, y lo que puede pedir Googlebot segun el
            # robots.txt guardado (decision 113). Si se sabe, manda Googlebot:
            # una pagina que rastreamos y Google no puede pedir no es indexable.
            bloqueada_rastreo = bool(bloqueada_robots) or (estado_actual or "").startswith("Blocked")
            # Para comparar, solo lo que decidio el RASTREO: el «Blocked» que
            # escribe este mismo paso en una pagina que si se pidio no cuenta,
            # o re-analizar se compararia consigo mismo.
            bloqueada_g = (self._veredicto_googlebot(
                url_id, page_url,
                bool(bloqueada_robots) or (status_code is None and bloqueada_rastreo))
                if robots else None)
            # Una sola funcion, la misma que usa el spider
            # (shared/indexabilidad.py). Antes aqui se repetian las reglas con
            # otro normalizador de URLs —w3lib, que no quita el puerto por
            # defecto— y la misma pagina salia "Canonicalised" para el analyzer
            # e "Indexable" para el spider.
            #
            # Y con los MISMOS datos que el spider: antes aqui no llegaban ni el
            # `<meta name="googlebot">` ni el canonical de la cabecera `Link`,
            # asi que una pagina que el rastreo marcaba "Noindex" o
            # "Canonicalised" por cualquiera de los dos volvia a "Indexable" al
            # analizar, porque este paso reescribe la columna en todas (#26).
            meta_robots = {
                "robots": meta_robots_generico,
                "googlebot": meta_robots_googlebot,
            }
            es_indexable_calc, motivo_calc = estado_indexabilidad(
                status_code,
                meta_robots=meta_robots,
                x_robots=x_robots,
                canonical_href=canonical_href,
                canonical_header=canonical_header,
                page_url=page_url,
                bloqueada_por_robots=(bloqueada_rastreo if bloqueada_g is None
                                      else bloqueada_g),
                response_class=clase_respuesta,
                canonicals_distintos=canonical_distintos,
            )
            has_noindex = es_noindex(meta_robots=meta_robots, x_robots=x_robots)
            canonical_ok = motivo_calc != "Canonicalised"
            # Bloqueada por robots.txt no es indexable por mucho que el
            # servidor devolviera 200: el rastreo la alcanzo por el destino de
            # una redireccion, Google no. Sin esto quedaban 22 paginas de un
            # SSO marcadas indexables con el motivo "Blocked by robots.txt" al
            # lado, las dos columnas diciendo lo contrario.
            is_indexable = es_indexable_calc
            # Una meta refresh es una redireccion, aunque responda 200: el
            # estado decia «Redirect (meta refresh)» y la columna `indexable`
            # true, y asi entraba en los titulos duplicados y en
            # `canonical_missing` (B2 de #150, decision 120). Como un 3xx.
            if estado_actual == ESTADO_META_REFRESH:
                is_indexable = False

            if is_indexable:
                indexable_ids.append(url_id)
            else:
                non_indexable_ids.append(url_id)

            (noindex_ids if has_noindex else con_indice_ids).append(url_id)
            if has_noindex:
                self._add_issue(url_id, "noindex_page", "info")
            elif is_indexable and status_code == 200:
                self._avisar_fragmento(url_id, meta_robots, x_robots)

            # El motivo tambien se recalcula aqui, y no solo en el rastreo.
            # El spider lo computaba contra la URL de PARTIDA de una cadena de
            # redirecciones mientras guardaba la de destino: toda pagina
            # alcanzada por un 301 salia como "Canonicalised" con un canonical
            # identico a su propia URL (1.254 de 34.704 en un rastreo medido, y
            # 1.329 en otro; el 100% llegadas por redireccion). Arreglado en el
            # spider, pero los rastreos ya guardados solo se reparan desde
            # aqui: re-analizar un job corrige el dato. Ademas evita que las
            # dos columnas del mismo CSV se contradigan.
            # El «Blocked by robots.txt» del rastreo de una pagina que SI se
            # pidio (modo audit) se recalcula si Googlebot puede pedirla.
            recalcular = (estado_actual is None or estado_actual in _MOTIVOS_PROPIOS
                          or (bloqueada_g is not None and status_code is not None
                              and estado_actual == "Blocked by robots.txt"))
            if recalcular:
                if motivo_calc and motivo_calc != estado_actual:
                    estados_por_motivo.setdefault(motivo_calc, []).append(url_id)

        # Bulk-update the indexable column.
        self._bulk_update_indexable(indexable_ids, True)
        self._bulk_update_indexable(non_indexable_ids, False)
        self._bulk_update_campo(noindex_ids, Url.noindex, True)
        self._bulk_update_campo(con_indice_ids, Url.noindex, False)
        for motivo, ids in estados_por_motivo.items():
            self._bulk_update_estado(ids, motivo)
            logger.info("indexability_status corregido a %r en %d URLs", motivo, len(ids))
        if robots:
            self._cerrar_robots_googlebot()

        self._flush_issues()

    def _avisar_fragmento(self, url_id: int, meta_robots, x_robots) -> None:
        """Decision 137: lo que una pagina indexable le niega al fragmento y,
        con el, a las funciones de IA de la busqueda (AI Overviews, AI Mode),
        que segun Google se controlan con las MISMAS directivas. Solo en
        indexables: en una noindex no hay resultado que recortar."""
        sin_fragmento, maximo = limite_de_fragmento(meta_robots=meta_robots, x_robots=x_robots)
        if sin_fragmento:
            self._add_issue(url_id, "nosnippet_en_indexable", "warning",
                            {"directiva": "max-snippet:0" if maximo == 0 else "nosnippet"})
        elif maximo is not None and maximo < MAX_SNIPPET_CORTO:
            self._add_issue(url_id, "max_snippet_restrictivo", "info", {"max_snippet": maximo})

    # -- robots.txt (decisiones 112 y 113) -----------------------------------

    def analyze_robots_txt(self) -> None:
        """Un aviso por host cuyo robots.txt respondio 5xx, 429 o no respondio.

        Para Google eso es el sitio entero bloqueado mientras dure (y los
        errores de red cuentan como 5xx); Scrapy lo trataba como «todo
        permitido» sin que quedara rastro. El rastreo sigue pidiendo las URLs
        del host (decision 112): el aviso es un hallazgo del sitio, no un fallo
        del dato, y la indexabilidad no cambia por el (no sabemos si Google
        tiene copia en cache ni si el fallo fue pasajero).

        - `error` si fallo tambien la comprobacion al cerrar, o no la hubo;
          `warning` si a la segunda respondio (intermitente) o si es un 429,
          que suele ser un limite para nuestra IP y no para Googlebot.
        - 4xx (salvo 429): nada, es «todo permitido» tambien para Google. Un
          muro delante (403 de Cloudflare): nada, no se ha visto el robots.txt.
        - Una fila por host, anclada en la raiz si se rastreo y si no en la URL
          MENOR de ese host. Nunca la de id mas bajo: el id sigue al orden de
          rastreo, y el mismo aviso saldria resuelto y nuevo a la vez al
          comparar dos censos (decision 88).
        """
        from analysis.robots_txt import RobotsDelJob, estado_de_comprobacion, estado_de_fila
        from shared.models import Job
        from shared.robots_txt import INACCESIBLE, PROCESADO, SIN_RESTRICCIONES, limitado

        self._robots = None
        try:
            # En un SAVEPOINT: sin la tabla (una base sin migrar) el analisis
            # sigue como antes, sin robots.txt, y no se pierde lo ya escrito.
            with self.session.begin_nested():
                self._robots = RobotsDelJob(self.session, self.job_id)
        except Exception:  # noqa: BLE001
            logger.warning("No se pudo leer robots_txt del job %s; se analiza sin el",
                           self.job_id, exc_info=True)
            return
        self._robots_conteo: dict[str, dict[str, Any]] = {}
        self._robots_googlebot: dict[bool, list[int]] = {True: [], False: []}
        self._robots_anclas: dict[str, int | None] = {}
        job = self.session.query(Job).filter(Job.id == self.job_id).one_or_none()
        config = (job.config or {}) if job else {}
        self._robots_mode = config.get("robots_mode", "respect")
        self._robots_ua = config.get("user_agent") or None
        # La muestra por plantilla con la que se evaluan los demas bots (129).
        from analysis.robots_txt import MuestraPorPlantilla

        self._robots_muestra = MuestraPorPlantilla(config.get("templates"))
        for o, fila in self._robots.filas.items():
            if estado_de_fila(fila) != INACCESIBLE:
                continue
            ancla = self._ancla_de_origen(o)
            if ancla is None:
                continue
            segundo = estado_de_comprobacion(fila)
            intermitente = segundo in (PROCESADO, SIN_RESTRICCIONES)
            lim = limitado(fila.status_code, fila.response_class)
            self._add_issue(
                ancla, "robots_txt_inaccesible",
                "warning" if intermitente or lim else "error",
                {"host": fila.host, "url": fila.url, "status_code": fila.status_code,
                 "error": fila.error, "intentos": fila.intentos,
                 "response_class": fila.response_class,
                 "comprobacion": fila.comprobacion,
                 "intermitente": intermitente, "limitado": lim},
                group_key=_clave_de_grupo(o),
            )
        self._flush_issues()

    def _ancla_de_origen(self, o: str) -> int | None:
        """La URL del censo en la que se cuelga un aviso de un host."""
        if o in self._robots_anclas:
            return self._robots_anclas[o]
        partes = urlparse(o)
        filtro = (Url.job_id == self.job_id, Url.host == (partes.hostname or ""),
                  Url.scheme == partes.scheme)
        # Por URL y nunca por id: el id depende del orden de rastreo y la
        # comparacion entre censos casa por (tipo, url, group_key) (decision
        # 88); con el id menor, dos censos iguales rastreados en otro orden
        # darian el mismo aviso por resuelto y por nuevo a la vez.
        ancla = self.session.execute(
            select(Url.id).where(*filtro, Url.path.in_(["/", ""]))
            .order_by(Url.url, Url.id).limit(1)).scalar()
        if ancla is None:
            ancla = self.session.execute(
                select(Url.id).where(*filtro).order_by(Url.url, Url.id).limit(1)).scalar()
        self._robots_anclas[o] = ancla
        return ancla

    def _veredicto_googlebot(self, url_id: int, url: str, bloqueada_rastreo: bool) -> bool | None:
        """Si Googlebot tiene prohibida la URL; None = no evaluado."""
        o, permitida = self._robots.veredicto(url, BOT_POR_DEFECTO)
        if permitida is None:
            return None
        bloqueada = not permitida
        self._robots_googlebot[bloqueada].append(url_id)
        self._robots_muestra.anadir(o, url_id, url)
        c = self._robots_conteo.setdefault(o, {
            "evaluadas": 0, "bloqueadas": 0, "solo_rastreador": 0, "solo_googlebot": 0,
            "ejemplos_solo_rastreador": [], "ejemplos_solo_googlebot": []})
        c["evaluadas"] += 1
        c["bloqueadas"] += bloqueada
        # En `ignore` el rastreo no obedecio nada: no hay veredicto propio que
        # comparar. En `respect` lo bloqueado no se pidio; en `audit` se pidio
        # y quedo marcado. En los dos, `blocked_by_robots` es lo que decidio.
        if self._robots_mode in ("respect", "audit") and bloqueada != bloqueada_rastreo:
            clave = "solo_googlebot" if bloqueada else "solo_rastreador"
            c[clave] += 1
            # Las URLs menores, no las primeras que llegan: las filas vienen en
            # el orden de rastreo y dos censos iguales darian otra muestra.
            ejemplos = c["ejemplos_" + clave]
            if len(ejemplos) < self._MUESTRA_EJEMPLOS or url < ejemplos[-1]:
                bisect.insort(ejemplos, url)
                del ejemplos[self._MUESTRA_EJEMPLOS:]
        return bloqueada

    def _cerrar_robots_googlebot(self) -> None:
        """Escribe `urls.bloqueada_googlebot`, el resumen por host y el aviso.

        `robots_difiere_para_googlebot`: una fila por host donde el veredicto
        como Googlebot no es el de nuestro rastreo, con los dos contadores y
        ejemplos; nunca una por URL (decision 36).
        """
        from analysis.robots_txt import estado_evaluable, evaluar_bots
        from shared.models import RobotsTxt

        # Lo que dijera un analisis anterior se borra antes: con otro codigo
        # una URL puede pasar a «no evaluada».
        self.session.execute(
            update(Url).where(Url.job_id == self.job_id, Url.bloqueada_googlebot.isnot(None))
            .values(bloqueada_googlebot=None))
        for valor, ids in self._robots_googlebot.items():
            self._bulk_update_campo(ids, Url.bloqueada_googlebot, valor)
        for o, fila in self._robots.filas.items():
            c = self._robots_conteo.get(o)
            evaluacion = {
                BOT_POR_DEFECTO: {"estado": estado_evaluable(fila),
                                  "evaluadas": c["evaluadas"] if c else 0,
                                  "bloqueadas": c["bloqueadas"] if c else 0}}
            bots = self._evaluar_bots_de_origen(o, fila, evaluar_bots)
            if bots is not None:
                evaluacion["bots"] = bots
            self.session.execute(
                update(RobotsTxt).where(RobotsTxt.id == fila.id).values(evaluacion=evaluacion))
            if not c or not (c["solo_rastreador"] or c["solo_googlebot"]):
                continue
            ancla = self._ancla_de_origen(o)
            if ancla is None:
                continue
            self._add_issue(
                ancla, "robots_difiere_para_googlebot", "warning",
                {"host": fila.host, "url": fila.url, "bot": BOT_POR_DEFECTO,
                 "user_agent": self._robots_ua, "robots_mode": self._robots_mode,
                 "evaluadas": c["evaluadas"],
                 "solo_rastreador": c["solo_rastreador"],
                 "solo_googlebot": c["solo_googlebot"],
                 "ejemplos_solo_rastreador": c["ejemplos_solo_rastreador"],
                 "ejemplos_solo_googlebot": c["ejemplos_solo_googlebot"]},
                group_key=_clave_de_grupo(f"{o}|{BOT_POR_DEFECTO}"),
            )
        self.session.flush()

    def _evaluar_bots_de_origen(self, o: str, fila, evaluar_bots) -> dict | None:
        """Que bloquea cada bot en un host, y el aviso si es un buscador de IA.

        `bot_busqueda_ia_bloqueado` (info, uno por host) solo cuando un bot de
        BUSQUEDA de IA tiene cerrado el sitio entero: la home y toda la muestra.
        Bloquear uno de entrenamiento es una decision legitima del cliente y no
        saca de ninguna busqueda, asi que no avisa (decision 129).
        """
        from shared.robots_txt import BOTS_INFO, BUSQUEDA_IA

        ev = self._robots.evaluador(o)
        if ev is None:
            return None
        muestra = getattr(self, "_robots_muestra", None)
        plantillas = muestra.de(o) if muestra else {}
        try:
            bots = evaluar_bots(ev, o, plantillas, muestra.total(o) if muestra else 0)
        except Exception:  # noqa: BLE001 -- la tabla por bot no tumba el analisis
            logger.warning("No se pudo evaluar por bot el robots.txt de %s", o, exc_info=True)
            return None
        cerrados = [
            {"bot": b["bot"], "token": b["token"], "proveedor": b["proveedor"],
             "regla": bots[b["bot"]].get("regla_home")}
            for b in BOTS_INFO
            if b["tipo"] == BUSQUEDA_IA and bots.get(b["bot"], {}).get("alcance") == "todo"]
        if cerrados:
            ancla = self._ancla_de_origen(o)
            if ancla is not None:
                self._add_issue(
                    ancla, "bot_busqueda_ia_bloqueado", "info",
                    {"host": fila.host, "url": fila.url, "bots": cerrados,
                     # Con `*` cerrado tambien esta fuera Google, y eso cambia
                     # lo que hay que leer del aviso.
                     "googlebot_alcance": bots.get(BOT_POR_DEFECTO, {}).get("alcance"),
                     "evaluadas": bots[cerrados[0]["bot"]]["evaluadas"],
                     "plantillas": bots[cerrados[0]["bot"]]["plantillas"]},
                    group_key=_clave_de_grupo(f"{o}|busqueda_ia"),
                )
        return bots

    def _bulk_update_campo(self, url_ids: list[int], columna, valor) -> None:
        """Escribe una columna de `urls` por lotes."""
        for start in range(0, len(url_ids), BATCH_SIZE):
            batch = url_ids[start : start + BATCH_SIZE]
            self.session.execute(
                update(Url).where(Url.id.in_(batch)).values({columna: valor})
            )
        self.session.flush()

    def _bulk_update_estado(self, url_ids: list[int], estado: str) -> None:
        """Escribe ``Url.indexability_status`` por lotes."""
        for start in range(0, len(url_ids), BATCH_SIZE):
            batch = url_ids[start : start + BATCH_SIZE]
            self.session.execute(
                update(Url)
                .where(Url.id.in_(batch))
                .values(indexability_status=estado)
            )
        self.session.flush()

    # -- Sintaxis de las directivas robots -----------------------------------

    def analyze_robots_syntax(self) -> None:
        """Avisar de directivas robots pegadas con un separador invalido.

        ``content="noindex/nofollow"`` no es sintaxis valida: la oficial separa
        por comas. Google ignora lo que no reconoce, asi que esa pagina se
        indexa y sus enlaces se siguen. No se toca la indexabilidad calculada
        --interpretar la barra seria fabricar un bloqueo que el buscador no
        aplica-- pero se reporta, porque el hallazgo es justamente ese: el
        cliente cree tener un bloqueo que no funciona (decision 7 de CLAUDE.md,
        lo roto se reporta, no se filtra).

        La severidad depende de que directiva se este perdiendo: si es
        restrictiva (``noindex``, ``nofollow``...) hay una intencion que no se
        cumple; si es ``index/follow`` no se pierde nada, porque son el
        comportamiento por defecto.
        """
        logger.debug("Analyzing robots directive syntax ...")

        # Tambien los no HTML con `X-Robots-Tag`: un PDF solo puede llevar sus
        # directivas en la cabecera, y la fila de `html_meta` que guarda el
        # spider para ellos tiene solo eso (#107). De un no HTML se mira solo la
        # cabecera: sus meta robots no existen.
        stmt = (
            select(
                Url.id,
                Url.is_html,
                HtmlMeta.meta_robots,
                HtmlMeta.meta_robots_googlebot,
                HtmlMeta.x_robots_tag,
            )
            .join(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(Url.job_id == self.job_id,
                   (Url.is_html.is_(True)) | (HtmlMeta.x_robots_tag.isnot(None)))
        )

        for url_id, es_html, meta_robots, meta_googlebot, x_robots in self.session.execute(stmt):
            fuentes = (("meta_robots", meta_robots), ("meta_robots_googlebot", meta_googlebot),
                       ("x_robots_tag", x_robots)) if es_html else (("x_robots_tag", x_robots),)
            for fuente, valor in fuentes:
                # De las `X-Robots-Tag` solo se lee lo que va a Google, con el
                # mismo criterio que la indexabilidad (decision 107): una
                # `bingbot: noindex/nofollow` no le quita nada, y el prefijo
                # pegado (`googlebot:noindex/nofollow`) escondia el `noindex`.
                leido = x_robots_para_bot(valor) if fuente == "x_robots_tag" else valor
                problemas = robots_bad_separators(leido)
                if not problemas:
                    continue

                ignoradas = sorted(
                    {d for p in problemas for d in p["ignoradas"]}
                )
                self._add_issue(
                    url_id,
                    "robots_invalid_syntax",
                    "warning" if ignoradas else "info",
                    {
                        "source": fuente,
                        "raw": valor,
                        "tokens": [p["token"] for p in problemas],
                        "ignored_directives": ignoradas,
                    },
                )

        self._flush_issues()

    def _bulk_update_indexable(self, url_ids: list[int], value: bool) -> None:
        """Set ``Url.indexable`` for a list of URL ids in batches."""
        for start in range(0, len(url_ids), BATCH_SIZE):
            batch = url_ids[start : start + BATCH_SIZE]
            self.session.execute(
                update(Url)
                .where(Url.id.in_(batch))
                .values(indexable=value)
            )
        self.session.flush()

    # -- Duplicate Content --------------------------------------------------

    def analyze_duplicates(self) -> None:
        """Paginas que sirven EXACTAMENTE el mismo contenido.

        Se compara `content_hash` —el SHA-256 del contenido principal con la
        caja y los espacios normalizados— y no `body_hash`, que es el de los
        bytes de la respuesta: un token CSRF, un nonce de CSP o una marca de
        tiempo en el HTML bastaban para que dos paginas identicas tuvieran
        hashes distintos, asi que en un CMS moderno esto no encontraba nada.
        Google compara el contenido, no los bytes.

        Solo paginas indexables: dos variantes `?utm` o dos ordenaciones de un
        listado sirven el mismo contenido a proposito y estan canonicalizadas,
        de modo que no compiten con nadie. Lo que hay que ver es que dos URLs
        que Google SI puede posicionar sirvan lo mismo.

        Los rastreos anteriores a la columna no tienen `content_hash`: ahi se
        cae a `body_hash`, que es lo que habia.
        """
        logger.debug("Analyzing duplicate content ...")

        columna = Url.content_hash
        hay_content_hash = self.session.execute(
            select(func.count(Url.id)).where(
                Url.job_id == self.job_id, Url.content_hash.isnot(None)
            )
        ).scalar()
        if not hay_content_hash:
            columna = Url.body_hash
            logger.info(
                "El job no tiene content_hash (rastreo anterior a la columna): "
                "los duplicados exactos se miran sobre body_hash, que cambia "
                "con cualquier token de la pagina"
            )

        condiciones = (
            Url.job_id == self.job_id,
            columna.isnot(None),
            columna != "",
            Url.is_html.is_(True),
            Url.is_internal.is_(True),
            Url.status_code == 200,
            Url.indexable.is_(True),
        )

        dup_stmt = (
            select(columna)
            .where(*condiciones)
            .group_by(columna)
            .having(func.count(Url.id) > 1)
        )
        dup_hashes = [row[0] for row in self.session.execute(dup_stmt).all()]

        if not dup_hashes:
            self._flush_issues()
            return

        for hash_batch_start in range(0, len(dup_hashes), BATCH_SIZE):
            hash_batch = dup_hashes[hash_batch_start : hash_batch_start + BATCH_SIZE]

            rows = self.session.execute(
                select(Url.id, columna).where(*condiciones, columna.in_(hash_batch))
            ).all()

            hash_to_ids: dict[str, list[int]] = defaultdict(list)
            for url_id, valor in rows:
                hash_to_ids[valor].append(url_id)

            for valor, url_ids in hash_to_ids.items():
                if len(url_ids) < 2:
                    continue
                for uid in url_ids:
                    other_ids = [x for x in url_ids if x != uid]
                    self._add_issue(
                        uid,
                        "duplicate_content",
                        "warning",
                        self._detalle_duplicados(other_ids, content_hash=valor),
                        # El hash del contenido YA es la clave del grupo: no
                        # hace falta volver a resumirlo.
                        group_key=(valor or None),
                    )

        self._flush_issues()

    # -- Casi duplicados ----------------------------------------------------

    def analyze_near_duplicates(self) -> None:
        """Detectar paginas que comparten casi todo el texto.

        `analyze_duplicates` solo ve el duplicado byte-identico, que en un
        sitio real casi no existe: basta un precio distinto para que dos fichas
        clonadas dejen de parecerlo. Aqui se mide la similitud real del
        contenido (ver `analysis/near_duplicates.py`).

        Se mide sobre `page_content.content_text` --el contenido sin plantilla--
        y no sobre el body: con cabecera y pie dentro, todo el sitio saldria
        duplicado de todo. Y entre las mismas paginas que el duplicado exacto
        (`analyze_duplicates`, decision 47): internas, 200 HTML e indexables.
        Una variante canonicalizada comparte el texto con su canonica a
        proposito, una noindex o una externa no compite con nadie en el indice
        del cliente; medirlas daba la variante como casi duplicada de su propia
        canonica (decision 118).
        """
        logger.debug("Analyzing near-duplicate content ...")

        if self.near_duplicate_similarity < nd.UMBRAL_MINIMO_FIABLE:
            # Por debajo de ~0,6 el filtro por bandas empieza a dejarse parejas
            # y "casi duplicado" deja de querer decir gran cosa. Se avisa y se
            # mide igual: el umbral lo pone quien audita.
            logger.warning(
                "Umbral de casi duplicados muy bajo (%.2f): el recuento sera "
                "incompleto y poco significativo",
                self.near_duplicate_similarity,
            )

        firmas, urls = self.firmas_casi_duplicados()

        # Lo que no se mide en ESTE analisis queda en NULL ("no medido"), no con
        # el recuento de un analisis anterior: al re-analizar un censo, una
        # pagina que ahora es noindex, o cuyo texto ya no llega al minimo,
        # conservaba su `near_duplicate_count` viejo.
        medidas_antes = self.session.execute(
            select(Url.id).where(
                Url.job_id == self.job_id,
                or_(
                    Url.near_duplicate_count.isnot(None),
                    Url.closest_similarity.isnot(None),
                ),
            )
        ).scalars()
        self._bulk_update_near_duplicates(
            {uid: (None, None) for uid in medidas_antes if uid not in firmas}
        )

        if not firmas:
            return

        resultado = nd.analizar(firmas, self.near_duplicate_similarity)

        # Medida y sin ninguna es 0, no NULL: NULL queda para "no se pudo medir"
        # (sin contenido guardado, o texto por debajo del minimo de palabras).
        sin_duplicados = [uid for uid in firmas if uid not in resultado]
        self._bulk_update_near_duplicates(
            {uid: (0, None) for uid in sin_duplicados}
        )
        self._bulk_update_near_duplicates(
            {uid: (dato["count"], dato["closest"]) for uid, dato in resultado.items()}
        )

        # Sin `group_key` a proposito: un casi duplicado no pertenece a un
        # grupo estable, sino a un conjunto de parecidos que cambia con cada
        # censo. Inventar una clave aqui haria que el mismo problema pareciera
        # resolverse y reaparecer cada semana — exactamente la mentira que la
        # clave existe para evitar. La URL y el tipo ya lo identifican.
        for url_id, dato in resultado.items():
            self._add_issue(
                url_id,
                "near_duplicate_content",
                "warning",
                {
                    "count": dato["count"],
                    "closest_similarity": round(dato["closest"], 3),
                    "threshold": self.near_duplicate_similarity,
                    "matches": [
                        {"url": urls[otro], "similarity": round(s, 3)}
                        for otro, s in dato["ejemplos"]
                    ],
                },
            )

        self._flush_issues()

    def firmas_casi_duplicados(self) -> tuple[dict[int, Any], dict[int, str]]:
        """Firma MinHash y URL de cada pagina que entra en los casi duplicados.

        Las mismas condiciones que `analyze_duplicates`. La usa tambien el
        `--dry-run` de `scripts/near_duplicates.py`, para que la prevision y el
        analisis no midan conjuntos distintos.
        """
        stmt = (
            select(Url.id, Url.url, PageContent.content_text)
            .join(PageContent, PageContent.url_id == Url.id)
            .where(
                Url.job_id == self.job_id,
                Url.is_html.is_(True),
                Url.is_internal.is_(True),
                Url.status_code == 200,
                Url.indexable.is_(True),
            )
        )

        firmas: dict[int, Any] = {}
        urls: dict[int, str] = {}
        # `yield_per` importa: el texto de un censo grande no cabe en memoria de
        # golpe. De cada fila solo se queda la firma (256 bytes) y la URL.
        for url_id, url, texto in self.session.execute(
            stmt.execution_options(yield_per=BATCH_SIZE)
        ):
            f = nd.firma(texto)
            if f is None:
                continue
            firmas[url_id] = f
            urls[url_id] = url
        return firmas, urls

    def _bulk_update_near_duplicates(
        self, valores: dict[int, tuple[int | None, float | None]]
    ) -> None:
        """Guardar recuento y mejor similitud por URL, en lotes."""
        if not valores:
            return
        filas = [
            {
                "id": uid,
                "near_duplicate_count": cuenta,
                "closest_similarity": cercana,
            }
            for uid, (cuenta, cercana) in valores.items()
        ]
        for inicio in range(0, len(filas), BATCH_SIZE):
            lote = filas[inicio : inicio + BATCH_SIZE]
            # "ORM bulk UPDATE by primary key": sin WHERE y con `id` en cada
            # fila. Con un WHERE sobre un bindparam, SQLAlchemy 2.x lanza
            # InvalidRequestError y el analisis entero se caia aqui.
            self.session.execute(update(Url), lote)
        self.session.flush()

    # -- Redirect Chains ----------------------------------------------------

    def analyze_redirect_chains(self) -> None:
        """Cadenas de redireccion de dos saltos o mas, y bucles.

        Criterio SEO: una redireccion es normal; dos encadenadas ya son algo que
        arreglar —Google las sigue pero pierde parte de la senal y gasta
        presupuesto de rastreo—, y un bucle es un error. Lo que se reporta es la
        cadena entera, para que se vea donde cortarla.
        """
        logger.debug("Analyzing redirect chains ...")

        # Build an in-memory redirect graph: url -> redirect_url.
        stmt = select(Url.id, Url.url, Url.redirect_url, Url.is_internal).where(
            Url.job_id == self.job_id,
            Url.redirect_url.isnot(None),
            Url.redirect_url != "",
        )
        rows = self.session.execute(stmt).all()

        if not rows:
            return

        # url_string -> (url_id, redirect_target_string)
        redirect_map: dict[str, str] = {}
        url_to_id: dict[str, int] = {}
        internas: set[str] = set()
        for url_id, url_str, redirect_url, interna in rows:
            redirect_map[url_str] = redirect_url
            url_to_id[url_str] = url_id
            if interna:
                internas.add(url_str)

        # Donde acaba cada cadena: el codigo de la ultima URL (decision 101).
        estado_final = _estado_por_url(self.session, self.job_id)
        # Y si es una pagina 200 en `noindex` (decision 120). `Url.noindex` lo
        # acaba de escribir `analyze_indexability`, que va antes en `run_all`.
        finales_noindex = self._finales_noindex()
        # Destino noindex -> origenes que acaban en el.
        a_noindex: dict[int, list[dict[str, Any]]] = defaultdict(list)
        # Portada final -> origenes que acaban en ella (decision 228).
        a_portada: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # Los origenes cuyo aviso ya es el destino: su meta refresh no se avisa.
        con_aviso_de_destino: set[int] = set()

        # Walk each redirect origin and trace the chain. Primero el veredicto
        # de cada origen y luego los avisos: `redirect_chain` es UNO por cadena
        # (decision 117), y para saber si un origen es el primero de la suya
        # hay que conocer el de quien redirige a el.
        cadenas: dict[str, dict[str, Any]] = {}
        for origin_url in list(redirect_map.keys()):
            visited: list[str] = [origin_url]
            current = origin_url
            is_loop = False

            while current in redirect_map:
                target = redirect_map[current]
                if target in visited:
                    is_loop = True
                    break
                visited.append(target)
                current = target

            origin_id = url_to_id[origin_url]
            hops = len(visited) - 1  # number of redirects

            # Solo desde una URL interna: una cadena que empieza en otro sitio
            # (`http://research.uoc.edu/...` enlazada desde el censo) no es del
            # sitio auditado, y la pestana Redirecciones —que filtra por
            # interna— la contaba en el chip sin ensenarla en la lista. Lo que
            # el sitio puede hacer ahi es cambiar el enlace, y eso no es una
            # cadena suya. Mismo criterio que `redireccion_a_error`.
            if origin_url not in internas:
                continue

            if is_loop:
                self._add_issue(
                    origin_id,
                    "redirect_loop",
                    "error",
                    {"chain": visited + [redirect_map[current]]},
                )
                con_aviso_de_destino.add(origin_id)
                continue

            # Una redireccion (o una cadena) que acaba en un 4xx o un 5xx: el
            # usuario y Google llegan a un error, y lo que la URL vieja tenia de
            # senal se pierde. El 404 ya avisa en SU URL, pero el salto que
            # lleva a el no avisaba en ninguna: es otra regla que arreglar
            # —redirigir a una pagina que exista—. Un aviso por hallazgo: si
            # acaba en error, ese es el aviso y no tambien `redirect_chain`,
            # porque redirigir directo a una pagina buena arregla las dos.
            final_status = estado_final.get(current)
            if final_status is None:
                final_status = estado_final.get(_clave(current))
            # Mas de 10 saltos: Google no llega al final (decision 117), asi
            # que manda el limite aunque la cadena acabe en error —Google ni
            # llega a verlo—, en el mismo aviso con `final_status`. Una cadena
            # que el rastreo corto en MAX_SALTOS_SEGUIDOS acaba en una URL sin
            # rastrear: `final_status` None, y no se afirma ningun error.
            supera = hops > LIMITE_SALTOS_GOOGLE
            # Si el salto solo normaliza (http → https, www, barra final) la
            # redireccion esta bien hecha: el error es el destino, que ya
            # tiene su `4xx_error` / `5xx_error`. Medido en www.uoc.edu: 383 de
            # las 473 redirecciones de un salto que acababan en error eran
            # esto, casi todas el 307 de Chromium hacia https.
            if (not supera and _es_error(final_status)
                    and not _solo_normaliza(origin_url, current)):
                self._add_issue(
                    origin_id,
                    "redireccion_a_error",
                    "error",
                    {"chain": visited, "hops": hops, "final_status": final_status},
                )
                con_aviso_de_destino.add(origin_id)
            elif (not supera and final_status == 200
                    and (destino_noindex := _buscar_en(finales_noindex, current)) is not None
                    and not _solo_normaliza(origin_url, current)):
                # Acaba en una pagina que pide no estar en el indice: lo que la
                # URL vieja tenia de senal no llega a ninguna parte indexable.
                # Como `redireccion_a_error`, sustituye a `redirect_chain` (36),
                # y un http → https de una noindex es una normalizacion bien
                # hecha: el noindex es de la pagina y ya avisa en su URL.
                a_noindex[destino_noindex].append(
                    {"id": origin_id, "url": origin_url, "chain": visited, "hops": hops,
                     "final": current})
                con_aviso_de_destino.add(origin_id)
            elif (not supera and final_status == 200
                    and _redirige_a_portada(origin_url, current)):
                # Una pagina que redirige a la portada (#11, decision 228): lo
                # que habia en la URL vieja no tiene sustituto, y Google trata
                # ese salto como un soft 404. Como los de arriba, sustituye a
                # `redirect_chain`: redirigir a una sustituta arregla los dos.
                a_portada[current].append(
                    {"id": origin_id, "url": origin_url, "chain": visited, "hops": hops})
                con_aviso_de_destino.add(origin_id)
            elif supera or hops > self.max_redirect_chain:
                detalle: dict[str, Any] = {"chain": visited, "hops": hops}
                if supera:
                    detalle["supera_limite_google"] = True
                    detalle["final_status"] = final_status
                cadenas[origin_url] = {"id": origin_id, "detalle": detalle,
                                       "severidad": "error" if supera else "warning"}

        # Un aviso por cadena, en su primer origen. Cada origen intermedio de
        # A → B → C → D tambien es una cadena (B → C → D), y salia una fila por
        # cada uno: 11 avisos para una cadena de 12 saltos. El arreglo es una
        # regla del servidor —que todas salten directas a la final—, asi que
        # va en una fila, con las intermedias en `paginas_afectadas` (36, 64).
        # El primero es el origen al que no redirige ningun otro origen con
        # cadena: el anterior de una cadena siempre tiene mas saltos, asi que
        # si tambien la tiene, este va dentro de la suya.
        anterior_con_cadena = {
            destino for origen, destino in redirect_map.items() if origen in cadenas
        }
        intermedias: dict[str, list[str]] = defaultdict(list)
        primeros = [u for u in cadenas if u not in anterior_con_cadena]
        for primero in primeros:
            for url in cadenas[primero]["detalle"]["chain"][1:]:
                if url in cadenas:
                    intermedias[primero].append(url)
        for primero in primeros:
            c = cadenas[primero]
            otras = intermedias.get(primero, [])
            self._add_issue(
                c["id"], "redirect_chain", c["severidad"],
                {**c["detalle"], "paginas_afectadas": 1 + len(otras),
                 "intermedias": otras[:20]},
            )

        self._avisar_redireccion_a_noindex(a_noindex)
        self._avisar_redireccion_a_portada(a_portada)
        self._avisar_meta_refresh(con_aviso_de_destino)
        self._flush_issues()

    def _finales_noindex(self) -> dict[Any, int]:
        """Las paginas 200 en `noindex` del job, por URL y por clave -> id.
        Sin los muros: no dicen que hay detras (103)."""
        finales: dict[Any, int] = {}
        for uid, url in self.session.execute(
            select(Url.id, Url.url).where(
                Url.job_id == self.job_id, Url.status_code == 200,
                Url.noindex.is_(True), _respuesta_valida())
        ).all():
            finales[url] = uid
            k = _clave(url)
            if k is not None:
                finales.setdefault(k, uid)
        return finales

    def _avisar_redireccion_a_noindex(self, a_noindex: dict[int, list[dict[str, Any]]]) -> None:
        """`redireccion_a_noindex` (decision 120): por origen, o UNA fila en el
        destino cuando le llegan `enlaces_plantilla_min_paginas` redirecciones
        o mas —todo `/mi-cuenta/*` a `/login`—, que es una regla del servidor y
        casi siempre deliberada."""
        for destino_id, origenes in a_noindex.items():
            origenes.sort(key=lambda o: o["url"])
            if len(origenes) >= self.enlaces_plantilla_min_paginas:
                self._add_issue(
                    destino_id, "redireccion_a_noindex", "warning",
                    {"alcance": "destino", "final": origenes[0]["final"],
                     "redirecciones_que_llegan": len(origenes),
                     "ejemplos": [o["url"] for o in origenes[: self._MUESTRA_EJEMPLOS]]},
                    group_key=_clave_de_grupo(origenes[0]["final"]),
                )
                continue
            for o in origenes:
                self._add_issue(
                    o["id"], "redireccion_a_noindex", "warning",
                    {"alcance": "origen", "chain": o["chain"], "hops": o["hops"],
                     "final": o["final"]},
                )

    def _avisar_redireccion_a_portada(self, a_portada: dict[str, list[dict[str, Any]]]) -> None:
        """`redireccion_a_portada` (decision 228), con el reparto de
        `redireccion_a_noindex`: por origen, o UNA fila en la portada cuando le
        llegan `enlaces_plantilla_min_paginas` o mas —«todo lo borrado, a la
        home»—, que es una regla del servidor."""
        if not a_portada:
            return
        ids = dict(self.session.execute(
            select(Url.url, Url.id).where(Url.job_id == self.job_id,
                                          Url.url.in_(list(a_portada)))
        ).all())
        for final, origenes in a_portada.items():
            origenes.sort(key=lambda o: o["url"])
            if len(origenes) >= self.enlaces_plantilla_min_paginas and final in ids:
                self._add_issue(
                    ids[final], "redireccion_a_portada", "warning",
                    {"alcance": "destino", "final": final,
                     "redirecciones_que_llegan": len(origenes),
                     "paginas_afectadas": len(origenes),
                     "ejemplos": [o["url"] for o in origenes[: self._MUESTRA_EJEMPLOS]]},
                    group_key=_clave_de_grupo(final),
                )
                continue
            for o in origenes:
                self._add_issue(
                    o["id"], "redireccion_a_portada", "warning",
                    {"alcance": "origen", "chain": o["chain"], "hops": o["hops"],
                     "final": final},
                )

    def _avisar_meta_refresh(self, con_aviso_de_destino: set[int]) -> None:
        """`meta_refresh_redireccion` (decision 120).

        La fuente es el estado «Redirect (meta refresh)» con `redirect_url`,
        que el spider solo pone con un destino fuera de `<noscript>` y distinto
        de la propia URL: `html_meta.meta_refresh` no nulo no basta (una
        recarga `content="300"` o una refresh en `<noscript>` no redirigen,
        B5). Inmediata = `info` (Google la trata como permanente, pero pide la
        del servidor); con retardo = `warning` (la trata como temporal y puede
        quedarse con la de origen; el usuario ve la pagina N segundos). Sin
        `html_meta` —el salto que registra el render— el retardo no se sabe:
        `retardo_s` None, e `info`.

        Si la URL ya avisa de a donde acaba (error, noindex, bucle), ese es el
        aviso: redirigir bien desde el servidor arregla los dos (36). Con
        `redirect_chain` conviven: piden cosas distintas. Lo que lleva una
        plantilla entera va en una fila por (host, plantilla, tipo de retardo).
        """
        filas = self.session.execute(
            select(Url.id, Url.url, Url.host, Url.path, Url.redirect_url,
                   HtmlMeta.meta_refresh)
            .outerjoin(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(Url.job_id == self.job_id, Url.is_internal.is_(True),
                   Url.indexability_status == ESTADO_META_REFRESH,
                   Url.redirect_url.isnot(None), Url.redirect_url != "",
                   _respuesta_valida())
        ).all()
        grupos: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for uid, url, host, path, destino, content in filas:
            if uid in con_aviso_de_destino:
                continue
            retardo = retardo_meta_refresh(content)
            clase = ("desconocido" if retardo is None
                     else "inmediata" if retardo == 0 else "con_retardo")
            grupos[(host or "", firma_de_ruta(path or "/"), clase)].append(
                {"id": uid, "url": url, "destino": destino,
                 "retardo_s": None if retardo is None else (
                     int(retardo) if retardo == int(retardo) else retardo)})
        for (host, plantilla, clase), paginas in grupos.items():
            severidad = "warning" if clase == "con_retardo" else "info"
            paginas.sort(key=lambda p: p["url"])
            if len(paginas) >= self.enlaces_plantilla_min_paginas:
                p = paginas[0]
                self._add_issue(
                    p["id"], "meta_refresh_redireccion", severidad,
                    {"alcance": "plantilla", "host": host, "plantilla": plantilla,
                     "retardo_s": p["retardo_s"], "destino": p["destino"],
                     "paginas_afectadas": len(paginas),
                     "paginas_ejemplo": [x["url"] for x in paginas[: self._MUESTRA_EJEMPLOS]]},
                    group_key=_clave_de_grupo(f"{host}|{plantilla}|{clase}"),
                )
                continue
            for p in paginas:
                self._add_issue(
                    p["id"], "meta_refresh_redireccion", severidad,
                    {"alcance": "pagina", "retardo_s": p["retardo_s"],
                     "destino": p["destino"]},
                )

    # -- Images -------------------------------------------------------------

    def analyze_images(self) -> None:
        """Flag images that are missing alt text."""
        logger.debug("Analyzing images ...")

        stmt = (
            select(Resource.url_id, Resource.resource_url, Url.url)
            .join(Url, Url.id == Resource.url_id)
            .where(
                Url.job_id == self.job_id,
                Resource.resource_type == "image",
                # Solo cuando falta el atributo. Un alt="" declara la imagen
                # como decorativa y es lo correcto segun WCAG para iconos y
                # adornos: marcarlo como error generaba falsos positivos en
                # masa (medido en un sitio real: 791.455 avisos, el 94% del
                # total de incidencias del rastreo).
                Resource.alt_text.is_(None),
                # Un 1x1 es un pixel de seguimiento o un espaciador, nunca
                # contenido: no hay nada que describir en el y el aviso solo
                # tapa las imagenes de verdad.
                or_(
                    Resource.width.is_(None), Resource.height.is_(None),
                    Resource.width > 1, Resource.height > 1,
                ),
            )
        )
        rows = self.session.execute(stmt).all()

        # UNA incidencia por IMAGEN, no por aparicion. La unidad de trabajo es
        # la imagen: ponerle el alt al logo del pie se hace una vez, no 10.990
        # —que es las veces que salia en el informe de un cliente, repartido en
        # cinco variantes responsive del MISMO logo—. Es la misma cura que la
        # decision 53 aplico a las cabeceras de seguridad.
        #
        # Medido sobre cinco censos: 287.175 -> 19.287 avisos (-93%) en el peor,
        # y entre el 30% y el 75% menos en los otros cuatro. No se pierde nada:
        # la fila va con cuantas paginas la llevan y un ejemplo, y `resources`
        # sigue teniendo todas las apariciones.
        # Anclada en la pagina de URL menor que la lleva, no en la de id menor:
        # el id depende del orden de rastreo y la comparacion entre censos casa
        # por (tipo, url, group_key) (decision 88).
        #
        # La imagen es su URL SIN los parametros de version que pone el CMS
        # (`?t=1778841841031`, `&version=3.3`): en Lopesan, 10 de las 242
        # imagenes sin alt «resueltas» entre dos censos seguian igual y solo
        # habia cambiado el `t`, y salian a la vez como nuevas (#32).
        por_imagen: dict[str, list[int]] = {}
        ancla_de_imagen: dict[str, tuple[str, int, str]] = {}
        for url_id, resource_url, page_url in rows:
            imagen = _url_sin_version(resource_url)
            por_imagen.setdefault(imagen, []).append(url_id)
            actual = ancla_de_imagen.get(imagen)
            if actual is None or (page_url, url_id) < actual[:2]:
                ancla_de_imagen[imagen] = (page_url, url_id, resource_url)

        for imagen, paginas in por_imagen.items():
            self._add_issue(
                ancla_de_imagen[imagen][1],
                "image_missing_alt",
                "warning",
                {
                    "image_url": ancla_de_imagen[imagen][2],
                    "paginas_afectadas": len(set(paginas)),
                },
                group_key=_clave_de_grupo(imagen),
            )

        self._flush_issues()

    # -- Security -----------------------------------------------------------

    def analyze_security(self) -> None:
        """Seguridad: lo que decide algo por pagina, por pagina; lo demas, una vez.

        Criterio SEO: HTTPS es senal de ranking y el contenido mixto rompe el
        candado y puede bloquear recursos, asi que esos dos son problemas DE LA
        PAGINA. Las cabeceras de seguridad (HSTS, CSP, X-Frame-Options,
        X-Content-Type-Options) no afectan al posicionamiento y, sobre todo, son
        una propiedad del SERVIDOR: la misma respuesta en las 29.808 paginas del
        sitio. Emitirlas por pagina multiplicaba el recuento sin anadir nada —
        medido en los censos guardados: 131.096 avisos de `unsafe_crossorigin`,
        93.545 de `missing_csp` y 41.863 de `missing_x_frame_options`— y tapaba
        los hallazgos reales. Ahora va UN aviso por host, con el numero de
        paginas en los detalles.

        `unsafe_crossorigin` desaparece: desde 2021 todos los navegadores
        aplican `noopener` por defecto a `target="_blank"`, asi que no hay nada
        que arreglar. Era el aviso mas numeroso de todos.
        """
        logger.debug("Analyzing security ...")

        stmt = (
            select(
                Url.id,
                Url.host,
                Url.url,
                SecurityHeaders.is_https,
                SecurityHeaders.has_mixed_content,
                SecurityHeaders.has_hsts,
                SecurityHeaders.has_csp,
                SecurityHeaders.has_x_content_type_options,
                SecurityHeaders.has_x_frame_options,
            )
            .join(SecurityHeaders, SecurityHeaders.url_id == Url.id)
            .where(Url.job_id == self.job_id)
        )
        rows = self.session.execute(stmt).all()

        # Por host: paginas, paginas sin cada cabecera y el ancla de cada tipo.
        por_host: dict[str, dict] = {}

        for (
            url_id,
            host,
            page_url,
            is_https,
            has_mixed_content,
            has_hsts,
            has_csp,
            has_x_content_type_options,
            has_x_frame_options,
        ) in rows:
            # HTTP URL (scheme != "https"). Es de la pagina: esa URL concreta
            # va sin cifrar y es la que hay que redirigir.
            if is_https is False:
                self._add_issue(url_id, "http_url", "warning")

            # Mixed content (HTTPS page loading HTTP resources). Tambien es de
            # la pagina: depende de lo que esa pagina incruste.
            if has_mixed_content is True:
                self._add_issue(url_id, "mixed_content", "warning")

            resumen = por_host.setdefault(
                host or "", {"paginas": 0, "anclas": {},
                             "missing_hsts": 0, "missing_csp": 0,
                             "missing_x_content_type_options": 0,
                             "missing_x_frame_options": 0}
            )
            resumen["paginas"] += 1
            faltan = []
            # HSTS solo tiene sentido sobre https: en http el navegador ignora
            # la cabecera, asi que avisarlo ahi era pedir algo que no aplica.
            if has_hsts is False and is_https is not False:
                faltan.append("missing_hsts")
            if has_csp is False:
                faltan.append("missing_csp")
            if has_x_content_type_options is False:
                faltan.append("missing_x_content_type_options")
            if has_x_frame_options is False:
                faltan.append("missing_x_frame_options")
            for tipo in faltan:
                resumen[tipo] += 1
                # El ancla de cada tipo es la URL menor de las paginas a las que
                # les FALTA esa cabecera: no la primera fila leida, que sigue al
                # orden de rastreo (decision 88), ni la menor del host, que con
                # una pagina en http (`http://` < `https://`) dejaba
                # `missing_hsts` anclado justo donde HSTS no aplica.
                actual = resumen["anclas"].get(tipo)
                if actual is None or (page_url, url_id) < actual:
                    resumen["anclas"][tipo] = (page_url, url_id)

        for host, resumen in por_host.items():
            for tipo in ("missing_hsts", "missing_csp",
                         "missing_x_content_type_options",
                         "missing_x_frame_options"):
                if not resumen[tipo]:
                    continue
                self._add_issue(
                    resumen["anclas"][tipo][1],
                    tipo,
                    "info",
                    {"host": host, "paginas_afectadas": resumen[tipo],
                     "paginas_del_host": resumen["paginas"]},
                    group_key=_clave_de_grupo(host),
                )

        self._flush_issues()

    # -- Content ------------------------------------------------------------

    def analyze_content(self) -> None:
        """Contenido escaso: paginas indexables con poco texto PROPIO.

        Tres decisiones, con lo que decide Google detras de cada una:

        1. Se mide ``content_word_count`` (el contenido principal) y no
           ``word_count`` (todo el body). El menu, el megamenu y el pie son la
           misma plantilla en todas las paginas: Google los trata como
           boilerplate y no los cuenta como contenido de la pagina. Medido en
           dos censos: por body salian 997 de 29.808 paginas escasas, por
           contenido 10.433 — 9.436 fichas y archivos con dos frases propias
           que el menu disfrazaba de pagina completa.
        2. Solo se avisa de las paginas INDEXABLES. Que una pagina noindex o
           canonicalizada tenga poco texto no decide nada: Google no la va a
           posicionar. De 10.433 escasas, 4.736 son indexables; las otras 5.697
           solo tapaban las que importan.
        3. No se emite ``low_text_ratio`` ni ``very_low_text_ratio``. El ratio
           texto/HTML no es una senal de Google, y bien medido (antes contaba la
           indentacion de la plantilla como texto) salta en la mayoria de las
           paginas de cualquier sitio moderno: 29.005 de 29.808 en un censo,
           12 de 20 paginas de control. Lo que insinuaba —pagina escasa o
           montada con JS— ya lo responden el contenido y ``js_check``. La
           columna ``text_ratio`` se sigue calculando y exportando.
        """
        logger.debug("Analyzing content ...")

        # Only real, served HTML pages qualify: a 404/redirect body having
        # few words is not a "thin content" problem, and flagging it just
        # buries the genuine low-content pages in noise.
        stmt = (
            select(Url.id, Url.word_count, Url.content_word_count)
            .where(
                Url.job_id == self.job_id,
                Url.is_html.is_(True),
                Url.is_internal.is_(True),
                Url.status_code == 200,
                Url.indexable.is_(True),
            )
        )
        rows = self.session.execute(stmt).all()

        for url_id, word_count, content_word_count in rows:
            # content_word_count es None en los rastreos anteriores a la
            # columna y en los jobs que no extraen contenido: ahi se cae al
            # recuento del body, que es lo que habia.
            palabras = content_word_count if content_word_count is not None else word_count
            if palabras is None or palabras >= self.min_word_count:
                continue
            detalle = {"word_count": palabras}
            if content_word_count is not None:
                detalle = {"content_word_count": content_word_count,
                           "body_word_count": word_count}
            self._add_issue(url_id, "low_word_count", "warning", detalle)

        self._flush_issues()

    def analyze_soft_404(self) -> None:
        """Paginas 200 que son paginas de error (decision 105).

        Va DESPUES de `analyze_content`: una pagina que es soft 404 no lleva
        ademas `low_word_count`. La logica, en `analysis/soft404.py`.
        """
        from analysis import soft404

        self._flush_issues()
        soft404.analizar(self)

    # -- Paridad movil/escritorio (decision 119) ------------------------------

    _CAMPOS_INDEXACION = ("noindex", "canonical", "nofollow")
    _CAMPOS_RESPUESTA = ("status", "redireccion", "urls_separadas")

    def analyze_paridad_movil(self) -> None:
        """Lo que cambia con el otro perfil, una fila por (plantilla, campo).

        Lee `capturas_alternativas`, que el spider llena con una muestra por
        plantilla pedida con el perfil movil (o con el de escritorio, si el
        censo ya se rastreo con UA de movil). Es la PLANTILLA la que sirve otra
        cosa a un movil, asi que va agrupado (decisiones 36, 64): una fila por
        (perfil, plantilla, campo) con `paginas_afectadas` sobre las
        `paginas_muestreadas` de esa plantilla y unos ejemplos, anclada en la
        URL menor (decision 88).

        Severidad por consecuencia (64): Google indexa la version movil, asi
        que un `noindex` o un canonical distintos son error; title y H1,
        aviso; la description, informativa; el contenido principal o los
        enlaces internos, aviso a partir del umbral de `shared/paridad.py`.
        Una redireccion a otra URL es aviso salvo un m-dot con la anotacion
        bidireccional completa, que es una configuracion valida (info).

        No se afirma lo que no se pudo medir: los campos volatiles (cambian
        tambien entre dos peticiones de escritorio) ya vienen quitados, y una
        captura `no_evaluada` (muro, error, robots, control fallido) no avisa.
        Sin tabla (base anterior a la migracion), no se evalua.
        """
        from sqlalchemy import inspect

        from shared.models import CapturaAlternativa as C
        from shared.paridad import vary_por_user_agent

        try:
            # Con la conexion de la sesion, no con el engine: en SQLite el
            # inspector devolveria al pool la conexion de la transaccion en
            # curso y se llevaria por delante lo no confirmado.
            if not inspect(self.session.connection()).has_table(C.__tablename__):
                return
        except Exception:  # noqa: BLE001
            return
        filas = self.session.execute(
            select(C.url_id, Url.url, C.perfil, C.estado, C.plantilla, C.status_code,
                   C.redirige_a, C.vary_base, C.vary, C.diferencias, C.detalle,
                   Url.status_code, Url.response_class)
            .join(Url, Url.id == C.url_id)
            # La tabla guarda tambien la respuesta frente al render (decision
            # 140), que no es un dispositivo y tiene su propio analisis.
            .where(C.job_id == self.job_id, Url.job_id == self.job_id,
                   C.perfil.in_(("movil", "escritorio")))
        ).all()
        muestreadas: dict[tuple[str, str], int] = defaultdict(int)
        grupos: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for (url_id, url, perfil, estado, plantilla, status, redirige_a, vary_base, vary,
             difs, detalle, status_base, clase_base) in filas:
            # La pagina del censo tiene que seguir siendo una pagina 2xx: si se
            # re-rastreo y ahora es un 404 o un muro, la comparacion no vale.
            if not (status_base and 200 <= status_base < 300) or clase_base in NO_VALIDAS:
                continue
            if estado not in ("comparada", "redirige", "respuesta_distinta"):
                continue
            destino = (detalle or {}).get("destino") or {}
            if estado == "redirige" and (destino.get("error")
                                         or destino.get("clase") in NO_VALIDAS):
                # El destino del m-dot es un muro o no se pudo pedir: la
                # anotacion no se sabe, y no se afirma que falte (decision 103,
                # revision de #161).
                continue
            plantilla = plantilla or "?"
            muestreadas[(perfil, plantilla)] += 1
            sin_vary = not (vary_por_user_agent(vary_base) or vary_por_user_agent(vary))
            base = {"url_id": url_id, "url": url, "sin_vary": sin_vary}
            if estado == "comparada":
                for d in difs or []:
                    grupos[(perfil, plantilla, d["campo"])].append({**base, **d})
            elif estado == "respuesta_distinta":
                grupos[(perfil, plantilla, "status")].append(
                    {**base, "base": status_base, "alternativa": status})
            else:
                anotada = ((detalle or {}).get("tipo") == "otro_host"
                           and destino.get("canonical_a_base") is True
                           and destino.get("alternate_al_destino") is True)
                grupos[(perfil, plantilla, "urls_separadas" if anotada else "redireccion")].append({
                    **base, "base": url, "alternativa": redirige_a, "status": status,
                    "tipo": (detalle or {}).get("tipo"),
                    "canonical_a_base": destino.get("canonical_a_base"),
                    "alternate_al_destino": destino.get("alternate_al_destino"),
                })

        for (perfil, plantilla, campo), miembros in sorted(grupos.items()):
            miembros.sort(key=lambda m: m["url"])
            ancla = miembros[0]["url_id"]
            ejemplos = [{k: v for k, v in m.items() if k not in ("url_id", "campo", "sin_vary")}
                        for m in miembros[: self._MUESTRA_EJEMPLOS]]
            detalles = {
                "campo": campo, "perfil": perfil, "plantilla": plantilla,
                "paginas_afectadas": len(miembros),
                "paginas_muestreadas": muestreadas[(perfil, plantilla)],
                "ejemplos": ejemplos,
                # Servido dinamico sin `Vary: User-Agent`: una cache o CDN puede
                # dar la version equivocada a quien no es (Google lo pide).
                "sin_vary_user_agent": sum(1 for m in miembros if m["sin_vary"]),
            }
            clave = _clave_de_grupo(f"{perfil}|{plantilla}|{campo}")
            if campo in self._CAMPOS_INDEXACION:
                self._add_issue(ancla, "paridad_movil_indexacion",
                                "warning" if campo == "nofollow" else "error",
                                detalles, group_key=clave)
            elif campo in self._CAMPOS_RESPUESTA:
                self._add_issue(ancla, "paridad_movil_respuesta",
                                "info" if campo == "urls_separadas" else "warning",
                                detalles, group_key=clave)
            else:
                self._add_issue(ancla, "paridad_movil_contenido",
                                "info" if campo == "description" else "warning",
                                detalles, group_key=clave)
        self._flush_issues()

    # -- URL Issues ---------------------------------------------------------

    def analyze_url_issues(self) -> None:
        """URL tab equivalent -- flag structural problems in URLs."""
        logger.debug("Analyzing URL issues ...")

        # Solo documentos internos, y nunca los saltos de una redireccion.
        #
        # Criterio SEO: estos avisos se arreglan cambiando la URL de una pagina.
        # En un salto de redireccion no hay nada que arreglar —la URL se esta
        # yendo, y su destino ya se revisa por separado—, y en una imagen, un
        # CSS o un JS la forma de la URL no es una decision editorial. Los PDF
        # SI entran: son documentos que Google indexa.
        stmt = (
            select(Url.id, Url.url, Url.path)
            .where(
                Url.job_id == self.job_id,
                Url.is_internal.is_(True),
                Url.resource_type != "redirect",
                or_(Url.is_html.is_(True), Url.resource_type == "pdf"),
            )
        )
        rows = self.session.execute(stmt).all()

        for url_id, url_str, path in rows:
            url_len = len(url_str) if url_str else 0

            # URL over 115 characters.
            if url_len > URL_MAX_LENGTH:
                self._add_issue(
                    url_id,
                    "url_too_long",
                    "warning",
                    {"length": url_len},
                )

            # Caracteres no ASCII. Hay que DECODIFICAR antes: Scrapy guarda
            # las URLs escapadas (`caf%C3%A9`), que es puro ASCII, asi que este
            # aviso no saltaba nunca — ni en un censo con URLs en catalan,
            # castellano o arabe.
            if url_str and _NON_ASCII_RE.search(unquote(url_str)):
                self._add_issue(url_id, "url_non_ascii", "warning")

            # Path-specific checks (only when path is available).
            if path:
                # Uppercase letters in path.
                if path != path.lower():
                    self._add_issue(url_id, "url_uppercase", "info")

                # Underscores in path.
                if "_" in path:
                    self._add_issue(url_id, "url_underscores", "info")

                # Multiple consecutive slashes in path.
                if _MULTIPLE_SLASHES_RE.search(path):
                    self._add_issue(url_id, "url_multiple_slashes", "warning")

            # URL contains query parameters.
            if url_str and "?" in url_str:
                self._add_issue(url_id, "url_has_parameters", "info")

            # Non-SEO-friendly URL (malformed patterns discoverable by bots).
            if url_str and _NON_SEO_FRIENDLY_RE.search(url_str):
                self._add_issue(url_id, "url_non_seo_friendly", "error")

            # CMS faceted/filter URL (wastes crawl budget, index bloat).
            if url_str and _CMS_FACETED_RE.search(url_str):
                self._add_issue(url_id, "url_cms_faceted", "warning",
                                {"hint": "Crawl budget waste — consider blocking with robots.txt or noindex"})

        self._flush_issues()

    # -- Link Counts --------------------------------------------------------

    def _memoria_para_aristas(self) -> None:
        """Memoria de la sesion para la temporal de aristas (#281, decision 226).

        Con los valores de serie (`temp_buffers` 8 MB, `work_mem` 4 MB), la
        temporal de un censo de 11,6 M de enlaces y sus agregados con
        `count(distinct)` iban a disco: medido con
        `scripts/bench/analisis_por_fases.py` (60.000 URLs), esta fase pasaba
        de ~90 s a 49 con 256 MB y 64 MB, sin mejorar mas por encima.

        `work_mem` con `SET LOCAL`: dura hasta el commit, y esta fase no hace
        ninguno. Al PageRank NO se le sube: con 64 MB el planificador cambia a
        un merge join y su `pr_edges_tmp` pasa de 15 a 26 s. `temp_buffers` es
        un tope por sesion y solo se puede cambiar antes de su primera
        temporal: si la conexion ya uso alguna, se sigue con el que tenga.
        Nada de esto cambia un resultado; si falla, se sigue sin ello.
        """
        if not self.session.get_bind().dialect.name.startswith("postgres"):
            return
        self.session.execute(text("SET LOCAL work_mem = '64MB'"))
        try:
            with self.session.begin_nested():
                self.session.execute(text("SET temp_buffers = '256MB'"))
        except Exception:
            logger.debug("temp_buffers no se pudo subir: la conexion ya uso temporales")

    def compute_link_counts(self) -> None:
        """Rellena inlinks, unique_inlinks, outlinks y external_outlinks.

        UNA sola lectura de `links`, no cuatro. La tabla guarda los enlaces de
        TODOS los rastreos —46 GB y 181 millones de filas en produccion— y el
        planificador la recorre entera para sacar los de un job: cuatro
        agregados eran cuatro recorridos. Medido en el censo de penguin
        (10,3 M enlaces del job), el analisis completo pasaba de 4 minutos a
        mas de 25.

        Ahora las aristas del job se materializan una vez en una temporal
        —lo mismo que ya hacia `compute_pagerank` con `pr_edges_tmp`— y los
        cuatro conteos salen de ahi, que es pequena y cabe en memoria.
        """
        logger.debug("Computing link counts ...")
        self._memoria_para_aristas()

        # A cero antes de agregar. Los UPDATE de abajo solo tocan filas con
        # coincidencia, asi que una URL que perdio todos sus inlinks entre dos
        # rastreos conservaba el conteo viejo: salia con 12 inlinks cuando ya no
        # tenia ninguno, y por tanto no salia como huerfana. Dato rancio que se
        # lee como dato bueno.
        self.session.execute(
            update(Url)
            .where(Url.job_id == self.job_id)
            .values(
                inlinks_count=0,
                unique_inlinks_count=0,
                outlinks_count=0,
                external_outlinks_count=0,
            )
        )

        # --- La unica lectura de `links` -----------------------------------
        #
        # Se resuelve aqui el id del DESTINO (no solo su hash) para que los
        # agregados de abajo no tengan que volver a `urls` ni filtrar por job:
        # la temporal ya solo tiene las aristas de este rastreo.
        #
        # Criterio SEO de lo que entra:
        #
        # - Un enlace de una pagina a SI MISMA no dice que este enlazada. Eran
        #   62.326 de los 2.342.192 inlinks de blogs.uoc.edu, concentrados en
        #   las paginas con menu o migas que se enlazan a si mismas.
        # - Un enlace desde una pagina `noindex` tampoco cuenta (C3 de #24):
        #   Google acaba tratandolos como nofollow, asi que una pagina que solo
        #   cuelga de noindex no esta enlazada a efectos de buscador.
        # - Ni desde una pagina que no responde 200. Un 404 o un 500 sale del
        #   indice y se lleva sus enlaces con el: lo que solo cuelga de ahi no
        #   esta enlazado. Medido en www.uoc.edu: **503 paginas que devuelven
        #   500** aportaban 264.991 enlaces, y 137 URLs tenian TODOS sus
        #   entrantes internos ahi — huerfanas de hecho que salian enlazadas.
        # - Los `nofollow` SI cuentan: la pagina esta enlazada, solo que sin
        #   respaldo. La autoridad se mira en el PageRank, que lleva su propio
        #   grafo. Son dos preguntas distintas y no caben en un entero.
        #
        # Se construye con tipos de SQLAlchemy y no con SQL a mano: el `job_id`
        # es un UUID y comparado como cadena no liga igual en todos los
        # motores, asi que la primera version de esto no actualizaba ni una
        # fila en los tests contra SQLite.
        from sqlalchemy import (BigInteger, Boolean, Column, Integer, MetaData, String,
                                Table, Text, case, insert, literal, null)

        con_sondas = self._con_sondas = avisos_de_sondas.hay_sondas(self)
        self.session.execute(text("DROP TABLE IF EXISTS aristas_tmp"))
        aristas = Table(
            "aristas_tmp", MetaData(),
            Column("destino_id", BigInteger),
            Column("origen_id", BigInteger),
            Column("es_interno", Boolean),
            Column("origen_cuenta", Boolean),
            # Solo para la profundidad de clic: el `nofollow` SI cuenta como
            # enlace entrante (abajo), pero no es un camino que se recorra.
            Column("seguible", Boolean),
            # Apariciones identicas en la pagina (decision 94). Los conteos por
            # INSTANCIA suman esto; los de origenes distintos no lo miran.
            Column("veces", Integer),
            # El hash del destino solo si lleva `utm_*` (decision 106). NULL en
            # el resto: no engorda la temporal de un censo de millones.
            Column("utm_hash", String(64)),
            # Enlace interno sin nombre (decision 121): ni texto, ni
            # `aria-label`/`title`/svg (que el extractor ya pone en el ancla),
            # ni alt. Solo en esas filas, como `utm_hash`: el destino tal cual,
            # donde esta el enlace y si es una imagen.
            Column("sin_ancla_destino", Text),
            Column("sin_ancla_posicion", String(20)),
            Column("sin_ancla_imagen", Boolean),
            # Paginacion (decision 122), de la MISMA lectura: el origen es una
            # pagina 2+ en noindex o canonicalizada a la 1, y, solo para las
            # paginas con `rel=next` y los destinos SIN rastrear, la URL (para
            # ver si hay un `<a>` a la siguiente, que el spider no sigue por
            # el rel). NULL en el resto: no engorda la temporal.
            # No cambian `origen_cuenta`: es otra pregunta (decision 38).
            Column("origen_pag_excluida", Boolean),
            Column("origen_pag_profunda", Boolean),
            Column("rel_destino_url", Text),
            # El del destino EXTERNO, para cruzarlo con `respuestas_sondeadas`
            # (decision 123). Solo si el censo tiene sondas; si no, NULL.
            Column("externo_hash", String(64)),
            # El ancla, solo si es generica («leer mas», «aqui», «read more»;
            # decision 147). NULL en el resto: no engorda la temporal.
            Column("ancla_generica", Text),
            # El enlace es `nofollow` por su propio `rel` (o `ugc`/`sponsored`),
            # no por la directiva de la pagina (decision 183). True o NULL.
            Column("nofollow_rel", Boolean),
            prefixes=["TEMPORARY"],
        )
        aristas.create(self.session.connection())

        origen = aliased(Url)
        destino = aliased(Url)
        pag = avisos_de_paginacion.preparar_temporal(self)
        sin_ancla = and_(
            Link.is_internal.is_(True),
            or_(Link.anchor_text.is_(None), func.trim(Link.anchor_text) == ""),
            or_(Link.alt_text.is_(None), func.trim(Link.alt_text) == ""),
        )
        consulta = select(
            destino.id, Link.from_url_id, Link.is_internal,
            and_(origen.noindex.isnot(True), origen.status_code == 200),
            Link.follow.isnot(False),
            Link.repeticiones,
            case((or_(func.lower(Link.to_url).like("%?utm\\_%", escape="\\"),
                      func.lower(Link.to_url).like("%&utm\\_%", escape="\\")),
                  Link.to_url_hash), else_=None),
            case((sin_ancla, Link.to_url), else_=None),
            case((sin_ancla, func.coalesce(Link.link_position, "")), else_=None),
            case((sin_ancla, Link.link_type == "image"), else_=None),
            pag.c.excluida if pag is not None else null(),
            pag.c.profunda if pag is not None else null(),
            case((and_(pag.c.con_rel.is_(True), destino.id.is_(None)), Link.to_url),
                 else_=None)
            if pag is not None else null(),
            (case((Link.is_internal.is_(False), Link.to_url_hash), else_=None)
             if con_sondas else literal(None, String(64))),
            case((and_(Link.is_internal.is_(True),
                       func.lower(func.trim(Link.anchor_text)).in_(avisos_de_enlaces.ANCLAS_GENERICAS)),
                  func.lower(func.trim(Link.anchor_text))), else_=None),
            sql_nofollow_por_rel(Link.follow, Link.rel),  # decision 183
        ).join(origen, origen.id == Link.from_url_id)
        if pag is not None:
            # Una temporal de las paginas de paginacion, por clave primaria:
            # no es otra lectura de `links`, y sin paginacion ni se une.
            consulta = consulta.outerjoin(pag, pag.c.url_id == Link.from_url_id)
        self.session.execute(
            insert(aristas).from_select(
                ["destino_id", "origen_id", "es_interno", "origen_cuenta", "seguible",
                 "veces", "utm_hash", "sin_ancla_destino", "sin_ancla_posicion",
                 "sin_ancla_imagen", "origen_pag_excluida", "origen_pag_profunda",
                 "rel_destino_url", "externo_hash", "ancla_generica", "nofollow_rel"],
                consulta
                .outerjoin(destino, and_(
                    destino.url_hash == Link.to_url_hash,
                    destino.job_id == Link.job_id,
                ))
                .where(Link.job_id == self.job_id),
            )
        )
        self.session.execute(text(
            "CREATE INDEX ix_aristas_tmp_destino ON aristas_tmp (destino_id)"
        ))
        self.session.execute(text(
            "CREATE INDEX ix_aristas_tmp_origen ON aristas_tmp (origen_id)"
        ))

        # --- Salientes: internos y externos, de una pasada sobre la temporal -
        salientes = (
            select(
                aristas.c.origen_id.label("url_id"),
                func.coalesce(func.sum(aristas.c.veces).filter(aristas.c.es_interno), 0)
                .label("internos"),
                func.coalesce(func.sum(aristas.c.veces).filter(~aristas.c.es_interno), 0)
                .label("externos"),
            )
            .group_by(aristas.c.origen_id)
            .subquery()
        )
        self.session.execute(
            update(Url)
            .where(Url.id == salientes.c.url_id)
            .values(
                outlinks_count=salientes.c.internos,
                external_outlinks_count=salientes.c.externos,
            )
        )

        # --- Entrantes: totales y origenes distintos, otra pasada ------------
        entrantes = (
            select(
                aristas.c.destino_id.label("url_id"),
                func.sum(aristas.c.veces).label("entrantes"),
                func.count(func.distinct(aristas.c.origen_id)).label("origenes"),
            )
            .where(
                aristas.c.origen_cuenta,
                aristas.c.destino_id.isnot(None),
                aristas.c.origen_id != aristas.c.destino_id,
            )
            .group_by(aristas.c.destino_id)
            .subquery()
        )
        self.session.execute(
            update(Url)
            .where(Url.id == entrantes.c.url_id)
            .values(
                inlinks_count=entrantes.c.entrantes,
                unique_inlinks_count=entrantes.c.origenes,
            )
        )

        # Sobre las mismas aristas: una segunda lectura de `links` costaria lo
        # mismo que todo lo anterior (decision 41). La paginacion va antes que
        # la profundidad: lo que solo cuelga de una serie excluida no lleva
        # ademas `not_reachable_from_home` (36).
        avisos_de_paginacion.desde_aristas(self, aristas)  # decision 122
        self.compute_click_depth(aristas)
        avisos_de_enlaces.avisar_enlaces_a_respuestas(self, aristas)  # decision 106
        avisos_de_enlaces.avisar_enlaces_sin_ancla(self, aristas)  # decision 121
        avisos_de_enlaces.avisar_anclas_genericas(self, aristas)  # decision 147
        avisos_de_nofollow.avisar_enlaces_nofollow(  # decision 183
            self, aristas, excluir=self._solo_con_nofollow)
        if con_sondas:
            avisos_de_sondas.avisar_enlaces_externos(self, aristas)  # decision 123

        self.session.execute(text("DROP TABLE IF EXISTS aristas_tmp"))
        avisos_de_paginacion.borrar_temporal(self)
        self.session.flush()

    # -- Profundidad de clic -------------------------------------------------

    def _portadas(self) -> list[int]:
        """Las URLs desde las que se cuenta la profundidad: la raiz de cada
        host de las semillas (`https://host/`), si se rastreo.

        No las semillas: un censo sembrado con 3.040 URLs (Lopesan, 13-oct)
        tenia 2.867 de sus 3.237 indexables a profundidad 0, y medido desde la
        home esas mismas paginas estaban entre 1 y 12 clics.
        """
        from shared.models import Job

        semillas = self.session.execute(
            select(Job.seeds).where(Job.id == self.job_id)
        ).scalar() or []
        candidatas: list[str] = []
        for semilla in semillas:
            host = urlparse(str(semilla)).hostname
            if not host:
                continue
            for esquema in ("https", "http"):
                candidatas += [f"{esquema}://{host}/", f"{esquema}://{host}"]
        if not candidatas:
            return []
        return list(self.session.execute(
            select(Url.id).where(
                Url.job_id == self.job_id,
                Url.is_internal.is_(True),
                Url.url.in_(set(candidatas)),
            )
        ).scalars())

    def compute_click_depth(self, aristas) -> None:
        """`urls.click_depth`: clics desde la home, como cuenta Google.

        `crawl_depth` es otra cosa —saltos del rastreador desde donde empezo,
        con cada semilla a 0 y lo del sitemap a 1— y sigue haciendo falta,
        porque es la que corta el rastreo (`max_depth`).

        Criterio, el mismo grafo que los enlaces entrantes:
        - se parte de la raiz de cada host de las semillas y de las portadas
          de idioma que esa raiz declara en su hreflang: `/es/`, `/en/` y
          `/de/` son portadas para Google, y contando solo desde una todo lo
          que no esta en ese idioma sale varios clics mas lejos;
        - una redireccion NO es un clic: el destino hereda la profundidad del
          salto (lo mismo que hace el spider, decision 27). La raiz de Lopesan
          es un 302 a `/es/`, y `/es/` es la profundidad 0;
        - solo se avanza por enlaces internos, follow, desde paginas 200 que
          no son noindex (decisiones 38 y 57): de una 404 o una noindex no
          sale ningun camino;
        - lo que no tiene camino queda en NULL, y si es indexable y alguien la
          enlaza emite `not_reachable_from_home` (si nadie la enlaza ya es
          `orphan_page` o `sitemap_orphan`, decision 36), o
          `solo_enlazada_con_nofollow` si todo lo que la enlaza es `nofollow`
          (decision 183).

        Por niveles y en el servidor, no cargando el grafo en Python: en
        penguin son 10 millones de aristas.
        """
        from sqlalchemy import BigInteger, Column, Integer, MetaData, Table, exists, insert, literal

        from shared.models import Hreflang

        self._solo_con_nofollow = set()
        self.session.execute(
            update(Url).where(Url.job_id == self.job_id).values(click_depth=None)
        )
        portadas = self._portadas()
        if not portadas:
            logger.warning(
                "Profundidad de clic: no se rastreo la raiz de ningun host de "
                "las semillas; click_depth queda vacia en el job %s", self.job_id)
            return

        self.session.execute(text("DROP TABLE IF EXISTS prof_tmp"))
        prof = Table(
            "prof_tmp", MetaData(),
            Column("id", BigInteger, primary_key=True),
            Column("d", Integer),
            prefixes=["TEMPORARY"],
        )
        prof.create(self.session.connection())
        # Alias para el NOT EXISTS: con la misma tabla dentro y fuera,
        # SQLAlchemy autocorrela la subconsulta y la deja sin FROM.
        visto = prof.alias("visto")
        self.session.execute(insert(prof), [{"id": i, "d": 0} for i in set(portadas)])

        def insertar(consulta) -> int:
            return self.session.execute(
                insert(prof).from_select(["id", "d"], consulta)
            ).rowcount or 0

        def cerrar_redirecciones(d: int) -> None:
            salto = aliased(Url)
            destino = aliased(Url)
            while insertar(
                select(destino.id, literal(d, Integer)).distinct()
                .select_from(salto)
                .join(prof, and_(prof.c.id == salto.id, prof.c.d == d))
                .join(destino, and_(
                    destino.job_id == salto.job_id,
                    destino.url == salto.redirect_url,
                ))
                .where(
                    salto.job_id == self.job_id,
                    destino.is_internal.is_(True),
                    ~exists().where(visto.c.id == destino.id),
                )
            ):
                pass

        cerrar_redirecciones(0)
        # Portadas de idioma: el hreflang de la home (ya resuelta la
        # redireccion de la raiz), no el de cualquier pagina.
        portada = aliased(Url)
        alterna = aliased(Url)
        insertar(
            select(alterna.id, literal(0, Integer)).distinct()
            .select_from(Hreflang)
            .join(portada, portada.id == Hreflang.url_id)
            .join(prof, and_(prof.c.id == portada.id, prof.c.d == 0))
            .join(alterna, and_(
                alterna.job_id == portada.job_id,
                alterna.url == Hreflang.href,
            ))
            .where(
                portada.job_id == self.job_id,
                portada.status_code == 200,
                Hreflang.en_body.isnot(True),
                alterna.is_internal.is_(True),
                ~exists().where(visto.c.id == alterna.id),
            )
        )
        cerrar_redirecciones(0)

        d = 0
        while d < 1000:
            nuevos = insertar(
                select(aristas.c.destino_id, literal(d + 1, Integer)).distinct()
                .select_from(aristas)
                .join(prof, and_(prof.c.id == aristas.c.origen_id, prof.c.d == d))
                .where(
                    aristas.c.es_interno.is_(True),
                    aristas.c.origen_cuenta.is_(True),
                    aristas.c.seguible.is_(True),
                    aristas.c.destino_id.isnot(None),
                    ~exists().where(visto.c.id == aristas.c.destino_id),
                )
            )
            if not nuevos:
                break
            d += 1
            cerrar_redirecciones(d)

        self.session.execute(
            update(Url)
            .where(Url.id == prof.c.id, Url.job_id == self.job_id)
            .values(click_depth=prof.c.d)
        )
        self.session.execute(text("DROP TABLE IF EXISTS prof_tmp"))

        sin_camino = self.session.execute(
            select(Url.id, Url.inlinks_count, Url.in_sitemap).where(
                Url.job_id == self.job_id,
                Url.is_internal.is_(True),
                Url.is_html.is_(True),
                Url.status_code == 200,
                Url.indexable.is_(True),
                Url.click_depth.is_(None),
                Url.inlinks_count > 0,
            )
        ).all()
        de_paginacion = avisos_de_paginacion.sustituidas(self)  # decision 122
        # El camino desde la home puede pasar por lo que un tope dejo sin
        # rastrear (decision 172): no se afirma que no lo haya.
        if self._topes_cortaron():
            sin_camino = []
        # Las que solo reciben `nofollow` llevan ese aviso, que dice la causa
        # (decision 183); la paginacion va antes, como con la profundidad.
        self._solo_con_nofollow = avisos_de_nofollow.solo_con_nofollow(
            self, aristas, [u for u, _, _ in sin_camino if u not in de_paginacion])
        for url_id, entrantes, en_sitemap in sin_camino:
            if url_id in de_paginacion or url_id in self._solo_con_nofollow:
                continue
            self._add_issue(
                url_id, "not_reachable_from_home", "warning",
                {"inlinks": entrantes, "in_sitemap": en_sitemap},
            )
        logger.info(
            "Profundidad de clic: %d portadas, %d niveles, %d indexables "
            "enlazadas sin camino desde la home", len(portadas), d, len(sin_camino))

    # -- PageRank -----------------------------------------------------------

    # La tabla de pesos por posicion vive en analysis/pagerank.py; se deja el
    # alias por compatibilidad con quien la leia desde aqui.
    _POSITION_WEIGHT = prk.PESO_POSICION

    def compute_pagerank(
        self,
        damping: float = 0.85,
        max_iter: int = 100,
        tol: float = 1e-6,
    ) -> None:
        """PageRank interno. El modelo esta en `analysis/pagerank.py`.

        Aristas: enlaces follow internos pesados por su repeticion medida en
        el sitio (la posicion solo desempata), mas salto -> destino en las
        redirecciones, mas variante -> canonical en las paginas
        canonicalizadas. Teletransporte y masa colgante solo entre paginas
        200 indexables. Deja en `jobs.pagerank_resumen` cuanto PageRank acaba
        en cada tipo de URL, y el desperdiciado.

        Una pagina NO reparte autoridad si no responde 200 o si lleva
        `noindex` (C3 de #24, el mismo criterio que la decision 38 aplica a los
        enlaces entrantes): Google acaba tratando los enlaces de una noindex
        como nofollow, asi que lo que recibe de ella no es autoridad real. Lo
        que ya tenia acumulado no se pierde: la pagina queda colgante y su masa
        va al teletransporte, o sea al conjunto de paginas indexables, en vez de
        a los destinos concretos que ella enlazaba. Ser noindex NO impide
        recibir —un enlace a una noindex es autoridad que se tira, y eso es
        justo lo que mide `reparto["no_indexable"]`.

        Las aristas se agregan EN SQL y se iteran vectorizadas con numpy. Con
        139 millones de enlaces internos (un e-commerce real, ~2.300 por pagina
        por los megamenus) cargarlos como objetos de Python eran ~14 GB;
        agregados en el servidor y leidos por bloques quedan en ~240 MB.
        """
        logger.debug("Computing PageRank ...")

        import numpy as np

        # Los backlinks del cliente se cruzan ANTES de mirar si hay grafo: sus
        # avisos (un 404 con backlinks) no dependen de los enlaces internos, y
        # sin ellos un censo sin aristas se quedaba con los de un analisis
        # anterior (decision 212).
        self._preparar_backlinks()

        # 1. Nodos internos del job, con su categoria (ver prk.categoria)
        url_rows = self.session.execute(
            select(
                Url.id, Url.status_code, Url.is_html, Url.indexable,
                Url.redirect_url.isnot(None),
            ).where(Url.job_id == self.job_id, Url.is_internal.is_(True))
        ).all()
        if not url_rows:
            return
        # Ordenados porque el mapeo id->indice se hace con searchsorted, que
        # exige orden. El indice i corresponde siempre a ids_ordenados[i].
        url_rows.sort(key=lambda r: r[0])
        ids_ordenados = np.array([r[0] for r in url_rows], dtype=np.int64)
        categorias = [
            prk.categoria(r[1], r[2], r[3], "x" if r[4] else None)
            for r in url_rows
        ]
        del url_rows
        n = len(ids_ordenados)

        # 2. Aviso de posiciones sin peso declarado: el CASE las absorberia en
        # el valor por defecto sin ruido, y asi fue como `nav` acabo pesando
        # mas que header y footer.
        conocidas = [p for p in prk.PESO_POSICION if p is not None]
        desconocidas = self.session.execute(
            text(
                """
                SELECT l.link_position, SUM(l.repeticiones) AS n
                FROM links l
                WHERE l.job_id = :jid AND l.is_internal AND l.follow
                  AND l.link_position IS NOT NULL
                  AND NOT (l.link_position = ANY(:conocidas))
                GROUP BY 1 ORDER BY 2 DESC
                """
            ),
            {"jid": self.job_id, "conocidas": conocidas},
        ).all()
        if desconocidas:
            logger.warning(
                "PageRank: posiciones de enlace sin peso declarado, entran con "
                "el valor por defecto (%s) y pueden sesgar el reparto: %s",
                prk.PESO_POSICION[None],
                ", ".join(f"{p}={c}" for p, c in desconocidas),
            )

        # 3. Aristas de enlaces, agregadas EN EL SERVIDOR a una tabla temporal
        modo_peso = self._aristas_de_enlaces()

        # 4. Redirecciones (3xx y meta refresh): arista salto -> destino con
        # peso completo. Sin ella, el PageRank que llegaba a una 301 quedaba
        # colgante y se repartia entre todas las URLs en vez de pasar a su
        # destino. Se une por la URL (no por hash) porque redirect_url se
        # guarda ya normalizada y asi valen tambien los censos anteriores.
        aristas_redireccion = self.session.execute(text(
            """
            INSERT INTO pr_edges_tmp (src, dst, w)
            SELECT r.id, d.id, 1.0::real
            FROM urls r
            JOIN urls d ON d.job_id = r.job_id AND d.url = r.redirect_url
            WHERE r.job_id = :jid AND r.is_internal AND d.is_internal
              AND r.redirect_url IS NOT NULL AND r.id <> d.id
              AND NOT EXISTS (
                SELECT 1 FROM pr_edges_tmp e WHERE e.src = r.id AND e.dst = d.id
              )
            """
        ), {"jid": self.job_id}).rowcount

        # 5. Canonicals: Google consolida las senales de la variante en la
        # canonica. Antes `?orden=precio`, `/page/2` o `?utm=` retenian su
        # PageRank y lo repartian por su cuenta. Se modela como una
        # redireccion: la variante pierde sus enlaces salientes (son los de la
        # canonica, casi siempre la misma plantilla) y pasa todo a la canonica.
        # Solo si la canonica se rastreo y responde 200: si no, consolidar
        # seria mandar el PageRank a un sitio que no existe.
        # El canonical es el mismo que decide la indexabilidad: manda el del
        # HTML y, si no hay, el de la cabecera `Link`. Sin la cabecera, una
        # pagina "Canonicalised" solo por ella —un PDF, o un HTML que la usa en
        # vez del <link>— retenia su PageRank y lo repartia por su cuenta (#26).
        self.session.execute(text("DROP TABLE IF EXISTS pr_canon_tmp"))
        self.session.execute(text(
            """
            CREATE TEMP TABLE pr_canon_tmp AS
            SELECT u.id AS src, d.id AS dst
            FROM urls u
            JOIN html_meta m ON m.url_id = u.id
            JOIN urls d ON d.job_id = u.job_id
             AND d.url = COALESCE(NULLIF(btrim(m.canonical_href), ''), m.canonical_header)
            WHERE u.job_id = :jid AND u.is_internal AND d.is_internal
              AND u.indexability_status = 'Canonicalised'
              AND d.status_code = 200 AND d.id <> u.id
            """
        ), {"jid": self.job_id})
        self.session.execute(text(
            "DELETE FROM pr_edges_tmp e USING pr_canon_tmp c WHERE e.src = c.src"
        ))
        aristas_canonical = self.session.execute(text(
            "INSERT INTO pr_edges_tmp (src, dst, w) "
            "SELECT src, dst, 1.0::real FROM pr_canon_tmp"
        )).rowcount
        self.session.execute(text("DROP TABLE IF EXISTS pr_canon_tmp"))

        total = self.session.execute(
            text("SELECT COUNT(*) FROM pr_edges_tmp")
        ).scalar() or 0
        if not total:
            logger.info("PageRank: el job %s no tiene aristas", self.job_id)
            self.session.execute(text("DROP TABLE IF EXISTS pr_edges_tmp"))
            return
        logger.info(
            "PageRank: %d nodos, %d aristas (peso por %s; %d de redireccion, "
            "%d de canonical)",
            n, total, modo_peso, aristas_redireccion, aristas_canonical,
        )

        src = np.empty(total, dtype=np.int32)
        dst = np.empty(total, dtype=np.int32)
        w = np.empty(total, dtype=np.float32)

        cruda = self.session.connection().connection
        cur = cruda.cursor(name="pr_edges_cursor")
        cur.itersize = 1_000_000
        cur.execute("SELECT src, dst, w FROM pr_edges_tmp")
        pos = 0
        while True:
            filas = cur.fetchmany(1_000_000)
            if not filas:
                break
            k = len(filas)
            # fromiter evita construir listas intermedias de 1 M de elementos
            s_bloque = np.fromiter((f[0] for f in filas), dtype=np.int64, count=k)
            d_bloque = np.fromiter((f[1] for f in filas), dtype=np.int64, count=k)
            src[pos:pos + k] = np.searchsorted(ids_ordenados, s_bloque)
            dst[pos:pos + k] = np.searchsorted(ids_ordenados, d_bloque)
            w[pos:pos + k] = np.fromiter(
                (f[2] for f in filas), dtype=np.float32, count=k
            )
            pos += k
            del filas, s_bloque, d_bloque
        cur.close()
        self.session.execute(text("DROP TABLE IF EXISTS pr_edges_tmp"))

        # 6. Iteracion, con el teletransporte solo entre paginas indexables
        indexables = np.array([c == prk.INDEXABLE for c in categorias])
        pr = prk.pagerank(
            n, src, dst, w, teletransporte=indexables,
            damping=damping, max_iter=max_iter, tol=tol,
        )
        reparto = prk.reparto(pr, categorias)
        resumen = {
            "peso": modo_peso,
            "nodos": n,
            "aristas": int(total),
            "aristas_redireccion": int(aristas_redireccion or 0),
            "aristas_canonical": int(aristas_canonical or 0),
            "reparto": reparto,
            "desperdiciado": prk.desperdiciado(reparto),
        }
        # A7 de #24: si la comprobacion automatica vio plantillas que montan
        # sus enlaces con JavaScript, el grafo esta incompleto y el PageRank se
        # calcula igual. Antes solo quedaba un WARNING en el log del worker, y
        # el numero se entregaba como si nada. Ahora el aviso viaja CON el
        # dato: en jobs.pagerank_resumen, en el endpoint del job y en una
        # columna del CSV, para que quien ordene por PageRank en una hoja de
        # calculo lo vea.
        resumen.update(self._fiabilidad_del_grafo())
        logger.info(
            "PageRank: %.1f%% en paginas indexables, %.1f%% desperdiciado en "
            "errores (job %s)",
            reparto[prk.INDEXABLE] * 100, resumen["desperdiciado"] * 100,
            self.job_id,
        )

        # 6b. Con la autoridad que entra de fuera (decision 212), en la misma
        # pasada: las aristas ya estan cargadas. Best-effort: si falla, el
        # PageRank interno se guarda igual.
        try:
            with self.session.begin_nested():
                externo = self._pagerank_externo(
                    n, src, dst, w, ids_ordenados, categorias, indexables,
                    damping=damping, max_iter=max_iter, tol=tol)
        except Exception:
            logger.exception("PageRank externo del job %s: no se calcula", self.job_id)
            externo = None
        if externo is not None:
            resumen["externo"] = externo

        # 7. Tres escalas, porque son tres preguntas (C4 de #24)
        #
        # La de siempre, 0-10 lineal, no distingue la pagina 250 de la 25.000:
        # la home vale 10 porque es el maximo y el resto del sitio se apelotona
        # en 0,00xx. Medido en blogs.uoc.edu: 33.956 de 34.704 paginas por
        # debajo de 0,1, o sea el 97,8% indistinguible entre si.
        #
        # `pagerank_raw` es la probabilidad tal cual (suma 1): por el numero de
        # nodos da "veces la pagina media", que si se puede comparar entre
        # sitios de tamaño distinto. `pagerank_score` es 0-100 en logaritmico
        # —el equivalente al Link Score de Screaming Frog— y es la que hay que
        # leer: reparte la cola larga en vez de aplastarla.
        crudo = pr.copy()
        puntuacion = prk.puntuacion_log(crudo)

        maximo = pr.max()
        if maximo > 0:
            pr = pr / maximo * 10.0

        # 8. Guardado en bloque. Antes se emitia una UPDATE por URL: en un job
        # de 60.000 paginas eran 60.000 consultas sueltas.
        self.session.execute(text(
            "CREATE TEMP TABLE pr_tmp (id BIGINT PRIMARY KEY, pr DOUBLE PRECISION, "
            "crudo DOUBLE PRECISION, score INTEGER) ON COMMIT DROP"
        ))
        filas = [{"id": int(i), "pr": round(float(v), 4),
                  "crudo": float(c), "score": int(sc)}
                 for i, v, c, sc in zip(ids_ordenados, pr, crudo, puntuacion)]
        for i in range(0, len(filas), 10_000):
            self.session.execute(
                text("INSERT INTO pr_tmp (id, pr, crudo, score) "
                     "VALUES (:id, :pr, :crudo, :score)"),
                filas[i:i + 10_000],
            )
        self.session.execute(text(
            "UPDATE urls SET pagerank = pr_tmp.pr, pagerank_raw = pr_tmp.crudo, "
            "pagerank_score = pr_tmp.score FROM pr_tmp WHERE urls.id = pr_tmp.id"
        ))
        from shared.models import Job
        self.session.execute(
            update(Job).where(Job.id == self.job_id).values(pagerank_resumen=resumen)
        )
        self.session.flush()
        logger.info("PageRank computed for %d URLs (job %s)", n, self.job_id)

    def _preparar_backlinks(self) -> None:
        """Cruza el CSV de backlinks mas reciente del cliente con el censo y lo
        deja en `self._backlinks`. Antes pone a NULL lo de un analisis
        anterior: sin importacion, o sin grafo (donde no se calcula el PageRank
        desde fuera), no puede quedar el de antes. Best-effort, con su
        savepoint."""
        from shared.backlinks import cruzar, filas_de, rango_de, ultima_importacion

        self._backlinks = self._backlinks_import = None
        try:
            with self.session.begin_nested():
                self.session.execute(text(
                    "UPDATE urls SET pagerank_externo_score = NULL, backlinks_externos = NULL, backlinks_nofollow = NULL, "
                    "backlinks_spam = NULL, backlinks_spam_pct = NULL, autoridad_externa = NULL "
                    "WHERE job_id = :jid AND backlinks_externos IS NOT NULL"
                ), {"jid": self.job_id})
                imp = ultima_importacion(self.session, self._cliente_id)
                if imp is None:
                    return
                urls = self.session.execute(
                    select(Url.id, Url.url, Url.status_code, Url.indexable, Url.redirect_url)
                    .where(Url.job_id == self.job_id, Url.is_internal.is_(True))).all()

                self._backlinks = cruzar(filas_de(self.session, imp),
                                         [(u[0], u[1], rango_de(u[2], u[3], u[4])) for u in urls])
                self._backlinks_import = imp
        except Exception:
            self._backlinks = self._backlinks_import = None
            logger.exception("Backlinks del job %s: no se cruzan", self.job_id)

    def _pagerank_externo(self, n, src, dst, w, ids_ordenados, categorias, indexables,
                          *, damping, max_iter, tol) -> dict | None:
        """PageRank personalizado con los backlinks del cliente (#31, decision 212).

        Usa la importacion mas reciente de su cliente (`shared.backlinks`). Lo
        que llega a una 301 pasa a su destino por la arista de redireccion; lo
        que llega a un error se queda ahi y cuenta como desperdiciado. La masa
        colgante va a las indexables, como en el interno: si fuera al salto, un
        404 con backlinks se la devolveria a si mismo. Guarda en `urls` la
        escala 0-100, los backlinks y lo que aportan; sin importacion, los deja
        a NULL (un re-analisis tras borrarla no puede ensenar los de antes).
        """
        import numpy as np

        cruce, imp = self._backlinks, getattr(self, "_backlinks_import", None)
        if cruce is None or imp is None:
            return None
        externo = np.zeros(n, dtype=np.float64)
        for uid, d in cruce.por_url.items():
            externo[int(np.searchsorted(ids_ordenados, uid))] += d["aportacion"]
        beta = min(1.0, max(0.0, self.pagerank_externo_beta))
        pr = prk.pagerank(
            n, src, dst, w,
            teletransporte=prk.teletransporte_externo(indexables, externo, beta),
            colgante=indexables, damping=damping, max_iter=max_iter, tol=tol)
        puntuacion = prk.puntuacion_log(pr)

        self.session.execute(text("DROP TABLE IF EXISTS pr_ext_tmp"))
        self.session.execute(text(
            "CREATE TEMP TABLE pr_ext_tmp (id BIGINT PRIMARY KEY, score INTEGER, "
            "backlinks INTEGER, nofollow INTEGER, spam INTEGER, spam_pct DOUBLE PRECISION, "
            "autoridad DOUBLE PRECISION)"))
        filas = []
        for i, uid in enumerate(ids_ordenados):
            d = cruce.por_url.get(int(uid))
            backlinks, nofollow, spam = (d["backlinks"], d.get("nofollow", 0), d.get("spam", 0)) if d else (0, 0, 0)
            filas.append({"id": int(uid), "score": int(puntuacion[i]),
                          "backlinks": backlinks - nofollow, "nofollow": nofollow, "spam": spam,
                          "spam_pct": round(100 * spam / backlinks, 1) if backlinks else None,
                          "autoridad": round(d["aportacion"], 6) if d else 0.0})
        for i in range(0, len(filas), 10_000):
            self.session.execute(text(
                "INSERT INTO pr_ext_tmp (id, score, backlinks, nofollow, spam, spam_pct, autoridad) "
                "VALUES (:id, :score, :backlinks, :nofollow, :spam, :spam_pct, :autoridad)"), filas[i:i + 10_000])
        self.session.execute(text(
            "UPDATE urls SET pagerank_externo_score = t.score, backlinks_externos = t.backlinks, "
            "backlinks_nofollow = t.nofollow, "
            "backlinks_spam = t.spam, backlinks_spam_pct = t.spam_pct, autoridad_externa = t.autoridad "
            "FROM pr_ext_tmp t WHERE urls.id = t.id"))
        self.session.execute(text("DROP TABLE IF EXISTS pr_ext_tmp"))

        # De la autoridad que llega DESDE FUERA (lo casado), donde cae de
        # entrada: lo que se pierde ya en la primera pagina.
        por_categoria = {c: 0.0 for c in prk.CATEGORIAS}
        cats = np.asarray(categorias)
        if externo.sum() > 0:
            for c in prk.CATEGORIAS:
                por_categoria[c] = round(float(externo[cats == c].sum() / externo.sum()), 4)
        reparto = prk.reparto(pr, categorias)
        logger.info("PageRank externo (job %s): %d de %d backlinks casados, beta %.2f",
                    self.job_id, cruce.casadas, cruce.filas, beta)
        return {
            "import_id": imp.id, "fuente": imp.fuente,
            "fecha_dato": imp.fecha_dato.isoformat() if imp.fecha_dato else None,
            "subido": imp.created_at.isoformat() if imp.created_at else None,
            "backlinks": cruce.filas, "casados": cruce.casadas, "parte_casada": cruce.parte_casada,
            # Lo que el proveedor marca como spam y los nofollow: cuentan en
            # `backlinks`, no aportan.
            "spam": cruce.spam, "spam_casados": cruce.spam_casados,
            "nofollow": cruce.nofollow, "nofollow_casados": cruce.nofollow_casados,
            "paginas_con_backlinks": len(cruce.por_url), "beta": beta,
            "entra_en": por_categoria, "reparto": reparto,
            "desperdiciado": prk.desperdiciado(reparto),
            "no_rastreadas": cruce.no_rastreadas[:20],
        }

    def _fiabilidad_del_grafo(self) -> dict:
        """Dice si el grafo de enlaces es fiable, segun la comprobacion de render.

        `jobs.js_check` lo rellena `scripts/check_js_templates.py` al cerrar un
        rastreo SIN `render_js`: si alguna plantilla esconde enlaces en
        JavaScript, el grafo esta incompleto y el PageRank sale de un grafo
        parcial. NULL = no se llego a comprobar (p. ej. el rastreo ya iba con
        render), y entonces no se afirma nada.
        """
        from shared.models import Job

        js_check = self.session.execute(
            select(Job.js_check).where(Job.id == self.job_id)
        ).scalar()
        if not isinstance(js_check, dict):
            return {"grafo_fiable": None}
        fiable = js_check.get("grafo_fiable")
        if fiable is False:
            plantillas = [
                p.get("plantilla")
                for p in (js_check.get("plantillas") or [])
                if p.get("enlaces_solo_js")
            ]
            return {
                "grafo_fiable": False,
                "aviso": (
                    "PageRank calculado sin render: hay plantillas con enlaces "
                    "solo en JavaScript, asi que el grafo esta incompleto. "
                    "Re-rastrear con render_js=true antes de fiarse de estas "
                    "cifras."
                ),
                "plantillas_con_enlaces_js": [p for p in plantillas if p][:10],
            }
        return {"grafo_fiable": bool(fiable)}

    def _aristas_de_enlaces(self) -> str:
        """Crea `pr_edges_tmp` con las aristas de `links`. Devuelve el modo.

        Peso por repeticion medida (ver `analysis/pagerank.py`): la fraccion
        de paginas de origen que llevan el mismo enlace, destino + anchor, en
        todo el sitio y en su seccion (host + primer segmento); cuenta la
        mayor. Si hay menos de MIN_FUENTES_REPETICION paginas con enlaces, la
        fraccion es ruido y se usa el peso por posicion.
        """
        jid = {"jid": self.job_id}
        temporales = ("pr_fuentes_tmp", "pr_lk_tmp", "pr_rep_tmp", "pr_sec_tmp")
        for tabla in ("pr_edges_tmp",) + temporales:
            self.session.execute(text(f"DROP TABLE IF EXISTS {tabla}"))

        self.session.execute(text(
            r"""
            CREATE TEMP TABLE pr_fuentes_tmp AS
            SELECT id, dense_rank() OVER (ORDER BY sec)::int AS sec
            FROM (
                SELECT u.id,
                       COALESCE(substring(u.url FROM '^https?://[^/?#]+(?:/[^/?#]*)?'), '')
                           AS sec
                FROM urls u
                WHERE u.job_id = :jid AND u.status_code = 200
                  AND u.noindex IS NOT TRUE AND EXISTS (
                    SELECT 1 FROM links l
                    WHERE l.from_url_id = u.id AND l.job_id = :jid
                      AND l.is_internal AND l.follow
                )
            ) x
            """
        ), jid)
        self.session.execute(text("ANALYZE pr_fuentes_tmp"))
        n_fuentes = self.session.execute(
            text("SELECT COUNT(*) FROM pr_fuentes_tmp")
        ).scalar() or 0

        anchor = "COALESCE(lower(btrim(l.anchor_text)), '')"
        if n_fuentes < prk.MIN_FUENTES_REPETICION:
            self.session.execute(text(
                f"""
                CREATE TEMP TABLE pr_edges_tmp AS
                SELECT l.from_url_id AS src, u.id AS dst,
                       MAX({prk.sql_peso_posicion('l.link_position')})::real AS w
                FROM links l
                JOIN urls u ON u.url_hash = l.to_url_hash AND u.job_id = l.job_id
                JOIN urls o ON o.id = l.from_url_id
                WHERE l.job_id = :jid AND l.is_internal AND l.follow
                  AND u.is_internal AND l.from_url_id <> u.id
                  AND o.status_code = 200 AND o.noindex IS NOT TRUE
                GROUP BY 1, 2
                """
            ), jid)
            self.session.execute(text("DROP TABLE IF EXISTS pr_fuentes_tmp"))
            return "posicion"

        # Los enlaces, UNA vez, con todo lo que piden los dos pasos caros ya
        # resuelto, y UNA fila por (origen, destino, ancla).
        #
        # Claves enteras y no texto (#52): el destino es su id, la seccion un
        # entero (`pr_fuentes_tmp`) y el ancla su md5 como uuid. Con el hash de
        # la URL, el ancla y la seccion en texto, cada fila arrastraba ~140
        # bytes de claves que se ordenaban con la collation del idioma: 710 MB
        # a disco solo en `pr_rep_tmp` de penguin-libros (5,1 M de filas).
        #
        # Una fila por (origen, destino, ancla) con el MAYOR peso de posicion:
        # la repeticion cuenta ORIGENES distintos, que con esta tabla es un
        # COUNT(*) sin DISTINCT, y el peso de la arista es
        # max(min(posicion, techo)), que es min(max(posicion), techo) porque el
        # techo no depende de la posicion. Mismo resultado que guardar cada
        # posicion por separado.
        #
        # Solo destinos internos que estan en el censo: los demas no dan arista,
        # y su repeticion es por destino, asi que no cambia la de ningun otro.
        self.session.execute(text(
            f"""
            CREATE TEMP TABLE pr_lk_tmp AS
            SELECT l.from_url_id AS src, u.id AS dst, md5({anchor})::uuid AS anc,
                   f.sec, MAX({prk.sql_peso_posicion('l.link_position')}) AS pw
            FROM links l
            JOIN pr_fuentes_tmp f ON f.id = l.from_url_id
            JOIN urls u ON u.job_id = :jid AND u.url_hash = l.to_url_hash
            WHERE l.job_id = :jid AND l.is_internal AND l.follow AND u.is_internal
            GROUP BY 1, 2, 3, 4
            """
        ), jid)
        self.session.execute(text("ANALYZE pr_lk_tmp"))
        # Cuantas paginas de cada seccion llevan el enlace (c) y cuantas del
        # sitio (cg). Cada pagina esta en una sola seccion, asi que el total
        # del sitio es la suma de sus secciones.
        self.session.execute(text(
            """
            CREATE TEMP TABLE pr_rep_tmp AS
            SELECT dst, anc, sec, c, SUM(c) OVER (PARTITION BY dst, anc) AS cg
            FROM (
                SELECT dst, anc, sec, COUNT(*) AS c
                FROM pr_lk_tmp GROUP BY 1, 2, 3
            ) x
            """
        ))
        self.session.execute(text(
            "CREATE TEMP TABLE pr_sec_tmp AS "
            "SELECT sec, COUNT(*) AS n FROM pr_fuentes_tmp GROUP BY 1"
        ))
        for tabla in ("pr_rep_tmp", "pr_sec_tmp"):
            self.session.execute(text(f"ANALYZE {tabla}"))

        repeticion = (
            "GREATEST(r.cg::float8 / :n_fuentes, "
            "CASE WHEN sn.n >= :min_sec THEN r.c::float8 / sn.n ELSE 0.0 END)"
        )
        techo = prk.sql_techo_por_repeticion(repeticion)
        self.session.execute(text(
            f"""
            CREATE TEMP TABLE pr_edges_tmp AS
            SELECT lk.src, lk.dst, MAX(LEAST(lk.pw, {techo}))::real AS w
            FROM pr_lk_tmp lk
            JOIN pr_rep_tmp r ON r.dst = lk.dst AND r.anc = lk.anc AND r.sec = lk.sec
            JOIN pr_sec_tmp sn ON sn.sec = lk.sec
            WHERE lk.src <> lk.dst
            GROUP BY 1, 2
            """
        ), {**jid, "n_fuentes": n_fuentes, "min_sec": prk.MIN_FUENTES_SECCION})
        for tabla in temporales:
            self.session.execute(text(f"DROP TABLE IF EXISTS {tabla}"))
        return "repeticion"

    # -- Link Analysis ------------------------------------------------------

    def _topes_cortaron(self) -> bool:
        """True si algun tope de `topes_por_carpeta` dejo URLs sin pedir
        (decision 172).

        Entonces el censo esta truncado y NO solo en el grupo cortado: las
        paginas que el tope no pidio tambien enlazan a otras carpetas (un post
        de /blog/ sin pedir puede ser el unico que enlaza a /producto/x). Que
        una URL no tenga entrantes, o que no se llegue a ella desde la home, no
        se puede afirmar en ninguna parte del censo (decisiones 67 y 70).
        """
        from shared.topes_carpeta import corto

        return corto(self._topes_carpeta)

    def analyze_links(self) -> None:
        """Link analysis -- flag orphan pages and pages with excessive outlinks."""
        logger.debug("Analyzing links ...")

        # Orphan pages: internal HTML pages with 0 inlinks. Seed pages
        # (crawl_depth 0, e.g. the homepage) legitimately have no discovered
        # inlinks and must not be flagged as orphans. Only 200-OK internal
        # pages are considered — a 404/redirect having no inlinks is not an
        # "orphan" in the SEO sense.
        #
        # Tampoco el destino de una redireccion interna: los enlaces apuntan a
        # la URL vieja, asi que el destino tiene 0 inlinks y salia huerfano.
        # Toda migracion o paso de http a https llenaba el informe de
        # huerfanas falsas.
        stmt = (
            select(Url.id)
            .where(
                Url.job_id == self.job_id,
                Url.is_html.is_(True),
                Url.is_internal.is_(True),
                Url.status_code == 200,
                (Url.crawl_depth.is_(None)) | (Url.crawl_depth > 0),
                (Url.inlinks_count.is_(None)) | (Url.inlinks_count == 0),
                ~_es_destino_de_redireccion(),
                # Las que estan en el sitemap las cuenta `analyze_sitemap` como
                # `sitemap_orphan`, que dice lo mismo pero mas fuerte: esta
                # declarada para indexar y aun asi nadie la enlaza. Emitir los
                # dos avisos sobre la misma URL es ruido, y hacia que el
                # informe pareciera tener el doble de problemas.
                (Url.in_sitemap.isnot(True)),
            )
        )
        rows = self.session.execute(stmt).all()

        # La canonica que nadie enlaza ya tiene su aviso, que dice que hay que
        # hacer (decision 101): un aviso por hallazgo.
        sin_enlazar = self._avisar_canonical_sin_enlazar()
        # La que solo cuelga de paginas 2+ en noindex o canonicalizadas a la 1
        # tiene su aviso, que dice de donde cuelga (decision 122).
        # Con un tope que corto, «solo la enlaza la paginacion» tampoco se
        # afirma: la pueden enlazar paginas que no se pidieron (decision 172).
        if self._topes_cortaron():
            desde_paginacion = avisos_de_paginacion.sustituidas(self)
            rows = []
        else:
            desde_paginacion = avisos_de_paginacion.avisar_solo_desde_paginacion(
                self, excluir=sin_enlazar)
        for (url_id,) in rows:
            if url_id not in sin_enlazar and url_id not in desde_paginacion:
                self._add_issue(url_id, "orphan_page", "warning")

        self._avisar_solo_por_redireccion()

        # Demasiados enlaces salientes, contando solo los EDITORIALES.
        #
        # Criterio SEO: lo que preocupa de una pagina con cientos de enlaces es
        # que diluya el presupuesto de rastreo y el reparto de autoridad entre
        # sus enlaces propios. Un megamenu de 500 entradas repetido en todo el
        # sitio no es eso: es un hecho de la plantilla, igual en todas las
        # paginas, y no dice nada de ninguna. Por eso se cuentan destinos
        # DISTINTOS en `content` y no instancias en toda la pagina.
        #
        # Medido en blogs.uoc.edu (34.704 URLs): con `outlinks_count` avisaban
        # 7.011 paginas, el 24% de las HTML; deduplicando, 6.578 —apenas
        # ayuda, porque lo que infla es la plantilla—; contando solo contenido,
        # 51. El 99,3% del aviso era ruido que el cliente leia como problemas.
        # Se filtra por `links.job_id` y NO uniendo con `urls`: la tabla de
        # enlaces guarda los de TODOS los rastreos —46 GB y 181 millones de
        # filas en esta instalacion— y poner el job en el lado de `urls` deja
        # el filtro fuera del alcance del indice. Medido con EXPLAIN: recorrido
        # secuencial de la tabla entera, coste 6.189.456, frente a 122.247
        # filtrando aqui. Cincuenta veces.
        enlaces_de_contenido = (
            select(
                Link.from_url_id.label("url_id"),
                func.count(func.distinct(Link.to_url_hash)).label("destinos"),
            )
            .where(
                Link.job_id == self.job_id,
                Link.is_internal.is_(True),
                Link.link_position == "content",
                # Un nofollow no reparte autoridad: no diluye nada.
                Link.follow.is_(True),
            )
            .group_by(Link.from_url_id)
            .having(func.count(func.distinct(Link.to_url_hash)) > self.max_outlinks)
        )

        for url_id, destinos in self.session.execute(enlaces_de_contenido).all():
            self._add_issue(
                url_id,
                "high_outlink_count",
                "info",
                {"count": destinos, "criterio": "destinos distintos en contenido"},
            )

        self._flush_issues()

    def _ids_canonical_sin_enlazar(self) -> dict[int, dict[str, Any]]:
        """Canonicas a las que no llega ni un enlace interno, y sus variantes.

        `{url_id: detalle}` de las paginas que cumplen las dos cosas
        (decision 101):

        - la canonica: HTML interna, 200, indexable, con `inlinks_count` = 0
          —que ya descuenta los enlaces desde `noindex` y desde paginas que no
          dan 200, decisiones 38 y 57—, que no es semilla (misma exclusion que
          `orphan_page`) ni destino de una redireccion (eso es
          `solo_enlazada_por_redireccion`, decision 63);
        - al menos una variante —200 y canonicalizada a ella— que SI recibe
          enlaces desde FUERA del grupo (ni de la canonica ni de otra variante
          suya). Si tampoco las variantes estan enlazadas, la pagina es
          huerfana de verdad y lo dice `orphan_page` / `sitemap_orphan`.

        `inlinks_count` NULL es «no se sabe» y no entra. Con los enlaces
        archivados (decision 95) no se calcula: los conteos no se pueden
        rehacer, y un aviso sobre conteos rancios seria inventado.
        """
        if getattr(self, "_cache_canonical_sin_enlazar", None) is not None:
            return self._cache_canonical_sin_enlazar
        resultado: dict[int, dict[str, Any]] = {}
        self._cache_canonical_sin_enlazar = resultado
        if self._enlaces_archivados:
            logger.warning(
                "canonical_sin_enlazar: los enlaces del job %s estan archivados; "
                "no se evalua", self.job_id,
            )
            return resultado

        candidatas = self.session.execute(
            select(Url.id, Url.url, Url.in_sitemap).where(
                Url.job_id == self.job_id,
                Url.is_html.is_(True),
                Url.is_internal.is_(True),
                Url.status_code == 200,
                Url.indexable.is_(True),
                Url.inlinks_count == 0,
                (Url.crawl_depth.is_(None)) | (Url.crawl_depth > 0),
                ~_es_destino_de_redireccion(),
            )
        ).all()
        if not candidatas:
            return resultado
        por_clave: dict[Any, tuple[int, bool]] = {}
        for uid, url, en_sitemap in candidatas:
            por_clave[url] = (uid, bool(en_sitemap))
            k = _clave(url)
            if k is not None:
                por_clave.setdefault(k, (uid, bool(en_sitemap)))

        variantes = self.session.execute(
            select(Url.id, Url.url, Url.url_hash, Url.inlinks_count,
                   HtmlMeta.canonical_href, HtmlMeta.canonical_header)
            .join(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(
                Url.job_id == self.job_id,
                Url.is_internal.is_(True),
                Url.status_code == 200,
                Url.indexability_status == "Canonicalised",
            )
        ).all()
        # canonica -> [(id, url, hash, inlinks)] de sus variantes
        grupos: dict[int, list[tuple[int, str, str, int]]] = defaultdict(list)
        en_sitemap_de: dict[int, bool] = {}
        for vid, url, h, inlinks, c_href, c_cab in variantes:
            canonical = (c_href or "").strip() or (c_cab or "").strip()
            if not canonical or misma_url(canonical, url):
                continue
            hallada = por_clave.get(canonical)
            if hallada is None:
                hallada = por_clave.get(_clave(canonical))
            if hallada is None:
                continue
            uid, en_sitemap = hallada
            grupos[uid].append((vid, url, h, int(inlinks or 0)))
            en_sitemap_de[uid] = en_sitemap

        # Un enlace a la variante desde la propia canonica o desde otra
        # variante suya no dice que el SITIO enlace ese contenido: es el
        # selector de color o de talla de la ficha. Con solo esos, el grupo
        # entero es huerfano y lo sigue diciendo `orphan_page` /
        # `sitemap_orphan`. Se cuentan los de fuera con el mismo criterio que
        # `inlinks_count` (origen 200 y no noindex, SUM(repeticiones),
        # decision 94), filtrando el job en `links` (decision 37).
        hash_a_grupo: dict[str, tuple[int, int]] = {}
        for uid, vs in grupos.items():
            for vid, _url, h, inlinks in vs:
                if inlinks > 0 and h:
                    hash_a_grupo[h] = (uid, vid)
        de_fuera: dict[int, int] = defaultdict(int)
        if hash_a_grupo:
            miembros = {uid: {uid} | {v[0] for v in vs} for uid, vs in grupos.items()}
            origen = aliased(Url)
            hashes = list(hash_a_grupo)
            for n in range(0, len(hashes), 500):
                lote = hashes[n:n + 500]
                filas = self.session.execute(
                    select(Link.to_url_hash, Link.from_url_id,
                           func.sum(Link.repeticiones))
                    .join(origen, origen.id == Link.from_url_id)
                    .where(
                        Link.job_id == self.job_id,
                        Link.to_url_hash.in_(lote),
                        origen.status_code == 200,
                        origen.noindex.isnot(True),
                    )
                    .group_by(Link.to_url_hash, Link.from_url_id)
                ).all()
                for h, desde, veces in filas:
                    uid, vid = hash_a_grupo[h]
                    if desde in miembros[uid]:
                        continue
                    de_fuera[vid] += int(veces or 0)

        for uid, vs in grupos.items():
            d = {
                "variantes": len(vs), "variantes_enlazadas": 0,
                "enlaces_a_variantes": 0, "ejemplos_variante": [],
                "en_sitemap": en_sitemap_de[uid],
            }
            for vid, url, _h, _inlinks in vs:
                fuera = de_fuera.get(vid, 0)
                if fuera > 0:
                    d["variantes_enlazadas"] += 1
                    d["enlaces_a_variantes"] += fuera
                    if len(d["ejemplos_variante"]) < 5:
                        d["ejemplos_variante"].append(url)
            if d["variantes_enlazadas"]:
                resultado[uid] = d
        return resultado

    def _avisar_canonical_sin_enlazar(self) -> dict[int, dict[str, Any]]:
        """La canonica que el sitio no enlaza: enlaza sus variantes.

        Google usa los enlaces internos como una senal mas de cual es la
        canonica, y cuando todos apuntan a la variante puede quedarse con ella
        e ignorar el canonical declarado. El arreglo es concreto: que los
        enlaces apunten a la canonica. `warning`, como `orphan_page`, que es el
        aviso que sustituye en esas paginas.
        """
        ids = self._ids_canonical_sin_enlazar()
        if self._topes_cortaron():  # decision 172
            return ids
        for uid, detalle in ids.items():
            self._add_issue(uid, "canonical_sin_enlazar", "warning", dict(detalle))
        return ids

    def _avisar_solo_por_redireccion(self) -> None:
        """Paginas a las que SOLO se llega por un salto: ni un enlace directo.

        Excluir los destinos de redireccion de `orphan_page` (decision 36) evita
        llenar el informe de huerfanas falsas tras una migracion, pero abrio un
        agujero: una pagina indexable, con 200 y CERO enlaces internos, a la que
        solo se llega a traves de un 301, no recibia ningun aviso. Medido
        sobre los tres censos: **522 paginas asi en www.uoc.edu, 363 de ellas
        declaradas en el sitemap**, 109 en blogs.uoc.edu (las 109 en sitemap) y
        1 en progym —que resulta ser la pagina MAS fuerte del sitio por
        PageRank, porque hereda el de la URL vieja que todo el mundo sigue
        enlazando—. Ninguna tenia un solo issue antes de esto.

        No es `orphan_page`: la pagina es alcanzable, y por el salto le llega
        casi toda la senal. Lo que hay que arreglar es otra cosa y es concreta:
        los enlaces internos apuntan a la URL vieja, y Google acaba dejando de
        rastrearla. Si ademas esta en el sitemap, se esta declarando para
        indexar algo que el propio sitio no enlaza: eso es `warning`; sin
        sitemap, `info`.
        """
        origen = aliased(Url)
        filas = self.session.execute(
            select(
                Url.id,
                Url.in_sitemap,
                func.count(origen.id).label("saltos"),
                func.min(origen.url).label("ejemplo"),
            )
            .join(
                origen,
                and_(
                    origen.job_id == Url.job_id,
                    origen.redirect_url == Url.url,
                    origen.is_internal.is_(True),
                ),
            )
            .where(*criterio_solo_por_redireccion(Url, self.job_id))
            .group_by(Url.id, Url.in_sitemap)
        ).all()

        if self._topes_cortaron():  # decision 172
            filas = []
        for url_id, en_sitemap, saltos, ejemplo in filas:
            self._add_issue(
                url_id,
                "solo_enlazada_por_redireccion",
                "warning" if en_sitemap else "info",
                {
                    "saltos_que_apuntan": saltos,
                    "ejemplo_origen": ejemplo,
                    "en_sitemap": bool(en_sitemap),
                },
            )

    # -- Sitemap --------------------------------------------------------------

    def analyze_sitemap(self) -> None:
        """Sitemap coverage checks (Screaming Frog "Sitemaps" tab parity).

        Runs only when the crawl ingested a sitemap (some ``in_sitemap`` is
        True); otherwise all rows are NULL and there is nothing to compare.

        - ``sitemap_orphan``: URL listed in the sitemap but with zero internal
          inlinks — only reachable through the sitemap. Stronger signal than
          plain ``orphan_page``.
        - ``not_in_sitemap``: indexable internal 200 HTML page missing from
          the sitemap — should probably be listed.
        - ``sitemap_no_indexable`` (decision 100): URL declarada en el sitemap
          que no es indexable — salto, 4xx, 5xx, noindex, canonicalizada a
          otra, bloqueada por robots.txt o sin contenido —, una por URL y con el
          motivo en ``details``. Sustituye a ``sitemap_orphan`` en esas
          paginas: lo que hay que arreglar es la contradiccion, no el enlazado
          (decision 36).

        No lee ``links``: solo ``urls`` y ``html_meta``, asi que vale igual en
        un censo con los enlaces archivados (decision 95).
        """
        logger.debug("Analyzing sitemap coverage ...")

        has_sitemap = self.session.execute(
            select(func.count(Url.id)).where(
                Url.job_id == self.job_id, Url.in_sitemap.is_(True),
            )
        ).scalar() or 0
        if not has_sitemap:
            return

        # In sitemap but not linked internally (run after compute_link_counts).
        rows = self.session.execute(
            select(Url.id).where(
                Url.job_id == self.job_id,
                Url.in_sitemap.is_(True),
                Url.is_html.is_(True),
                Url.status_code == 200,
                _respuesta_valida(),
                (Url.crawl_depth.is_(None)) | (Url.crawl_depth > 0),
                (Url.inlinks_count.is_(None)) | (Url.inlinks_count == 0),
                # Una no indexable del sitemap ya lleva sitemap_no_indexable,
                # y «enlazala» seria el consejo equivocado: lo que sobra es la
                # entrada del sitemap o la directiva (decision 100).
                Url.indexable.isnot(False),
                ~_es_destino_de_redireccion(),
            )
        ).all()
        sin_enlazar = self._ids_canonical_sin_enlazar()
        desde_paginacion = avisos_de_paginacion.sustituidas(self)  # decision 122
        if self._topes_cortaron():  # decision 172
            rows = []
        for (url_id,) in rows:
            if url_id not in sin_enlazar and url_id not in desde_paginacion:
                self._add_issue(url_id, "sitemap_orphan", "warning")

        self._sitemap_no_indexable()

        # Indexable page the sitemap forgot.
        rows = self.session.execute(
            select(Url.id).where(
                Url.job_id == self.job_id,
                Url.in_sitemap.is_(False),
                Url.is_internal.is_(True),
                Url.is_html.is_(True),
                Url.status_code == 200,
                Url.indexable.is_(True),
            )
        ).all()
        for (url_id,) in rows:
            self._add_issue(url_id, "not_in_sitemap", "info")

        self._flush_issues()

    def _sitemap_no_indexable(self) -> None:
        """URLs que el sitemap declara y que Google no va a indexar (decision 100).

        El sitemap es la lista de URLs canonicas que el sitio pide indexar;
        cada entrada que salta, falla, lleva noindex o se canonicaliza a otra
        es una instruccion que la propia pagina contradice. Una incidencia por
        URL —es la URL la que hay que quitar del sitemap, o la directiva la que
        esta mal— con el motivo, el codigo y el destino en ``details``.

        Lo que no se sabe no se afirma: un 429 o un 503 es el sitio frenando
        al rastreador y una URL sin respuesta no dice como la ve Google, asi
        que no se emiten (se cuentan en el log).
        """
        rows = self.session.execute(
            select(
                Url.id, Url.status_code, Url.indexability_status,
                Url.redirect_url, HtmlMeta.canonical_href,
                HtmlMeta.canonical_header,
            )
            .outerjoin(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(
                Url.job_id == self.job_id,
                Url.in_sitemap.is_(True),
                Url.is_internal.is_(True),
                Url.indexable.isnot(True),
                # Un muro no es la respuesta del sitio: «4xx» seria afirmar lo
                # que no se ha visto (decision 103).
                _respuesta_valida(),
            )
        ).all()

        por_motivo: dict[str, int] = defaultdict(int)
        sin_comprobar = 0
        for url_id, codigo, estado, salto, canonical, canonical_cab in rows:
            motivo = motivo_sitemap_no_indexable(codigo, estado)
            if motivo is None:
                sin_comprobar += 1
                continue
            por_motivo[motivo] += 1
            details: dict[str, Any] = {
                "motivo": motivo,
                "status_code": codigo,
                "indexability_status": estado,
            }
            if motivo == "redireccion" and salto:
                details["destino"] = salto
            elif motivo == "canonicalizada" and (canonical or canonical_cab):
                details["destino"] = canonical or canonical_cab
            self._add_issue(url_id, "sitemap_no_indexable", "warning", details)

        if por_motivo or sin_comprobar:
            logger.info(
                "Sitemap: %d URLs declaradas no indexables (%s); %d sin "
                "comprobar (429, 503 o sin respuesta)",
                sum(por_motivo.values()),
                ", ".join(f"{m}={n}" for m, n in sorted(por_motivo.items())),
                sin_comprobar,
            )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _es_redireccion(status: int | None) -> bool:
    """3xx, o sin codigo cuando la redireccion la siguio el navegador (render
    JS, decision 27: se guarda `redirect_url` con el salto sin codigo)."""
    return status is None or 300 <= status < 400


def _es_error(status: int | None) -> bool:
    """¿El codigo dice que ahi NO hay pagina? 4xx y 5xx, salvo el 429.

    Un 429 es el sitio frenando al rastreador, no la respuesta que vera
    Google: en el censo de penguin, 35 de las 132 redirecciones que «acababan
    en 4xx» acababan en un 429. Afirmar que ahi hay un error seria inventarlo.
    """
    return status is not None and 400 <= status < 600 and status != 429


def _solo_normaliza(a: str | None, b: str | None) -> bool:
    """¿*a* y *b* son la misma ruta salvo el esquema, el `www` o la barra
    final? Es la forma de una redireccion de normalizacion (http → https,
    sin-www → www, `/a` → `/a/`), que esta bien hecha aunque el destino falle:
    lo que hay que arreglar entonces es el destino, y ya avisa en su URL.
    """
    if not a or not b:
        return False
    try:
        _, ha, ra, qa = clave_url(a)
        _, hb, rb, qb = clave_url(b)
    except Exception:
        return False

    def _host(h: str) -> str:
        return h[4:] if h.startswith("www.") else h

    def _ruta(r: str) -> str:
        return r.rstrip("/") or "/"

    return _host(ha) == _host(hb) and _ruta(ra) == _ruta(rb) and qa == qb


# Lo que en la raiz de un sitio (o de un idioma) es la propia portada con otro
# nombre: redirigirlo a `/` es consolidarla, no tirar una pagina.
_ALIAS_DE_PORTADA = frozenset({
    "index", "index.html", "index.htm", "index.php", "index.asp", "index.aspx",
    "index.jsp", "default.asp", "default.aspx", "home", "home.html", "inicio",
    "portada", "start", "accueil", "startseite",
})


def _redirige_a_portada(origen: str | None, final: str | None) -> bool:
    """¿La redireccion de *origen* acaba en una portada (`/` o la de un idioma,
    `/es/`) sin que *origen* lo sea? (decision 228)

    No cuenta lo que ya es la portada: otra portada (`/es/` → `/`, el idioma
    por el navegador), un alias (`/index.html`, `/inicio`), la propia con
    parametros (`/?utm_source=x`) ni un http → https o un www.
    """
    from shared.soft404 import es_portada

    if not origen or not final or _solo_normaliza(origen, final):
        return False
    try:
        ruta_final = urlsplit(final).path
        ruta_origen = urlsplit(origen).path
    except ValueError:
        return False
    if not es_portada(ruta_final) or es_portada(ruta_origen):
        return False
    tramos = [t for t in ruta_origen.split("/") if t]
    if tramos and tramos[-1].lower() in _ALIAS_DE_PORTADA and es_portada("/".join(tramos[:-1])):
        return False
    return True


def _buscar_en(por_url: dict[Any, Any], url: str | None):
    """Busca *url* tal cual y, si no esta, por su clave de `misma_url`."""
    if not url:
        return None
    v = por_url.get(url)
    if v is None:
        k = _clave(url)
        if k is not None:
            v = por_url.get(k)
    return v


def _a_https(url: str) -> str:
    return "https://" + url.split("://", 1)[1] if "://" in url else url


def _estado_por_url(session: Session, job_id) -> dict[Any, int | None]:
    """Codigo de cada URL del job, por la URL tal cual y por su clave."""
    estado: dict[Any, int | None] = {}
    for url, sc, clase in session.execute(
        select(Url.url, Url.status_code, Url.response_class)
        .where(Url.job_id == job_id)
    ).all():
        # Un muro no dice que responde la URL: NULL, como sin rastrear
        # (decision 103). Si no, una redireccion hacia un desafio de 403 seria
        # `redireccion_a_error`.
        if clase in NO_VALIDAS:
            sc = None
        estado[url] = sc
        k = _clave(url)
        if k is not None:
            estado.setdefault(k, sc)
    return estado


# Google sigue hasta 10 redirecciones; pasadas esas no llega al contenido y
# Search Console da un error de redireccion. Se lee asi la documentacion: 10
# saltos seguidos de contenido llegan, 11 no (sin medir contra Google). El
# umbral del job (`max_redirect_chain_length`) no lo mueve (decision 117).
LIMITE_SALTOS_GOOGLE = 10


# El estado que el spider pone a una pagina 200 que redirige con meta refresh
# (y a su salto, con render). No es la pagina: es una redireccion (120).
ESTADO_META_REFRESH = "Redirect (meta refresh)"


class _Ficha:
    __slots__ = ("id", "url", "status_code", "redirect_url", "noindex", "canonical",
                 "meta_refresh")

    def __init__(self, id, url, status_code, redirect_url, noindex, canonical,
                 meta_refresh=False):
        self.id = id
        self.url = url
        self.status_code = status_code
        self.redirect_url = (redirect_url or "").strip() or None
        self.noindex = noindex
        self.canonical = (canonical or "").strip() or None
        self.meta_refresh = bool(meta_refresh)

    @property
    def redirige(self) -> bool:
        """Un 3xx (o un salto sin codigo, con render) con destino, o una meta
        refresh: un 200 con `redirect_url`. `analyze_redirect_chains` ya seguia
        las dos y aqui solo la primera, asi que la misma cadena tenia dos
        recorridos (B6 de #150, decision 120)."""
        return bool(self.redirect_url) and (
            _es_redireccion(self.status_code) or self.meta_refresh)


class _Fichas:
    """Las URLs del job con lo que hace falta para seguir un canonical o una
    redireccion hasta el final (decision 101).

    Se buscan por la URL tal cual y por la clave de `misma_url` (decision 39):
    con otro normalizador el mismo destino seria «rastreado» para la
    indexabilidad y «desconocido» aqui. El canonical de cada una es el que
    usa la indexabilidad: el del HTML y, si no hay, el de la cabecera `Link`.
    """

    MAX_SALTOS = 20

    def __init__(self, session: Session, job_id) -> None:
        self._por_url: dict[Any, _Ficha] = {}
        filas = session.execute(
            select(
                Url.id, Url.url, Url.status_code, Url.redirect_url, Url.noindex,
                HtmlMeta.canonical_href, HtmlMeta.canonical_header,
                Url.response_class, HtmlMeta.canonical_distintos,
                Url.indexability_status,
            )
            .outerjoin(HtmlMeta, HtmlMeta.url_id == Url.id)
            .where(Url.job_id == job_id)
        ).all()
        for uid, url, sc, red, noindex, c_href, c_cab, clase, distintos, estado in filas:
            # Un muro delante del destino no dice que responde: como si no se
            # hubiera rastreado (decision 103).
            if clase in NO_VALIDAS:
                continue
            canonical = (c_href or "").strip() or (c_cab or "").strip()
            # Con varios canonicals distintos Google no usa ninguno: el destino
            # es autocanonico de hecho, no el eslabon de una cadena (115).
            if distintos is not None and distintos > 1:
                canonical = None
            f = _Ficha(uid, url, sc, red, noindex, canonical,
                       meta_refresh=estado == ESTADO_META_REFRESH)
            self._por_url[url] = f
            k = _clave(url)
            if k is not None:
                self._por_url.setdefault(k, f)

    def buscar(self, url: str | None) -> _Ficha | None:
        if not url:
            return None
        f = self._por_url.get(url)
        if f is None:
            k = _clave(url)
            if k is not None:
                f = self._por_url.get(k)
        return f

    def seguir_redirecciones(self, inicio: _Ficha):
        """``(final, cadena, bucle)``. `final` es None si la cadena sale de lo
        rastreado o hace bucle: ahi no se sabe donde acaba."""
        cadena = [inicio.url]
        vistos = {inicio.id}
        actual = inicio
        for _ in range(self.MAX_SALTOS):
            if not actual.redirige:
                return actual, cadena, False
            sig = self.buscar(actual.redirect_url)
            cadena.append(actual.redirect_url)
            if sig is None:
                return None, cadena, False
            if sig.id in vistos:
                return None, cadena, True
            vistos.add(sig.id)
            actual = sig
        return None, cadena, False

    def seguir_canonicals(self, page_url: str, inicio: _Ficha):
        """``(cadena, final, bucle)`` desde la pagina A por los canonicals.

        Se para en la primera pagina autocanonica o que no da 200 (ahi el
        canonical ya no cuenta), y `final` es esa. Si vuelve a una ya vista,
        bucle y `final` None: Google ignora los dos canonicals.
        """
        cadena = [page_url, inicio.url]
        vistos = {_clave(page_url), _clave(inicio.url)}
        actual = inicio
        for _ in range(self.MAX_SALTOS):
            if (actual.status_code != 200 or actual.noindex or not actual.canonical
                    or misma_url(actual.canonical, actual.url)):
                return cadena, actual, False
            k = _clave(actual.canonical)
            cadena.append(actual.canonical)
            if k in vistos:
                return cadena, None, True
            vistos.add(k)
            sig = self.buscar(actual.canonical)
            if sig is None:
                return cadena, None, False
            if sig.redirige:
                sig, _, _ = self.seguir_redirecciones(sig)
                if sig is None:
                    return cadena, None, False
            if sig.id == actual.id:
                # El canonical de `actual` es una variante suya que redirige
                # de vuelta a ella (barra final, http): es autocanonica de
                # hecho, no un bucle. Lo que tenga de malo lo avisa en su URL.
                return cadena, actual, False
            actual = sig
        return cadena, None, False


# Prefijo de `indexability_status` (shared/indexabilidad.py) -> motivo de
# `sitemap_no_indexable`. Lo que no esta aqui ("Sin respuesta", "Indexable",
# NULL) no se afirma.
_MOTIVOS_SITEMAP = (
    ("Redirect", "redireccion"),
    ("Client Error", "4xx"),
    ("Server Error", "5xx"),
    ("Noindex", "noindex"),
    ("Canonicalised", "canonicalizada"),
    ("Blocked by robots.txt", "bloqueada_robots"),
    ("Sin contenido", "sin_contenido"),
)


# Respuestas que dicen «vuelve luego», no como es la pagina (decision 100).
_CODIGOS_TEMPORALES = frozenset({429, 503})


def motivo_sitemap_no_indexable(status_code, indexability_status) -> str | None:
    """Por que una URL del sitemap no es indexable, o None si no se sabe.

    El 429 y el 503 se descartan: Google documenta los dos como la senal
    temporal de «frena», y Scrapy los reintenta igual (RETRY_HTTP_CODES). Son
    el sitio frenando al rastreador, no lo que vera Google (decision 100). Un
    500 si se afirma: es un error de la pagina, no una peticion de esperar.
    """
    if status_code in _CODIGOS_TEMPORALES or not indexability_status:
        return None
    for prefijo, motivo in _MOTIVOS_SITEMAP:
        if indexability_status.startswith(prefijo):
            return motivo
    return None


def criterio_solo_por_redireccion(u, job_id) -> tuple:
    """Condiciones sobre la PAGINA FINAL de `solo_enlazada_por_redireccion`.

    En una funcion porque las leen dos: el aviso (decision 63) y los avisos de
    enlaces a una redireccion (decision 106), que no repiten el hallazgo cuando
    la URL final ya lo lleva. Dos copias del criterio acaban discrepando (23).
    """
    return (
        u.job_id == job_id,
        u.is_html.is_(True),
        u.is_internal.is_(True),
        u.status_code == 200,
        u.indexable.is_(True),
        (u.inlinks_count.is_(None)) | (u.inlinks_count == 0),
        # La semilla no: es la puerta de entrada del rastreo y no tiene
        # entrantes DESCUBIERTOS por definicion. Pasa en cuanto se siembra con
        # `http://` y el sitio salta a `https://`: el destino es la home, es
        # destino de un salto, y decir de ella que "solo se llega por una
        # redireccion" es falso. Misma exclusion que `orphan_page`.
        (u.crawl_depth.is_(None)) | (u.crawl_depth > 0),
    )


def _es_destino_de_redireccion():
    """EXISTS: la fila de `Url` es el destino de una redireccion interna.

    Los enlaces apuntan a la URL vieja, asi que el destino tiene 0 inlinks
    propios aunque este perfectamente enlazado a traves del salto.
    """
    origen = aliased(Url)
    return (
        select(origen.id)
        .where(
            origen.job_id == Url.job_id,
            origen.redirect_url == Url.url,
            origen.is_internal.is_(True),
        )
        .exists()
    )

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _clave_candado(job_id: str) -> int:
    """Clave estable de 63 bits para el advisory lock, a partir del UUID.

    La misma que toma el archivado de enlaces (`shared/candados.py`): asi no
    se archiva un censo a mitad de analizarlo (decisiones 93 y 95).
    """
    from shared.candados import clave_de_job

    return clave_de_job(job_id)


@contextmanager
def candado_de_job(job_id: str):
    """Serializa el analisis de un job. Cede True si se ha tomado el candado.

    Dos analisis del mismo job a la vez se pisan en el DELETE+INSERT de
    `issues` y DUPLICAN filas: medido en v2-experimental, 1.390 incidencias
    distintas acabaron como 4.170 filas. Pasa de verdad — un resume que
    reencola el job mientras el analisis anterior sigue vivo, o dos
    lanzamientos a mano.

    Tres detalles que parecen de fontaneria y son justo donde falla:

    1. La conexion es DEDICADA, no la sesion del analisis. Un advisory lock de
       sesion se suelta en la conexion que lo pidio, y la sesion del analyzer
       hace docenas de commits que la devuelven al pool: el unlock podia caer
       en otra conexion y fallar en silencio.
    2. El motor es `NullPool`, para que cerrar cierre DE VERDAD. Con el pool
       normal, `close()` solo devuelve la conexion y la sesion de Postgres
       sigue viva con el candado puesto.
    3. UN SOLO `yield`, y el `except` del montaje no lo envuelve. La primera
       version tenia el yield dentro de un try/except amplio: cuando el
       analisis de dentro reventaba, la excepcion entraba por el yield, la
       cazaba ese except y se cedia por segunda vez, asi que Python lanzaba
       `generator didn't stop after throw()` y el error ORIGINAL desaparecia.
       Medido: el analisis de un censo de 60.399 URLs fallo y el log solo
       decia eso. Un candado no puede tragarse los errores de lo que protege.

    En SQLite no hay advisory locks: cede True sin serializar (los tests del
    analyzer corren ahi).
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from shared.database import engine as motor_app

    motor = conexion = None
    clave = _clave_candado(job_id)
    es_postgres = False
    tomado = True
    try:
        motor = create_engine(motor_app.url, poolclass=NullPool)
        conexion = motor.connect()
        es_postgres = conexion.dialect.name.startswith("postgres")
        if es_postgres:
            tomado = bool(
                conexion.execute(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": clave}
                ).scalar()
            )
            if not tomado:
                logger.warning(
                    "El job %s ya se esta analizando: se omite esta ejecucion "
                    "para no duplicar incidencias", job_id,
                )
    except Exception:
        logger.debug("Sin candado disponible; el analisis sigue sin serializar")
        tomado = True
        es_postgres = False

    try:
        yield tomado
    finally:
        if conexion is not None:
            if es_postgres and tomado:
                try:
                    conexion.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": clave})
                except Exception:
                    pass  # al cerrar la conexion se suelta igual
            conexion.close()
        if motor is not None:
            motor.dispose()


class EnlacesArchivados(RuntimeError):
    """El job tiene sus enlaces en Parquet: no se puede analizar sin restaurar."""


def _registrar_evolucion(session, job_id) -> None:
    """`profile_runs` del job, sin dejar escapar nada (decisiones 74 y 77): el
    `try` cubre tambien el import. Un fallo aqui no puede dejar en `failed` un
    analisis que ha terminado bien."""
    try:
        from shared.evolucion import registrar_sin_fallar

        registrar_sin_fallar(session, job_id)
    except Exception:
        logger.exception("Job %s: no se pudo registrar su evolucion", job_id)


def run_analysis(job_id: str) -> None:
    """Entry point called by the crawler worker after a crawl completes.

    Creates its own database session, runs every analysis check, and
    ensures the session is closed on exit. Serializado por job: ver
    ``candado_de_job``.
    """
    with candado_de_job(job_id) as puedo:
        if not puedo:
            return
        session = SessionLocal()
        restaurado = False
        try:
            # Un censo vaciado por la retencion (decision 223) ya no tiene
            # URLs: analizarlo lo dejaria sin incidencias y le reescribiria
            # la evolucion con ceros.
            from shared.models import Job

            if session.execute(select(Job.status).where(Job.id == job_id)).scalar() == "vaciado":
                logger.warning("Job %s vaciado por la retencion: no se analiza", job_id)
                return
            # Un censo completado tiene sus enlaces en Parquet desde que acabo
            # su analisis (decision 150). Re-analizarlo —a mano, o la
            # referencia de la comparacion (decision 93)— los devuelve a
            # `links`, analiza y los vuelve a archivar, todo bajo este candado:
            # el archivado de otro proceso no puede colarse en medio.
            restaurado = _restaurar_si_archivado(session, job_id)
            analyzer = SEOAnalyzer(session, job_id)
            analyzer.run_all()
            # La fila de la evolucion del perfil (decision 130), con las
            # cifras que acaban de quedar. Aqui y no en el worker porque esto
            # cubre tambien el re-analisis a mano y el de la referencia
            # (decision 93), que cambian las cifras de un censo viejo.
            # Best-effort: nunca lanza.
            _registrar_evolucion(session, job_id)
        finally:
            if restaurado:
                _volver_a_archivar(session, job_id)
            session.close()


def _restaurar_si_archivado(session, job_id) -> bool:
    from shared import archivo_enlaces
    from shared.models import Job

    job = session.get(Job, uuid.UUID(str(job_id)))
    if job is None or not archivo_enlaces.esta_archivado(job):
        return False
    inicio = time.time()
    n = archivo_enlaces.restaurar(session, job.id)
    logger.info("Job %s: %d enlaces restaurados del Parquet para analizar (%.0f s)",
                job_id, n, time.time() - inicio)
    return True


def _volver_a_archivar(session, job_id) -> None:
    """Best-effort con el `try` entero (decision 74): si falla, los enlaces se
    quedan en `links`, que es un estado valido, y el cierre del siguiente
    rastreo lo archivara."""
    try:
        from shared import archivo_enlaces

        session.rollback()
        archivo_enlaces.archivar(session, job_id, candado_tomado=True)
    except Exception:
        session.rollback()
        logger.exception("Job %s: no se pudieron volver a archivar los enlaces; "
                         "siguen en `links`", job_id)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m analysis.analyzer <job_id>")
        sys.exit(1)
    run_analysis(sys.argv[1])
