"""Search Console por cliente: llave, descarga diaria y estado (decision 141,
Ola 4.1).

Lo que hace sin que nadie lo pida, una vez que el cliente tiene una
integracion `gsc` activa con su propiedad y su llave:

- la primera vez descarga `SEARCH_CONSOLE_DIAS_INICIALES` (90) dias hacia atras;
- despues, una vez al dia, desde tres dias antes del ultimo guardado hasta
  hoy menos dos: Google da los datos con 2-3 dias de retraso y los de los
  ultimos dias cambian hasta que son definitivos (`dataState: final`);
- por dia y con `dimensions=page`, de 25.000 en 25.000 filas. Google corta en
  50.000 filas por dia y propiedad: si se llega, el dia queda marcado como
  truncado, porque ahi «esta URL no tuvo impresiones» no se puede afirmar
  (decision 67);
- un dia se reescribe entero (borrar y meter) en su propia transaccion: si la
  descarga se corta a medias, los dias anteriores quedan bien y el siguiente
  intento sigue.

La llamada a Google va por `Consultor`, que se puede sustituir en los tests:
ningun test llama a la red. Los errores de Google se traducen a lo que hay que
hacer («anade la cuenta X como usuario en la propiedad Y»), porque el que lo
lee es quien tiene que arreglarlo en la consola de Google.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

ALCANCE = "https://www.googleapis.com/auth/webmasters.readonly"
API = "https://searchconsole.googleapis.com/webmasters/v3"
RETRASO_DIAS = 2
SOLAPE_DIAS = 3
FILAS_POR_PAGINA = 25_000
TOPE_FILAS_DIA = 50_000
REINTENTAR_ERROR = timedelta(hours=6)
EN_CURSO_CADUCA = timedelta(hours=3)
HORA_UTC_DIARIA = 4


# Ventana de busquedas y paginas que se cruza con un censo: los 90 dias que
# acaban el dia en que empezo (decision 142). Aqui y no en `analysis/` para que
# el analizador y el enriquecido de la API (#169, decision 176), que no tiene
# `analysis/` en su imagen, lean la MISMA ventana.
VENTANA_DIAS = 90


def dia_del_censo(job) -> date:
    t = job.started_at or job.created_at or datetime.now(timezone.utc)
    return t.date()


# Inspecciones de URL que valen para un censo (decision 144): de 30 dias antes
# a 14 despues del dia del censo. Las lee el analisis (avisos de la
# inspeccion) y la ficha de URL de la API (decision 189): con dos copias, la
# tarjeta de la ficha y los avisos de la misma pagina acabarian discrepando.
INSPECCION_ANTES_DIAS = 30
INSPECCION_DESPUES_DIAS = 14


def ventana_de_inspeccion(job) -> tuple[datetime, datetime]:
    dia = dia_del_censo(job)
    return (datetime.combine(dia - timedelta(days=INSPECCION_ANTES_DIAS), datetime.min.time(), timezone.utc),
            datetime.combine(dia + timedelta(days=INSPECCION_DESPUES_DIAS), datetime.max.time(), timezone.utc))


def ventana_del_censo(job) -> tuple[date, date]:
    hasta = dia_del_censo(job)
    return hasta - timedelta(days=VENTANA_DIAS - 1), hasta


def propiedades_activas(session, cliente_id) -> list[str]:
    """Las propiedades de Search Console del cliente con datos (`gsc_estado`),
    solo las de sus integraciones `gsc` activas: si paso de una de prefijo a
    `sc-domain:`, la vieja sigue en la base y sus filas contarian dos veces.
    Sin integraciones declaradas, todas las que tienen estado (decision 157);
    con todas apagadas, ninguna."""
    from shared.models import Client, GscEstado

    if not cliente_id:
        return []
    cliente = session.get(Client, cliente_id)
    declaradas = [i for i in (getattr(cliente, "integraciones", None) or [])
                  if isinstance(i, dict) and i.get("tipo") == "gsc"]
    activas = {str((i.get("parametros") or {}).get("propiedad") or "").strip()
               for i in declaradas if i.get("activa", True)}
    # Con integraciones declaradas y todas apagadas, ninguna: apagar Search
    # Console es no querer sus datos.
    return sorted({e.propiedad for e in session.query(GscEstado).filter(GscEstado.cliente_id == cliente_id)
                   if not declaradas or e.propiedad in activas})


def dias_iniciales() -> int:
    try:
        return max(1, min(480, int(os.getenv("SEARCH_CONSOLE_DIAS_INICIALES", "90"))))
    except ValueError:
        return 90


class GscError(RuntimeError):
    def __init__(self, status: int | None, mensaje: str):
        super().__init__(mensaje)
        self.status = status


class LlaveNoValida(ValueError):
    """El JSON subido no es la llave de una cuenta de servicio ni un OAuth de usuario."""


def leer_llave(texto: str) -> dict[str, Any]:
    """Valida la llave y devuelve el JSON. Mensajes para quien la sube."""
    try:
        info = json.loads(texto)
    except (TypeError, ValueError):
        raise LlaveNoValida("No es un JSON. Descarga la llave de la cuenta de servicio en "
                            "Google Cloud → IAM → Cuentas de servicio → Claves → Añadir clave → JSON.")
    if isinstance(info, dict) and info.get("type") == "authorized_user":
        # El login de usuario con refresh token (el de `gcloud auth
        # application-default login` o el de los MCP de Search Console): ve las
        # propiedades a las que ya tiene acceso esa persona, sin dar de alta una
        # cuenta de servicio en cada una. No lleva clave privada.
        for campo in ("client_id", "client_secret", "refresh_token"):
            if not info.get(campo):
                raise LlaveNoValida(f"Al OAuth de usuario le falta «{campo}»: está incompleto.")
        return info
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise LlaveNoValida("Es un JSON, pero no la llave de una cuenta de servicio "
                            "(falta \"type\": \"service_account\") ni un OAuth de usuario "
                            "(\"type\": \"authorized_user\").")
    for campo in ("client_email", "private_key", "token_uri"):
        if not info.get(campo):
            raise LlaveNoValida(f"A la llave le falta «{campo}»: está incompleta.")
    if "PRIVATE KEY" not in str(info.get("private_key")):
        raise LlaveNoValida("La clave privada de la llave no tiene el formato esperado.")
    return info


def publico(info: dict[str, Any]) -> dict[str, Any]:
    """Lo unico que se ensena de una llave: lo que no es secreto."""
    if info.get("type") == "authorized_user":
        return {"client_email": info.get("account") or "OAuth de usuario",
                "project_id": info.get("quota_project_id")}
    return {"client_email": info.get("client_email"), "project_id": info.get("project_id")}


def clave_de_url(url: str) -> str:
    from shared.indexabilidad import clave_url

    return hashlib.sha256("|".join(clave_url(url)).encode("utf-8")).hexdigest()


def traducir(status: int | None, detalle: str, cuenta: str | None, propiedad: str) -> str:
    cuenta = cuenta or "la cuenta de servicio"
    if status == 403:
        return (f"La cuenta {cuenta} no tiene acceso a la propiedad {propiedad}. En Search Console → "
                "Configuración → Usuarios y permisos, añádela como usuario (con permiso restringido basta).")
    if status in (400, 404):
        return (f"Google no reconoce la propiedad «{propiedad}». Se escribe como en Search Console: "
                "sc-domain:dominio.com para una propiedad de dominio, o https://www.dominio.com/ "
                "(con la barra final) para una de prefijo de URL.")
    if status == 401:
        return ("Google rechaza la llave: puede estar revocada, la cuenta de servicio deshabilitada "
                "o el login de usuario caducado. Sube una nueva.")
    if status == 429:
        return "Google ha limitado las peticiones (cuota). Se reintentará más tarde."
    return f"Error de Search Console ({status or 'sin respuesta'}): {detalle[:300]}"


class Consultor:
    """La llamada real a Google, con la llave de la cuenta de servicio o el
    OAuth de usuario. Solo
    se construye en el worker (y en la API para listar propiedades)."""

    def __init__(self, info: dict[str, Any]):
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        if info.get("type") == "authorized_user":
            from google.oauth2.credentials import Credentials

            # Sin scopes: se renueva con los que se concedieron en el login.
            creds = Credentials.from_authorized_user_info(info)
        else:
            creds = service_account.Credentials.from_service_account_info(info, scopes=[ALCANCE])
        self._s = AuthorizedSession(creds)

    def _peticion(self, metodo: str, url: str, **kw) -> dict:
        try:
            r = self._s.request(metodo, url, timeout=60, **kw)
        except Exception as exc:  # noqa: BLE001 — red, DNS, token
            raise GscError(None, f"{type(exc).__name__}: {exc}") from exc
        if r.status_code >= 400:
            try:
                detalle = r.json().get("error", {}).get("message", r.text)
            except Exception:  # noqa: BLE001
                detalle = r.text
            raise GscError(r.status_code, str(detalle))
        return r.json() if r.content else {}

    def consultar(self, propiedad: str, cuerpo: dict) -> dict:
        from urllib.parse import quote

        return self._peticion("POST", f"{API}/sites/{quote(propiedad, safe='')}/searchAnalytics/query",
                              json=cuerpo)

    def propiedades(self) -> list[dict]:
        return (self._peticion("GET", f"{API}/sites") or {}).get("siteEntry") or []

    def sitemaps(self, propiedad: str) -> list[dict]:
        from urllib.parse import quote

        return (self._peticion("GET", f"{API}/sites/{quote(propiedad, safe='')}/sitemaps")
                or {}).get("sitemap") or []


def descargar_dia(consultar: Callable[[str, dict], dict], propiedad: str,
                  dia: date) -> tuple[list[dict], bool]:
    """Las filas de un dia por pagina, y si Google corto en el tope."""
    filas: list[dict] = []
    inicio = 0
    while True:
        resp = consultar(propiedad, {
            "startDate": dia.isoformat(), "endDate": dia.isoformat(),
            "dimensions": ["page"], "type": "web", "dataState": "final",
            "rowLimit": FILAS_POR_PAGINA, "startRow": inicio,
        })
        lote = resp.get("rows") or []
        filas.extend(lote)
        if len(lote) < FILAS_POR_PAGINA:
            return filas, False
        inicio += FILAS_POR_PAGINA
        if inicio >= TOPE_FILAS_DIA:
            return filas, True


def toca(estado, ahora: datetime) -> bool:
    """Si hay que sincronizar ahora este (cliente, propiedad)."""
    if estado is None:
        return True
    ult = estado.ultimo_intento
    if estado.estado == "en_curso" and ult and ahora - ult < EN_CURSO_CADUCA:
        return False
    if estado.pedida_en and (ult is None or estado.pedida_en > ult):
        return True
    if estado.ultimo_ok is None or estado.estado == "error":
        return ult is None or ahora - ult >= REINTENTAR_ERROR
    return estado.ultimo_ok.date() < ahora.date() and ahora.hour >= HORA_UTC_DIARIA


def _estado(db, cliente_id, propiedad: str):
    from shared.models import GscEstado

    e = (db.query(GscEstado)
         .filter(GscEstado.cliente_id == cliente_id, GscEstado.propiedad == propiedad).one_or_none())
    if e is None:
        e = GscEstado(cliente_id=cliente_id, propiedad=propiedad, estado="pendiente")
        db.add(e)
        db.flush()
    return e


def sincronizar(db, cliente, integracion: dict, *, hoy: date | None = None,
                ahora: datetime | None = None,
                consultor: Callable[[dict], Any] | None = None) -> Any:
    """Descarga lo que falta y deja el estado. Nunca lanza: el error queda
    en el estado, con el motivo en castellano."""
    from sqlalchemy import func

    from shared.credenciales import CredencialNoDisponible, credencial
    from shared.models import GscPagina

    ahora = ahora or datetime.now(timezone.utc)
    hoy = hoy or ahora.date()
    propiedad = str(((integracion or {}).get("parametros") or {}).get("propiedad") or "").strip()
    if not propiedad:
        return None
    e = _estado(db, cliente.id, propiedad)
    e.estado, e.ultimo_intento, e.motivo = "en_curso", ahora, None
    db.commit()
    cuenta = None
    try:
        info = leer_llave(credencial(integracion))
        cuenta = info.get("client_email")
        e.cuenta = cuenta
        c = consultor(info) if consultor else Consultor(info)
        hasta = hoy - timedelta(days=RETRASO_DIAS)
        desde = (e.ultimo_dia - timedelta(days=SOLAPE_DIAS) if e.ultimo_dia
                 else hasta - timedelta(days=dias_iniciales() - 1))
        truncados = set(e.dias_truncados or [])
        dia = desde
        while dia <= hasta:
            filas, truncado = descargar_dia(c.consultar, propiedad, dia)
            (db.query(GscPagina).filter(GscPagina.cliente_id == cliente.id,
                                        GscPagina.propiedad == propiedad, GscPagina.fecha == dia)
             .delete(synchronize_session=False))
            vistos: dict[str, dict] = {}
            for f in filas:
                url = (f.get("keys") or [None])[0]
                if not url:
                    continue
                clave = clave_de_url(url)
                # Dos URLs que solo difieren en lo que `clave_url` iguala (el
                # orden de los parametros) son una: se suman.
                v = vistos.setdefault(clave, {"url": url, "clics": 0, "impresiones": 0, "pos_x_imp": 0.0})
                imp = int(f.get("impressions") or 0)
                v["clics"] += int(f.get("clicks") or 0)
                v["impresiones"] += imp
                v["pos_x_imp"] += float(f.get("position") or 0) * imp
            db.bulk_insert_mappings(GscPagina, [
                {"cliente_id": cliente.id, "propiedad": propiedad, "fecha": dia, "url": v["url"],
                 "url_clave": k, "clics": v["clics"], "impresiones": v["impresiones"],
                 "posicion": round(v["pos_x_imp"] / v["impresiones"], 2) if v["impresiones"] else None}
                for k, v in vistos.items()])
            (truncados.add if truncado else truncados.discard)(dia.isoformat())
            e.ultimo_dia = max(e.ultimo_dia or dia, dia)
            e.primer_dia = min(e.primer_dia or dia, dia)
            e.dias_truncados = sorted(truncados)
            db.commit()
            dia += timedelta(days=1)
        e.filas = (db.query(func.count(GscPagina.id))
                   .filter(GscPagina.cliente_id == cliente.id, GscPagina.propiedad == propiedad).scalar())
        e.estado, e.ultimo_ok, e.motivo = "ok", ahora, None
        db.commit()
    except CredencialNoDisponible as exc:
        db.rollback()
        e.estado, e.motivo = "error", f"Falta la llave: {exc}"
        db.commit()
    except LlaveNoValida as exc:
        db.rollback()
        e.estado, e.motivo = "error", str(exc)
        db.commit()
    except GscError as exc:
        db.rollback()
        e.cuenta = cuenta or e.cuenta
        e.estado, e.motivo = "error", traducir(exc.status, str(exc), cuenta, propiedad)
        db.commit()
        logger.warning("Search Console de %s (%s): %s", getattr(cliente, "slug", "?"), propiedad, e.motivo)
    return e


def pendientes(db, ahora: datetime) -> list[tuple[Any, dict]]:
    """Los (cliente, integracion) con Search Console activa y configurada a
    los que les toca sincronizar."""
    from shared.credenciales import esta_configurada
    from shared.models import Client, GscEstado

    salida = []
    for cliente in db.query(Client).all():
        for integ in cliente.integraciones or []:
            if not (isinstance(integ, dict) and integ.get("tipo") == "gsc" and integ.get("activa", True)):
                continue
            propiedad = str((integ.get("parametros") or {}).get("propiedad") or "").strip()
            if not propiedad or not esta_configurada(integ):
                continue
            e = (db.query(GscEstado).filter(GscEstado.cliente_id == cliente.id,
                                            GscEstado.propiedad == propiedad).one_or_none())
            from shared.gsc_detalle import toca as toca_detalle
            from shared.gsc_inspeccion import toca as toca_inspeccion

            # Tambien si solo falta la inspeccion del dia (decision 144) o las
            # busquedas y sitemaps (decision 157).
            if toca(e, ahora) or toca_inspeccion(e, ahora) or toca_detalle(e, ahora):
                salida.append((cliente, integ))
    return salida
