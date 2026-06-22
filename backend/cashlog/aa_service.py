"""AA service layer: people, structured AA on transactions, settlement, and the
receipt calculator. Builds on aa.py (pure math) + service.py conventions.
Money crosses this boundary in major units."""
from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from . import aa, jsonsync, money, service


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
def list_persons(conn: sqlite3.Connection, active_only: bool = False) -> list:
    q = "SELECT id, name, initial, is_self, active FROM person"
    if active_only:
        q += " WHERE active = 1"
    q += " ORDER BY is_self DESC, name"
    return [dict(r) for r in conn.execute(q)]


def create_person(conn: sqlite3.Connection, name: str, initial: Optional[str] = None,
                  *, write_json: bool = True) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    try:
        cur = conn.execute("INSERT INTO person (name, initial) VALUES (?, ?)", (name, initial))
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"person already exists: {name}") from exc
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return dict(conn.execute("SELECT id, name, initial, is_self, active FROM person WHERE id = ?",
                             (cur.lastrowid,)).fetchone())


def update_person(conn: sqlite3.Connection, person_id: int, data: dict,
                  *, write_json: bool = True) -> dict:
    fields, params = [], []
    for key in ("name", "initial", "active"):
        if key in data:
            fields.append(f"{key} = ?")
            params.append(int(data[key]) if key == "active" else data[key])
    if fields:
        params.append(person_id)
        try:
            conn.execute(f"UPDATE person SET {', '.join(fields)} WHERE id = ?", params)
        except sqlite3.IntegrityError as exc:                # e.g. renaming onto an existing name
            raise ValueError(f"person already exists: {data.get('name')}") from exc
        conn.commit()
        if write_json:
            jsonsync.export_json(conn)
    row = conn.execute("SELECT id, name, initial, is_self, active FROM person WHERE id = ?",
                       (person_id,)).fetchone()
    if row is None:
        raise KeyError(person_id)
    return dict(row)


