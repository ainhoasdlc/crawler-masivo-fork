"""Pydantic schemas for the SEO crawler API."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.perfiles import (
    IMPERSONATE_POR_DEFECTO,
    PERFILES_IMPERSONATE,
    claves_deducidas,
)
from shared.config import (
    DEFAULT_CONCURRENT_REQUESTS,
    DEFAULT_CONCURRENT_REQUESTS_PER_DOMAIN,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_URLS,
    DEFAULT_USER_AGENT,
)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------
class Recommendation(BaseModel):
    priority: str
    title: str
    description: str
    affected_count: int
    issue_types: list[str] = []
    url_filter: dict[str, Any] = {}


class CategoryInsight(BaseModel):
    key: str
    name: str
    score: int
    icon: str
    metrics: dict[str, Any]
    recommendations: list[Recommendation]


class TopeDeNota(BaseModel):
    """Por que la nota global no pasa de cierto valor (UX-05)."""
    tope: int
    paginas_con_error: int
    de: int
    pct: float
    motivo: str


class InsightsResponse(BaseModel):
    job_id: uuid.UUID
    overall_score: int
    # La media ponderada antes del tope. Se devuelve para que se vea cuanto
    # recorta: un 88 que baja a 49 no es lo mismo que un 52 que baja a 49.
    overall_score_sin_tope: int | None = None
    tope: TopeDeNota | None = None
    categories: list[CategoryInsight]
    generated_at: datetime


# ---------------------------------------------------------------------------
# Job configuration — sub-models
# ---------------------------------------------------------------------------
class ResourceTypeConfig(BaseModel):
    """Which resource types to crawl."""

    crawl_images: bool = True
    crawl_css: bool = True
    crawl_js: bool = True
    crawl_pdfs: bool = True
    crawl_fonts: bool = False
    crawl_svg: bool = True
    crawl_other: bool = True
    # Comprobar tambien los recursos embebidos de OTROS hosts (imagenes de un
    # CDN, scripts de terceros) con la sonda de respuesta (decision 124). No
    # hacia nada hasta esa decision. Sin credenciales del job (114) y con el
    # robots.txt del tercero. Usa el presupuesto `crawl_behavior.recursos_max`.
    check_external_resources: bool = False


class CrawlBehaviorConfig(BaseModel):
    """Speed and behavior tuning."""

    download_timeout: int = Field(default=30, ge=5, le=120)
    retry_count: int = Field(default=2, ge=0, le=10)
    request_delay: float = Field(default=0.0, ge=0.0, le=30.0)
    autothrottle_enabled: bool = True
    autothrottle_target_concurrency: float = Field(default=8.0, ge=1.0, le=100.0)
    follow_nofollow: bool = False
    crawl_subdomains: bool = False
    # Red de seguridad dura, no el mecanismo principal: la parada real la
    # decide stall_timeout_minutes. Adivinar cuanto tarda un rastreo es
    # imposible —el mismo sitio rinde 7x distinto con y sin render— y cortar
    # por reloj mato un rastreo al 97,5%.
    max_runtime_hours: int = Field(default=72, ge=1, le=720)
    # Minutos sin avanzar tras los que se da el rastreo por muerto. 0 lo
    # desactiva. El spider estampa un latido al actualizar progreso y en cada
    # lote de siembra de la frontera, asi que un rastreo lento pero vivo no
    # se ve afectado.
    stall_timeout_minutes: int = Field(default=30, ge=0, le=1440)
    # Al reanudar, repetir las paginas perdidas (status NULL), 5xx y las que
    # Chromium dejo en pagina de error, en vez de darlas por rastreadas.
    retry_failed_on_resume: bool = True
    # Al reanudar, volver a rastrear tambien las URLs que casen (regex).
    recrawl_patterns: list[str] = Field(default_factory=list)
    # Al reanudar, repetir las HTML 200 internas guardadas sin contenido
    # extraido (tras corregir el stripper o los selectores del cliente).
    recrawl_empty_content: bool = False
    # Tope (ms) de la espera a que el DOM se calme tras domcontentloaded con
    # render_js; 0/None = el del entorno (PLAYWRIGHT_BANNER_WAIT_MS, def. 2000).
    render_wait_ms: int | None = Field(default=None, ge=0, le=60000)
    # Salud del rastreo (decision 103): si de las ultimas `salud_ventana`
    # respuestas, la fraccion `salud_umbral` o mas no son la pagina (desafio de
    # un WAF, captcha, 429, cuerpo binario), el rastreo se para y el job queda
    # `failed` con `bloqueado_por_waf` o `rate_limited`. Con
    # `parar_si_bloqueado=false` sigue, pero el job se juzga igual al cerrar.
    parar_si_bloqueado: bool = True
    salud_ventana: int = Field(default=50, ge=10, le=1000)
    salud_umbral: float = Field(default=0.8, ge=0.1, le=1.0)
    # Sondas de soft 404 (decision 105): cuantas URLs inexistentes se piden
    # como mucho (una por host de las semillas y una por plantilla de ruta).
    # No gastan max_urls ni se guardan como URL del censo. 0 = sin sondas.
    soft404_sondas: int = Field(default=12, ge=0, le=100)
    # Retry-After de un 429 o un 503 (decision 111): pausa del host durante lo
    # que pide el servidor, con este tope en segundos. Por debajo del vigilante
    # de estancamiento (30 min): el spider sigue estampando el latido.
    respetar_retry_after: bool = True
    # None = el `RETRY_AFTER_MAX` del entorno (60). Con un 60 aqui, como los
    # defaults se copian en `jobs.config`, el worker lo pasaba SIEMPRE por
    # `-s` y la variable de entorno no tenia ningun efecto.
    retry_after_max_s: int | None = Field(default=None, ge=0, le=600)
    # Sonda del certificado TLS, una vez por host https interno (decision 110).
    sonda_tls: bool = True
    # Paridad movil/escritorio (decision 119): cuantas paginas del censo se
    # vuelven a pedir con el perfil movil (o con el de escritorio, si el UA
    # del job ya es de movil), como mucho `paridad_movil_por_plantilla` por
    # plantilla. Sondas fuera de max_urls; cada una cuesta 1 o 2 peticiones
    # (la de control, solo si algo difiere). 0 = apagado, que es lo de serie.
    paridad_movil_muestra: int = Field(default=0, ge=0, le=500)
    paridad_movil_por_plantilla: int = Field(default=3, ge=1, le=50)
    # Respuesta frente a render (decision 140, Ola 7.1): una muestra por
    # plantilla pedida en el OTRO modo (sin render si el job renderiza). None =
    # 30 con `render_js` y 0 sin el: sin render, la otra version es un render
    # por pagina y hay que pedirlo.
    render_crudo_muestra: int | None = Field(default=None, ge=0, le=500)
    render_crudo_por_plantilla: int = Field(default=3, ge=1, le=50)
    # Accesibilidad con axe-core (decision 174, Ola 8): cuantas paginas del
    # censo se vuelven a renderizar para pasarles axe (WCAG 2.x A/AA), como
    # mucho `axe_por_plantilla` por plantilla. Cada una es un render mas,
    # tambien en un censo sin render: 0 = apagado, que es lo de serie.
    axe_muestra: int = Field(default=0, ge=0, le=500)
    axe_por_plantilla: int = Field(default=1, ge=1, le=20)
    # chrome_android por defecto: con Googlebot desde nuestra IP un WAF que
    # verifica bots lo bloquea o sirve otra cosa (decision 98)
    paridad_movil_ua: Literal["chrome_android", "googlebot_smartphone"] = "chrome_android"
    # Capturas de pantalla (decision 173): la primera pantalla de una muestra
    # por plantilla, con render aunque el censo no lo lleve, guardada en el
    # volumen de archivo y visible en la ficha de la URL. Con el dispositivo
    # del censo y, con `capturas_ambos_perfiles`, tambien con el otro (movil o
    # escritorio). Sondas fuera de max_urls: un render por pagina y perfil.
    # 0 = apagado, que es lo de serie. Tope pequeno a proposito: son imagenes.
    capturas_muestra: int = Field(default=0, ge=0, le=50)
    capturas_por_plantilla: int = Field(default=1, ge=1, le=5)
    capturas_ambos_perfiles: bool = False
    # Sondas de respuesta (decisiones 123 y 124): piden con HEAD (GET de
    # repuesto) lo que el sitio enlaza a otros sitios y lo que embebe, sin que
    # sea del censo: no gastan max_urls, no se guardan en `urls` y no cuentan
    # para la salud del rastreo. Apagadas: multiplican las peticiones.
    comprobar_enlaces_externos: bool = False
    # URLs externas distintas que se comprueban como mucho.
    enlaces_externos_max: int = Field(default=5000, ge=0, le=100000)
    # Recursos embebidos del sitio (imagenes, CSS, JS) que el censo no pide.
    comprobar_recursos: bool = False
    # Recursos distintos que se comprueban como mucho (internos y externos).
    recursos_max: int = Field(default=20000, ge=0, le=500000)
    # Tope de URLs por host externo (enlaces y recursos juntos). 0 = sin tope.
    sondas_por_host: int = Field(default=50, ge=0, le=10000)
    # Dimensiones de la og:image (decision 154): cuantas imagenes distintas se
    # piden (GET de 64 KB, fuera de max_urls) para medirlas, y cuantas nuevas
    # por forma de ruta de la pagina. Encendida de serie porque esta acotada;
    # `og_image_muestra` 0 = apagada; `og_image_por_plantilla` 0 = sin tope
    # por plantilla (solo el global).
    og_image_muestra: int = Field(default=200, ge=0, le=5000)
    og_image_por_plantilla: int = Field(default=5, ge=0, le=100)


class UrlFilterConfig(BaseModel):
    """URL-level filtering rules."""

    max_url_length: int = Field(default=0, ge=0, le=10000)
    max_folder_depth: int = Field(default=0, ge=0, le=100)


class ExtractionConfig(BaseModel):
    """Toggle extraction of optional data."""

    extract_structured_data: bool = True
    extract_hreflang: bool = True
    extract_security_headers: bool = True
    extract_page_content: bool = True
    strip_promo_blocks: bool = True
    custom_boilerplate_selectors: list[str] = Field(default_factory=list)
    store_raw_html: bool = False


class HttpConfig(BaseModel):
    """Ajustes HTTP del job. Las cabeceras propias, las cookies y el Basic solo
    van a los hosts de las semillas (decision 114); Accept-Language, a todas."""

    custom_headers: dict[str, str] = Field(default_factory=dict)
    accept_language: str = ""
    cookies: dict[str, str] = Field(default_factory=dict)
    basic_auth_user: str = ""
    basic_auth_password: str = ""
    # Guardar las cookies que pone el sitio entre paginas. Por defecto no,
    # como Googlebot; las de `cookies` se mandan igual (decision 114).
    conservar_cookies: bool = False


class AnalysisThresholdsConfig(BaseModel):
    """Per-job thresholds for SEO analysis."""

    title_min_length: int = Field(default=10, ge=0, le=200)
    title_max_length: int = Field(default=60, ge=1, le=500)
    description_min_length: int = Field(default=50, ge=0, le=500)
    description_max_length: int = Field(default=160, ge=1, le=1000)
    min_word_count: int = Field(default=200, ge=0, le=10000)
    # Saltos de redireccion que se consideran aceptables. Uno es una
    # redireccion normal; dos encadenadas (A->B->C) ya son algo que arreglar y
    # es lo que Google pide evitar. Estaba en 2 —o sea, hacian falta tres— y
    # eso dejaba sin reportar 372 cadenas de dos saltos en un solo censo.
    max_redirect_chain_length: int = Field(default=1, ge=1, le=20)
    max_outlinks: int = Field(default=100, ge=1, le=10000)
    # Soft 404 (decision 105). Similitud MinHash con la huella de la sonda a
    # partir de la que una pagina ES la pagina de error del sitio (como en los
    # casi duplicados, 0,9 = comparten nueve de cada diez trigramas).
    soft404_similitud: float = Field(default=0.9, ge=0.6, le=1.0)
    # Por debajo de estas palabras el contenido igual no basta: se exige
    # tambien el mismo titulo.
    soft404_min_palabras_igualdad: int = Field(default=5, ge=1, le=200)
    # Si la huella de una sonda casa con mas de esta fraccion de las paginas de
    # su alcance, no es una pagina de error sino la plantilla (un shell de SPA,
    # una plantilla vacia): no se afirma, va como candidato agrupado.
    soft404_max_proporcion_huella: float = Field(default=0.5, gt=0.0, le=1.0)

    # Paginas distintas desde las que un mismo enlace (tipo y destino) cuenta
    # como de plantilla: se avisa una vez y no en cada pagina (decision 106).
    enlaces_plantilla_min_paginas: int = Field(default=10, ge=2, le=100000)

    # Respuesta lenta (decision 109): mediana del TTFB por (host, plantilla)
    # por encima de estos ms, en plantillas con al menos `_min_paginas`.
    # Valores de partida: hay que medirlos en censos antes de fijarlos (13).
    respuesta_lenta_ms: int = Field(default=1000, ge=100, le=60000)
    respuesta_lenta_grave_ms: int = Field(default=3000, ge=100, le=120000)
    respuesta_lenta_min_paginas: int = Field(default=20, ge=1, le=100000)
    # Certificado que caduca en estos dias o menos (decision 110). No 30: con
    # renovaciones a 30 dias y certificados de 45, uno sano estaria siempre.
    tls_dias_aviso: int = Field(default=7, ge=1, le=90)
    # Umbral ABSOLUTO de las alertas de la comparacion cuando el censo es una
    # lista (`max_depth=0`, decision 128): con este numero de paginas afectadas
    # salta, sin porcentaje ni el piso de 20 de la decision 68. En una lista
    # cada URL la ha elegido alguien, asi que por defecto basta una.
    alerta_lista_min_paginas: int = Field(default=1, ge=1, le=100000)

    # Oportunidades de Search Console (decision 157). Valores de partida, a
    # medir en censos reales antes de fijarlos (13).
    # Posicion 4-20 con poco enlazado, con estas impresiones en la ventana.
    gsc_oportunidad_min_impresiones: int = Field(default=500, ge=1, le=100_000_000)
    gsc_oportunidad_posicion_min: float = Field(default=4.0, ge=1.0, le=100.0)
    gsc_oportunidad_posicion_max: float = Field(default=20.0, ge=1.0, le=100.0)
    # Profundidad minima desde la que una pagina esta «lejos»; si el sitio es
    # mas profundo, manda su cuartil alto.
    gsc_oportunidad_profundidad: int = Field(default=4, ge=1, le=1000)
    # CTR bajo para su posicion: impresiones minimas de la pagina (sumando sus
    # busquedas que entran en la curva).
    gsc_ctr_min_impresiones: int = Field(default=200, ge=1, le=100_000_000)
    # ...y que le falten al menos estos clics frente a la mediana de su tramo:
    # el cuartil bajo, por definicion, es una de cada cuatro paginas.
    gsc_ctr_min_clics_que_faltan: int = Field(default=20, ge=0, le=100_000_000)
    # Canibalizacion: parte minima de los clics (o de las impresiones si la
    # busqueda no tiene clics) que se lleva cada URL; clics minimos de la
    # busqueda (o impresiones, si no tiene ninguno), y desde cuantos clics es
    # warning y no info.
    gsc_canibalizacion_min_parte: float = Field(default=0.2, gt=0.0, lt=1.0)
    gsc_canibalizacion_min_clics: int = Field(default=10, ge=1, le=100_000_000)
    gsc_canibalizacion_min_impresiones: int = Field(default=1000, ge=1, le=100_000_000)
    gsc_canibalizacion_clics_grave: int = Field(default=100, ge=1, le=100_000_000)
    # WordPress (decision 161): un termino (categoria, etiqueta) con estas
    # entradas publicadas o menos es una taxonomia anemica si su archivo es
    # indexable. 1 = el archivo repite la unica entrada que tiene.
    wp_taxonomia_anemica_max: int = Field(default=1, ge=0, le=1000)
    # PageRank con autoridad externa (decision 212): la parte del salto que
    # sigue repartida por igual entre las indexables. 1 = el PageRank interno
    # (sin backlinks); 0 = todo el salto donde entra la autoridad de fuera. La
    # mitad es un juicio: el indice de cada proveedor es incompleto, y sin
    # parte uniforme la home (que se lleva casi todos los backlinks) lo domina.
    pagerank_externo_beta: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Job configuration
# ---------------------------------------------------------------------------
# Extraccion y busqueda a medida por job (#34, decision 104). La logica vive en
# `shared/extraccion_a_medida.py`, que la comparten el spider y la API.
NOMBRE_REGLA = r"^[a-z][a-z0-9_]{0,39}$"


class ExtractorAMedida(BaseModel):
    """Un dato que se saca de cada pagina: CSS, XPath o regex."""

    model_config = ConfigDict(extra="forbid")

    etiqueta: str | None = Field(None, max_length=80)
    tipo: Literal["css", "xpath", "regex"]
    expresion: str = Field(..., min_length=1, max_length=2000)
    # css/xpath: que devuelve cada elemento
    devuelve: Literal["texto", "html_interno", "html", "atributo"] = "texto"
    atributo: str | None = Field(None, pattern=r"^[A-Za-z_:][-A-Za-z0-9_:.]*$")
    # regex: None = 1 si la regex tiene grupos, si no 0 (la coincidencia entera)
    grupo: int | None = Field(None, ge=0, le=9)
    ignorar_mayusculas: bool = False
    # css/xpath solo "html"; una regex puede correr sobre el texto visible o el
    # contenido principal
    fuente: Literal["html", "texto", "contenido"] = "html"
    cuantos: Literal["primero", "todos", "recuento"] = "primero"
    max_valores: int = Field(20, ge=1, le=100)          # solo con "todos"
    max_caracteres: int = Field(1000, ge=1, le=10_000)
    valor: Literal["texto", "numero"] = "texto"         # "recuento" es siempre numero
    # None = automatico; un caso ambiguo (`1.234`) da conversion_fallida
    separador_decimal: Literal[",", "."] | None = None
    solo_urls: str | None = Field(None, max_length=500)  # regex sobre el path


class BusquedaAMedida(BaseModel):
    """¿Contiene la pagina esto? Texto literal o regex."""

    model_config = ConfigDict(extra="forbid")

    etiqueta: str | None = Field(None, max_length=80)
    modo: Literal["texto", "regex"] = "texto"
    patron: str = Field(..., min_length=1, max_length=1000)
    ignorar_mayusculas: bool = True
    fuente: Literal["html", "texto", "contenido"] = "html"
    dentro_de: str | None = Field(None, max_length=500)  # selector CSS que acota
    solo_urls: str | None = Field(None, max_length=500)


class WordPressAdapterConfig(BaseModel):
    """Adaptador WordPress (#33, decision 161): leer la REST API publica.

    `auto` (por defecto) pide la raiz de la REST API de cada host de las
    semillas y solo sigue si responde un indice de WordPress; `on` la pide
    tambien si el sitio no la anuncia (la misma peticion, hoy); `off`, nada.
    Las peticiones van por el spider (UA, huella TLS, cabeceras del job,
    robots.txt y ritmo del host) y no cuentan en `max_urls`.
    """

    model_config = ConfigDict(extra="forbid")

    modo: Literal["auto", "on", "off"] = "auto"
    # Peticiones a la REST API a la vez, como mucho (comparten el slot del host
    # con el rastreo, asi que su Crawl-delay y su Retry-After valen igual).
    max_concurrencia: int = Field(default=2, ge=1, le=2)
    # Tope de peticiones del adaptador en un rastreo: indice, tipos, listados y sondas.
    max_peticiones: int = Field(default=1000, ge=10, le=20_000)
    # Minutos como mucho leyendo la REST API desde la primera peticion. Con un
    # Crawl-delay alto la cola puede seguir cuando ya no quedan paginas: esto
    # acota cuanto puede alargar el job (con latido, decision 161).
    max_minutos: int = Field(default=20, ge=1, le=240)
    # Entidades leidas por tipo (entradas, paginas, cada taxonomia). El total
    # se sabe igual por `X-WP-Total`.
    max_entidades_por_tipo: int = Field(default=20_000, ge=100, le=1_000_000)
    # Medios: solo para la muestra de paginas de adjunto y el recuento.
    max_medios: int = Field(default=1000, ge=0, le=100_000)
    # Paginas de adjunto que se piden si el rastreo no las encuentra (hallazgo 2).
    muestra_adjuntos: int = Field(default=20, ge=0, le=500)
    # Archivos (home y terminos) a los que se pide la pagina N+1 (hallazgo 5).
    sondas_paginacion: int = Field(default=5, ge=0, le=50)


class AdaptersConfig(BaseModel):
    """Adaptadores de CMS por job (decision 161)."""

    model_config = ConfigDict(extra="forbid")

    wordpress: WordPressAdapterConfig = Field(default_factory=WordPressAdapterConfig)


class TemplateRule(BaseModel):
    """Regla de plantilla: la primera cuyo ``patron`` (regex sobre el path)
    casa da nombre a la plantilla. Las usan check_js_templates.py y
    check_content_quality.py para muestrear por plantilla."""

    nombre: str = Field(..., min_length=1, max_length=80)
    patron: str = Field(..., min_length=1, max_length=500)


class ReglaSegmento(BaseModel):
    """Una regla de segmento de negocio (decision 125, `shared/segmentos.py`).

    `patron` es el mismo de `TemplateRule` (regex sobre el path, sin distinguir
    mayusculas), asi que una lista de `templates` vale como lista de segmentos.
    `si` es el arbol de condiciones (Y/O/NO, campo, regla a medida); con los dos
    tienen que casar los dos. La valida `shared.segmentos.validar`, que conoce
    las reglas a medida del config entero, desde `JobConfig`."""

    model_config = ConfigDict(extra="forbid")

    nombre: str = Field(..., min_length=1, max_length=80)
    etiqueta: str | None = Field(None, max_length=120)
    patron: str | None = Field(None, max_length=500)
    si: dict[str, Any] | None = None


class IncrementalConfig(BaseModel):
    """Rastreo incremental de un perfil programado (#36 F4, decision 220).

    Solo lo leen los disparos de una programacion colgada de un perfil
    (`shared/incremental.preparar_job`): un rastreo puntual o de copia fija lo
    ignora y rastrea todo. Apagado, nada cambia.
    """

    activo: bool = False
    # Un completo cada N ciclos (incluido), y siempre que cambie la config,
    # las semillas o el robots.txt: es el unico que puede afirmar que una URL
    # ha desaparecido de verdad.
    completo_cada: int = Field(default=4, ge=1, le=52)
    # Fraccion al azar de lo que no toca que se pide igual en cada ciclo. Si
    # cambia mas de `umbral_control`, el siguiente es completo.
    muestra_control: float = Field(default=0.1, ge=0, le=1)
    umbral_control: float = Field(default=0.2, gt=0, le=1)
    # El intervalo de una URL que no cambia crece hasta esto, en ciclos.
    intervalo_max: float = Field(default=4.0, ge=1, le=52)


class RetencionConfig(BaseModel):
    """Retencion de censos de un perfil (decision 223).

    Al cerrar un rastreo del perfil, el worker vacia los terminados mas
    antiguos que sus `conservar` censos completados mas recientes: borra sus
    URLs, enlaces e incidencias y deja la fila del job (`status='vaciado'`) y
    su punto de la evolucion. Apagado, no se toca nada.
    """

    activo: bool = False
    conservar: int = Field(default=8, ge=2, le=200)


class JobConfig(BaseModel):
    """Crawl configuration that travels with every job."""

    # Tope 1000, no 50: en WordPress el paginador solo enlaza a la pagina
    # siguiente, asi que /page/120/ esta a profundidad 120 de la home. Con 50
    # se cortaba la cadena y los posts de las paginas profundas salian como
    # huerfanos aunque estuvieran enlazados.
    #
    # `0` es el MODO LISTA (decision 128): solo las semillas, sin seguir un
    # enlace. Para QA de despliegues: «estas 50 URLs clave siguen bien». Sin
    # pedirlo, una lista tampoco lee el sitemap (ver `_lista_sin_sitemap`).
    max_depth: int = Field(default=DEFAULT_MAX_DEPTH, ge=0, le=1000)
    # None = rastrear hasta agotar la frontera (comportamiento de Screaming
    # Frog). Antes era obligatorio con default 50.000, asi que habia que
    # adivinar el tamano del sitio ANTES de rastrearlo: quedarse corto truncaba
    # el crawl en silencio y el PageRank salia calculado sobre un grafo parcial.
    max_urls: int | None = Field(default=None, ge=1, le=5_000_000)
    # Topes por subdominio o carpeta (Ola 8, decision 172): un presupuesto
    # aparte de `max_urls`, `{"regla": tope}` con la sintaxis de
    # `shared/topes_carpeta.py` (`"*"` por carpeta de primer nivel, `"/blog/"`,
    # `"blogs.uoc.edu/*"`). Un dict: en la herencia cliente -> perfil -> job se
    # fusiona por regla y `null` la quita (por eso `| None` tambien aqui).
    topes_por_carpeta: dict[str, int | None] = Field(default_factory=dict)
    follow_external: bool = False
    robots_mode: Literal["respect", "ignore", "audit"] = "respect"
    concurrent_requests: int = Field(default=DEFAULT_CONCURRENT_REQUESTS, ge=1, le=256)
    concurrent_requests_per_domain: int = Field(
        default=DEFAULT_CONCURRENT_REQUESTS_PER_DOMAIN, ge=1, le=64
    )
    user_agent: str = DEFAULT_USER_AGENT
    render_js: bool = False
    # Huella TLS de curl_cffi para lo que no va por Chromium (decision 132). Va
    # con el UA: si solo se fija uno, el otro se deduce (`_ua_y_huella`).
    impersonate: str = IMPERSONATE_POR_DEFECTO
    exclude_patterns: list[str] = Field(default_factory=list)
    include_patterns: list[str] = Field(default_factory=list)
    use_sitemap: bool = True
    sitemap_urls: list[str] = Field(default_factory=list)
    # Reglas de plantilla por cliente (ver projects/README.md)
    templates: list[TemplateRule] = Field(default_factory=list)

    # Advanced configuration sub-models
    resource_types: ResourceTypeConfig = Field(default_factory=ResourceTypeConfig)
    crawl_behavior: CrawlBehaviorConfig = Field(default_factory=CrawlBehaviorConfig)
    url_filters: UrlFilterConfig = Field(default_factory=UrlFilterConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    analysis_thresholds: AnalysisThresholdsConfig = Field(default_factory=AnalysisThresholdsConfig)

    # Extraccion y busqueda a medida (#34, decision 104): nombre -> regla. Las
    # columnas salen como `x.<nombre>` en el Explorador y en los CSV. En la
    # herencia cliente -> perfil -> job una regla se SUSTITUYE entera por
    # nombre y `null` la quita (`shared/clientes._fusionar_en`).
    # `| None` tambien en el JOB: un rastreo puntual tiene que poder apagar una
    # regla del cliente sin crear un perfil. El `null` lo consume
    # `fusionar_config`, asi que en `jobs.config` no llega a guardarse.
    custom_extraction: dict[str, ExtractorAMedida | None] = Field(default_factory=dict)
    custom_search: dict[str, BusquedaAMedida | None] = Field(default_factory=dict)
    # Segmentos de negocio (decision 125): la PRIMERA regla que casa da el
    # segmento de la URL; si ninguna, la forma de la ruta. Es una lista, asi
    # que en la herencia cliente -> perfil -> job se SUSTITUYE entera: la
    # precedencia es el orden, y sumar listas la haria imposible de leer.
    segmentos: list[ReglaSegmento] = Field(default_factory=list)
    # Nombres de marca del cliente (decision 157): las busquedas que los
    # contienen no cuentan como canibalizacion de la home. Coincidencia simple,
    # sin mayusculas ni acentos; lo ambiguo es trabajo de #169.
    marcas: list[str] = Field(default_factory=list, max_length=50)
    # Adaptadores de CMS (decision 161): hoy WordPress por su REST API.
    adapters: AdaptersConfig = Field(default_factory=AdaptersConfig)
    # Taxonomia de negocio del cliente (#12, decision 178): las opciones de la
    # pregunta `categoria_cliente` del analisis enriquecido. Hasta 20 (con mas,
    # un choice se reparte y no decide nada); sin ella, ese modulo no pregunta.
    # Cada categoria es un nombre o `{"nombre", "descripcion"}`: la descripcion
    # (que entra, que no) es lo que el modelo lee para decidir, y sin ella solo
    # tiene el nombre.
    taxonomia: list[str | dict[str, Any]] = Field(default_factory=list, max_length=20)
    # Rastreo incremental en los programados de un perfil (decision 220).
    incremental: IncrementalConfig = Field(default_factory=IncrementalConfig)
    retencion: RetencionConfig = Field(default_factory=RetencionConfig)

    @field_validator("taxonomia")
    @classmethod
    def _taxonomia_valida(cls, v: list) -> list:
        limpias: list = []
        vistos: set[str] = set()
        for c in v or []:
            if isinstance(c, dict):
                sobran = set(c) - {"nombre", "descripcion"}
                if sobran:
                    raise ValueError(f"categoria con claves desconocidas: {sorted(sobran)}")
                nombre = " ".join(str(c.get("nombre") or "").split())
                descripcion = " ".join(str(c.get("descripcion") or "").split())
                if len(descripcion) > 400:
                    raise ValueError(f"descripcion de mas de 400 caracteres en {nombre[:40]!r}")
            else:
                nombre, descripcion = " ".join(str(c or "").split()), ""
            if not nombre:
                continue
            if len(nombre) > 80:
                raise ValueError(f"categoria de mas de 80 caracteres: {nombre[:40]!r}...")
            if nombre.lower() == "ninguna":
                raise ValueError("«ninguna» no puede ser una categoria: es la respuesta para "
                                 "las paginas que no son de ninguna")
            if nombre.lower() in vistos:
                raise ValueError(f"categoria repetida: {nombre!r}")
            vistos.add(nombre.lower())
            limpias.append({"nombre": nombre, "descripcion": descripcion} if descripcion else nombre)
        return limpias

    @field_validator("impersonate")
    @classmethod
    def _huella_soportada(cls, v: str) -> str:
        v = (v or "").strip()
        if v not in PERFILES_IMPERSONATE:
            raise ValueError(
                f"perfil de huella TLS desconocido: {v!r}. Los de curl_cffi 0.16: "
                + ", ".join(sorted(PERFILES_IMPERSONATE)))
        return v

    @model_validator(mode="after")
    def _ua_y_huella(self):
        """El UA y la huella TLS son el mismo navegador (decision 132).

        Si solo se fija uno, el otro se deduce de el: un config que fija el UA
        de Chrome 124 y no la huella sigue saliendo con la de Chrome 124 (era
        la de serie), y uno que pide `safari17_0` sin UA sale con el de Safari,
        no con un Chrome de Windows encima. Si se fijan los dos, mandan los dos:
        quien escribe una combinacion rara puede tener su motivo, y el spider la
        avisa en el log. Por `__dict__`, como `_lista_sin_sitemap`, para que la
        clave deducida no cuente como fijada al fusionar capas.
        """
        # La regla vive en `shared.perfiles.claves_deducidas`: el worker la
        # aplica igual al disparar una programacion colgada de un perfil.
        deducidas = claves_deducidas(self.model_fields_set, {
            "user_agent": self.user_agent, "impersonate": self.impersonate})
        for clave in ("user_agent", "impersonate"):
            if clave in deducidas:
                self.__dict__[clave] = deducidas[clave]
        return self

    @field_validator("topes_por_carpeta")
    @classmethod
    def _topes_validos(cls, v: dict) -> dict:
        from shared.topes_carpeta import compilar

        compilar(v)  # ValueError con todos los motivos juntos
        return v

    @model_validator(mode="after")
    def _lista_sin_sitemap(self):
        """Modo lista (decision 128): sin sitemap salvo que se pida.

        Con `use_sitemap` por defecto, una lista de 50 URLs clave sembraba
        ademas TODO el sitemap (a profundidad 1, que no sigue enlaces pero se
        rastrea): un censo de miles de paginas donde se pidieron 50. Solo si la
        clave no viene: quien escribe `use_sitemap: true` lo quiere.

        Por `__dict__` y no con asignacion: asignar la marcaria como fijada y,
        con `exclude_unset`, el override de un job (`max_depth: 0` a secas)
        pisaria el `use_sitemap: true` que fijase su perfil. Asi se decide otra
        vez sobre la config FUSIONADA (`resolver_config`).
        """
        # Misma regla que el worker: `shared.perfiles.claves_deducidas`.
        deducidas = claves_deducidas(self.model_fields_set, {"max_depth": self.max_depth})
        if "use_sitemap" in deducidas:
            self.__dict__["use_sitemap"] = deducidas["use_sitemap"]
        return self

    @model_validator(mode="after")
    def _reglas_de_segmento(self):
        if not self.segmentos:
            return self
        from shared.segmentos import validar

        # Solo la forma. Que cada `x` exista se comprueba sobre la config
        # FUSIONADA (`resolver_config`, y `create_job` sin cliente): aqui puede
        # llegar una capa suelta —el perfil, el override de un job— cuyos
        # segmentos usan una extraccion que fija el cliente.
        errores = validar([r.model_dump(exclude_none=True) for r in self.segmentos], None)
        if errores:
            raise ValueError("; ".join(errores))
        return self

    @model_validator(mode="after")
    def _reglas_a_medida(self):
        if not self.custom_extraction and not self.custom_search:
            return self
        from shared.extraccion_a_medida import validar

        errores = validar(
            {k: v.model_dump() for k, v in self.custom_extraction.items() if v is not None},
            {k: v.model_dump() for k, v in self.custom_search.items() if v is not None},
            extract_page_content=self.extraction.extract_page_content,
            max_urls=self.max_urls,
        )
        if errores:
            raise ValueError("; ".join(errores))
        return self


# ---------------------------------------------------------------------------
# Job create / response
# ---------------------------------------------------------------------------
def _validar_expresion_cron(v: str) -> str:
    """Se valida al ESCRIBIRLA, no al dispararla.

    Una expresion que no se puede interpretar, guardada, es una programacion
    que no se dispara nunca — y eso se lee igual que un sitio que no cambia.
    El error tiene que salir cuando alguien la escribe.
    """
    from shared.programaciones import cron_valido

    if not cron_valido(v):
        raise ValueError(
            f"'{v}' no es una expresion cron valida de cinco campos "
            f"(minuto hora dia-del-mes mes dia-de-semana). "
            f"Por ejemplo: '0 3 * * 1' es todos los lunes a las 3:00"
        )
    return v.strip()


def _validar_zona(v: str | None) -> str | None:
    if v is None:
        return v
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"zona horaria desconocida: {v!r}") from exc
    return v


class ProgramacionCreate(BaseModel):
    """Un rastreo que se repite. Dos formas (decision 193):

    - **Colgada de un perfil** (la de la interfaz): `profile_id` y, si acaso,
      `config_propia` (solo lo que cambia esta programacion, p. ej. un tope de
      URLs). Sin semillas: en cada disparo usa las del perfil y la config del
      cliente y del perfil de ESE momento.
    - **Copia fija** (la de siempre): `seeds` y `config` completas. Se sigue
      aceptando para no romper a quien ya llama asi (scripts, MCP con semillas
      propias), pero no hereda los cambios del cliente ni del perfil.

    `hereda_perfil` sin mandar = colgada si hay perfil y no hay semillas.
    """

    nombre: str | None = Field(default=None, min_length=1, max_length=512)
    seeds: list[str] = Field(default_factory=list)
    client_id: str | None = Field(default=None, max_length=128)
    cliente_id: uuid.UUID | None = None
    profile_id: uuid.UUID | None = None
    hereda_perfil: bool | None = None
    config: JobConfig = Field(default_factory=JobConfig)
    config_propia: dict[str, Any] = Field(default_factory=dict)
    # Expresion de cinco campos: `minuto hora dia-del-mes mes dia-de-semana`.
    cron: str = Field(..., min_length=1, max_length=128)
    zona_horaria: str | None = Field(default=None, max_length=64)
    activa: bool = True

    @field_validator("cron")
    @classmethod
    def validar_cron(cls, v: str) -> str:
        return _validar_expresion_cron(v)

    @field_validator("zona_horaria")
    @classmethod
    def validar_zona_horaria(cls, v: str | None) -> str | None:
        return _validar_zona(v)

    @field_validator("seeds", mode="before")
    @classmethod
    def validar_semillas(cls, v: list[str] | None) -> list[str]:
        return _limpiar_semillas(v, obligatorias=False)

    @field_validator("config_propia")
    @classmethod
    def validar_config_propia(cls, v: dict) -> dict:
        return validar_config_parcial(v)

    @model_validator(mode="after")
    def _forma(self):
        if self.hereda_perfil is None:
            self.hereda_perfil = bool(self.profile_id) and not self.seeds
        if self.hereda_perfil:
            if not self.profile_id:
                raise ValueError(
                    "Una programacion que hereda del perfil necesita `profile_id`")
            if self.seeds:
                raise ValueError(
                    "Una programacion colgada de un perfil usa las semillas del "
                    "perfil: no mandes `seeds` (o manda hereda_perfil=false)")
        else:
            if not self.seeds:
                raise ValueError("At least one valid seed URL is required")
            if not self.nombre:
                raise ValueError("Falta el nombre de la programacion")
            if self.config_propia:
                raise ValueError(
                    "`config_propia` es solo para las que heredan del perfil; "
                    "una copia fija lleva su `config` entera")
        return self


class ProgramacionUpdate(BaseModel):
    """Lo que se puede cambiar de una programacion ya creada."""

    nombre: str | None = Field(default=None, min_length=1, max_length=512)
    cron: str | None = Field(default=None, min_length=1, max_length=128)
    zona_horaria: str | None = Field(default=None, max_length=64)
    activa: bool | None = None
    # Solo en las colgadas de un perfil (decision 193).
    config_propia: dict[str, Any] | None = None

    @field_validator("cron")
    @classmethod
    def validar_cron(cls, v: str | None) -> str | None:
        return None if v is None else _validar_expresion_cron(v)

    @field_validator("zona_horaria")
    @classmethod
    def validar_zona_horaria(cls, v: str | None) -> str | None:
        return _validar_zona(v)

    @field_validator("config_propia")
    @classmethod
    def validar_config_propia(cls, v: dict | None) -> dict | None:
        return None if v is None else validar_config_parcial(v)


class ProgramacionRepetida(BaseModel):
    id: uuid.UUID
    nombre: str
    motivo: str  # «mismo perfil» | «mismas semillas»


class ProgramacionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    client_id: str | None = None
    cliente_id: uuid.UUID | None = None
    profile_id: uuid.UUID | None = None
    # Si hereda del perfil en cada disparo (decision 193). Falso = copia fija.
    hereda_perfil: bool = False
    # Las semillas que lanzaria hoy: las del perfil si hereda. Con
    # `?resumen=true`, solo las tres primeras (un censo sembrado desde el
    # sitemap son 3.040: 233 kB por programacion).
    seeds: list[str]
    n_semillas: int = 0
    # Si hereda: solo lo propio de la programacion. Si es copia fija: entera.
    config: dict[str, Any] | None = None
    cron: str
    zona_horaria: str | None = None
    activa: bool
    proxima_ejecucion: datetime | None = None
    ultima_ejecucion: datetime | None = None
    ultimo_job_id: uuid.UUID | None = None
    ultimo_motivo: str | None = None
    created_at: datetime | None = None
    cliente_nombre: str | None = None
    perfil_nombre: str | None = None
    # Otras activas que repiten trabajo de esta (mismo perfil o mismas
    # semillas). Vacia si esta no esta activa.
    repetida_con: list[ProgramacionRepetida] = Field(default_factory=list)


def _limpiar_semillas(v: list[str] | None, *, obligatorias: bool = True) -> list[str]:
    cleaned: list[str] = []
    for url in v or []:
        url = url.strip()
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Seed URL must start with http:// or https://: {url}")
        # Una semilla con credenciales se guardaria en `jobs.seeds`, que lee
        # cualquiera (decision 83), y el rastreo las quitaria al normalizar:
        # el staging se quedaria en el login sin aviso. Se rechaza y se dice
        # donde van.
        if "@" in urlsplit(url).netloc:
            raise ValueError(
                "La semilla lleva credenciales (usuario:clave@): quitalas y usa "
                "http.basic_auth_user / http.basic_auth_password"
            )
        cleaned.append(url)
    if obligatorias and not cleaned:
        raise ValueError("At least one valid seed URL is required")
    return cleaned


class CensoDeSerie(BaseModel):
    """Un rastreo en la serie de su cliente, con las cifras que se comparan
    de un censo a otro (UX-07/08)."""

    id: uuid.UUID
    name: str
    status: str
    tipo: str
    created_at: datetime
    urls: int = 0
    paginas_html: int = 0
    indexables: int = 0
    errores: int = 0                    # incidencias de gravedad error (no paginas)
    avisos: int = 0
    # Paginas distintas con algun error: la cifra de la tarjeta del censo y del
    # Estado del cliente. La portada y la serie decian «Errores 85» (las
    # incidencias) junto a «72 paginas con error» (decision 202).
    paginas_con_error: int = 0
    # El tope de URLs si el rastreo se paro al llegar a el: la portada dice
    # «topado en N URLs» (revision de UX del 25-oct, 1.6; decision 203).
    topado: int | None = None
    alertas: int | None = None          # de la comparacion automatica; None = no se comparo
    alertas_criticas: int | None = None
    comparado_con: uuid.UUID | None = None
    # La fecha del censo con el que se comparo (ISO, de la comparacion): la
    # ficha del cliente dice «frente al 19 oct» aunque ese censo no este en la
    # serie (de otro cliente o fuera del limite). Revision de UX del 25-oct, 2.3.
    fecha_anterior: str | None = None


class PanelCliente(BaseModel):
    id: uuid.UUID
    nombre: str
    slug: str
    n_rastreos: int = 0
    ultimo: CensoDeSerie | None = None
    anterior: CensoDeSerie | None = None
    # De `profile_runs` (decision 130): la serie mas reciente con puntos
    # comparables, su ultimo punto y la tendencia de errores (que no dice sube
    # ni baja si entre los dos cambio la version del analisis). None = sin
    # ninguna ejecucion comparable agregada.
    evolucion: dict | None = None
    # Alertas abiertas o vistas de sus series (decision 139).
    incidentes_vivos: int = 0


class PanelResponse(BaseModel):
    clientes: list[PanelCliente]
    rastreos_sin_cliente: int = 0


class JobUpdate(BaseModel):
    """Lo que se puede cambiar de un rastreo ya hecho (UX-07/08): el nombre,
    el tipo y el cliente. Lo rastreado y lo analizado no se tocan.

    `cliente_id` explicito a null deja el rastreo sin cliente; omitirlo no lo
    cambia (se lee con `exclude_unset`). `tipo` a null vuelve a deducirlo del
    nombre.
    """

    name: str | None = Field(default=None, min_length=1, max_length=512)
    tipo: Literal["censo", "canario", "prueba"] | None = None
    cliente_id: uuid.UUID | None = None


class JobCreate(BaseModel):
    """Payload to create a new crawl job.

    Con cliente (#36): `cliente_id` y/o `profile_id`. La configuracion que
    llega aqui es solo lo que el job CAMBIA: se fusiona encima de la del
    cliente y la del perfil (`shared/clientes.fusionar_config`) y lo resuelto
    se copia en `jobs.config`. Por eso se lee con `exclude_unset`: si se
    leyera el `JobConfig` entero, sus valores por defecto pisarian todo lo
    heredado. Sin perfil, las semillas son obligatorias; con perfil, si no se
    mandan se usan las del perfil.

    `client_id` (texto) se mantiene por compatibilidad —`lanzar_job.py` y los
    backups viejos lo mandan—: se resuelve por slug y, si no existe, se crea el
    cliente.
    """

    name: str = Field(..., min_length=1, max_length=512)
    seeds: list[str] = Field(default_factory=list)
    client_id: str | None = Field(default=None, max_length=128)
    cliente_id: uuid.UUID | None = None
    profile_id: uuid.UUID | None = None
    # El tipo que elige quien lanza (revision de UX del 25-oct, 1.6; decision
    # 203): sin marcar, un rastreo de prueba contaba como censo en la portada
    # salvo que el nombre lo dijera. None = como antes (lo deduce del nombre):
    # los scripts y las programaciones no lo mandan.
    tipo: Literal["censo", "canario", "prueba"] | None = None
    config: JobConfig = Field(default_factory=JobConfig)

    @field_validator("seeds", mode="before")
    @classmethod
    def _semillas(cls, v: list[str] | None) -> list[str]:
        # Vacias se permiten AQUI: con perfil salen del perfil. El endpoint
        # comprueba que al final haya alguna.
        return _limpiar_semillas(v, obligatorias=False)

    @classmethod
    def validate_seeds(cls, v: list[str]) -> list[str]:
        """Semillas obligatorias. Lo reutilizan las programaciones."""
        return _limpiar_semillas(v, obligatorias=True)


class JobResponse(BaseModel):
    """Full representation of a crawl job."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    client_id: str | None
    cliente_id: uuid.UUID | None = None
    # Lo rellena el endpoint con una consulta aparte: una relacion cargada en
    # cada `query(Job)` seria un JOIN en el worker y el analizador para nada.
    cliente_nombre: str | None = None
    profile_id: uuid.UUID | None = None
    owner_id: str | None
    status: str
    # "finished" = frontera agotada; "max_urls_reached" = truncado
    finish_reason: str | None = None
    crawler_version: str | None = None
    # Comprobacion de render JS por plantilla (solo en rastreos sin render_js)
    js_check: dict[str, Any] | None = None
    comparacion: dict[str, Any] | None = None
    # Reglas propias del cliente evaluadas al cerrar el rastreo (decision 135)
    alertas_cliente: dict[str, Any] | None = None
    gsc_resumen: dict[str, Any] | None = None
    analisis_version: str | None = None
    # Reparto del PageRank por tipo de URL y fraccion desperdiciada en errores
    pagerank_resumen: dict[str, Any] | None = None
    logs_resumen: dict[str, Any] | None = None
    # Respuestas por clase (contenido, challenge_waf, rate_limited...) y la
    # causa si el rastreo se dio por bloqueado (decision 103).
    health: dict[str, Any] | None = None
    # Con que reglas se materializo `urls.segmento` y cuantas casaron (125).
    segmentacion: dict[str, Any] | None = None
    # Lo que el sitio responde a una URL que no existe, por host (decision 105).
    soft404: dict[str, Any] | None = None
    # Certificado TLS por host, el dia del rastreo (decision 110).
    tls: dict[str, Any] | None = None
    # Lo que leyo el adaptador de WordPress (decision 161): detectado, estado
    # de la REST API, plugin SEO, totales por tipo y si se corto.
    adapters: dict[str, Any] | None = None
    # Enlaces externos y recursos comprobados (decisiones 123 y 124). Con
    # «comprobados < distintos», que no haya aviso no dice nada: sin este campo
    # en la respuesta, eso solo se veia entrando en la base de datos.
    sondas_resumen: dict[str, Any] | None = None
    # Capa de decisiones (#7): llamadas, tokens, coste real, aciertos de
    # cache, 429, latencia y distribucion de respuestas. NULL = nunca se le
    # pregunto nada a un modelo sobre este job.
    decisiones_resumen: dict[str, Any] | None = None
    seeds: list[str]
    config: dict[str, Any]
    # El marcado a mano (NULL si no) y el que vale: el marcado o el que dice
    # el nombre (UX-07).
    tipo: str | None = None
    tipo_efectivo: str | None = None
    total_urls_discovered: int
    total_urls_crawled: int
    total_urls_failed: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class JobDetailResponse(JobResponse):
    """La ficha de UN job: lo de `JobResponse` y lo que solo se mira ahi.

    `sitemaps` (decision 126) es una fila por fichero leido, y un sitio con un
    indice de 500 ficheros la haria viajar en cada fila de `GET /api/jobs`, que
    pinta la lista de rastreos y no la usa. Por eso va en la ficha (GET, PATCH,
    cancelar y reanudar de un job) y no en `JobResponse`.
    """

    # Los ficheros de sitemap que se leyeron: `{ficheros: [{url, status,
    # formato, declaradas, devueltas, hijos, internas, bytes, cortado,
    # entradas_guardadas, leido_at}], pedidos, leidos, parcial, tope_entradas,
    # entradas_guardadas, entradas_recortadas}`. NULL = rastreo anterior o sin
    # sitemap.
    sitemaps: dict[str, Any] | None = None
    # Lo que dejaron sin rastrear los topes por carpeta (decision 172): por
    # regla y por grupo cortado. NULL = el job no tenia topes.
    topes_carpeta: dict[str, Any] | None = None
    # Rastreo incremental (decision 220): modo, motivo del completo, que se
    # selecciono y, tras el arrastre, cuanto se copio del censo anterior y de
    # cuando es. NULL = el perfil no tiene el incremental activo.
    incremental: dict[str, Any] | None = None
    # Segundos por fase del ultimo analisis (decision 226).
    analisis_fases: dict[str, Any] | None = None
    # Ritmo del rastreo y lo que lo limito (decision 227).
    ritmo: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# URL / HTML meta
# ---------------------------------------------------------------------------
class HtmlMetaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url_id: int
    title: str | None = None
    title_len: int | None = None
    meta_description: str | None = None
    meta_description_len: int | None = None
    meta_keywords: str | None = None
    meta_robots: str | None = None
    x_robots_tag: str | None = None
    canonical_href: str | None = None
    canonical_header: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image: str | None = None
    og_url: str | None = None
    og_type: str | None = None
    twitter_card: str | None = None
    twitter_title: str | None = None
    twitter_description: str | None = None
    rel_next: str | None = None
    rel_prev: str | None = None
    # Screaming Frog parity
    title_pixel_width: int | None = None
    meta_description_pixel_width: int | None = None
    meta_refresh: str | None = None
    has_meta_outside_head: bool | None = None
    # Decision 102: donde corta el navegador el head y que queda fuera.
    head_cortado_por: str | None = None
    fuera_del_head: str | None = None
    # Decision 108: lo que el HTML declara de si mismo.
    viewport: str | None = None
    viewport_count: int | None = None
    html_lang: str | None = None
    content_language: str | None = None
    canonical_crudo: str | None = None
    og_image_forma: str | None = None
    twitter_image: str | None = None
    redireccion_js: str | None = None
    charset_meta: str | None = None
    charset_bom: str | None = None
    cuerpo_solo_ascii: bool | None = None
    texto_mal_codificado: bool | None = None
    # Decisiones 155 y 156: videos de la pagina y versiones AMP y movil.
    videos: list[dict[str, Any]] | None = None
    amphtml: str | None = None
    alternate_movil: str | None = None
    # Decision 170: lo que data-nosnippet esconde al fragmento.
    data_nosnippet: dict[str, Any] | None = None


class PageContentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url_id: int
    content_text: str | None = None
    content_length: int | None = None
    content_markdown: str | None = None


class HeadingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tag: str
    position: int
    text: str | None = None
    oculto: bool | None = None


class ResourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_url: str
    resource_type: str
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None
    is_mixed_content: bool | None = None


class HreflangResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lang: str
    href: str
    return_tag_ok: bool | None = None
    lang_valid: bool | None = None
    origen: str | None = None  # html | cabecera; None = rastreo anterior (html)


class StructuredDataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    format: str
    schema_type: str | None = None
    validation_status: str | None = None
    validation_issues: dict[str, Any] | list | None = None
    raw: dict[str, Any] | list | None = None
    json_invalido: str | None = None


class SecurityHeadersResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    is_https: bool | None = None
    has_mixed_content: bool | None = None
    has_hsts: bool | None = None
    has_csp: bool | None = None
    has_x_content_type_options: bool | None = None
    has_x_frame_options: bool | None = None
    referrer_policy: str | None = None
    has_unsafe_crossorigin: bool | None = None


class UrlResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: uuid.UUID
    url: str
    host: str | None = None
    path: str | None = None
    scheme: str | None = None
    is_internal: bool | None = None
    crawl_depth: int | None = None
    click_depth: int | None = None
    # Search Console, decision 142
    gsc_clics: int | None = None
    gsc_impresiones: int | None = None
    gsc_posicion: float | None = None
    content_type: str | None = None
    content_length: int | None = None
    status_code: int | None = None
    status_group: str | None = None
    response_time_ms: float | None = None
    # Decision 109: TTFB real y Content-Encoding servido.
    ttfb_ms: float | None = None
    content_encoding: str | None = None
    is_html: bool | None = None
    resource_type: str | None = None
    redirect_url: str | None = None
    indexable: bool | None = None
    segmento: str | None = None  # decision 125
    first_seen_at: datetime | None = None
    last_crawled_at: datetime | None = None
    # Screaming Frog parity
    url_length: int | None = None
    folder_depth: int | None = None
    word_count: int | None = None
    content_word_count: int | None = None
    content_hash: str | None = None
    html_bytes_servidos: int | None = None
    text_ratio: float | None = None
    redirect_type: int | None = None
    status_text: str | None = None
    last_modified: str | None = None
    http_version: str | None = None
    transfer_size: int | None = None
    indexability_status: str | None = None
    blocked_by_robots: bool | None = None
    # Si Googlebot puede pedirla segun el robots.txt guardado (decision 113).
    # NULL = no evaluado.
    bloqueada_googlebot: bool | None = None
    # La respuesta era la pagina o un muro delante (decision 103).
    response_class: str | None = None
    # En un incremental (decision 220): fetched, not_modified o carried
    # (copiada del censo anterior; su `last_crawled_at` es de entonces).
    fetch_mode: str | None = None
    etag: str | None = None
    inlinks_count: int | None = None
    outlinks_count: int | None = None
    external_outlinks_count: int | None = None
    unique_inlinks_count: int | None = None
    pagerank: float | None = None
    # La escala que hay que leer y ordenar (decision 34). Sin esto en la
    # respuesta, la tabla solo podia pintar la 0-10 con cuatro decimales, donde
    # el 85% de las paginas de un censo queda en 0,00xx.
    pagerank_score: int | None = None
    pagerank_raw: float | None = None
    # Con los backlinks del cliente (decision 212); NULL sin CSV subido.
    pagerank_externo_score: int | None = None
    backlinks_externos: int | None = None
    backlinks_nofollow: int | None = None
    backlinks_spam: int | None = None
    backlinks_spam_pct: float | None = None
    autoridad_externa: float | None = None
    # Logs del servidor (decision 213); NULL sin logs subidos.
    googlebot_visitas: int | None = None
    googlebot_ultima: datetime | None = None
    in_sitemap: bool | None = None
    near_duplicate_count: int | None = None
    closest_similarity: float | None = None
    html_meta: HtmlMetaResponse | None = None
    page_content: PageContentResponse | None = None
    # Solo con `?origenes=true` (#131): la pagina que mas veces la enlaza y
    # cuantas paginas distintas la enlazan. Lo que convierte un 404 en tarea.
    enlazada_desde: str | None = None
    origenes: int | None = None
    # Solo con `?h1=true`: el primer H1 que se pinta y cuantos hay (los
    # ocultos no cuentan, decision 46).
    h1: str | None = None
    h1_count: int | None = None
    # Solo con `?cambios=true`: que cambio esta URL frente al censo de
    # referencia (el de la comparacion automatica o `?con=<job>`). «nueva» si
    # no estaba; None si no cambio nada de lo que se compara.
    cambio: str | None = None
    # Solo con `?a_medida=precio,sku|todas` (decision 104): las reglas a medida
    # EVALUADAS en esta URL, por nombre ({estado, n, valor, valores, valor_num,
    # truncado, render}). Un nombre que no esta es «no evaluada», no «vacio».
    a_medida: dict[str, dict[str, Any]] | None = None


class UrlDetailResponse(UrlResponse):
    """Full URL detail with all related data for the detail view."""

    # El de `links.to_url_hash`: «quien la enlaza» en la pestaña Enlaces
    # (decision 195), por el indice y sin depender de como se escribio la URL.
    url_hash: str | None = None

    headings: list[HeadingResponse] = []
    resources: list[ResourceResponse] = []
    hreflangs: list[HreflangResponse] = []
    structured_data: list[StructuredDataResponse] = []
    security: SecurityHeadersResponse | None = None
    issues: list[IssueResponse] = []
    inlinks: list[LinkResponse] = []
    outlinks: list[LinkResponse] = []
    # La misma URL pedida con otro perfil (decision 119): una por perfil
    capturas_alternativas: list[dict[str, Any]] = []
    # Capturas de pantalla de la URL (decision 173), una por perfil: los
    # metadatos y `src`, la ruta de la imagen en la API. Vacia = no se capturo.
    capturas_pantalla: list[dict[str, Any]] = []
    # La linea de robots.txt que bloquea la URL, para Googlebot y para nuestro
    # rastreo (decision 129). None = no esta bloqueada o no se puede afirmar.
    robots_regla: dict[str, Any] | None = None
    # De que ficheros de sitemap viene y con que lastmod (decision 126): uno
    # por fichero. Vacio = no esta en ningun fichero guardado (o el censo es
    # anterior a la tabla; `in_sitemap` dice si estaba).
    sitemaps: list[dict[str, Any]] = []
    # Lo que la REST API de WordPress dice de esta URL (decision 161, 168):
    # tipo (`post`, `page`, `category`...), su ID, estado y `modified_gmt`.
    # Emparejado como en el analisis: por `url_hash` o por la misma URL con el
    # otro esquema. Vacio = el adaptador no la leyo (no es WordPress, no se
    # analizo, o no es una entidad que la REST API liste).
    wordpress: list[dict[str, Any]] = []
    # La ultima inspeccion de Google de la URL (decision 189): fecha, ultima
    # visita, cobertura y canonical que elige Google frente al que vio
    # declarado. None = Search Console no la ha inspeccionado (es una muestra
    # diaria del cliente) o el censo no tiene cliente.
    google_inspeccion: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------
class IssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: uuid.UUID
    url_id: int
    url: str | None = None
    issue_type: str
    severity: str
    details: dict[str, Any] | None = None
    detected_at: datetime | None = None


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------
class LinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: uuid.UUID
    from_url_id: int
    from_url: str | None = None
    to_url: str
    anchor_text: str | None = None
    rel: str | None = None
    is_internal: bool | None = None
    link_position: str | None = None
    # Screaming Frog parity
    follow: bool | None = None
    target: str | None = None
    alt_text: str | None = None
    link_type: str | None = None
    # Apariciones identicas en la pagina de origen (decision 94)
    repeticiones: int = 1
    # Lo que respondio el destino a la sonda de enlaces externos (decision
    # 123): veredicto de `shared/sondas.py` y codigo. NULL = no se sondeo.
    estado_externo: str | None = None
    status_externo: int | None = None
    # Estado del destino, interno o externo (decision 195): roto,
    # redireccion, no_concluyente, sin_dato u ok; y su codigo (el del censo o
    # el de la sonda). NULL en las respuestas que no lo calculan.
    estado_destino: str | None = None
    status_destino: int | None = None


class EnlacesResponse(BaseModel):
    """`GET /links` con filtros (decision 195). `por_estado`: filas de cada
    estado del destino con los demas filtros, solo con `orden=estado`;
    `filtros`: los que se han aplicado, para que quien llama sepa que el
    servidor filtra (una API anterior devolvia la lista entera)."""
    items: list[LinkResponse]
    total: int
    page: int
    page_size: int
    pages: int
    orden: str
    por_estado: dict[str, int] | None = None
    filtros: dict[str, Any] = {}
    archivado: bool = False


class AnclaContada(BaseModel):
    texto: str
    veces: int


class DestinoEnlazadoResponse(BaseModel):
    to_url: str | None = None
    to_url_hash: str
    is_internal: bool
    paginas: int          # paginas distintas que lo enlazan
    enlaces: int          # filas: enlaces distintos (decision 94)
    apariciones: int      # SUM(repeticiones)
    nofollow: int         # enlaces nofollow
    anclas: list[AnclaContada] = []
    estado_destino: str
    status_destino: int | None = None
    veredicto_sonda: str | None = None
    url_id: int | None = None


class DestinosResponse(BaseModel):
    items: list[DestinoEnlazadoResponse]
    total: int
    page: int
    page_size: int
    pages: int
    orden: str
    por_estado: dict[str, int]
    filtros: dict[str, Any] = {}
    archivado: bool = False


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
class StatusGroupCount(BaseModel):
    status_group: str
    count: int


class IssueTypeCount(BaseModel):
    issue_type: str
    severity: str
    count: int


class HostCount(BaseModel):
    host: str
    count: int


class ResourceTypeCount(BaseModel):
    resource_type: str
    count: int


class JobStats(BaseModel):
    job_id: uuid.UUID
    total_urls: int
    total_urls_crawled: int
    total_urls_failed: int
    urls_by_status_group: list[StatusGroupCount]
    issues_by_type: list[IssueTypeCount]
    top_hosts: list[HostCount]
    urls_by_resource_type: list[ResourceTypeCount] = []
    internal_count: int = 0
    external_count: int = 0
    # Lo que dicen las tarjetas de la ficha (UX-13): sobre paginas HTML
    # internas que responden 2xx, que es donde la indexabilidad significa algo.
    paginas_html: int = 0
    indexables: int = 0
    no_indexables: int = 0
    # False en los censos analizados antes de la decision 90: ahi un
    # click_depth NULL es «sin calcular», no «sin camino desde la home».
    click_depth_calculada: bool = False
    # URLs distintas con alguna incidencia de gravedad error (la tarjeta
    # «Páginas con error»; la misma cuenta que el tope de la Puntuacion).
    paginas_con_error: int = 0


# ---------------------------------------------------------------------------
# Borrado en masa (decision 96)
# ---------------------------------------------------------------------------
class BorradoEnMasa(BaseModel):
    """Que rastreos borrar. Ids explicitos, nunca un filtro: ver el endpoint."""

    ids: list[uuid.UUID] = Field(min_length=1)
    # La vista previa del dialogo: mismos guardias, mismas cifras, sin borrar.
    simular: bool = False
    # Pasar por encima del guardia del censo de referencia de una programacion
    # activa. Lo pide la interfaz aparte, no va por defecto. Un rastreo en
    # marcha no se borra ni con esto (ver `_motivo_para_no_borrar`).
    forzar: bool = False
    # Presupuesto de tiempo de ESTA peticion. Lo que no se termine vuelve en
    # `pendientes` para repetirlo.
    segundos: int = Field(default=60, ge=5, le=600)


class JobBorrado(BaseModel):
    id: uuid.UUID
    nombre: str
    status: str
    created_at: datetime | None = None
    # Filas por tabla (`urls`, `links`, `issues`). None = no se pudieron contar.
    filas: dict[str, int] | None = None
    # Bytes estimados en la base, no medidos fila a fila (ver
    # shared/almacenamiento.py). Un censo archivado no cuenta aqui sus enlaces:
    # no estan en la base.
    bytes: int | None = None
    # Enlaces archivados en Parquet (decision 95) y lo que ocupa ese fichero,
    # medido. None = archivado pero no se sabe cuanto ocupa.
    archivado: bool = False
    archivo_bytes: int | None = 0
    # Capturas de pantalla del censo (decision 173), medidas en disco.
    capturas_bytes: int = 0
    # Solo en la simulacion: lo que conviene saber antes de darle, sin que
    # impida nada.
    aviso: str | None = None


class JobOmitido(BaseModel):
    id: uuid.UUID
    nombre: str | None = None
    motivo: str
    # Si `forzar` lo saltaria. Un rastreo en marcha no, ni uno que no existe.
    forzable: bool = False


class BorradoEnMasaResultado(BaseModel):
    simulado: bool
    eliminados: list[JobBorrado]
    omitidos: list[JobOmitido]
    # Los que no se llegaron a terminar dentro del presupuesto de tiempo.
    # Repetir la peticion con estos ids los acaba.
    pendientes: list[uuid.UUID]
    bytes_aprox: int | None = None
    # True = de alguno no se pudo medir el tamano, asi que `bytes_aprox` se
    # queda corto. Decirlo es mejor que dar una cifra que parece completa.
    bytes_incompletos: bool = False
    # Parquet de enlaces archivados que se van con estos censos. Aparte de
    # `bytes_aprox` porque ESTE espacio si vuelve al disco (ver `nota`).
    archivo_bytes: int = 0
    # True = algun Parquet no se pudo medir y `archivo_bytes` se queda corto.
    archivo_incompleto: bool = False
    # Capturas de pantalla que se van con estos censos (decision 173): como el
    # Parquet, vuelven al disco en el acto.
    capturas_bytes: int = 0
    filas: dict[str, int] = {}
    nota: str


# ---------------------------------------------------------------------------
# Espacio en disco (decision 96)
# ---------------------------------------------------------------------------
class TablaEnDisco(BaseModel):
    tabla: str
    bytes: int
    filas_aprox: int | None = None


class Almacenamiento(BaseModel):
    # None fuera de Postgres: no es que no ocupe nada, es que no se sabe.
    total_bytes: int | None = None
    censo_bytes: int | None = None
    tablas: list[TablaEnDisco] = []
    # Los Parquet de enlaces archivados (decision 95), fuera de Postgres y por
    # tanto fuera de `total_bytes`. None = el directorio no se pudo leer.
    archivo_bytes: int | None = None
    archivo_ficheros: int | None = None
    # Las capturas de pantalla (decision 173), tambien en el volumen de archivo.
    capturas_bytes: int | None = None
    nota: str


# ---------------------------------------------------------------------------
# Paginated wrapper
# ---------------------------------------------------------------------------
class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


# ---------------------------------------------------------------------------
# Clientes, perfiles e integraciones (#36, F1)
# ---------------------------------------------------------------------------
# Dicts que son DATOS del usuario: sus claves no las declara ningun schema.
_DICTS_DE_DATOS = {"http.custom_headers", "http.cookies"}
# Dicts de reglas con nombre (decision 104): sus claves son nombres que pone el
# usuario y cada valor es una regla ENTERA. No se entra dentro de una regla: una
# regla parcial no es valida (`tipo` y `expresion` son obligatorios) y en la
# herencia se sustituye completa. `null` en `<dict>.<nombre>` es quitar una
# regla heredada.
_DICTS_DE_REGLAS = {"custom_extraction", "custom_search"}


def _claves(d: Any, prefijo: str = "") -> set[str]:
    """Rutas de las claves de un dict anidado: `{"a": {"b": 1}}` -> {a, a.b}."""
    if not isinstance(d, dict):
        return set()
    rutas: set[str] = set()
    for k, v in d.items():
        ruta = f"{prefijo}{k}"
        rutas.add(ruta)
        if ruta in _DICTS_DE_REGLAS and isinstance(v, dict):
            rutas |= {f"{ruta}.{nombre}" for nombre in v}
        elif ruta not in _DICTS_DE_DATOS:
            rutas |= _claves(v, ruta + ".")
    return rutas


def _separar_nones(d: dict, prefijo: str = "") -> tuple[dict, list[str]]:
    """`{"a": None, "b": {"c": None, "d": 1}}` -> `({"b": {"d": 1}}, ["a", "b.c"])`."""
    valores: dict = {}
    borrados: list[str] = []
    for k, v in d.items():
        ruta = f"{prefijo}{k}"
        if v is None:
            borrados.append(ruta)
        elif ruta in _DICTS_DE_REGLAS and isinstance(v, dict):
            valores[k] = {n: r for n, r in v.items() if r is not None}
            borrados += [f"{ruta}.{n}" for n, r in v.items() if r is None]
        elif isinstance(v, dict) and ruta not in _DICTS_DE_DATOS:
            sub, sub_borrados = _separar_nones(v, ruta + ".")
            valores[k] = sub
            borrados += sub_borrados
        else:
            valores[k] = v
    return valores, borrados


def validar_config_parcial(d: dict[str, Any] | None) -> dict[str, Any]:
    """Valida una configuracion PARCIAL (la de un cliente o un perfil) y
    devuelve solo lo que fija, ya normalizado.

    Dos cosas que `JobConfig.model_validate(d).model_dump()` haria mal:

    - rellenaria todos los valores por defecto, asi que un cliente que solo
      fija `render_js` «fijaria» tambien `max_depth=3` y pisaria al perfil;
    - **tiraria en silencio lo que no esta declarado** (decision 33). En un job
      eso ya costo `use_sitemap`; en la configuracion de un cliente, que se
      escribe una vez y se hereda en cada rastreo, seria peor. Aqui una clave
      desconocida es un error que se nombra.

    Ademas, la contrasena de autenticacion basica no se acepta en un cliente
    ni en un perfil: se guardaria en la base de datos para siempre y saldria
    por `GET /api/clients` a cualquiera (decision 83). En un job puntual sigue
    pudiendo ir, como hasta ahora.
    """
    d = d or {}
    if not isinstance(d, dict):
        raise ValueError("la configuracion tiene que ser un objeto")
    # Un `None` explicito significa «quitar lo heredado» (un perfil que deja
    # sin tope de URLs a un cliente que lo fija). No es un valor, asi que no
    # se valida contra JobConfig —`render_js: None` no lo aceptaria—, pero se
    # GUARDA: es la unica forma de expresar esa intencion.
    valores, borrados = _separar_nones(d)
    modelo = JobConfig.model_validate(valores)
    parcial = modelo.model_dump(exclude_unset=True, mode="json")
    borrables = _claves(JobConfig().model_dump())
    tiradas = sorted((_claves(valores) - _claves(parcial))
                     | {b for b in borrados if b not in borrables
                        and b.rpartition(".")[0] not in _DICTS_DE_REGLAS})
    if tiradas:
        raise ValueError(
            "claves de configuracion desconocidas (no tendrian ningun efecto): "
            + ", ".join(tiradas))
    for ruta in borrados:
        destino = parcial
        *padres, hoja = ruta.split(".")
        for p in padres:
            destino = destino.setdefault(p, {})
        destino[hoja] = None
    if (parcial.get("http") or {}).get("basic_auth_password"):
        raise ValueError(
            "http.basic_auth_password no se guarda en un cliente ni en un "
            "perfil: la API no tiene autenticacion y se podria leer. Ponla en "
            "el rastreo concreto")
    return parcial


class Integracion(BaseModel):
    """Una API externa del cliente. **Sin secretos** (decision 83).

    `credencial_env` es el NOMBRE de la variable de entorno del servidor que
    tiene la clave (`DATAFORSEO_LIN3S`), no la clave. Tiene que empezar por el
    prefijo de su tipo (`shared/credenciales.PREFIJOS`).
    """

    model_config = ConfigDict(extra="forbid")

    tipo: Literal["gsc", "dataforseo", "ahrefs", "semrush", "majestic", "pagespeed", "slack"]
    etiqueta: str | None = Field(default=None, max_length=128)
    # Parametros publicos: propiedad de GSC, ubicacion e idioma de DataForSEO...
    parametros: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    credencial_env: str | None = Field(default=None, max_length=128)
    activa: bool = True

    @field_validator("credencial_env", mode="before")
    @classmethod
    def _vacio_es_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
        return v or None

    @field_validator("parametros")
    @classmethod
    def _sin_secretos(cls, v: dict) -> dict:
        from shared.credenciales import parametro_sospechoso

        clave = parametro_sospechoso(v)
        if clave:
            raise ValueError(
                f"el parametro {clave!r} parece un secreto. Los secretos no se "
                "guardan en la base de datos: van en una variable de entorno "
                "del servidor y aqui se pone su nombre en credencial_env")
        return v

    @model_validator(mode="after")
    def _variable_valida(self):
        from shared.credenciales import error_en_variable

        error = error_en_variable(self.tipo, self.credencial_env)
        if error:
            raise ValueError(error)
        return self


class IntegracionResponse(BaseModel):
    """Lo que se devuelve de una integracion: nunca el valor del secreto."""

    tipo: str
    etiqueta: str | None = None
    parametros: dict[str, Any] = Field(default_factory=dict)
    credencial_env: str | None = None
    activa: bool = True
    # Si la variable existe y no esta vacia en el entorno de la API.
    configurada: bool = False


_PATRON_DOMINIO = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")


def _validar_dominios(v: list[str] | None) -> list[str]:
    """`https://WWW.X.com/blog` -> `www.x.com`. Sin duplicados, en orden."""
    vistos: list[str] = []
    for d in v or []:
        d = (d or "").strip().lower()
        if not d:
            continue
        d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", d).split("/", 1)[0].split(":", 1)[0]
        if d != "localhost" and not _PATRON_DOMINIO.match(d):
            raise ValueError(f"{d!r} no es un dominio")
        if d not in vistos:
            vistos.append(d)
    return vistos


class DecisionesCliente(BaseModel):
    """Lo del cliente en la capa de decisiones (#7). Un presupuesto, no un
    secreto: la clave de OpenRouter va en el entorno (decision 84)."""

    model_config = ConfigDict(extra="forbid")

    # Tope de gasto en llamadas a modelos por mes natural (UTC), sumando todas
    # las ejecuciones del cliente. None = sin tope propio (manda el global,
    # `ENRICHMENT_MAX_USD_MES`). Con rastreos semanales, un tope por ejecucion
    # se multiplica sin control; este no.
    presupuesto_mensual_usd: float | None = Field(default=None, ge=0, le=100_000)


class _ClienteCampos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("slug", check_fields=False)
    @classmethod
    def _slug(cls, v: str | None) -> str | None:
        from shared.clientes import slug_valido

        if v is None:
            return v
        v = v.strip()
        if not slug_valido(v):
            raise ValueError(
                f"{v!r} no es un slug valido: minusculas, digitos y guiones")
        return v

    @field_validator("dominios", check_fields=False)
    @classmethod
    def _dominios(cls, v):
        return None if v is None else _validar_dominios(v)

    @field_validator("zona_horaria", check_fields=False)
    @classmethod
    def _zona(cls, v):
        return _validar_zona(v)

    @field_validator("config_defecto", check_fields=False)
    @classmethod
    def _config(cls, v):
        return None if v is None else validar_config_parcial(v)


class ClientCreate(_ClienteCampos):
    nombre: str = Field(..., min_length=1, max_length=256)
    # Si no se manda, sale del nombre.
    slug: str | None = Field(default=None, max_length=128)
    dominios: list[str] = Field(default_factory=list)
    zona_horaria: str | None = Field(default="Europe/Madrid", max_length=64)
    config_defecto: dict[str, Any] = Field(default_factory=dict)
    integraciones: list[Integracion] = Field(default_factory=list)
    decisiones: DecisionesCliente | None = None
    notas: str | None = None
    # Alta guiada (decision 194): crea tambien el perfil «Sitio principal» con
    # la home del primer dominio como semilla. Sin dominios no hace nada.
    perfil_principal: bool = False


class ClientUpdate(_ClienteCampos):
    nombre: str | None = Field(default=None, min_length=1, max_length=256)
    slug: str | None = Field(default=None, max_length=128)
    dominios: list[str] | None = None
    zona_horaria: str | None = Field(default=None, max_length=64)
    config_defecto: dict[str, Any] | None = None
    # Se sustituye la lista entera: es como la edita la interfaz.
    integraciones: list[Integracion] | None = None
    decisiones: DecisionesCliente | None = None
    notas: str | None = None


class ClientResponse(BaseModel):
    id: uuid.UUID
    nombre: str
    slug: str
    dominios: list[str] = Field(default_factory=list)
    zona_horaria: str | None = None
    config_defecto: dict[str, Any] = Field(default_factory=dict)
    integraciones: list[IntegracionResponse] = Field(default_factory=list)
    decisiones: dict[str, Any] | None = None
    notas: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    n_perfiles: int = 0
    n_jobs: int = 0
    ultimo_job_at: datetime | None = None


class _PerfilCampos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("seeds", check_fields=False, mode="before")
    @classmethod
    def _semillas(cls, v):
        return None if v is None else _limpiar_semillas(v, obligatorias=True)

    @field_validator("config", check_fields=False)
    @classmethod
    def _config(cls, v):
        return None if v is None else validar_config_parcial(v)


class ProfileCreate(_PerfilCampos):
    nombre: str = Field(..., min_length=1, max_length=256)
    rol: Literal["propio", "competidor"] = "propio"
    seeds: list[str] = Field(..., min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    notas: str | None = None
    activo: bool = True
    # «Programar» desde un rastreo (revision de UX del 25-oct, 2.2): el perfil
    # nuevo guarda lo que la config de ese rastreo tiene de distinto respecto
    # al cliente (sus exclusiones, su profundidad...). `config`, si viene, va
    # encima.
    desde_job_id: uuid.UUID | None = None


class ProfileUpdate(_PerfilCampos):
    nombre: str | None = Field(default=None, min_length=1, max_length=256)
    rol: Literal["propio", "competidor"] | None = None
    seeds: list[str] | None = None
    config: dict[str, Any] | None = None
    notas: str | None = None
    activo: bool | None = None


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cliente_id: uuid.UUID
    nombre: str
    rol: str
    seeds: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    notas: str | None = None
    activo: bool = True
    last_job_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Lo que no se pudo copiar al crear el perfil desde un rastreo.
    avisos: list[str] = Field(default_factory=list)


class AvisoDeConfig(BaseModel):
    nivel: Literal["peligro", "aviso", "info"]
    texto: str
    # La clave de la configuracion a la que se refiere, si es una.
    campo: str | None = None


class ProgramacionPropia(BaseModel):
    id: uuid.UUID
    nombre: str
    claves: list[str] = Field(default_factory=list)


class ConfigResueltaResponse(BaseModel):
    """La configuracion que tendria un job lanzado ahora desde este cliente
    (y perfil): para precargar el modal con lo heredado."""

    # None en un borrador sin cliente (decision 196).
    cliente_id: uuid.UUID | None = None
    profile_id: uuid.UUID | None = None
    seeds: list[str] = Field(default_factory=list)
    # Completa: lo que tendria el job (defaults incluidos).
    config: dict[str, Any]
    # Solo lo que fijan cliente y perfil, sin los defaults. Es lo que precarga
    # el modal: con la completa, un default de la API (el UA `SEOCrawler/1.0`)
    # pisaria el del formulario sin que nadie lo hubiera elegido.
    config_heredada: dict[str, Any] = Field(default_factory=dict)
    # Decision 196 (revision de UX del 25-oct, 2.4): de donde sale cada clave
    # de `config` («cliente», «perfil» o el nivel del borrador); lo que no
    # sale es el valor de serie, que va entero en `serie`. Con `avisos`, el
    # bloque «Así rastreará» de la interfaz.
    origen: dict[str, str] = Field(default_factory=dict)
    # Cabeceras, cookies, topes y reglas con nombre se fusionan clave a clave:
    # aqui la capa de cada clave (`{"http.custom_headers": {"X-A": "cliente"}}`).
    origen_por_clave: dict[str, dict[str, str]] = Field(default_factory=dict)
    serie: dict[str, Any] = Field(default_factory=dict)
    avisos: list[AvisoDeConfig] = Field(default_factory=list)
    # Las programaciones del perfil que cambian algo por su cuenta
    # (`config_propia`, decision 193): el proximo disparo lleva ademas eso.
    programaciones: list[ProgramacionPropia] = Field(default_factory=list)


class ConfigBorrador(BaseModel):
    """`POST /api/clients/config-resuelta` (decision 196): la configuracion
    con la que saldria un rastreo si `config` fuera la del `nivel` indicado,
    sin guardar nada. Es lo que pinta el bloque «Así rastreará» mientras se
    edita el formulario del cliente, del perfil o del rastreo."""

    model_config = ConfigDict(extra="forbid")

    cliente_id: uuid.UUID | None = None
    profile_id: uuid.UUID | None = None
    nivel: Literal["cliente", "perfil", "rastreo"] = "rastreo"
    config: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Backup / Import
# ---------------------------------------------------------------------------
class BackupManifest(BaseModel):
    format_version: str
    export_timestamp: datetime
    job_id: uuid.UUID
    job_name: str
    job_status: str
    row_counts: dict[str, int]
    has_page_content: bool


class ImportResponse(BaseModel):
    new_job_id: uuid.UUID
    original_job_id: uuid.UUID
    rows_imported: dict[str, int]
    rows_skipped: dict[str, int]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Post-crawl cleaning
# ---------------------------------------------------------------------------
class CleaningRule(BaseModel):
    """One cleaning rule. See api/cleaning_engine.py for semantics."""

    type: Literal[
        "line_exact", "line_prefix", "line_contains",
        "cut_from_line", "remove_substring", "regex",
    ]
    value: str = Field(..., min_length=1, max_length=2000)


class CleaningLineaRepetida(BaseModel):
    texto: str
    paginas: int


class CleaningGroupInfo(BaseModel):
    group_key: str
    pages: int
    cleaned_pages: int
    avg_content_length: int
    sample_urls: list[str]
    # Texto repetido en una muestra del grupo (decision 198). None si no se
    # midio (grupo de menos de 3 paginas o fuera de los mas grandes).
    repetido_parte: float | None = None
    repetido_chars_medio: int | None = None
    repetido_muestra: int | None = None
    lineas_repetidas: list[CleaningLineaRepetida] = []
    # Cuantas lineas repetidas hay en total y que parte del texto quitan las
    # de `lineas_repetidas` (las de mas peso, con tope): la cifra del grupo es
    # de todas y «Quitar todas estas lineas» solo de las que se mandan.
    lineas_repetidas_total: int | None = None
    repetido_parte_lineas: float | None = None


class CleaningPreviewRequest(BaseModel):
    group_key: str | None = None
    url_regex: str | None = Field(default=None, max_length=500)
    rules: list[CleaningRule] = Field(..., min_length=1, max_length=50)
    targets: Literal["text", "markdown", "both"] = "both"
    sample_size: int = Field(default=5, ge=1, le=20)


class CleaningPreviewSample(BaseModel):
    url: str
    before_excerpt: str
    after_excerpt: str
    chars_removed: int
    removed_pct: float


class CleaningPreviewResponse(BaseModel):
    samples: list[CleaningPreviewSample]
    total_chars_removed: int
    pages_skipped_safety: int


class CleaningApplyRequest(BaseModel):
    group_key: str | None = None
    url_regex: str | None = Field(default=None, max_length=500)
    rules: list[CleaningRule] = Field(..., min_length=1, max_length=50)
    targets: Literal["text", "markdown", "both"] = "both"


class CleaningRevertRequest(BaseModel):
    group_key: str | None = None
    url_regex: str | None = Field(default=None, max_length=500)


class CleaningApplyResponse(BaseModel):
    ruleset_id: int | None
    pages_updated: int
    pages_skipped_safety: int
    total_chars_removed: int


class CleaningRulesetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: uuid.UUID
    group_key: str | None
    url_regex: str | None
    rules: list
    targets: str
    pages_updated: int
    pages_skipped: int
    chars_removed: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Analisis enriquecido (#40, decision 85)
# ---------------------------------------------------------------------------
class AlcanceEnriquecido(BaseModel):
    """Sobre que URLs. Vacio = todas las HTML internas, 200 e indexables.

    `extra="forbid"`: una clave mal escrita (`max_url`) seria un alcance que
    se ignora en silencio, y aqui eso es pagar por todo el sitio en vez de
    por la muestra que se pidio (decision 33)."""

    model_config = ConfigDict(extra="forbid")

    carpeta: str | None = Field(default=None, max_length=512)
    max_urls: int | None = Field(default=None, ge=1, le=1_000_000)
    muestra: bool = False


class EnriquecidoEstimar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modulos: list[str] = Field(..., min_length=1, max_length=50)
    alcance: AlcanceEnriquecido = Field(default_factory=AlcanceEnriquecido)


class EnriquecidoCrear(EnriquecidoEstimar):
    # Obligatorio: lanzar sin tope de ejecucion seria dejar todo en manos del
    # mensual, y el dialogo siempre propone uno.
    presupuesto_usd: float = Field(..., ge=0, le=10_000)


class EnrichmentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    modulos: list[str]
    alcance: dict[str, Any]
    estimacion: dict[str, Any] | None = None
    presupuesto_usd: float | None = None
    gastado_usd: float = 0.0
    estado: str
    motivo: str | None = None
    progreso: dict[str, Any] | None = None
    errores: list[str] | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    latido_at: datetime | None = None
    # Distribucion de respuestas por pregunta, para la pestaña.
    resultados: dict[str, Any] | None = None
