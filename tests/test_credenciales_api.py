"""Llaves y Search Console por la API (decision 141), EJECUTADOS con TestClient
y SQLite: la llave se sube y nunca vuelve, el nombre lleva su prefijo, no se
borra una que se usa, el estado del cliente y «Sincronizar ahora»."""

from __future__ import annotations

import json
import uuid

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import BigInteger, create_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from shared.database import get_session  # noqa: E402
from shared.models import Base, Client, GscEstado  # noqa: E402

LLAVE = {"type": "service_account", "project_id": "lin3s-seo",
         "client_email": "crawler@lin3s-seo.iam.gserviceaccount.com",
         "private_key": "-----BEGIN PRIVATE KEY-----\nSECRETO\n-----END PRIVATE KEY-----\n",
         "token_uri": "https://oauth2.googleapis.com/token"}


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(tipo, compilador, **kw):
    return "INTEGER"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    from api.routers import credenciales

    monkeypatch.setenv("SECRETOS_DIR", str(tmp_path / "secretos"))
    engine = create_engine(f"sqlite:///{tmp_path}/c.db")
    Base.metadata.create_all(engine)
    Sesion = sessionmaker(bind=engine, expire_on_commit=False)
    s = Sesion()
    acme = Client(nombre="Acme", slug="acme", dominios=["acme.com"], integraciones=[
        {"tipo": "gsc", "credencial_env": "GSC_LIN3S", "activa": True,
         "parametros": {"propiedad": "sc-domain:acme.com"}}])
    vacio = Client(nombre="Vacio", slug="vacio", dominios=[], integraciones=[])
    s.add_all([acme, vacio])
    s.commit()
    ids = {"acme": acme.id, "vacio": vacio.id}
    s.close()
    app = FastAPI()
    app.include_router(credenciales.router)

    def _sesion():
        ses = Sesion()
        try:
            yield ses
        finally:
            ses.close()

    app.dependency_overrides[get_session] = _sesion
    return TestClient(app), ids, Sesion, tmp_path


def _subir(api, nombre="GSC_LIN3S", contenido=None):
    return api.post("/api/credenciales", json={"tipo": "gsc", "nombre": nombre,
                                               "contenido": contenido or json.dumps(LLAVE)})


def test_la_llave_se_sube_y_nunca_vuelve(entorno):
    api, ids, _, tmp = entorno
    r = _subir(api)
    assert r.status_code == 201
    assert r.json()["client_email"] == LLAVE["client_email"] and r.json()["en_uso_por"] == ["acme"]
    assert "SECRETO" not in r.text
    lista = api.get("/api/credenciales")
    assert [x["nombre"] for x in lista.json()] == ["GSC_LIN3S"] and "SECRETO" not in lista.text
    assert (tmp / "secretos" / "GSC_LIN3S.json").exists()


@pytest.mark.parametrize("nombre, contenido, trozo", [
    ("DATAFORSEO_X", None, "GSC_"),
    ("GSC LIN3S", None, "Nombre no válido"),
    ("GSC_LIN3S", json.dumps({"type": "external_account"}), "cuenta de servicio"),
    ("GSC_LIN3S", json.dumps({"type": "authorized_user"}), "OAuth de usuario"),
])
def test_lo_que_no_vale_es_un_422_que_dice_por_que(entorno, nombre, contenido, trozo):
    api, *_ = entorno
    r = _subir(api, nombre, contenido)
    assert r.status_code == 422 and trozo in r.text


def test_no_se_borra_una_llave_en_uso(entorno):
    api, *_ = entorno
    _subir(api)
    r = api.delete("/api/credenciales/GSC_LIN3S")
    assert r.status_code == 409 and "acme" in r.text
    assert api.delete("/api/credenciales/GSC_LIN3S?forzar=true").status_code == 204
    assert api.delete("/api/credenciales/GSC_LIN3S?forzar=true").status_code == 404


