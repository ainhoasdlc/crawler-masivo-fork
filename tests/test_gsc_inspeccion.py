"""Inspeccion de URLs de Search Console (decision 144), con un Google de
mentira y SQLite: que muestra se pide y en que orden, que no se repite lo
reciente, que hace un error, y los dos avisos del analisis."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from shared import gsc_inspeccion as GI
from shared.gsc import GscError, clave_de_url
from shared.models import Base, Client, GscEstado, GscInspeccion, GscPagina, Issue, Job, Url

AHORA = datetime(2026, 10, 19, 6, tzinfo=timezone.utc)


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(tipo, compilador, **kw):
    return "INTEGER"


@pytest.fixture
def s(tmp_path, monkeypatch):
    import json

    from shared import secretos

    monkeypatch.setenv("SECRETOS_DIR", str(tmp_path / "secretos"))
    secretos.guardar("GSC_ACME", json.dumps({
        "type": "service_account", "client_email": "x@y.iam.gserviceaccount.com", "token_uri": "t",
        "private_key": "-----BEGIN PRIVATE KEY-----\nA\n-----END PRIVATE KEY-----\n"}))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


INTEG = {"tipo": "gsc", "credencial_env": "GSC_ACME", "parametros": {"propiedad": "sc-domain:x.com"}}


def _montar(s):
    c = Client(id=uuid.uuid4(), nombre="Acme", slug="acme", dominios=[], config_defecto={}, integraciones=[INTEG])
    s.add(c)
    s.flush()
    j = Job(id=uuid.uuid4(), name="acme semanal", status="completed", seeds=["https://x.com/"], config={},
            cliente_id=c.id, created_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
            started_at=datetime(2026, 10, 14, 3, tzinfo=timezone.utc))
    s.add(j)
    s.add(GscEstado(cliente_id=c.id, propiedad="sc-domain:x.com", estado="ok"))
    s.flush()
    return c, j


def _url(s, j, ruta, *, indexable=True, status=200, clics=None, imp=None, estado="Indexable"):
    u = Url(job_id=j.id, url=f"https://x.com{ruta}", url_hash=ruta, is_internal=True, is_html=True,
            status_code=status, indexable=indexable, indexability_status=estado, gsc_clics=clics, gsc_impresiones=imp)
    s.add(u)
    s.flush()
    return u


def test_el_orden_de_la_muestra_y_lo_reciente_no_se_repite(s, monkeypatch):
    c, j = _montar(s)
    _url(s, j, "/top", imp=900, clics=50)
    _url(s, j, "/media", imp=100, clics=2)
    _url(s, j, "/riesgo", indexable=False, estado="Canonicalised", clics=30, imp=300)
    _url(s, j, "/muda", imp=0, clics=0)
    _url(s, j, "/rota", status=404, indexable=False, clics=0)
    _url(s, j, "/vista", imp=5000, clics=900)
    s.add(GscInspeccion(cliente_id=c.id, propiedad="sc-domain:x.com", url="https://x.com/vista",
                        url_clave=clave_de_url("https://x.com/vista"), fecha=AHORA - timedelta(days=2)))
    s.commit()
    urls = GI.candidatas(s, c.id, "sc-domain:x.com", 10, AHORA)
    assert [u.rsplit("/", 1)[1] for u in urls] == ["riesgo", "top", "media", "muda"]
    assert GI.candidatas(s, c.id, "sc-domain:x.com", 2, AHORA) == urls[:2]


class Falso:
    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.pedidas = []

    def __call__(self, info):
        return self

    def _peticion(self, metodo, url, json=None):
        self.pedidas.append(json["inspectionUrl"])
        r = self.respuestas.get(json["inspectionUrl"].rsplit("/", 1)[1])
        if isinstance(r, Exception):
            raise r
        return {"inspectionResult": {"indexStatusResult": r}}


def test_inspeccionar_guarda_la_ultima_y_un_error_por_url(s, monkeypatch):
    c, j = _montar(s)
    for r in ("a", "b", "c"):
        _url(s, j, f"/{r}", imp=10)
    s.commit()
    falso = Falso({"a": {"verdict": "PASS", "coverageState": "Enviada e indexada",
                         "googleCanonical": "https://x.com/a", "userCanonical": "https://x.com/a",
                         "lastCrawlTime": "2026-10-17T15:20:44Z", "crawledAs": "MOBILE"},
                   "b": GscError(500, "x"),
                   "c": {"verdict": "NEUTRAL", "coverageState": "Rastreada: actualmente sin indexar"}})
    assert GI.inspeccionar(s, c, INTEG, ahora=AHORA, consultor=falso) == 3
    filas = {f.url.rsplit("/", 1)[1]: f for f in s.query(GscInspeccion).all()}
    assert filas["a"].verdict == "PASS" and filas["a"].ultimo_rastreo.year == 2026
    assert filas["b"].error and filas["c"].cobertura.startswith("Rastreada")
    e = s.query(GscEstado).one()
    assert (e.inspeccion_hechas, e.inspeccion_motivo) == (3, None)
    assert not GI.toca(e, AHORA + timedelta(hours=2)) and GI.toca(e, AHORA + timedelta(days=1))


def test_lo_que_google_no_sabe_se_guarda_vacio(s):
    # crawledAs de una URL sin rastrear: 31 caracteres que no caben en la
    # columna de 16 (Postgres tiraba la tanda; SQLite no mide, por eso se
    # mira el valor y no el error).
    c, j = _montar(s)
    _url(s, j, "/nueva", imp=0)
    s.commit()
    falso = Falso({"nueva": {"verdict": "VERDICT_UNSPECIFIED", "coverageState": "URL desconocida para Google",
                             "crawledAs": "CRAWLING_USER_AGENT_UNSPECIFIED",
                             "indexingState": "INDEXING_STATE_UNSPECIFIED",
                             "robotsTxtState": "ROBOTS_TXT_STATE_UNSPECIFIED",
                             "pageFetchState": "PAGE_FETCH_STATE_UNSPECIFIED"}})
    assert GI.inspeccionar(s, c, INTEG, ahora=AHORA, consultor=falso) == 1
    f = s.query(GscInspeccion).one()
    assert (f.verdict, f.indexacion, f.robots, f.descarga, f.rastreada_como) == (None,) * 5
    assert f.cobertura == "URL desconocida para Google"


def test_sin_permiso_lo_dice_y_no_guarda_basura(s):
    c, j = _montar(s)
    _url(s, j, "/a", imp=10)
    s.commit()
    GI.inspeccionar(s, c, INTEG, ahora=AHORA, consultor=Falso({"a": GscError(403, "no")}))
    assert s.query(GscInspeccion).count() == 0
    assert "no tiene acceso" in s.query(GscEstado).one().inspeccion_motivo


def test_apagada_o_sin_descarga_no_toca(monkeypatch):
    e = GscEstado(estado="ok")
    assert GI.toca(e, AHORA)
    assert not GI.toca(GscEstado(estado="error"), AHORA)
    monkeypatch.setenv("SEARCH_CONSOLE_INSPECCIONES_DIA", "0")
    assert not GI.toca(e, AHORA)


def test_los_avisos_del_analisis(s):
    from analysis import avisos_de_gsc
    from analysis.analyzer import SEOAnalyzer

    c, j = _montar(s)
    ok = _url(s, j, "/ok", imp=10)
    sin = _url(s, j, "/sin", imp=10)
    otro = _url(s, j, "/oferta", imp=10)
    vieja = _url(s, j, "/vieja", imp=10)
    for u in (ok, sin, otro, vieja):
        s.add(GscPagina(cliente_id=c.id, propiedad="sc-domain:x.com", fecha=date(2026, 10, 10), url=u.url,
                        url_clave=clave_de_url(u.url), clics=1, impresiones=10))

    def insp(u, verdict, cobertura, user=None, google=None, cuando=AHORA):
        s.add(GscInspeccion(cliente_id=c.id, propiedad="sc-domain:x.com", url=u.url, url_clave=clave_de_url(u.url),
                            fecha=cuando, verdict=verdict, cobertura=cobertura,
                            canonical_usuario=user, canonical_google=google))
    insp(ok, "PASS", "Enviada e indexada", ok.url, ok.url)
    insp(sin, "NEUTRAL", "Rastreada: actualmente sin indexar")
    insp(otro, "PASS", "Enviada e indexada", "https://pruebas.lfr.cloud/oferta", "https://x.com/otra")
    from shared.models import HtmlMeta
    s.add(HtmlMeta(url_id=otro.id, canonical_href="https://pruebas.lfr.cloud/oferta"))   # hoy declara lo mismo
    antigua = _url(s, j, "/antigua", imp=10)
    s.add(HtmlMeta(url_id=antigua.id, canonical_href=antigua.url))                       # hoy autocanonica
    s.add(GscPagina(cliente_id=c.id, propiedad="sc-domain:x.com", fecha=date(2026, 10, 10), url=antigua.url,
                    url_clave=clave_de_url(antigua.url), clics=1, impresiones=10))
    insp(antigua, "PASS", "Enviada e indexada", "https://x.com/es/antigua", antigua.url)
    insp(vieja, "NEUTRAL", "x", cuando=AHORA - timedelta(days=90))      # fuera de la ventana
    s.commit()
    avisos_de_gsc.avisar(SEOAnalyzer(s, j.id))
    s.commit()
    vistos = {(u, t): d for u, t, d in s.execute(select(Issue.url_id, Issue.issue_type, Issue.details))}
    assert vistos[(sin.id, "indexable_no_indexada_por_google")]["cobertura"].startswith("Rastreada")
    d = vistos[(otro.id, "google_elige_otro_canonical")]
    assert (d["canonical_declarado"], d["canonical_de_google"]) == ("https://pruebas.lfr.cloud/oferta", "https://x.com/otra")
    d = vistos[(antigua.id, "google_tiene_canonical_antiguo")]
    assert (d["canonical_hoy"], d["canonical_visto_por_google"]) == (antigua.url, "https://x.com/es/antigua")
    assert (antigua.id, "google_elige_otro_canonical") not in vistos
    assert not any(u in (ok.id, vieja.id) for u, _ in vistos)
    assert s.get(Job, j.id).gsc_resumen["inspeccion"] == {
        "inspeccionadas": 4, "indexadas": 3, "no_indexadas": 1, "canonical_distinto": 1, "canonical_antiguo": 1}



def test_una_tanda_fallida_se_reintenta_a_la_hora():
    e = GscEstado(estado="ok", inspeccion_ultima=AHORA, inspeccion_hechas=None, inspeccion_motivo="sin tabla")
    assert not GI.toca(e, AHORA + timedelta(minutes=30))
    assert GI.toca(e, AHORA + timedelta(hours=1))
    e.inspeccion_hechas = 0      # termino, aunque sin nada que inspeccionar
    assert not GI.toca(e, AHORA + timedelta(hours=2))
