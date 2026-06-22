"""AA (split-the-bill) math — pure functions, no DB.

  allocate          exact integer split of a total across weights (largest
                    remainder, so the parts always sum back to the total).
  compute_owed      a transaction's per-participant owed amount (equal / weighted
                    / fixed split).
  net_balances      paid minus owed per person, used for settlement.
  min_cash_flow     minimal set of transfers that clears the net balances
                    (greedy largest-debtor / largest-creditor; the Splitwise
                    "simplify debts" approach).
  compute_session   receipt calculator: distribute a tax-included total across
                    line items proportionally to pretax amounts. The Amazon
                    calculator is the single-payer special case of this.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from typing import Dict, List, Optional


def allocate(total_minor: int, weights: List[Decimal]) -> List[int]:
    """Split total_minor across weights as integers summing exactly to total_minor.

    Floor each proportional share, then hand the leftover minor units to the
    largest fractional remainders. Requires total_minor >= 0 and a positive
    weight sum.
    """
    if total_minor < 0:
        raise ValueError("allocate expects a non-negative total")
    if not weights:
        return []
    wsum = sum(weights)
    if wsum <= 0:
        raise ValueError("weights must sum to a positive value")

    raws = [Decimal(total_minor) * w / wsum for w in weights]
    floors = [int(r.to_integral_value(rounding=ROUND_FLOOR)) for r in raws]
    remainder = total_minor - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: raws[i] - floors[i], reverse=True)
    for k in range(remainder):
        floors[order[k]] += 1
    return floors


def compute_owed(amount_minor: int, participants: List[dict]) -> List[int]:
    """Owed amount per participant.

    participants: [{person_id, weight?, fixed_amount_minor?}]
      - if every participant has fixed_amount_minor -> use them (must sum to total)
      - elif any weight given -> weighted split
      - else -> equal split
    Mixing fixed and non-fixed is rejected.
    """
    if not participants:
        raise ValueError("AA needs at least one participant")
    fixed = [p for p in participants if p.get("fixed_amount_minor") is not None]
    if fixed:
        if len(fixed) != len(participants):
            raise ValueError("cannot mix fixed and proportional shares")
        owed = [int(p["fixed_amount_minor"]) for p in participants]
        if sum(owed) != amount_minor:
            raise ValueError(
                f"fixed shares ({sum(owed)}) must sum to the amount ({amount_minor})")
        return owed
    weights = [Decimal(str(p["weight"])) if p.get("weight") else Decimal(1) for p in participants]
    return allocate(amount_minor, weights)


def net_balances(paid: Dict[int, int], owed: Dict[int, int]) -> Dict[int, int]:
    """net = paid - owed, per person. Positive = should receive money."""
    people = set(paid) | set(owed)
    return {pid: paid.get(pid, 0) - owed.get(pid, 0) for pid in people}


def min_cash_flow(net: Dict[int, int]) -> List[dict]:
    """Minimal transfers that settle the net balances.

    Greedy: repeatedly match the biggest debtor with the biggest creditor.
    Returns [{from, to, amount_minor}] with from=debtor, to=creditor.
    """
    creditors = sorted(([pid, amt] for pid, amt in net.items() if amt > 0),
                       key=lambda x: -x[1])
    debtors = sorted(([pid, -amt] for pid, amt in net.items() if amt < 0),
                     key=lambda x: -x[1])
    transfers: List[dict] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        d, c = debtors[i], creditors[j]
        pay = min(d[1], c[1])
        if pay > 0:
            transfers.append({"from": d[0], "to": c[0], "amount_minor": pay})
        d[1] -= pay
        c[1] -= pay
        if d[1] == 0:
            i += 1
        if c[1] == 0:
            j += 1
    return transfers


def compute_session(total_with_tax_minor: int, items: List[dict]) -> Dict[int, int]:
    """Receipt calculator: per-person tax-included amount.

    items: [{pretax_minor, shares: [{person_id, weight?}]}]
    Each item's pretax is split among its sharers (weighted/equal) to give a
    per-person pretax share; the tax-included total is then distributed across
    those pretax shares proportionally, with exact integer rounding.
    """
    pretax_share: Dict[int, Decimal] = {}
    for item in items:
        shares = item.get("shares") or []
        if not shares:
            continue
        wsum = sum(Decimal(str(s.get("weight") or 1)) for s in shares)
        pretax = Decimal(int(item["pretax_minor"]))
        for s in shares:
            w = Decimal(str(s.get("weight") or 1))
            pretax_share[s["person_id"]] = pretax_share.get(s["person_id"], Decimal(0)) + pretax * w / wsum

    if not pretax_share:
        return {}
    person_ids = list(pretax_share)
    weights = [pretax_share[pid] for pid in person_ids]
    if sum(weights) <= 0:
        return {pid: 0 for pid in person_ids}
    allocated = allocate(total_with_tax_minor, weights)
    return {pid: amt for pid, amt in zip(person_ids, allocated)}
