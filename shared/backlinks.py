"""Enlaces externos (backlinks) subidos en CSV, y su cruce con un censo (#31, decision 212).

Lo comparten la API (subir el CSV de un cliente) y el analizador (el PageRank
con la autoridad que entra de fuera y los avisos de lo que se pierde).

- **De un CSV exportado, sin API de pago.** Ahrefs, Semrush y Majestic cada
  uno con sus columnas: se reconocen por nombre, sin mayusculas ni espacios,
  y el separador y la codificacion (Ahrefs exporta UTF-16 con tabuladores) se
  detectan. Lo que no es dofollow o esta perdido no se guarda.
- **El spam que marca el proveedor se guarda, pero no aporta.** Ahrefs exporta
  «Is spam» por backlink: se guarda (`external_links.spam`) y se cuenta, para
  decir cuanto de lo que llega es spam, pero no suma autoridad. Una red de
  dominios de spam enlazando a la home inflaba su PageRank desde fuera (en
  mobilitycentro, 411 de 485 dofollow). Sin esa columna (Semrush, Majestic),
  NULL: no se afirma ni que sea ni que no sea spam.
- **La aportacion es la de cada backlink**, no la autoridad de la pagina de
  destino: la de destino (UR, Page Authority) ya incluye los enlaces internos
  del sitio vistos por el proveedor y se contaria dos veces. Por backlink:
  autoridad de la pagina de origen / (enlaces externos de esa pagina + 1),
  como reparte el PageRank. Sin autoridad, 1; sin enlaces externos, sin
  dividir.
- **El cruce no pasa la ruta a minusculas**: `/Producto` y `/producto` son dos
  URLs en casi cualquier servidor. Si cuenta: el esquema, el `www.`, la barra
  final, el fragmento y la codificacion (`%C3%B1` es `ñ`). Si la URL exacta con
  su query no esta en el censo, se prueba sin la query (un `?utm_` de una
  campaña).
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

# Lo que se acepta de un fichero. Un export de Ahrefs en UTF-16 con el contexto
# de cada enlace son 1-2 KB por fila: 200.000 filas, unos 400 MB. Se lee en
# streaming y solo se guardan las filas, no el fichero.
MAX_BYTES = 500 * 1024 * 1024
MAX_FILAS = 200_000

# Nombres de columna (sin mayusculas, espacios ni signos) -> campo.
_COLUMNAS = {
    "origen": ("referringpageurl", "sourceurl", "urlfrom", "referringurl", "source", "linkfrom", "fromurl"),
    "destino": ("targeturl", "urlto", "target", "linkto", "tourl", "destinationurl"),
    # La autoridad de la PAGINA de origen. Majestic no tiene una de pagina con
    # el mismo sentido: su Citation Flow de la fuente es lo mas parecido.
    "autoridad": ("ur", "urlrating", "pageascore", "sourcecitationflow", "sourcetrustflow",
                  "pageauthority", "pa", "rank", "pagerank"),
    "externos": ("externallinks", "externallinkscount", "outlinks", "sourceoutlinks",
                 "externaloutlinks", "linkeddomains"),
    "nofollow": ("nofollow", "flagnofollow", "isnofollow"),
    # Ahrefs y Semrush las exportan aparte del nofollow, como true/false.
    "ugc": ("ugc", "isugc", "flagugc"),
    "sponsored": ("sponsored", "issponsored", "flagsponsored"),
    "tipo": ("type", "linktype", "linkattributes", "rel"),
    "perdido": ("lost", "lostlink", "loststatus", "lostdate", "flagdeleted", "deleted"),
    "spam": ("isspam", "spam", "flagspam"),
}

FUENTES = ("ahrefs", "semrush", "majestic", "generico")


class CsvNoValido(ValueError):
    pass


def _norm_columna(nombre: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (nombre or "").strip().lower())


def _codificacion(muestra: bytes) -> str:
    """Por los primeros bytes: el BOM, o la mitad de los bytes a cero (UTF-16
    sin BOM). Sin eso, UTF-8; y si no lo es, latin-1."""
    if muestra.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if muestra.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if muestra and muestra.count(b"\x00") > len(muestra) // 4:
        return "utf-16-le" if muestra[1:2] == b"\x00" else "utf-16-be"
    try:
        muestra.decode("utf-8")
    except UnicodeDecodeError as exc:
        # Un caracter cortado al final de la muestra no es latin-1.
        return "utf-8" if exc.start >= len(muestra) - 3 else "latin-1"
    return "utf-8"


def _separador(cabecera: str) -> str:
    return max(("\t", ",", ";"), key=cabecera.count)


def _verdad(valor: str | None) -> bool | None:
    v = (valor or "").strip().lower()
    # Majestic marca sus banderas con «+» y «-».
    if v in ("true", "1", "yes", "si", "sí", "nofollow", "y", "+"):
        return True
    if v in ("false", "0", "no", "", "dofollow", "follow", "n", "-"):
        return False if v else None
    return None


def _numero(valor: str | None) -> float | None:
    v = (valor or "").strip().replace(" ", "")
    if not v:
        return None
    # «1.234» / «1,234» son miles; «12,5», «0.125» decimales; «1,234.5» y
    # «1.234,5», las dos cosas (manda el ultimo separador).
    if "," in v and "." in v:
        decimal = "," if v.rfind(",") > v.rfind(".") else "."
        v = v.replace("." if decimal == "," else ",", "").replace(",", ".")
    elif re.fullmatch(r"[1-9]\d{0,2}([.,]\d{3})+", v):
        v = re.sub(r"[.,]", "", v)
    else:
        v = v.replace(",", ".")
    try:
        n = float(v)
    except ValueError:
        return None
    return n if math.isfinite(n) else None


def fuente_de(cabeceras: Iterable[str]) -> str:
    c = {_norm_columna(x) for x in cabeceras}
    if "referringpageurl" in c or "ur" in c:
        return "ahrefs"
    if "pageascore" in c:
        return "semrush"
    if "sourcecitationflow" in c or "flagnofollow" in c:
        return "majestic"
    return "generico"


@dataclass
class Lectura:
    fuente: str
    filas: list[dict[str, Any]] = field(default_factory=list)
    leidas: int = 0
    descartadas_nofollow: int = 0
    descartadas_perdidas: int = 0
    descartadas_sin_url: int = 0
    spam: int = 0
    cortado: bool = False
    columnas: dict[str, str] = field(default_factory=dict)


def leer_csv(origen, *, fuente: str | None = None, max_filas: int = MAX_FILAS) -> Lectura:
    """Las filas dofollow y vivas de un export, con su aportacion. `origen` es
    un fichero binario (se lee en streaming: un export de Ahrefs en UTF-16 con
    el contexto de cada enlace son 1-2 KB por fila) o unos bytes.

    `CsvNoValido` si no hay columnas de origen y destino, o no se puede leer.
    """
    f = io.BytesIO(origen) if isinstance(origen, (bytes, bytearray)) else origen
    if isinstance(origen, (bytes, bytearray)) and len(origen) > MAX_BYTES:
        raise CsvNoValido(f"El fichero pasa de {MAX_BYTES // (1024 * 1024)} MB")
    try:
        return _leer(f, fuente, max_filas)
    except (UnicodeError, csv.Error) as exc:
        raise CsvNoValido(f"No se puede leer el fichero: {exc}") from exc


def _leer(f, fuente, max_filas) -> Lectura:
    muestra = f.read(4096)
    f.seek(0)
    texto = io.TextIOWrapper(f, encoding=_codificacion(muestra), errors="strict", newline="")
    cabecera_txt = texto.readline()
    if not cabecera_txt.strip():
        raise CsvNoValido("El fichero está vacío")
    delimitador = _separador(cabecera_txt)
    cabecera = next(csv.reader([cabecera_txt], delimiter=delimitador))
    lector = csv.reader(texto, delimiter=delimitador)
    normal = [_norm_columna(c) for c in cabecera]
    indice: dict[str, int] = {}
    for campo, alias in _COLUMNAS.items():
        for a in alias:
            if a in normal:
                indice[campo] = normal.index(a)
                break
    if "origen" not in indice or "destino" not in indice:
        raise CsvNoValido("No se reconocen las columnas de la página que enlaza y la enlazada "
                          "(«Referring page URL» y «Target URL» en Ahrefs; «Source url» y "
                          "«Target url» en Semrush; «Source URL» y «Target URL» en Majestic)")
    lec = Lectura(fuente=fuente if fuente in FUENTES else fuente_de(cabecera),
                  columnas={k: cabecera[i] for k, i in indice.items()})

    def celda(fila, campo):
        i = indice.get(campo)
        return fila[i] if i is not None and i < len(fila) else None

    for fila in lector:
        if not any(fila):
            continue
        lec.leidas += 1
        origen, destino = (celda(fila, "origen") or "").strip(), (celda(fila, "destino") or "").strip()
        if not origen.startswith(("http://", "https://")) or not destino.startswith(("http://", "https://")):
            lec.descartadas_sin_url += 1
            continue
        nofollow = (_verdad(celda(fila, "nofollow")) or _verdad(celda(fila, "ugc"))
                    or _verdad(celda(fila, "sponsored")))
        tipo = (celda(fila, "tipo") or "").lower()
        if nofollow or "nofollow" in tipo or "ugc" in tipo or "sponsored" in tipo:
            lec.descartadas_nofollow += 1
            continue
        perdido = (celda(fila, "perdido") or "").strip().lower()
        if perdido and perdido not in ("0", "false", "no", "-", "live", "active", "not lost"):
            lec.descartadas_perdidas += 1
            continue
        if len(lec.filas) >= max_filas:
            lec.cortado = True
            continue
        autoridad = _numero(celda(fila, "autoridad"))
        externos = _numero(celda(fila, "externos"))
        aporte = (autoridad if autoridad is not None and autoridad > 0 else 1.0) / (
            (externos if externos is not None and externos >= 0 else 0.0) + 1.0)
        spam = _verdad(celda(fila, "spam")) if "spam" in indice else None
        lec.spam += bool(spam)
        lec.filas.append({"url_from": origen[:2000], "url_to": destino[:2000],
                          "dominio_from": (urlsplit(origen).hostname or "")[:255],
                          "aportacion": round(aporte, 6), "spam": spam})
    return lec


def clave_backlink(url: str) -> str | None:
    """La URL tal como se cruza con el censo, sin pasar la ruta a minusculas."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    ruta = unquote(p.path or "/")
    if len(ruta) > 1:
        ruta = ruta.rstrip("/") or "/"
    clave = host + ruta
    return clave + ("?" + unquote(p.query) if p.query else "")


