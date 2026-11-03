"""Subir el CSV de backlinks de un cliente (#31, decision 212), EJECUTADO con
TestClient sobre SQLite: lectura, lo descartado, las tres que se guardan y el
borrado."""

from __future__ import annotations

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
from shared.models import BacklinkImport, Base, Client, ExternalLink  # noqa: E402
from test_backlinks import AHREFS, AHREFS_SPAM, SEMRUSH  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint(tipo, compilador, **kw):
    return "INTEGER"


@pytest.fixture()
def entorno(tmp_path):
    from api.routers import backlinks

    engine = create_engine(f"sqlite:///{tmp_path}/b.db")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(backlinks.router)

    def _sesion():
        s = S()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _sesion
    with S() as s:
        c = Client(id=uuid.uuid4(), nombre="X", slug="x", dominios=["x.com"], config_defecto={}, integraciones=[])
        s.add(c)
        s.commit()
        cid = c.id
    return TestClient(app), S, cid


def _subir(api, cid, contenido: bytes, nombre="export.csv", **form):
    return api.post(f"/api/clients/{cid}/backlinks", files={"fichero": (nombre, contenido, "text/csv")}, data=form)


def test_subir_un_export_de_ahrefs(entorno):
    api, S, cid = entorno
    r = _subir(api, cid, AHREFS.encode("utf-16"), fecha_dato="2026-10-20")
    assert r.status_code == 201, r.text
    j = r.json()
    assert (j["fuente"], j["filas"], j["leidas"], j["en_uso"]) == ("ahrefs", 2, 6, True)
    assert j["descartadas"] == {"nofollow": 3, "perdidas": 1, "sin_url": 0}
    assert j["fecha_dato"] == "2026-10-20" and j["dominios"] == 2
    with S() as s:
        assert s.query(ExternalLink).count() == 2


def test_el_spam_se_cuenta_en_la_importacion(entorno):
    api, S, cid = entorno
    j = _subir(api, cid, AHREFS_SPAM.encode("utf-16")).json()
    assert (j["filas"], j["spam"]) == (3, 2)
    with S() as s:
        assert sorted(x.spam for x in s.query(ExternalLink)) == [False, True, True]
    # Sin la columna, NULL: no se afirma que no haya spam.
    assert _subir(api, cid, AHREFS.encode("utf-16")).json()["spam"] is None
    assert [i["spam"] for i in api.get(f"/api/clients/{cid}/backlinks").json()] == [None, 2]


def test_se_guardan_las_tres_ultimas_y_la_primera_es_la_que_se_usa(entorno):
    api, S, cid = entorno
    ids = [_subir(api, cid, SEMRUSH.encode()).json()["id"] for _ in range(4)]
    lista = api.get(f"/api/clients/{cid}/backlinks").json()
    assert [i["id"] for i in lista] == ids[:0:-1] and [i["en_uso"] for i in lista] == [True, False, False]
    with S() as s:
        assert s.query(BacklinkImport).count() == 3
        assert s.query(ExternalLink).count() == 3, "las filas de la cuarta se fueron con ella"


def test_lo_que_no_se_puede_leer(entorno):
    api, _, cid = entorno
    assert _subir(api, cid, b"url,clics\nhttps://x.com/,1\n").status_code == 422
    solo_nofollow = SEMRUSH.split("\n")[0] + "\n" + SEMRUSH.split("\n")[2] + "\n"
    r = _subir(api, cid, solo_nofollow.encode())
    assert r.status_code == 422 and "dofollow" in r.json()["detail"]
    assert _subir(api, uuid.uuid4(), SEMRUSH.encode()).status_code == 404


def test_borrar_una_importacion(entorno):
    api, S, cid = entorno
    iid = _subir(api, cid, SEMRUSH.encode()).json()["id"]
    assert api.delete(f"/api/clients/{uuid.uuid4()}/backlinks/{iid}").status_code == 404
    assert api.delete(f"/api/clients/{cid}/backlinks/{iid}").status_code == 204
    with S() as s:
        assert s.query(ExternalLink).count() == 0 and s.query(BacklinkImport).count() == 0