def test_el_estado_del_cliente_y_sincronizar_ahora(entorno):
    api, ids, Sesion, _ = entorno
    (fila,) = api.get(f"/api/clients/{ids['acme']}/gsc").json()
    assert (fila["estado"], fila["configurada"]) == ("sin_configurar", False)
    assert "Falta la llave" in fila["motivo"]
    _subir(api)
    (fila,) = api.get(f"/api/clients/{ids['acme']}/gsc").json()
    assert (fila["estado"], fila["cuenta"]) == ("pendiente", LLAVE["client_email"])
    assert api.post(f"/api/clients/{ids['acme']}/gsc/sincronizar").status_code == 202
    with Sesion() as s:
        assert s.query(GscEstado).one().pedida_en is not None
    assert api.post(f"/api/clients/{ids['vacio']}/gsc/sincronizar").status_code == 409
    assert api.get(f"/api/clients/{uuid.uuid4()}/gsc").status_code == 404


def test_la_serie_diaria_y_lo_que_mas_trae(entorno):
    """GET /gsc/serie: un dia por fila con la suma por pagina, el truncado
    marcado, la posicion ponderada por impresiones y los tops de 28 dias
    frente a los 28 anteriores; la misma URL con otra `url_clave` no se junta."""
    from datetime import date, timedelta

    from shared.models import GscConsulta, GscPagina

    api, ids, Sesion, _ = entorno
    prop = "sc-domain:acme.com"
    hasta = date(2026, 10, 23)
    with Sesion() as s:
        s.add(GscEstado(cliente_id=ids["acme"], propiedad=prop, estado="ok", primer_dia=hasta - timedelta(days=59),
                        ultimo_dia=hasta, dias_truncados=[(hasta - timedelta(days=1)).isoformat()]))
        for d in range(60):
            dia = hasta - timedelta(days=d)
            s.add_all([
                GscPagina(cliente_id=ids["acme"], propiedad=prop, fecha=dia, url="https://acme.com/a",
                          url_clave="a", clics=10 if d < 28 else 2, impresiones=100, posicion=2.0),
                GscPagina(cliente_id=ids["acme"], propiedad=prop, fecha=dia, url="https://acme.com/b",
                          url_clave="b", clics=1, impresiones=300, posicion=10.0),
                GscConsulta(cliente_id=ids["acme"], propiedad=prop, fecha=dia, url_clave="a",
                            consulta="acme calderas", clics=7, impresiones=50, posicion=1.5),
            ])
        s.commit()

    (fila,) = api.get(f"/api/clients/{ids['acme']}/gsc/serie?dias=30").json()
    assert fila["propiedad"] == prop and len(fila["serie"]) == 30
    ultimo = fila["serie"][-1]
    assert ultimo == {"fecha": "2026-10-23", "clics": 11, "impresiones": 400, "ctr": 0.0275,
                      "posicion": 8.0, "truncado": False}
    assert fila["serie"][-2]["truncado"] is True
    assert fila["periodo"] == {"desde": "2026-09-26", "hasta": "2026-10-23",
                               "previo_desde": "2026-08-29", "previo_hasta": "2026-09-25"}
    assert fila["paginas"][0] == {"url": "https://acme.com/a", "clics": 280, "impresiones": 2800,
                                  "clics_previos": 56}
    assert [p["url"] for p in fila["paginas"]] == ["https://acme.com/a", "https://acme.com/b"]
    assert fila["consultas"] == [{"consulta": "acme calderas", "clics": 196, "impresiones": 1400,
                                  "clics_previos": 196}]

    (sin_top,) = api.get(f"/api/clients/{ids['acme']}/gsc/serie?top=0").json()
    assert "paginas" not in sin_top and len(sin_top["serie"]) == 60
    assert api.get(f"/api/clients/{ids['vacio']}/gsc/serie").json() == []
    assert api.get(f"/api/clients/{ids['acme']}/gsc/serie?dias=1").status_code == 422
    assert api.get(f"/api/clients/{uuid.uuid4()}/gsc/serie").status_code == 404
