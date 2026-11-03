"""Backlinks subidos en CSV (#31, decision 212): la lectura de cada export,
el cruce con el censo y el PageRank personalizado sobre grafos pequenos.
Funciones puras, sin base de datos (el analisis entero va en
`test_backlinks_db.py`)."""

from __future__ import annotations

import numpy as np
import pytest

from analysis import pagerank as prk
from shared import backlinks as B

AHREFS = ("Referring page title\tReferring page URL\tDomain rating\tUR\tExternal links\tTarget URL\t"
          "Anchor\tType\tNofollow\tUGC\tSponsored\tLost status\n"
          "Blog A\thttps://blog-a.com/post\t60\t30\t9\thttps://www.x.com/Producto/\tver\ttext\tfalse\tfalse\tfalse\t\n"
          "Blog B\thttps://blog-b.com/\t20\t12\t2\thttps://x.com/viejo\tleer\ttext\ttrue\tfalse\tfalse\t\n"
          "Foro\thttps://foro.com/hilo\t40\t5\t0\thttp://x.com/roto?utm_source=foro\taqui\ttext\tfalse\tfalse\tfalse\tlost\n"
          "Web C\thttps://web-c.com/\t10\t8\t3\thttps://x.com/a%C3%B1o/\tano\ttext\tfalse\tfalse\tfalse\t\n"
          "Foro UGC\thttps://foro2.com/\t50\t20\t1\thttps://x.com/\tugc\ttext\tfalse\ttrue\tfalse\t\n"
          "Patrocinio\thttps://ads.com/\t50\t20\t1\thttps://x.com/\tad\ttext\tfalse\tfalse\ttrue\t\n")
SEMRUSH = ("Page ascore,Source title,Source url,Target url,Anchor,External links,Internal links,Nofollow,"
           "Sponsored,Ugc,First seen,Last seen,New link,Lost link\n"
           "45,Uno,https://uno.com/a,https://x.com/,inicio,4,10,false,false,false,2026-01-01,2026-10-01,false,false\n"
           "30,Dos,https://dos.com/b,https://x.com/b,b,0,3,true,false,false,2026-01-01,2026-10-01,false,false\n")
# «Is spam» de Ahrefs: el tercero es spam y nofollow, y se descarta como nofollow.
AHREFS_SPAM = ("Referring page URL\tUR\tExternal links\tTarget URL\tNofollow\tIs spam\n"
               "https://bueno.com/a\t30\t2\thttps://x.com/\tfalse\tfalse\n"
               "https://red.shop/1\t10\t0\thttps://x.com/\tfalse\ttrue\n"
               "https://red.site/2\t10\t0\thttps://x.com/viejo\tfalse\ttrue\n"
               "https://red.online/3\t10\t0\thttps://x.com/\ttrue\ttrue\n")
MAJESTIC = ("Source URL,Target URL,Anchor Text,SourceCitationFlow,SourceTrustFlow,FlagNoFollow,FlagDeleted\n"
            "https://m.com/1,https://x.com/c,c,22,10,-,-\n"
            "https://m.com/2,https://x.com/d,d,30,10,+,-\n")


def test_ahrefs_en_utf16_con_tabuladores():
    lec = B.leer_csv(AHREFS.encode("utf-16"))
    assert lec.fuente == "ahrefs" and lec.leidas == 6
    assert (lec.descartadas_nofollow, lec.descartadas_perdidas) == (3, 1), "UGC y Sponsored van aparte"
    urls = [f["url_to"] for f in lec.filas]
    assert urls == ["https://www.x.com/Producto/", "https://x.com/a%C3%B1o/"]
    # La aportacion es la de cada backlink: UR del origen / (externos + 1)
    assert lec.filas[0]["aportacion"] == pytest.approx(30 / 10)
    assert lec.filas[0]["dominio_from"] == "blog-a.com"


def test_semrush_y_majestic():
    lec = B.leer_csv(SEMRUSH.encode())
    assert lec.fuente == "semrush" and [f["url_to"] for f in lec.filas] == ["https://x.com/"]
    assert lec.filas[0]["aportacion"] == pytest.approx(45 / 5)
    lec = B.leer_csv(MAJESTIC.encode("utf-8-sig"))
    assert lec.fuente == "majestic" and lec.filas[0]["aportacion"] == pytest.approx(22.0)
    assert len(lec.filas) == 1 and lec.descartadas_nofollow == 1, "el «+» de Majestic es nofollow"