# ---------------------------------------------------------------------------
# Structured AA on a transaction
# ---------------------------------------------------------------------------
def _person_names(conn: sqlite3.Connection) -> dict:
    return {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM person")}


def _validate_aa_persons(conn: sqlite3.Connection, payer_id: Optional[int],
                         person_ids: List[int]) -> None:
    """Pre-flight checks so bad AA input fails as a clean ValueError (-> 400) rather
    than leaking a SQLite FOREIGN KEY IntegrityError from the INSERT."""
    if not person_ids:
        raise ValueError("AA needs at least one participant")
    if len(set(person_ids)) != len(person_ids):
        raise ValueError("duplicate participant in AA")
    needed = set(person_ids)
    if payer_id is not None:
        needed.add(payer_id)
    found = {r["id"] for r in conn.execute(
        f"SELECT id FROM person WHERE id IN ({','.join('?' * len(needed))})", tuple(needed))}
    missing = sorted(needed - found)
    if missing:
        raise ValueError(f"unknown person id(s): {missing}")


def _parse_weight(raw) -> Optional[str]:
    """Validate an optional split weight; return it as a canonical string (or None)."""
    if raw in (None, ""):
        return None
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid weight: {raw!r}") from exc
    if d <= 0:
        raise ValueError(f"weight must be positive: {raw!r}")
    return str(d)


def _minor_unit_for_txn(conn: sqlite3.Connection, txn_id: int) -> int:
    row = conn.execute(
        "SELECT cur.minor_unit AS m FROM txn t JOIN currency cur ON cur.id = t.currency_id WHERE t.id = ?",
        (txn_id,)).fetchone()
    if row is None:
        raise KeyError(txn_id)
    return row["m"]


def get_txn_aa(conn: sqlite3.Connection, txn_id: int) -> dict:
    txn = conn.execute(
        "SELECT t.id, t.is_aa, t.payer_id, t.aa_settled, cur.minor_unit "
        "FROM txn t JOIN currency cur ON cur.id = t.currency_id WHERE t.id = ?",
        (txn_id,)).fetchone()
    if txn is None:
        raise KeyError(txn_id)
    mu = txn["minor_unit"]
    names = _person_names(conn)
    parts = []
    for p in conn.execute(
        "SELECT person_id, weight, fixed_amount_minor, owed_amount_minor "
        "FROM txn_participant WHERE txn_id = ? ORDER BY person_id", (txn_id,)):
        parts.append({
            "person_id": p["person_id"], "name": names.get(p["person_id"]),
            "weight": p["weight"],
            "fixed_amount": str(money.from_minor(p["fixed_amount_minor"], mu)) if p["fixed_amount_minor"] is not None else None,
            "owed": str(money.from_minor(p["owed_amount_minor"], mu)),
            "owed_minor": p["owed_amount_minor"],
        })
    return {
        "txn_id": txn["id"], "is_aa": bool(txn["is_aa"]),
        "payer_id": txn["payer_id"], "payer": names.get(txn["payer_id"]),
        "aa_settled": bool(txn["aa_settled"]), "participants": parts,
    }


def set_txn_aa(conn: sqlite3.Connection, txn_id: int, payer_id: Optional[int],
               participants: List[dict], settled: bool = False, *,
               write_json: bool = True) -> dict:
    """Mark a txn as AA and (re)compute each participant's owed share.

    participants: [{person_id, weight?, fixed_amount}]; fixed_amount is a major
    string and converted to minor here.
    """
    txn = conn.execute(
        "SELECT t.amount_minor, t.direction, cur.minor_unit FROM txn t "
        "JOIN currency cur ON cur.id = t.currency_id WHERE t.id = ?", (txn_id,)).fetchone()
    if txn is None:
        raise KeyError(txn_id)
    # Structured AA models an expense the payer fronted and others owe back. Income
    # / refund AA flips that ("who owes whom") and needs its own credit rule, so it
    # is rejected here for now rather than producing a reversed settlement.
    if txn["direction"] != "expense":
        raise ValueError("AA is only supported on expense transactions")
    if txn["amount_minor"] < 0:
        raise ValueError("AA is not supported on a negative amount")
    if payer_id is None:
        raise ValueError("AA requires a payer")
    _validate_aa_persons(conn, payer_id, [p["person_id"] for p in participants])
    mu = txn["minor_unit"]
    norm = []
    for p in participants:
        norm.append({
            "person_id": p["person_id"],
            "weight": _parse_weight(p.get("weight")),
            "fixed_amount_minor": money.to_minor(p["fixed_amount"], mu)
            if p.get("fixed_amount") not in (None, "") else None,
        })
    owed = aa.compute_owed(txn["amount_minor"], norm)

    conn.execute("UPDATE txn SET is_aa = 1, payer_id = ?, aa_settled = ? WHERE id = ?",
                 (payer_id, int(settled), txn_id))
    conn.execute("DELETE FROM txn_participant WHERE txn_id = ?", (txn_id,))
    for p, o in zip(norm, owed):
        conn.execute(
            "INSERT INTO txn_participant (txn_id, person_id, weight, fixed_amount_minor, owed_amount_minor) "
            "VALUES (?, ?, ?, ?, ?)",
            (txn_id, p["person_id"], p["weight"], p["fixed_amount_minor"], o))
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return get_txn_aa(conn, txn_id)


def clear_txn_aa(conn: sqlite3.Connection, txn_id: int, *, write_json: bool = True) -> dict:
    conn.execute("UPDATE txn SET is_aa = 0, payer_id = NULL, aa_settled = 0 WHERE id = ?", (txn_id,))
    conn.execute("DELETE FROM txn_participant WHERE txn_id = ?", (txn_id,))
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return get_txn_aa(conn, txn_id)


# ---------------------------------------------------------------------------
# Settlement (unsettled list + transfer solver)
# ---------------------------------------------------------------------------
def _unsettled_rows(conn: sqlite3.Connection, txn_ids: Optional[List[int]] = None) -> list:
    q = ("SELECT t.id, t.txn_date, t.content, t.amount_minor, t.payer_id, "
         "cur.id AS currency_id, cur.code AS currency, cur.minor_unit "
         "FROM txn t JOIN currency cur ON cur.id = t.currency_id "
         "WHERE t.is_aa = 1 AND t.aa_settled = 0")
    params: list = []
    if txn_ids:
        q += f" AND t.id IN ({','.join('?' * len(txn_ids))})"
        params += txn_ids
    q += " ORDER BY cur.code, t.txn_date, t.id"
    return conn.execute(q, params).fetchall()


def list_unsettled(conn: sqlite3.Connection) -> list:
    names = _person_names(conn)
    groups: dict = {}
    for t in _unsettled_rows(conn):
        g = groups.setdefault(t["currency"], {"currency": t["currency"],
                                              "minor_unit": t["minor_unit"], "txns": []})
        parts = [{"person_id": p["person_id"], "name": names.get(p["person_id"]),
                  "owed": str(money.from_minor(p["owed_amount_minor"], t["minor_unit"]))}
                 for p in conn.execute(
                     "SELECT person_id, owed_amount_minor FROM txn_participant WHERE txn_id = ?",
                     (t["id"],))]
        g["txns"].append({
            "id": t["id"], "date": t["txn_date"], "content": t["content"],
            "amount": str(money.from_minor(t["amount_minor"], t["minor_unit"])),
            "payer_id": t["payer_id"], "payer": names.get(t["payer_id"]),
            "participants": parts,
        })
    return list(groups.values())


def compute_settlement(conn: sqlite3.Connection, txn_ids: Optional[List[int]] = None) -> list:
    """Per-currency net balances + minimal transfers for the (selected) unsettled
    AA transactions."""
    names = _person_names(conn)
    rows = _unsettled_rows(conn, txn_ids)
    by_ccy: dict = {}
    for t in rows:
        by_ccy.setdefault(t["currency"], {"minor_unit": t["minor_unit"], "rows": []})["rows"].append(t)

    result = []
    for ccy, data in by_ccy.items():
        mu = data["minor_unit"]
        paid: dict = {}
        owed: dict = {}
        for t in data["rows"]:
            if t["payer_id"] is not None:
                paid[t["payer_id"]] = paid.get(t["payer_id"], 0) + t["amount_minor"]
            for p in conn.execute(
                "SELECT person_id, owed_amount_minor FROM txn_participant WHERE txn_id = ?", (t["id"],)):
                owed[p["person_id"]] = owed.get(p["person_id"], 0) + p["owed_amount_minor"]
        net = aa.net_balances(paid, owed)
        transfers = [{
            "from": tr["from"], "from_name": names.get(tr["from"]),
            "to": tr["to"], "to_name": names.get(tr["to"]),
            "amount": str(money.from_minor(tr["amount_minor"], mu)),
        } for tr in aa.min_cash_flow(net)]
        result.append({
            "currency": ccy,
            "balances": [{"person_id": pid, "name": names.get(pid),
                          "net": str(money.from_minor(amt, mu))} for pid, amt in net.items() if amt != 0],
            "transfers": transfers,
            "txn_ids": [t["id"] for t in data["rows"]],
        })
    return result


def settle(conn: sqlite3.Connection, txn_ids: List[int], *, write_json: bool = True) -> int:
    if not txn_ids:
        return 0
    cur = conn.execute(
        f"UPDATE txn SET aa_settled = 1 WHERE is_aa = 1 AND id IN ({','.join('?' * len(txn_ids))})",
        txn_ids)
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return cur.rowcount


# ---------------------------------------------------------------------------
# AA text candidates + batch structuring
# ---------------------------------------------------------------------------
def candidates(conn: sqlite3.Connection) -> list:
    """Expense transactions whose content mentions AA but are not yet structured.

    Restricted to non-negative expenses: structured AA only models an expense the
    payer fronted. Income / refund "AA" rows (e.g. an AA 退款) would settle the
    wrong direction, so they are excluded until a dedicated refund rule exists.
    """
    out = []
    for t in conn.execute(
        "SELECT t.id, t.txn_date, t.content, t.direction, t.amount_minor, "
        "cur.code AS currency, cur.minor_unit "
        "FROM txn t JOIN currency cur ON cur.id = t.currency_id "
        "WHERE t.is_aa = 0 AND t.direction = 'expense' AND t.amount_minor >= 0 "
        "AND t.content LIKE '%AA%' "
        "ORDER BY t.txn_date DESC"):
        out.append({"id": t["id"], "date": t["txn_date"], "content": t["content"],
                    "direction": t["direction"], "currency": t["currency"],
                    "amount": str(money.from_minor(t["amount_minor"], t["minor_unit"]))})
    return out


def batch_structure(conn: sqlite3.Connection, txn_ids: List[int], payer_id: int,
                    participant_ids: List[int], *, settled: bool = False,
                    write_json: bool = True) -> int:
    """Equal-split structure a batch of AA-text candidates with one payer and a
    shared participant set. Validated up front so a bad row in the batch can't
    leave some rows half-structured."""
    if not txn_ids or not participant_ids:
        raise ValueError("txn_ids and participant_ids required")
    if payer_id is None:
        raise ValueError("AA requires a payer")
    _validate_aa_persons(conn, payer_id, participant_ids)
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT id, direction, amount_minor FROM txn WHERE id IN ({','.join('?' * len(txn_ids))})",
        tuple(txn_ids))}
    for tid in txn_ids:
        r = rows.get(tid)
        if r is None:
            raise ValueError(f"unknown txn id: {tid}")
        if r["direction"] != "expense" or r["amount_minor"] < 0:
            raise ValueError(f"txn {tid} is not a non-negative expense; AA refund needs its own rule")
    participants = [{"person_id": pid} for pid in participant_ids]
    n = 0
    for tid in txn_ids:
        set_txn_aa(conn, tid, payer_id, participants, settled=settled, write_json=False)
        n += 1
    if write_json:
        jsonsync.export_json(conn)
    return n


