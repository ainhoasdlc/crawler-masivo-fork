"""Search Console por cliente (decision 141), con un Google de mentira: ningun
test llama a la red. La llave en fichero, la sincronizacion por dias, el
tope de filas, los errores traducidos y cuando toca."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from shared import gsc as G
from shared import secretos

LLAVE = {"type": "service_account", "project_id": "lin3s-seo", "client_email": "crawler@lin3s-seo.iam.gserviceaccount.com",
         "private_key": "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n",
         "token_uri": "https://oauth2.googleapis.com/token"}
OAUTH = {"type": "authorized_user", "client_id": "123.apps.googleusercontent.com", "client_secret": "SECRETO",
         "refresh_token": "1//SECRETO", "account": "seo@agencia.com"}


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(tipo, compilador, **kw):
    return "INTEGER"


@pytest.fixture(autouse=True)
def _secretos(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRETOS_DIR", str(tmp_path / "secretos"))
    monkeypatch.delenv("GSC_LIN3S", raising=False)


# -- La llave -------------------------------------------------------------------

@pytest.mark.parametrize("texto, trozo", [
    ("no es json", "No es un JSON"),
    (json.dumps({"type": "external_account"}), "cuenta de servicio"),
    (json.dumps({"type": "authorized_user"}), "OAuth de usuario"),
    (json.dumps({**OAUTH, "refresh_token": ""}), "refresh_token"),
    (json.dumps({**LLAVE, "private_key": ""}), "private_key"),
    (json.dumps({**LLAVE, "private_key": "abc"}), "formato"),
])
def test_una_llave_que_no_vale_dice_por_que(texto, trozo):
    with pytest.raises(G.LlaveNoValida, match=trozo):
        G.leer_llave(texto)


def test_de_la_llave_solo_se_ensena_lo_publico():
    assert G.publico(G.leer_llave(json.dumps(LLAVE))) == {
        "client_email": LLAVE["client_email"], "project_id": "lin3s-seo"}


def test_un_oauth_de_usuario_vale_y_solo_ensena_la_cuenta():
    assert G.leer_llave(json.dumps(OAUTH)) == OAUTH
    assert G.publico(OAUTH) == {"client_email": "seo@agencia.com", "project_id": None}
    assert G.publico({**OAUTH, "account": ""})["client_email"] == "OAuth de usuario"


def test_el_oauth_de_usuario_se_renueva_con_su_refresh_token():
    from google.oauth2.credentials import Credentials

    creds = G.Consultor(OAUTH)._s.credentials
    assert isinstance(creds, Credentials)
    assert creds.refresh_token == OAUTH["refresh_token"] and creds.client_id == OAUTH["client_id"]


def test_la_llave_subida_se_lee_como_credencial_y_el_entorno_manda(monkeypatch, tmp_path):
    from shared.credenciales import credencial, esta_configurada

    integ = {"tipo": "gsc", "credencial_env": "GSC_LIN3S"}
    assert not esta_configurada(integ)
    secretos.guardar("GSC_LIN3S", json.dumps(LLAVE))
    ruta = tmp_path / "secretos" / "GSC_LIN3S.json"
    assert ruta.stat().st_mode & 0o777 == 0o600
    assert esta_configurada(integ) and json.loads(credencial(integ))["project_id"] == "lin3s-seo"
    monkeypatch.setenv("GSC_LIN3S", json.dumps({**LLAVE, "project_id": "del-entorno"}))
    assert json.loads(credencial(integ))["project_id"] == "del-entorno"
    assert secretos.listar("GSC_") == ["GSC_LIN3S"]


@pytest.mark.parametrize("nombre", ["../etc/passwd", "gsc_x", "GSC.X", ""])
def test_un_nombre_raro_no_sale_del_directorio(nombre):
    with pytest.raises(ValueError):
        secretos.guardar(nombre, "{}")
    assert secretos.leer(nombre) is None


# -- La sincronizacion ------------------------------------------------------------

@pytest.fixture
def s():
    from shared.models import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.fixture
def cliente(s):
    from shared.models import Client

    secretos.guardar("GSC_LIN3S", json.dumps(LLAVE))
    c = Client(id=uuid.uuid4(), nombre="Acme", slug="acme", dominios=[], config_defecto={},
               integraciones=[{"tipo": "gsc", "credencial_env": "GSC_LIN3S", "activa": True,
                               "parametros": {"propiedad": "sc-domain:acme.com"}}])
    s.add(c)
    s.commit()
    return c


class GoogleFalso:
    def __init__(self, filas_por_dia=None, error=None):
        self.pedidas: list[tuple[str, int]] = []
        self.filas_por_dia = filas_por_dia or (lambda d: [
            {"keys": [f"https://acme.com/p{i}"], "clicks": i, "impressions": 10 * i, "position": 3.0}
            for i in range(1, 4)])
        self.error = error

    def __call__(self, info):
        assert info["client_email"] == LLAVE["client_email"]
        return self

    def consultar(self, propiedad, cuerpo):
        if self.error:
            raise self.error
        self.pedidas.append((cuerpo["startDate"], cuerpo["startRow"]))
        filas = self.filas_por_dia(cuerpo["startDate"])
        return {"rows": filas[cuerpo["startRow"]: cuerpo["startRow"] + cuerpo["rowLimit"]]}


def _integ(c):
    return c.integraciones[0]


def test_la_primera_vez_baja_los_dias_iniciales_y_despues_solo_lo_nuevo(s, cliente, monkeypatch):
    from shared.models import GscPagina

    monkeypatch.setenv("SEARCH_CONSOLE_DIAS_INICIALES", "5")
    g = GoogleFalso()
    hoy = date(2026, 10, 19)
    e = G.sincronizar(s, cliente, _integ(cliente), hoy=hoy, consultor=g)
    assert (e.estado, e.primer_dia, e.ultimo_dia, e.filas) == ("ok", date(2026, 10, 13), date(2026, 10, 17), 15)
    assert e.cuenta == LLAVE["client_email"] and e.motivo is None
    assert len(g.pedidas) == 5
    # Al dia siguiente: tres de solape (los datos cambian hasta ser finales) y uno nuevo
    g2 = GoogleFalso()
    e = G.sincronizar(s, cliente, _integ(cliente), hoy=hoy + timedelta(days=1), consultor=g2)
    assert [d for d, _ in g2.pedidas] == ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18"]
    assert e.filas == 18                       # reescritos, no duplicados
    p = s.query(GscPagina).filter(GscPagina.fecha == date(2026, 10, 18), GscPagina.url == "https://acme.com/p2").one()
    assert (p.clics, p.impresiones, p.posicion) == (2, 20, 3.0)


def test_el_tope_de_filas_marca_el_dia(s, cliente, monkeypatch):
    monkeypatch.setenv("SEARCH_CONSOLE_DIAS_INICIALES", "1")
    monkeypatch.setattr(G, "FILAS_POR_PAGINA", 2)
    monkeypatch.setattr(G, "TOPE_FILAS_DIA", 4)
    muchas = lambda d: [{"keys": [f"https://acme.com/x{i}"], "clicks": 1, "impressions": 1, "position": 1}
                        for i in range(10)]
    e = G.sincronizar(s, cliente, _integ(cliente), hoy=date(2026, 10, 19), consultor=GoogleFalso(muchas))
    assert e.dias_truncados == ["2026-10-17"] and e.filas == 4


def test_dos_urls_que_son_la_misma_se_suman(s, cliente, monkeypatch):
    from shared.models import GscPagina

    monkeypatch.setenv("SEARCH_CONSOLE_DIAS_INICIALES", "1")
    filas = lambda d: [{"keys": ["https://acme.com/a?x=1&y=2"], "clicks": 1, "impressions": 10, "position": 2},
                       {"keys": ["https://acme.com/a?y=2&x=1"], "clicks": 3, "impressions": 30, "position": 6}]
    G.sincronizar(s, cliente, _integ(cliente), hoy=date(2026, 10, 19), consultor=GoogleFalso(filas))
    (p,) = s.query(GscPagina).all()
    assert (p.clics, p.impresiones, p.posicion) == (4, 40, 5.0)


@pytest.mark.parametrize("status, trozo", [
    (403, "no tiene acceso a la propiedad sc-domain:acme.com"),
    (404, "no reconoce la propiedad"),
    (401, "rechaza la llave"),
])
def test_un_error_de_google_dice_que_hacer(s, cliente, status, trozo):
    e = G.sincronizar(s, cliente, _integ(cliente), hoy=date(2026, 10, 19),
                      consultor=GoogleFalso(error=G.GscError(status, "x")))
    assert e.estado == "error" and trozo in e.motivo
    if status == 403:
        assert LLAVE["client_email"] in e.motivo


def test_sin_llave_o_con_una_mala(s, cliente):
    secretos.borrar("GSC_LIN3S")
    e = G.sincronizar(s, cliente, _integ(cliente), hoy=date(2026, 10, 19), consultor=GoogleFalso())
    assert e.estado == "error" and "Falta la llave" in e.motivo


def test_cuando_toca():
    from shared.models import GscEstado

    ahora = datetime(2026, 10, 19, 5, tzinfo=timezone.utc)
    assert G.toca(None, ahora)
    ok_ayer = GscEstado(estado="ok", ultimo_ok=ahora - timedelta(days=1), ultimo_intento=ahora - timedelta(days=1))
    assert G.toca(ok_ayer, ahora)
    assert not G.toca(ok_ayer, ahora.replace(hour=2))           # antes de las 4 UTC
    ok_hoy = GscEstado(estado="ok", ultimo_ok=ahora, ultimo_intento=ahora)
    assert not G.toca(ok_hoy, ahora + timedelta(hours=1))
    ok_hoy.pedida_en = ahora + timedelta(minutes=30)              # «Sincronizar ahora»
    assert G.toca(ok_hoy, ahora + timedelta(hours=1))
    error = GscEstado(estado="error", ultimo_intento=ahora - timedelta(hours=2))
    assert not G.toca(error, ahora) and G.toca(error, ahora + timedelta(hours=5))
    corriendo = GscEstado(estado="en_curso", ultimo_intento=ahora - timedelta(minutes=10))
    assert not G.toca(corriendo, ahora)


def test_solo_toca_a_quien_tiene_propiedad_y_llave(s, cliente):
    from shared.models import Client

    s.add_all([
        Client(id=uuid.uuid4(), nombre="Sin llave", slug="sin-llave", dominios=[], config_defecto={},
               integraciones=[{"tipo": "gsc", "credencial_env": "GSC_OTRA", "parametros": {"propiedad": "sc-domain:x.com"}}]),
        Client(id=uuid.uuid4(), nombre="Sin propiedad", slug="sin-propiedad", dominios=[], config_defecto={},
               integraciones=[{"tipo": "gsc", "credencial_env": "GSC_LIN3S", "parametros": {}}]),
        Client(id=uuid.uuid4(), nombre="Apagada", slug="apagada", dominios=[], config_defecto={},
               integraciones=[{"tipo": "gsc", "credencial_env": "GSC_LIN3S", "activa": False,
                               "parametros": {"propiedad": "sc-domain:y.com"}}]),
    ])
    s.commit()
    assert [c.slug for c, _ in G.pendientes(s, datetime(2026, 10, 19, 5, tzinfo=timezone.utc))] == ["acme"]
