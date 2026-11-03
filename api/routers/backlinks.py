"""Backlinks de un cliente, subidos en CSV (#31, decision 212).

Por cliente y no por censo (como Search Console, decision 141): el analisis
de cada censo usa la importacion mas reciente de su cliente. Se aplican al
analizar: el proximo censo los lleva solos, y uno ya hecho, re-analizandolo.
La lectura y el cruce viven en `shared/backlinks.py`.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from shared import backlinks as B
from shared.database import get_session
from shared.models import BacklinkImport, Client, ExternalLink

router = APIRouter(prefix="/api/clients", tags=["backlinks"])

# Las importaciones que se guardan por cliente: el analisis usa la ultima; las
# anteriores sirven para volver atras si la nueva salio mal. Cada una son
# hasta `B.MAX_FILAS` filas.
GUARDADAS = 3


def _resumen(imp: BacklinkImport, en_uso: bool) -> dict:
    return {"id": imp.id, "fuente": imp.fuente, "fichero": imp.fichero,
            "fecha_dato": imp.fecha_dato.isoformat() if imp.fecha_dato else None,
            "filas": imp.filas, "spam": imp.spam, "nofollow": imp.nofollow,
            "descartadas": imp.descartadas or {},
            "columnas": imp.columnas or {},
            "cortado": bool(imp.cortado), "subido": imp.created_at.isoformat() if imp.created_at else None,
            "en_uso": en_uso}


def _cliente(db: Session, cliente_id: uuid.UUID) -> Client:
    c = db.get(Client, cliente_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return c


@router.get("/{cliente_id}/backlinks")
def listar(cliente_id: uuid.UUID, db: Session = Depends(get_session)):
    _cliente(db, cliente_id)
    imps = (db.query(BacklinkImport).filter(BacklinkImport.cliente_id == cliente_id)
            .order_by(BacklinkImport.created_at.desc(), BacklinkImport.id.desc()).all())
    return [_resumen(i, n == 0) for n, i in enumerate(imps)]


@router.post("/{cliente_id}/backlinks", status_code=201)
def subir(cliente_id: uuid.UUID, fichero: UploadFile = File(...),
          fuente: str | None = Form(None), fecha_dato: date | None = Form(None),
          db: Session = Depends(get_session)):
    """Lee un export de Ahrefs, Semrush o Majestic (o uno con «Source URL» y
    «Target URL») y guarda sus backlinks vivos, los nofollow marcados.

    Sincrona a proposito: FastAPI la corre en un hilo, y leer 200.000 filas e
    insertarlas no para el bucle de eventos (la interfaz, el MCP). El fichero
    se lee en streaming desde el temporal de la subida."""
    _cliente(db, cliente_id)
    f = fichero.file
    f.seek(0, 2)
    tamano = f.tell()
    f.seek(0)
    if tamano > B.MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"El fichero pasa de {B.MAX_BYTES // (1024 * 1024)} MB")
    try:
        lectura = B.leer_csv(f, fuente=fuente)
    except B.CsvNoValido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not lectura.filas:
        raise HTTPException(status_code=422, detail="El fichero no tiene ningún backlink vivo")
    imp = BacklinkImport(cliente_id=cliente_id, fuente=lectura.fuente, fichero=(fichero.filename or "")[:255],
                         fecha_dato=fecha_dato, filas=len(lectura.filas), cortado=lectura.cortado,
                         spam=lectura.spam if "spam" in lectura.columnas else None,
                         nofollow=lectura.nofollow, columnas=lectura.columnas,
                         descartadas={"perdidas": lectura.descartadas_perdidas,
                                      "sin_url": lectura.descartadas_sin_url})
    db.add(imp)
    db.flush()
    for i in range(0, len(lectura.filas), 5000):
        db.bulk_insert_mappings(ExternalLink, [{"import_id": imp.id, **f} for f in lectura.filas[i:i + 5000]])
    viejas = (db.query(BacklinkImport.id).filter(BacklinkImport.cliente_id == cliente_id)
              .order_by(BacklinkImport.created_at.desc(), BacklinkImport.id.desc())
              .offset(GUARDADAS).all())
    for (vid,) in viejas:
        db.query(ExternalLink).filter(ExternalLink.import_id == vid).delete(synchronize_session=False)
        db.query(BacklinkImport).filter(BacklinkImport.id == vid).delete(synchronize_session=False)
    db.commit()
    db.refresh(imp)
    return {**_resumen(imp, True), "leidas": lectura.leidas,
            "destinos": len(B.agrupar_por_destino(lectura.filas)),
            "dominios": len({f["dominio_from"] for f in lectura.filas})}


@router.delete("/{cliente_id}/backlinks/{import_id}", status_code=204)
def borrar(cliente_id: uuid.UUID, import_id: int, db: Session = Depends(get_session)):
    imp = db.get(BacklinkImport, import_id)
    if imp is None or imp.cliente_id != cliente_id:
        raise HTTPException(status_code=404, detail="Importación no encontrada")
    db.query(ExternalLink).filter(ExternalLink.import_id == import_id).delete(synchronize_session=False)
    db.delete(imp)
    db.commit()