# ---------------------------------------------------------------------------
# Receipt calculator (aa_session). Supersedes the Amazon calculator.
# ---------------------------------------------------------------------------
def _currency_minor(conn: sqlite3.Connection, code: str) -> sqlite3.Row:
    row = conn.execute("SELECT id, minor_unit FROM currency WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise ValueError(f"unknown currency: {code}")
    return row


def list_sessions(conn: sqlite3.Connection) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT s.id, s.name, cur.code AS currency, s.created_at "
        "FROM aa_session s LEFT JOIN currency cur ON cur.id = s.currency_id "
        "ORDER BY s.created_at DESC")]


def get_session(conn: sqlite3.Connection, session_id: int) -> dict:
    s = conn.execute(
        "SELECT s.*, cur.code AS currency, cur.minor_unit FROM aa_session s "
        "JOIN currency cur ON cur.id = s.currency_id WHERE s.id = ?", (session_id,)).fetchone()
    if s is None:
        raise KeyError(session_id)
    mu = s["minor_unit"]
    names = _person_names(conn)
    items = []
    calc_items = []
    for it in conn.execute(
        "SELECT id, label, pretax_minor FROM aa_session_item WHERE session_id = ? ORDER BY sort_order, id",
        (session_id,)):
        shares = [{"person_id": sh["person_id"], "name": names.get(sh["person_id"]),
                   "weight": sh["weight"]}
                  for sh in conn.execute(
                      "SELECT person_id, weight FROM aa_session_item_share WHERE item_id = ?", (it["id"],))]
        items.append({"id": it["id"], "label": it["label"],
                      "pretax": str(money.from_minor(it["pretax_minor"], mu)), "shares": shares})
        calc_items.append({"pretax_minor": it["pretax_minor"], "shares": shares})

    result = aa.compute_session(s["total_with_tax_minor"], calc_items)
    pretax_sum = sum(it["pretax_minor"] for it in calc_items)
    return {
        "id": s["id"], "name": s["name"], "currency": s["currency"], "minor_unit": mu,
        "payer_id": s["payer_id"], "payer": names.get(s["payer_id"]),
        "total_with_tax": str(money.from_minor(s["total_with_tax_minor"], mu)),
        "tax_amount": str(money.from_minor(s["total_with_tax_minor"] - pretax_sum, mu)),
        "pretax_total": str(money.from_minor(pretax_sum, mu)),
        "items": items,
        "result": [{"person_id": pid, "name": names.get(pid),
                    "amount": str(money.from_minor(amt, mu))} for pid, amt in result.items()],
    }