def sin_query(clave: str) -> str:
    return clave.split("?", 1)[0]


@dataclass
class Cruce:
    """Lo que llega de fuera a cada URL del censo, y lo que no casa."""
    por_url: dict[int, dict[str, Any]]
    filas: int
    casadas: int
    aportacion_total: float
    aportacion_casada: float
    no_rastreadas: list[dict[str, Any]]
    # Los marcados como spam por el proveedor: cuentan como backlinks, no aportan.
    spam: int = 0
    spam_casados: int = 0

    @property
    def parte_casada(self) -> float | None:
        return round(self.casadas / self.filas, 4) if self.filas else None


def _exacta(url: str) -> str:
    return url.strip().split("#", 1)[0]


def rango_de(status: int | None, indexable: bool | None, redirect: str | None) -> int:
    """Para desempatar dos URLs del censo con la misma clave: 200 indexable,
    200, redireccion, error."""
    if status == 200 and indexable:
        return 0
    if status == 200:
        return 1
    if redirect or (status is not None and 300 <= status < 400):
        return 2
    return 3


@dataclass
class IndiceCenso:
    """Las URLs internas de un censo, para cruzar con lo que llega de fuera
    (backlinks, logs del servidor): exactas, por clave suelta y por clave sin
    query. Lo comparten los dos cruces para que la regla de desempate sea una."""
    exactas: dict[str, int] = field(default_factory=dict)
    por_clave: dict[str, tuple[int, int]] = field(default_factory=dict)
    por_ruta: dict[str, tuple[int, int]] = field(default_factory=dict)

    def por_clave_suelta(self, k: str | None) -> int | None:
        if k is None:
            return None
        hit = self.por_clave.get(k) or (self.por_ruta.get(sin_query(k)) if "?" in k else None)
        return hit[1] if hit else None

    def buscar(self, url: str) -> int | None:
        uid = self.exactas.get(_exacta(url))
        return uid if uid is not None else self.por_clave_suelta(clave_backlink(url))