def test_el_spam_de_ahrefs_se_guarda_y_no_aporta():
    lec = B.leer_csv(AHREFS_SPAM.encode("utf-16"))
    assert (lec.spam, lec.descartadas_nofollow) == (2, 1)
    assert [f["spam"] for f in lec.filas] == [False, True, True]
    assert lec.columnas["spam"] == "Is spam"
    filas = [(f["url_to"], f["url_from"], f["dominio_from"], f["aportacion"], f["spam"]) for f in lec.filas]
    c = B.cruzar(filas, [(1, "https://x.com/")])
    d = c.por_url[1]
    assert (d["backlinks"], d["spam"]) == (2, 1), "el spam cuenta como backlink"
    assert d["aportacion"] == pytest.approx(30 / 3) and d["origenes"] == ["https://bueno.com/a"], "y no aporta"
    assert (c.filas, c.casadas, c.spam, c.spam_casados) == (3, 2, 2, 1)
    assert c.aportacion_total == pytest.approx(10.0)
    assert (c.no_rastreadas[0]["spam"], c.no_rastreadas[0]["aportacion"]) == (1, 0)


def test_sin_columna_de_spam_no_se_afirma_nada():
    assert all(f["spam"] is None for f in B.leer_csv(AHREFS.encode("utf-16")).filas)
    assert B.leer_csv(SEMRUSH.encode()).spam == 0
    # Las filas de cuatro campos (un cruce de antes) siguen valiendo.
    assert B.cruzar([("https://x.com/", "https://a.com/", "a.com", 2.0)], [(1, "https://x.com/")]).spam == 0


@pytest.mark.parametrize("texto,esperado", [
    ("1.234", 1234), ("1,234", 1234), ("12,5", 12.5), ("0.125", 0.125), ("1,234.5", 1234.5),
    ("1.234,5", 1234.5), ("", None), ("n/a", None)])
def test_numeros_con_separadores(texto, esperado):
    assert B._numero(texto) == (pytest.approx(esperado) if esperado is not None else None)


def test_se_lee_en_streaming_desde_un_fichero():
    import io

    lec = B.leer_csv(io.BytesIO(AHREFS.encode("utf-16")))
    assert len(lec.filas) == 2


def test_un_csv_sin_las_columnas_se_rechaza():
    with pytest.raises(B.CsvNoValido):
        B.leer_csv(b"url,clics\nhttps://x.com/,3\n")
    with pytest.raises(B.CsvNoValido):
        B.leer_csv(b"")
    with pytest.raises(B.CsvNoValido):
        B.leer_csv(b"\xff\xfeR\x00e\x00f")   # UTF-16 con un byte suelto: 422, no 500


def test_la_clave_no_pasa_la_ruta_a_minusculas():
    assert B.clave_backlink("https://www.X.com/Producto/") == "x.com/Producto"
    assert B.clave_backlink("http://x.com/Producto#arriba") == "x.com/Producto"
    assert B.clave_backlink("https://x.com/a%C3%B1o/") == B.clave_backlink("https://x.com/año")
    assert B.clave_backlink("https://x.com/producto") != B.clave_backlink("https://x.com/Producto")
    assert B.clave_backlink("https://x.com/") == "x.com/"


def test_con_dos_urls_de_la_misma_clave_gana_la_buena_y_siempre_la_misma():
    """WordPress: `/a` es un 404 (un enlace interno sin la barra) y `/a/` el 200."""
    urls = [(1, "https://x.com/a", 3), (2, "https://x.com/a/", 0)]
    c = B.cruzar([("https://www.x.com/a", "https://o.com/", "o.com", 1.0)], urls)
    assert set(c.por_url) == {2}, "ni la exacta en otra variante ni el 404"
    c = B.cruzar([("https://x.com/a", "https://o.com/", "o.com", 1.0)], urls)
    assert set(c.por_url) == {1}, "la exacta manda: el backlink apunta al 404 de verdad"
    c = B.cruzar([("http://x.com/a", "https://o.com/", "o.com", 1.0)], list(reversed(urls)))
    assert set(c.por_url) == {2}, "sin depender del orden"


