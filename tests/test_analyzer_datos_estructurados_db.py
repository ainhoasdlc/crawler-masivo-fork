"""Datos estructurados: un aviso por HALLAZGO, no por bloque.

Un bloque de plantilla —el `Organization` del pie, la miga de pan— es el mismo
en todo el sitio y se arregla una vez. Medido en tres censos reales:

| censo | filas de datos estructurados | hallazgos distintos |
|---|---|---|
| penguin (87.531 paginas) | **226.651** | **4** |
| Lopesan | 11.186 | 13 |
| Saunier Duval | 288 | 7 |

En penguin, 226.651 filas son el **39% de las incidencias del censo entero**
diciendo cuatro cosas. Es la misma cura que la decision 64b aplico a las
imagenes y la 53 a las cabeceras de seguridad.
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from analysis.analyzer import SEOAnalyzer
from shared.comparacion import _tipos_e_idiomas_de_censo
from shared.models import Base, Hreflang, Issue, Job, StructuredData, Url


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(tipo, compilador, **kw):
    return "INTEGER"


def _montar():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        Job.__table__, Url.__table__, StructuredData.__table__, Issue.__table__])
    s = sessionmaker(bind=engine)()
    j = Job(id=uuid.uuid4(), name="t", status="analyzing",
            seeds=["https://x.com/"], config={})
    s.add(j)
    s.flush()
    return s, j


def _pagina_con_bloque(s, j, n, raw):
    u = Url(job_id=j.id, url=f"https://x.com/p{n}", url_hash=f"p{n}",
            is_internal=True, is_html=True, status_code=200)
    s.add(u)
    s.flush()
    s.add(StructuredData(url_id=u.id, raw=raw, format="jsonld",
                         schema_type=raw.get("@type")))
    s.flush()
    return u


ORG_SIN_NADA = {"@type": "Organization", "name": "Tienda"}


def test_el_mismo_bloque_en_mil_paginas_es_un_aviso():
    s, j = _montar()
    for n in range(50):
        _pagina_con_bloque(s, j, n, dict(ORG_SIN_NADA))
    SEOAnalyzer(s, j.id).analyze_structured_data()
    s.flush()

    filas = s.query(Issue).filter(Issue.job_id == j.id).all()
    assert len(filas) == 1, "50 paginas con el MISMO bloque son un hallazgo"
    det = filas[0].details
    assert det["paginas_afectadas"] == 50
    assert det["schema_type"] == "Organization"
    assert len(det["paginas_ejemplo"]) == 5, "con ejemplos para ir a mirar"
    assert all(u.startswith("https://x.com/p") for u in det["paginas_ejemplo"])


def test_dos_problemas_distintos_siguen_siendo_dos_avisos():
    """Agrupar no puede tapar un hallazgo distinto."""
    s, j = _montar()
    for n in range(10):
        _pagina_con_bloque(s, j, n, dict(ORG_SIN_NADA))
    for n in range(10, 20):
        # Sin precio, resena ni valoracion: obligatorio, asi que es un error.
        _pagina_con_bloque(s, j, n, {"@type": "Product", "name": "Zapatilla"})
    SEOAnalyzer(s, j.id).analyze_structured_data()
    s.flush()

    tipos = sorted(i.issue_type for i in s.query(Issue).filter(Issue.job_id == j.id))
    assert tipos == ["structured_data_error", "structured_data_warning"]


def test_un_json_ld_con_coma_final_es_un_error_aunque_este_completo():
    """El extractor marca el bloque (`json_invalido`) y el analisis lo convierte
    en error: Google descarta el bloque entero, este como este de completo."""
    s, j = _montar()
    u = _pagina_con_bloque(s, j, 1, dict(ORG_SIN_NADA))
    s.query(StructuredData).filter(StructuredData.url_id == u.id).update(
        {"json_invalido": "coma final antes de '}' (linea 1, columna 40)"})
    SEOAnalyzer(s, j.id).analyze_structured_data()
    s.flush()

    bloque = s.query(StructuredData).filter(StructuredData.url_id == u.id).one()
    assert bloque.validation_status == "error"
    assert "coma final" in bloque.validation_issues[0]
    tipos = [i.issue_type for i in s.query(Issue).filter(Issue.job_id == j.id)]
    assert tipos == ["structured_data_error"]


def test_la_validacion_se_guarda_en_TODOS_los_bloques():
    """Agrupar los avisos no puede dejar sin validar los bloques.

    Los UPDATE van por lotes —en penguin eran 226.651 sentencias para escribir
    cuatro valores distintos— y es justo donde se pierde una fila sin que nada
    lo diga.
    """
    s, j = _montar()
    for n in range(30):
        _pagina_con_bloque(s, j, n, dict(ORG_SIN_NADA))
    SEOAnalyzer(s, j.id).analyze_structured_data()
    s.flush()

    bloques = s.query(StructuredData).all()
    assert len(bloques) == 30
    assert all(b.validation_status == "warning" for b in bloques)
    assert all(b.validation_issues for b in bloques)


def test_el_faq_de_plantilla_es_UN_aviso_informativo():
    """Un FAQ de plantilla en 30 paginas: una fila `info`, no 30 errores."""
    s, j = _montar()
    for n in range(30):
        _pagina_con_bloque(s, j, n, {"@type": "FAQPage", "mainEntity": []})
    SEOAnalyzer(s, j.id).analyze_structured_data()
    s.flush()

    filas = s.query(Issue).filter(Issue.job_id == j.id).all()
    assert [(f.issue_type, f.severity) for f in filas] == [
        ("structured_data_info", "info")]
    assert filas[0].details["paginas_afectadas"] == 30
    bloques = s.query(StructuredData).all()
    assert all(b.validation_status == "info" for b in bloques)


def test_un_faq_dentro_de_un_bloque_con_warning_sigue_dando_su_aviso_info():
    """El bloque se queda con el peor nivel; el aviso de retirado va aparte.

    Antes, un WebPage con una recomendada que falta y un FAQPage anidado daba
    UNA `structured_data_warning` con el aviso de «retirado» dentro, ninguna
    `structured_data_info`, y el warning del WebPage salia en un grupo distinto
    del de las paginas sin FAQ (decision 73).
    """
    s, j = _montar()
    org_sin_same_as = {"@type": "Organization", "name": "Tienda",
                       "logo": "https://x.com/l.png", "url": "https://x.com/"}
    for n in range(10):
        _pagina_con_bloque(s, j, n, {
            **org_sin_same_as,
            "subjectOf": {"@type": "FAQPage", "mainEntity": []},
        })
    for n in range(10, 20):
        _pagina_con_bloque(s, j, n, dict(org_sin_same_as))
    SEOAnalyzer(s, j.id).analyze_structured_data()
    s.flush()

    filas = s.query(Issue).filter(Issue.job_id == j.id).all()
    por_tipo = {f.issue_type: f for f in filas}
    assert sorted(por_tipo) == ["structured_data_info", "structured_data_warning"]
    assert len(filas) == 2, "el warning de Organization es UN grupo, lleve FAQ o no"
    assert por_tipo["structured_data_warning"].details["paginas_afectadas"] == 20
    assert por_tipo["structured_data_info"].details["paginas_afectadas"] == 10
    assert all("FAQPage" in m for m in
               por_tipo["structured_data_info"].details["validation_issues"])
    con_faq = s.query(StructuredData).join(Url).filter(Url.url == "https://x.com/p0").one()
    assert con_faq.validation_status == "warning", "el bloque guarda el peor nivel"


def _montar_con_hreflang():
    """Como `_montar`, pero con la tabla Hreflang: `_tipos_e_idiomas_de_censo`
    la consulta (el censo trae tipos e idiomas de una vez)."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        Job.__table__, Url.__table__, StructuredData.__table__,
        Hreflang.__table__])
    s = sessionmaker(bind=engine)()
    j = Job(id=uuid.uuid4(), name="t", status="completed",
            seeds=["https://x.com/"], config={})
    s.add(j)
    s.flush()
    return s, j


