"""FastAPI HTTP API for the Cashlog frontend.

Thin layer over service.py: a SQLite connection per request, pydantic request
models, and JSON responses with money in major units. CORS is open to the Vite
dev server; if a built frontend exists it is served from the same origin.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from datetime import date as _date

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from . import aa_service, budgets, config, dashboard, db, rates, seed, service, stats, xlsxsync

app = FastAPI(title="Cashlog API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _bootstrap_db() -> None:
    """Make the configured database usable before serving requests.

    * Fresh location (no ``category`` table — e.g. a first run of the desktop
      build against an empty per-user data dir): create the baseline schema and
      seed reference data so the app is immediately usable.
    * Existing database: just bring it up to the latest additive schema (e.g.
      the P6 budget table) so it gains new tables without a rebuild.

    Both paths are idempotent — seeding uses ``ON CONFLICT`` upserts — so this is
    safe to run on every startup and never disturbs the real ledger.
    """
    config.ensure_data_dirs()
    conn = db.connect()
    try:
        has_core = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='category'"
        ).fetchone()
        if has_core:
            db.ensure_schema(conn)
            return
    finally:
        conn.close()

    # Fresh database: build the baseline (schema.sql + migrations) then seed.
    db.init_db()
    conn = db.connect()
    try:
        seed.seed(conn)
    finally:
        conn.close()


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


class FiscalMonthIn(BaseModel):
    total_cny: Optional[str] = None          # blank/null clears manual override
    credit_card: str = "0"                  # major units in credit_card_currency
    credit_card_currency: str = "USD"


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


# --- AA: people -------------------------------------------------------------
class PersonIn(BaseModel):
    name: str
    initial: Optional[str] = None


class PersonPatch(BaseModel):
    name: Optional[str] = None
    initial: Optional[str] = None
    active: Optional[bool] = None


@app.get("/api/persons")
def list_persons(active_only: bool = False, conn=Depends(get_conn)):
    return aa_service.list_persons(conn, active_only)


@app.post("/api/persons", status_code=201)
def create_person(body: PersonIn, conn=Depends(get_conn)):
    try:
        return aa_service.create_person(conn, body.name, body.initial)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/api/persons/{person_id}")
def update_person(person_id: int, body: PersonPatch, conn=Depends(get_conn)):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return aa_service.update_person(conn, person_id, data)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- AA: structured AA on a transaction -------------------------------------
class ParticipantIn(BaseModel):
    person_id: int
    weight: Optional[str] = None
    fixed_amount: Optional[str] = None


class TxnAAIn(BaseModel):
    payer_id: Optional[int] = None
    participants: list[ParticipantIn]
    settled: bool = False


@app.get("/api/txns/{txn_id}/aa")
def get_txn_aa(txn_id: int, conn=Depends(get_conn)):
    try:
        return aa_service.get_txn_aa(conn, txn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")


@app.put("/api/txns/{txn_id}/aa")
def set_txn_aa(txn_id: int, body: TxnAAIn, conn=Depends(get_conn)):
    try:
        return aa_service.set_txn_aa(conn, txn_id, body.payer_id,
                                     [p.model_dump() for p in body.participants], body.settled)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/txns/{txn_id}/aa")
def clear_txn_aa(txn_id: int, conn=Depends(get_conn)):
    try:
        return aa_service.clear_txn_aa(conn, txn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")


# --- AA: settlement ---------------------------------------------------------
class TxnIds(BaseModel):
    txn_ids: Optional[list[int]] = None


@app.get("/api/aa/unsettled")
def aa_unsettled(conn=Depends(get_conn)):
    return aa_service.list_unsettled(conn)


@app.post("/api/aa/settlement")
def aa_settlement(body: TxnIds, conn=Depends(get_conn)):
    return aa_service.compute_settlement(conn, body.txn_ids)


@app.post("/api/aa/settle")
def aa_settle(body: TxnIds, conn=Depends(get_conn)):
    return {"settled": aa_service.settle(conn, body.txn_ids or [])}


# --- AA: candidates + batch structuring -------------------------------------
class StructureIn(BaseModel):
    txn_ids: list[int]
    payer_id: int
    participant_ids: list[int]
    settled: bool = False


@app.get("/api/aa/candidates")
def aa_candidates(conn=Depends(get_conn)):
    return aa_service.candidates(conn)


@app.post("/api/aa/structure")
def aa_structure(body: StructureIn, conn=Depends(get_conn)):
    try:
        return {"structured": aa_service.batch_structure(
            conn, body.txn_ids, body.payer_id, body.participant_ids, settled=body.settled)}
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- AA: receipt calculator -------------------------------------------------
class ShareIn(BaseModel):
    person_id: int
    weight: Optional[str] = None


class ItemIn(BaseModel):
    label: Optional[str] = None
    pretax: str
    person_ids: Optional[list[int]] = None
    shares: Optional[list[ShareIn]] = None


class SessionIn(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    currency: str
    payer_id: Optional[int] = None
    total_with_tax: str
    items: list[ItemIn] = []


class GenerateIn(BaseModel):
    date: str
    content: str
    category_id: Optional[int] = None


def _session_payload(body: SessionIn) -> dict:
    return {
        "id": body.id, "name": body.name, "currency": body.currency,
        "payer_id": body.payer_id, "total_with_tax": body.total_with_tax,
        "items": [{"label": it.label, "pretax": it.pretax,
                   "person_ids": it.person_ids,
                   "shares": [s.model_dump() for s in it.shares] if it.shares else None}
                  for it in body.items],
    }


@app.get("/api/aa/sessions")
def aa_sessions(conn=Depends(get_conn)):
    return aa_service.list_sessions(conn)


@app.get("/api/aa/sessions/{session_id}")
def aa_get_session(session_id: int, conn=Depends(get_conn)):
    try:
        return aa_service.get_session(conn, session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")


@app.post("/api/aa/sessions", status_code=201)
def aa_create_session(body: SessionIn, conn=Depends(get_conn)):
    try:
        return aa_service.save_session(conn, _session_payload(body))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/aa/sessions/{session_id}")
def aa_update_session(session_id: int, body: SessionIn, conn=Depends(get_conn)):
    payload = _session_payload(body)
    payload["id"] = session_id
    try:
        return aa_service.save_session(conn, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/aa/sessions/{session_id}", status_code=204)
def aa_delete_session(session_id: int, conn=Depends(get_conn)):
    if not aa_service.delete_session(conn, session_id):
        raise HTTPException(status_code=404, detail="not found")


@app.post("/api/aa/sessions/{session_id}/generate", status_code=201)
def aa_generate_txn(session_id: int, body: GenerateIn, conn=Depends(get_conn)):
    try:
        return aa_service.generate_txn_from_session(
            conn, session_id, date=body.date, content=body.content, category_id=body.category_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- statistics + visualization ---------------------------------------------
@app.get("/api/stats/fiscal")
def stats_fiscal(conn=Depends(get_conn)):
    return stats.fiscal_months(conn)


@app.put("/api/stats/fiscal/{period_end}")
def put_stats_fiscal(period_end: str, body: FiscalMonthIn, conn=Depends(get_conn)):
    try:
        return stats.save_fiscal_month(
            conn,
            period_end,
            credit_card=body.credit_card,
            total_cny=body.total_cny,
            credit_card_currency=body.credit_card_currency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/stats/categories")
def stats_categories(date_from: str, date_to: str,
                     direction: str = "expense", conn=Depends(get_conn)):
    try:
        return stats.category_breakdown(conn, date_from, date_to, direction=direction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/stats/category-trend")
def stats_category_trend(date_from: str, date_to: str, granularity: str = "month",
                         direction: str = "expense", conn=Depends(get_conn)):
    try:
        return stats.category_trend(conn, date_from, date_to,
                                    granularity=granularity, direction=direction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- budgets ----------------------------------------------------------------
class BudgetIn(BaseModel):
    category_id: Optional[int] = None       # null = overall budget
    amount_type: str = "absolute"           # 'absolute' | 'percent'
    amount: Optional[str] = None            # major CNY, for absolute
    amount_currency: Optional[str] = "CNY"   # CNY or USD input; stored as CNY
    period_end: Optional[str] = None         # rate date for non-CNY amount input
    percent: Optional[str] = None           # share of overall, for percent
    note: Optional[str] = None


@app.get("/api/budgets")
def get_budgets(conn=Depends(get_conn)):
    return budgets.list_budgets(conn)


@app.get("/api/budgets/status")
def get_budget_status(period_end: Optional[str] = None, conn=Depends(get_conn)):
    try:
        return budgets.budget_status(conn, period_end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/budgets")
def put_budget(body: BudgetIn, conn=Depends(get_conn)):
    try:
        return budgets.set_budget(conn, category_id=body.category_id,
                                  amount_type=body.amount_type, amount=body.amount,
                                  amount_currency=body.amount_currency or "CNY",
                                  period_end=body.period_end,
                                  percent=body.percent, note=body.note)
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: int, conn=Depends(get_conn)):
    if not budgets.delete_budget(conn, budget_id):
        raise HTTPException(status_code=404, detail="not found")


# --- dashboard --------------------------------------------------------------
@app.get("/api/dashboard")
def get_dashboard(conn=Depends(get_conn)):
    return dashboard.dashboard(conn)


# --- exchange rates ----------------------------------------------------------
class RateRefreshIn(BaseModel):
    currencies: Optional[list[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@app.get("/api/rates/status")
def rates_status(conn=Depends(get_conn)):
    return rates.rate_status(conn)


@app.post("/api/rates/refresh")
def refresh_rates(body: RateRefreshIn, conn=Depends(get_conn)):
    try:
        return rates.refresh_rates(conn, currency_codes=body.currencies,
                                   start_date=body.start_date, end_date=body.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- xlsx sync ---------------------------------------------------------------
class XlsxImportIn(BaseModel):
    apply_deletions: bool = False
    apply_conflicts: bool = False


@app.get("/api/xlsx/diff")
def xlsx_diff(conn=Depends(get_conn)):
    try:
        diff = xlsxsync.diff_from_xlsx(conn)
        return {"summary": diff.summary()}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/xlsx/export")
def xlsx_export(conn=Depends(get_conn)):
    try:
        return xlsxsync.export_to_xlsx(conn)
    except xlsxsync.WorkbookLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/xlsx/import")
def xlsx_import(body: XlsxImportIn, conn=Depends(get_conn)):
    try:
        diff = xlsxsync.diff_from_xlsx(conn)
        applied = xlsxsync.apply_diff(conn, None, diff,
                                      apply_deletions=body.apply_deletions,
                                      apply_conflicts=body.apply_conflicts)
        return {"summary": diff.summary(), "applied": applied}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- serve the built frontend (same origin) ---------------------------------
# Mounted last so it never shadows the `/api/...` routes above. When this exists
# the webview can load the UI straight from the backend; the desktop sidecar
# bundles `frontend/dist` precisely so the installed app serves a real UI here
# instead of a bare 404. (html=True makes "/" return index.html.)
if config.FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIST), html=True),
              name="frontend")