def indice_de_censo(urls: Iterable[tuple]) -> IndiceCenso:
    """`urls`: (id, url) o (id, url, rango). Primero la URL exacta (sin el
    fragmento); si no esta, la clave suelta (esquema, `www.`, barra final), y
    si varias URLs comparten clave (`/a` 404 y `/a/` 200 en un WordPress) gana
    la de menor `rango` (`rango_de`) y, a igualdad, la de menor id: siempre la
    misma, y nunca un 404 si esta su version buena."""
    ind = IndiceCenso()

    def _mejor(d, k, rango, uid):
        actual = d.get(k)
        if actual is None or (rango, uid) < actual:
            d[k] = (rango, uid)

    for u in urls:
        uid, url = u[0], u[1]
        rango = u[2] if len(u) > 2 else 0
        ind.exactas.setdefault(_exacta(url), uid)
        k = clave_backlink(url)
        if k is None:
            continue
        _mejor(ind.por_clave, k, rango, uid)
        if "?" not in k:
            _mejor(ind.por_ruta, k, rango, uid)
    return ind


def cruzar(filas: Iterable[tuple], urls: Iterable[tuple],
           *, max_no_rastreadas: int = 50, max_origenes: int = 5) -> Cruce:
    """`filas`: (url_to, url_from, dominio_from, aportacion[, spam]). `urls`:
    (id, url) o (id, url, rango) de las internas del censo (`indice_de_censo`).
    Un backlink spam cuenta en `backlinks` y en `spam`, no en la aportacion
    ni entre los origenes que se ensenan."""
    indice = urls if isinstance(urls, IndiceCenso) else indice_de_censo(urls)
    por_url: dict[int, dict[str, Any]] = {}
    fuera: dict[str, dict[str, Any]] = {}
    n = casadas = spam_total = spam_casados = 0
    total = casada = 0.0
    for fila in filas:
        url_to, url_from, dominio, aporte = fila[:4]
        es_spam = bool(fila[4]) if len(fila) > 4 else False
        n += 1
        spam_total += es_spam
        aporte = 0.0 if es_spam else float(aporte or 0)
        total += aporte
        uid = indice.buscar(url_to)
        if uid is None:
            f = fuera.setdefault(url_to, {"url": url_to, "backlinks": 0, "spam": 0, "aportacion": 0.0,
                                          "dominios": set()})
            f["backlinks"] += 1
            f["spam"] += es_spam
            f["aportacion"] += aporte
            f["dominios"].add(dominio)
            continue
        casadas += 1
        spam_casados += es_spam
        casada += aporte
        d = por_url.setdefault(uid, {"backlinks": 0, "spam": 0, "aportacion": 0.0, "dominios": set(),
                                     "origenes": []})
        d["backlinks"] += 1
        d["spam"] += es_spam
        d["aportacion"] += aporte
        d["dominios"].add(dominio)
        if not es_spam:
            d["origenes"].append((aporte, url_from))
    for d in por_url.values():
        d["origenes"] = [u for _, u in sorted(d["origenes"], reverse=True)[:max_origenes]]
        d["dominios"] = len(d["dominios"])
    no_rastreadas = sorted(fuera.values(), key=lambda f: -f["aportacion"])[:max_no_rastreadas]
    for f in no_rastreadas:
        f["dominios"] = len(f["dominios"])
        f["aportacion"] = round(f["aportacion"], 4)
    return Cruce(por_url=por_url, filas=n, casadas=casadas, aportacion_total=total,
                 aportacion_casada=casada, no_rastreadas=no_rastreadas,
                 spam=spam_total, spam_casados=spam_casados)


def ultima_importacion(session, cliente_id):
    """La importacion mas reciente del cliente, o None."""
    from shared.models import BacklinkImport

    if not cliente_id:
        return None
    return (session.query(BacklinkImport).filter(BacklinkImport.cliente_id == cliente_id)
            .order_by(BacklinkImport.created_at.desc(), BacklinkImport.id.desc()).first())


def filas_de(session, importacion) -> list[tuple[str, str, str, float, bool | None]]:
    from shared.models import ExternalLink as E

    return [tuple(f) for f in session.query(E.url_to, E.url_from, E.dominio_from, E.aportacion, E.spam)
            .filter(E.import_id == importacion.id).all()]


def agrupar_por_destino(filas: Iterable[dict]) -> dict[str, int]:
    """Cuantos backlinks hay por URL de destino (para el resumen de la subida)."""
    c: dict[str, int] = defaultdict(int)
    for f in filas:
        c[f["url_to"]] += 1
    return dict(c)