def test_un_type_doble_cuenta_como_dos_tipos_sueltos():
    """Un `@type` lista se guarda unido (`"Organization, LocalBusiness"`) pero
    el censo lo parte en tipos sueltos.

    Caso real de Workoholics: una pagina pasa de `Organization` sola a
    `["Organization", "LocalBusiness"]`. Comparado como atomo, la regla
    `pierden_datos_estructurados` avisaba de que pierde Organization y en la
    columna «ahora» lo enseñaba presente: un aviso que se contradice. Partido,
    `{Organization}` vs `{Organization, LocalBusiness}` no pierde nada.
    """
    s, j = _montar_con_hreflang()
    u = Url(job_id=j.id, url="https://x.com/", url_hash="h",
            is_internal=True, is_html=True, status_code=200)
    s.add(u)
    s.flush()
    # Lo que guarda extractors._tipo_normalizado para un @type lista.
    s.add(StructuredData(url_id=u.id, raw={}, format="jsonld",
                         schema_type="Organization, LocalBusiness"))
    s.add(StructuredData(url_id=u.id, raw={}, format="jsonld",
                         schema_type="BreadcrumbList"))
    s.flush()

    tipos, _ = _tipos_e_idiomas_de_censo(s, j.id)
    assert tipos[u.id] == ["BreadcrumbList", "LocalBusiness", "Organization"], \
        "el atomo unido se parte en tipos sueltos, comparables uno a uno"