def save_session(conn: sqlite3.Connection, data: dict, *, write_json: bool = True) -> dict:
    """Create or replace a calculator session with its items + shares.

    data: {id?, name, currency, payer_id?, total_with_tax (major),
           items: [{label?, pretax (major), person_ids: [..] | shares: [{person_id, weight?}]}]}
    """
    cur = _currency_minor(conn, data["currency"])
    mu = cur["minor_unit"]
    total_minor = money.to_minor(data["total_with_tax"], mu)
    items = data.get("items", [])
    tax_minor = max(total_minor - sum(money.to_minor(it["pretax"], mu) for it in items), 0)

    sid = data.get("id")
    if sid:
        conn.execute(
            "UPDATE aa_session SET name=?, total_with_tax_minor=?, tax_amount_minor=?, "
            "currency_id=?, payer_id=?, updated_at=datetime('now') WHERE id=?",
            (data.get("name"), total_minor, tax_minor, cur["id"], data.get("payer_id"), sid))
        conn.execute("DELETE FROM aa_session_item WHERE session_id = ?", (sid,))
    else:
        c = conn.execute(
            "INSERT INTO aa_session (name, total_with_tax_minor, tax_amount_minor, currency_id, payer_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (data.get("name"), total_minor, tax_minor, cur["id"], data.get("payer_id")))
        sid = c.lastrowid

    for order, it in enumerate(items):
        ic = conn.execute(
            "INSERT INTO aa_session_item (session_id, label, pretax_minor, sort_order) VALUES (?, ?, ?, ?)",
            (sid, it.get("label"), money.to_minor(it["pretax"], mu), order))
        shares = it.get("shares") or [{"person_id": pid} for pid in it.get("person_ids", [])]
        for sh in shares:
            conn.execute(
                "INSERT INTO aa_session_item_share (item_id, person_id, weight) VALUES (?, ?, ?)",
                (ic.lastrowid, sh["person_id"], str(sh["weight"]) if sh.get("weight") else None))
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return get_session(conn, sid)


def delete_session(conn: sqlite3.Connection, session_id: int, *, write_json: bool = True) -> bool:
    cur = conn.execute("DELETE FROM aa_session WHERE id = ?", (session_id,))
    conn.commit()
    if write_json:
        jsonsync.export_json(conn)
    return cur.rowcount > 0


def generate_txn_from_session(conn: sqlite3.Connection, session_id: int, *,
                              date: str, content: str, category_id: Optional[int] = None,
                              write_json: bool = True) -> dict:
    """Create an AA expense txn from a calculator session: amount = total, payer =
    session payer, each person's owed = their computed tax-included share."""
    s = get_session(conn, session_id)
    if not s["result"]:
        raise ValueError("session has no participants/items to generate from")
    txn = service.create_txn(conn, {
        "date": date, "direction": "expense", "amount": s["total_with_tax"],
        "currency": s["currency"], "content": content, "category_id": category_id,
    }, write_json=False)
    participants = [{"person_id": r["person_id"], "fixed_amount": r["amount"]} for r in s["result"]]
    set_txn_aa(conn, txn["id"], s["payer_id"], participants, write_json=False)
    if write_json:
        jsonsync.export_json(conn)
    return service.get_txn(conn, txn["id"])
