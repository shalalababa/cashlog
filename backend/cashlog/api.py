"""FastAPI HTTP API for the Cashlog frontend.

Thin layer over service.py: a SQLite connection per request, pydantic request
models, and JSON responses with money in major units. CORS is open to the Vite
dev server; if a built frontend exists it is served from the same origin.
"""
from __future__ import annotations

from typing import Optional

from datetime import date as _date

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from . import config, db, service

app = FastAPI(title="Cashlog API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


# --- request models ---------------------------------------------------------
class TxnIn(BaseModel):
    date: str
    direction: str
    amount: str
    currency: str
    content: str = ""
    category_id: Optional[int] = None
    note: Optional[str] = None
    is_aa: bool = False
    payer_id: Optional[int] = None
    aa_settled: bool = False

    @field_validator("date")
    @classmethod
    def _iso_date(cls, v: str) -> str:
        try:
            _date.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError("date must be YYYY-MM-DD")
        return v

    @field_validator("direction")
    @classmethod
    def _direction(cls, v: str) -> str:
        if v not in ("expense", "income"):
            raise ValueError("direction must be 'expense' or 'income'")
        return v


class CategoryIn(BaseModel):
    name: str
    kind: str
    color: Optional[str] = None
    icon: Optional[str] = None
    exclude_stats: bool = False
    sort_order: int = 0


class CategoryPatch(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    exclude_stats: Optional[bool] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None


# --- endpoints --------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version}


@app.get("/api/meta")
def meta(conn=Depends(get_conn)):
    return {
        "currencies": service.list_currencies(conn),
        "categories": service.list_categories(conn),
        "settings": {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM setting")},
    }


@app.get("/api/txns")
def list_txns(
    conn=Depends(get_conn),
    direction: Optional[str] = None, search: Optional[str] = None,
    category_id: Optional[int] = None, currency: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    aa: Optional[str] = None, uncategorized: bool = False,
    sort: str = "date", order: str = "desc",
    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
):
    return service.list_txns(conn, direction=direction, search=search,
                             category_id=category_id, currency=currency,
                             date_from=date_from, date_to=date_to, aa=aa,
                             uncategorized=uncategorized, sort=sort, order=order,
                             limit=limit, offset=offset)


@app.post("/api/txns", status_code=201)
def create_txn(body: TxnIn, conn=Depends(get_conn)):
    try:
        return service.create_txn(conn, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/txns/{txn_id}")
def get_txn(txn_id: int, conn=Depends(get_conn)):
    row = service.get_txn(conn, txn_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return row


@app.put("/api/txns/{txn_id}")
def update_txn(txn_id: int, body: TxnIn, conn=Depends(get_conn)):
    try:
        return service.update_txn(conn, txn_id, body.model_dump())
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/txns/{txn_id}", status_code=204)
def delete_txn(txn_id: int, conn=Depends(get_conn)):
    if not service.delete_txn(conn, txn_id):
        raise HTTPException(status_code=404, detail="not found")


@app.get("/api/autocomplete")
def autocomplete(direction: str, prefix: str, conn=Depends(get_conn)):
    return service.autocomplete(conn, direction, prefix)


@app.get("/api/rate")
def rate(currency: str, date: str, conn=Depends(get_conn)):
    try:
        return service.rate_for(conn, currency, date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/currencies")
def currencies(conn=Depends(get_conn)):
    return service.list_currencies(conn)


@app.get("/api/categories")
def categories(kind: Optional[str] = None, conn=Depends(get_conn)):
    return service.list_categories(conn, kind)


@app.post("/api/categories", status_code=201)
def create_category(body: CategoryIn, conn=Depends(get_conn)):
    try:
        return service.create_category(conn, body.model_dump())
    except Exception as exc:  # unique violation etc.
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/api/categories/{cat_id}")
def update_category(cat_id: int, body: CategoryPatch, conn=Depends(get_conn)):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return service.update_category(conn, cat_id, data)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")


# --- optionally serve a built frontend --------------------------------------
_DIST = config.REPO_ROOT / "frontend" / "dist"
if _DIST.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
