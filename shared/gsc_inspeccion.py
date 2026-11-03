"""Inspeccion de URLs de Search Console por muestra diaria (decision 144, Ola
4.4 y combinaciones 12-14 de `docs/INVESTIGACION_SEARCH_CONSOLE.md`).

La API de inspeccion dice, de una URL concreta, lo que el rastreo no puede
saber: si Google la tiene indexada y por que no, y **que canonical ha elegido
Google** frente al que declara la pagina. Es la prueba de que Google ignora
una senal. Google da 2.000 inspecciones al dia por propiedad y cada una tarda
unos 7 s (medido con Lopesan), asi que es una muestra rotatoria, no un censo:

1. URLs del ultimo censo con clics que no son indexables (trafico en riesgo);
2. indexables por impresiones, de mas a menos (las que importan);
3. indexables sin impresiones (¿las tiene Google?);
4. el resto de HTML 200 del censo, por antiguedad de la ultima inspeccion.

No se repite una URL inspeccionada hace menos de `REPETIR_DIAS`. Se guarda la
ultima inspeccion por URL. `SEARCH_CONSOLE_INSPECCIONES_DIA` (500) acota el
gasto de cuota; 0 lo apaga.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

URL_API = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
REPETIR_DIAS = 7
REINTENTO_FALLIDA = timedelta(hours=1)
HILOS = 6


def por_dia() -> int:
    try:
        return max(0, min(2000, int(os.getenv("SEARCH_CONSOLE_INSPECCIONES_DIA", "500"))))
    except ValueError:
        return 500


def toca(estado, ahora: datetime) -> bool:
    if por_dia() <= 0 or estado is None or estado.estado != "ok":
        return False
    ult = estado.inspeccion_ultima
    if ult is None or ult.date() < ahora.date():
        return True
    # Una tanda que fallo antes de terminar (`inspeccion_hechas` None) se
    # reintenta a la hora, no al dia siguiente. Visto en produccion: la
    # primera corrio a los pocos segundos del despliegue, con el worker ya
    # nuevo y la tabla aun sin crear, y quedaba «hecha» hasta el dia despues.
    return estado.inspeccion_hechas is None and ahora - ult >= REINTENTO_FALLIDA


def _ultimo_censo(db, cliente_id):
    from shared.clientes import tipo_de_rastreo
    from shared.models import Job

    for j in (db.query(Job).filter(Job.cliente_id == cliente_id, Job.status == "completed")
              .order_by(Job.created_at.desc()).limit(30)):
        if tipo_de_rastreo(j.name, j.tipo) == "censo":
            return j
    return None


def candidatas(db, cliente_id, propiedad: str, limite: int, ahora: datetime) -> list[str]:
    """Las URLs a inspeccionar hoy, en orden de prioridad."""
    from shared.gsc import clave_de_url
    from shared.models import GscInspeccion, Url

    job = _ultimo_censo(db, cliente_id)
    if job is None or limite <= 0:
        return []
    recientes = {k: f for k, f in db.query(GscInspeccion.url_clave, GscInspeccion.fecha)
                 .filter(GscInspeccion.cliente_id == cliente_id, GscInspeccion.propiedad == propiedad)}
    corte = ahora - timedelta(days=REPETIR_DIAS)
    filas = db.query(Url.url, Url.status_code, Url.indexable, Url.gsc_clics, Url.gsc_impresiones).filter(
        Url.job_id == job.id, Url.is_internal.is_(True), Url.is_html.is_(True)).all()
    grupos: list[list[tuple]] = [[], [], [], []]
    for url, status, indexable, clics, imp in filas:
        k = clave_de_url(url)
        f = recientes.get(k)
        if f is not None:
            f = f if f.tzinfo else f.replace(tzinfo=timezone.utc)
            if f >= corte:
                continue
        antig = f.timestamp() if f is not None else 0.0
        if (clics or 0) > 0 and not indexable:
            grupos[0].append((-(clics or 0), url))
        elif indexable and status == 200 and (imp or 0) > 0:
            grupos[1].append((-(imp or 0), url))
        elif indexable and status == 200 and imp == 0:
            grupos[2].append((antig, url))
        elif status == 200:
            grupos[3].append((antig, url))
    salida: list[str] = []
    for g in grupos:
        for _, url in sorted(g):
            salida.append(url)
            if len(salida) >= limite:
                return salida
    return salida


def _enum(v: Any) -> Any:
    """Google rellena con `*_UNSPECIFIED` lo que no sabe: es «sin dato». Visto
    en produccion: `crawledAs` de una URL que Google aun no ha rastreado es
    `CRAWLING_USER_AGENT_UNSPECIFIED`, 31 caracteres en una columna de 16, y
    tiraba la tanda entera (mobilitycentro, 3-nov-2026)."""
    return None if isinstance(v, str) and v.endswith("_UNSPECIFIED") else v


def _a_fila(url: str, r: dict[str, Any]) -> dict[str, Any]:
    i = ((r or {}).get("inspectionResult") or {}).get("indexStatusResult") or {}
    ultimo = i.get("lastCrawlTime")
    try:
        ultimo = datetime.fromisoformat(ultimo.replace("Z", "+00:00")) if ultimo else None
    except ValueError:
        ultimo = None
    return {"verdict": _enum(i.get("verdict")), "cobertura": i.get("coverageState"),
            "indexacion": _enum(i.get("indexingState")), "robots": _enum(i.get("robotsTxtState")),
            "descarga": _enum(i.get("pageFetchState")), "canonical_google": i.get("googleCanonical"),
            "canonical_usuario": i.get("userCanonical"), "ultimo_rastreo": ultimo,
            "rastreada_como": _enum(i.get("crawledAs")), "error": None}


def inspeccionar(db, cliente, integracion: dict, *, ahora: datetime | None = None,
                 consultor=None) -> int:
    """La tanda de hoy. Devuelve cuantas se hicieron; nunca lanza."""
    from shared.credenciales import credencial
    from shared.gsc import Consultor, GscError, _estado, clave_de_url, leer_llave, traducir
    from shared.models import GscInspeccion

    ahora = ahora or datetime.now(timezone.utc)
    propiedad = str(((integracion or {}).get("parametros") or {}).get("propiedad") or "").strip()
    e = _estado(db, cliente.id, propiedad)
    try:
        info = leer_llave(credencial(integracion))
        c = consultor(info) if consultor else Consultor(info)
        urls = candidatas(db, cliente.id, propiedad, por_dia(), ahora)

        def una(url: str):
            try:
                return url, c._peticion("POST", URL_API, json={
                    "inspectionUrl": url, "siteUrl": propiedad, "languageCode": "es"}), None
            except GscError as exc:
                return url, None, exc

        hechas, motivo = 0, None
        with ThreadPoolExecutor(max_workers=HILOS) as pool:
            for url, r, err in pool.map(una, urls):
                if err is not None and err.status in (401, 403, 429):
                    # Sin permiso o sin cuota: lo que quede no va a ir mejor.
                    motivo = traducir(err.status, str(err), info.get("client_email"), propiedad)
                    continue
                datos = _a_fila(url, r) if err is None else {"error": str(err)[:300]}
                k = clave_de_url(url)
                fila = (db.query(GscInspeccion)
                        .filter(GscInspeccion.cliente_id == cliente.id, GscInspeccion.propiedad == propiedad,
                                GscInspeccion.url_clave == k).one_or_none())
                if fila is None:
                    fila = GscInspeccion(cliente_id=cliente.id, propiedad=propiedad, url=url, url_clave=k)
                    db.add(fila)
                fila.fecha = ahora
                for campo, valor in datos.items():
                    setattr(fila, campo, valor)
                hechas += 1
                if hechas % 50 == 0:
                    db.commit()
        e.inspeccion_ultima, e.inspeccion_hechas, e.inspeccion_motivo = ahora, hechas, motivo
        db.commit()
        return hechas
    except Exception as exc:  # noqa: BLE001 — la descarga diaria ya quedo hecha
        db.rollback()
        e.inspeccion_ultima, e.inspeccion_hechas = ahora, None
        e.inspeccion_motivo = f"{type(exc).__name__}: {exc}"[:500]
        db.commit()
        logger.warning("Inspeccion de %s (%s): %s", getattr(cliente, "slug", "?"), propiedad, exc)
        return 0