def test_el_cruce_prueba_sin_la_query_y_guarda_lo_que_no_casa():
    urls = [(1, "https://x.com/"), (2, "https://x.com/roto"), (3, "https://x.com/b?pagina=2")]
    filas = [("https://www.x.com/", "https://a.com/", "a.com", 2.0),
             ("http://x.com/roto?utm_source=foro", "https://f.com/", "f.com", 1.0),
             ("https://x.com/b", "https://b.com/", "b.com", 1.0),        # la del censo lleva query: no casa
             ("https://x.com/antigua", "https://c.com/", "c.com", 5.0),
             ("https://x.com/antigua", "https://d.com/", "d.com", 1.0)]
    c = B.cruzar(filas, urls)
    assert set(c.por_url) == {1, 2}
    assert c.por_url[1] == {"backlinks": 1, "spam": 0, "aportacion": 2.0, "dominios": 1,
                            "origenes": ["https://a.com/"]}
    assert (c.filas, c.casadas, c.parte_casada) == (5, 2, 0.4)
    assert c.no_rastreadas[0] == {"url": "https://x.com/antigua", "backlinks": 2, "spam": 0, "aportacion": 6.0,
                                  "dominios": 2}


# ---------------------------------------------------------------------------
# PageRank personalizado
# ---------------------------------------------------------------------------
def _grafo():
    # 0 home -> 1, 2; 1 -> 0; 2 -> 0; 3 es una 301 a 1; 4 un 404
    src = np.array([0, 0, 1, 2, 3])
    dst = np.array([1, 2, 0, 0, 1])
    w = np.ones(5)
    indexables = np.array([True, True, True, False, False])
    return src, dst, w, indexables


def test_con_beta_1_es_exactamente_el_interno():
    src, dst, w, idx = _grafo()
    interno = prk.pagerank(5, src, dst, w, teletransporte=idx)
    externo = np.array([0, 0, 0, 5.0, 3.0])
    v = prk.teletransporte_externo(idx, externo, 1.0)
    assert np.allclose(prk.pagerank(5, src, dst, w, teletransporte=v, colgante=idx), interno)
    # Sin nada de fuera, igual
    v = prk.teletransporte_externo(idx, np.zeros(5), 0.3)
    assert np.allclose(prk.pagerank(5, src, dst, w, teletransporte=v, colgante=idx), interno)


def test_lo_que_llega_a_una_301_pasa_a_su_destino_y_lo_que_llega_a_un_404_se_pierde():
    src, dst, w, idx = _grafo()
    interno = prk.pagerank(5, src, dst, w, teletransporte=idx)
    a_301 = prk.pagerank(5, src, dst, w, teletransporte=prk.teletransporte_externo(
        idx, np.array([0, 0, 0, 1.0, 0]), 0.5), colgante=idx)
    assert a_301[1] > interno[1], "la 301 lleva su autoridad al destino"
    a_404 = prk.pagerank(5, src, dst, w, teletransporte=prk.teletransporte_externo(
        idx, np.array([0, 0, 0, 0, 1.0]), 0.5), colgante=idx)
    cats = [prk.INDEXABLE] * 3 + [prk.REDIRECCION, prk.ERROR]
    assert prk.desperdiciado(prk.reparto(a_404, cats)) > prk.desperdiciado(prk.reparto(interno, cats))
    assert a_404.sum() == pytest.approx(1.0)


def test_la_masa_colgante_no_vuelve_al_404():
    """Si fuera al salto, un 404 con backlinks recibiria otra vez su propia
    masa en cada vuelta y lo perdido saldria inflado."""
    src, dst, w, idx = _grafo()
    v = prk.teletransporte_externo(idx, np.array([0, 0, 0, 0, 1.0]), 0.5)
    bien = prk.pagerank(5, src, dst, w, teletransporte=v, colgante=idx)
    mal = prk.pagerank(5, src, dst, w, teletransporte=v)
    assert bien[4] < mal[4]
