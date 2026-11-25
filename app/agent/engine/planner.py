"""TazeRota plan: the business rules of dataa.xlsx (Riskli_Lot_Kontrol, Erken_Uyari).

Rules
- Daily demand per dealer = 0.6 x mean(last 7 days) + 0.4 x mean(15 days).
- Risky lot (days to unsafe-ship date <= risk_days):
    dealer capacity = floor(demand x (days to SKT - lead time) - dealer stock), at least 0.
    Lots are handled in SKT order; an earlier lot of the same product uses dealer capacity first.
    Ship to dealers with the largest capacity first. The rest goes to donation when the product is
    donation-eligible, otherwise it is disposed.
- No-action scenario: the depot only replenishes normally until the unsafe-ship date:
    sold = floor(sum demand x days to unsafe-ship date - sum dealer stock); the rest is disposed.
- Early warning (risk_days < days to unsafe-ship date <= early_days):
    capacity = floor(sum demand x (days to SKT - lead time) - sum dealer stock), minus what earlier
    lots of the same product already use. Surplus = depot quantity - capacity.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from . import config
from .loader import get_repository

SHIP, DONATE, DISPOSE = "SHIP_TO_DEALER", "DONATE", "DISPOSE"


def daily_demand(series: list[int]) -> float:
    recent = sum(series[-config.RECENT_DAYS:]) / config.RECENT_DAYS
    history = sum(series[-config.HISTORY_DAYS:]) / config.HISTORY_DAYS
    return config.W_RECENT * recent + config.W_HISTORY * history


def _enrich(lot: dict) -> dict:
    expiry = date.fromisoformat(lot["expiry_date"])
    unsafe = expiry - timedelta(days=int(lot["unsafe_ship_days"]))
    return {**lot, "quantity": int(lot["quantity"]), "unsafe_ship_date": unsafe.isoformat(),
            "days_to_expiry": (expiry - config.AS_OF_DATE).days,
            "days_to_unsafe": (unsafe - config.AS_OF_DATE).days}


def _status_label(ship: int, donate: int, dispose: int) -> str:
    if dispose:
        return "Kısmi imha" if ship or donate else "İmha"
    if donate:
        return "Kısmi bağış" if ship else "Bağış"
    return "Sorun yok"


def build_plan(risk_days: int | None = None, early_days: int | None = None) -> dict:
    risk_days = config.RISK_DAYS if risk_days is None else int(risk_days)
    early_days = config.EARLY_DAYS if early_days is None else int(early_days)
    if risk_days < 0 or early_days < risk_days:
        raise ValueError("Eşikler 0 <= riskli eşiği <= erken uyarı eşiği olmalı.")

    repo = get_repository()
    dealers = repo.dealers()
    lots = sorted((_enrich(l) for l in repo.lots()), key=lambda l: (l["expiry_date"], l["lot_id"]))

    used_ship: dict[tuple[str, str], int] = {}  # (dealer_id, product_code) -> units planned
    used_total: dict[str, int] = {}             # product_code -> units absorbed by earlier lots
    used_normal: dict[str, int] = {}            # product_code -> units sold in the no-action scenario
    risky, early, normal, expired = [], [], [], []

    for lot in lots:
        code = lot["product_code"]
        if lot["days_to_expiry"] < 0:
            expired.append(lot)
            continue
        rates = {d["dealer_id"]: daily_demand(repo.sales(d["dealer_id"], code)) for d in dealers}

        if lot["days_to_unsafe"] <= risk_days:
            rows = []
            for d in dealers:
                did = d["dealer_id"]
                series = repo.sales(did, code)
                stock = int(d["stock"].get(code, 0))
                window = lot["days_to_expiry"] - int(d["lead_time_days"])
                raw = math.floor(rates[did] * window - stock) if lot["days_to_unsafe"] >= 0 else 0
                cap = max(0, max(0, raw) - used_ship.get((did, code), 0))
                rows.append({"dealer_id": did, "dealer_name": d["dealer_name"],
                             "lead_time_days": int(d["lead_time_days"]), "sales_15d": sum(series[-15:]),
                             "sales_7d": sum(series[-7:]), "daily_demand": round(rates[did], 2),
                             "stock": stock, "capacity": cap, "recommended": 0})
            remaining = lot["quantity"]
            for row in sorted(rows, key=lambda r: (-r["capacity"], r["dealer_id"])):
                qty = min(remaining, row["capacity"])
                if qty > 0:
                    row["recommended"] = qty
                    used_ship[(row["dealer_id"], code)] = used_ship.get((row["dealer_id"], code), 0) + qty
                    remaining -= qty
            ship = lot["quantity"] - remaining
            donate = remaining if lot["donation_eligible"] else 0
            dispose = remaining - donate
            used_total[code] = used_total.get(code, 0) + ship

            total_rate = sum(rates.values())
            total_stock = sum(int(d["stock"].get(code, 0)) for d in dealers)
            normal_cap = max(0, math.floor(total_rate * max(0, lot["days_to_unsafe"]) - total_stock)
                             - used_normal.get(code, 0))
            normal_sold = min(lot["quantity"], normal_cap)
            used_normal[code] = used_normal.get(code, 0) + normal_sold

            if ship + donate + dispose != lot["quantity"]:
                raise AssertionError(f"{lot['lot_id']}: dağılım toplamı lot miktarına eşit değil")
            rows.sort(key=lambda r: (-r["recommended"], -r["capacity"], r["dealer_id"]))
            risky.append({**lot, "risk_qty": lot["quantity"], "dealers": rows,
                          "capacity_total": sum(r["capacity"] for r in rows),
                          "ship_qty": ship, "donate_qty": donate, "dispose_qty": dispose,
                          "no_action_disposed": lot["quantity"] - normal_sold,
                          "status": _status_label(ship, donate, dispose),
                          "reason": _risky_reason(lot, rows, ship, donate, dispose)})

        elif lot["days_to_unsafe"] <= early_days:
            total_rate = sum(rates.values())
            total_stock = sum(int(d["stock"].get(code, 0)) for d in dealers)
            raw = math.floor(sum(rates[d["dealer_id"]] * (lot["days_to_expiry"] - int(d["lead_time_days"]))
                                 for d in dealers) - total_stock)
            cap = max(0, raw - used_total.get(code, 0))
            used_total[code] = used_total.get(code, 0) + min(cap, lot["quantity"])
            surplus = max(0, lot["quantity"] - cap)
            early.append({**lot, "daily_demand": round(total_rate, 2), "capacity": cap, "surplus": surplus,
                          "days_to_sell_out": round(lot["quantity"] / total_rate) if total_rate > 0 else None,
                          "status": "Erken uyarı" if surplus > 0 else "Sorun beklenmiyor"})
        else:
            normal.append(lot)

    risky.sort(key=lambda l: (l["days_to_unsafe"], l["lot_id"]))
    early.sort(key=lambda l: (l["days_to_unsafe"], l["lot_id"]))
    return {"as_of_date": config.AS_OF_DATE.isoformat(), "warehouse_id": config.WAREHOUSE_ID,
            "risk_days": risk_days, "early_days": early_days, "risky": risky, "early": early,
            "normal_count": len(normal), "expired": expired, "kpis": _kpis(risky, early)}


def _kpis(risky: list[dict], early: list[dict]) -> dict:
    qty = sum(l["risk_qty"] for l in risky)
    ship = sum(l["ship_qty"] for l in risky)
    donate = sum(l["donate_qty"] for l in risky)
    dispose = sum(l["dispose_qty"] for l in risky)
    no_action = sum(l["no_action_disposed"] for l in risky)
    pct = lambda x: round(100 * x / qty, 1) if qty else 0.0
    warn = [l for l in early if l["surplus"] > 0]
    return {"risky_lot_count": len(risky), "risky_qty": qty,
            "shipped": ship, "shipped_pct": pct(ship), "donated": donate, "donated_pct": pct(donate),
            "disposed": dispose, "disposal_rate_pct": pct(dispose),
            "no_action_disposed": no_action, "no_action_disposal_rate_pct": pct(no_action),
            "early_warning_lot_count": len(warn), "early_warning_surplus": sum(l["surplus"] for l in warn),
            "early_window_lot_count": len(early), "early_window_no_issue_count": len(early) - len(warn)}


def _risky_reason(lot: dict, rows: list[dict], ship: int, donate: int, dispose: int) -> str:
    cap = sum(r["capacity"] for r in rows)
    parts = []
    top = max(rows, key=lambda r: r["capacity"]) if rows else None
    if ship == lot["quantity"]:
        parts.append(f"Bayilerin toplam kapasitesi {cap} adet, lotun tamamı ({ship}) bayilere sevk edilebilir.")
    else:
        parts.append(f"Bayilerin toplam kapasitesi {cap} adet; {ship} adet bayilere sevk edilir.")
    if top and top["capacity"] > 0:
        parts.append(f"En yüksek kapasite {top['dealer_name']} ({top['capacity']}).")
    if donate:
        parts.append(f"Kalan {donate} adet bağışa önerilir; kalite ve mevzuat kontrolü gerekir.")
    if dispose:
        parts.append(f"Kalan {dispose} adet bağışa uygun değil, imha edilir.")
    return " ".join(parts)


def find_lot(plan: dict, query: str) -> dict | None:
    """Find a lot in the plan by lot id (or prefix) or product name fragment."""
    q = query.strip().lower()
    pool = plan["risky"] + plan["early"]
    for l in pool:
        if l["lot_id"].lower() == q:
            return l
    for l in pool:
        if l["lot_id"].lower().startswith(q) or q in l["product_name"].lower():
            return l
    return None


PLAN_CSV_FIELDS = ["lot_id", "product_code", "product_name", "expiry_date", "unsafe_ship_date", "days_to_unsafe",
                   "location", "risk_qty", "action", "target_id", "target_name", "qty", "reason"]


def plan_rows(plan: dict) -> list[dict]:
    """Flat recommendation rows (one per action/target). sum(qty) per lot == risk_qty."""
    out = []
    for l in plan["risky"]:
        base = {k: l[k] for k in ("lot_id", "product_code", "product_name", "expiry_date", "unsafe_ship_date",
                                  "days_to_unsafe", "location", "risk_qty")}
        for r in l["dealers"]:
            if r["recommended"]:
                out.append({**base, "action": SHIP, "target_id": r["dealer_id"], "target_name": r["dealer_name"],
                            "qty": r["recommended"], "reason": l["reason"]})
        if l["donate_qty"]:
            out.append({**base, "action": DONATE, "target_id": "BAGIS", "target_name": "Bağış",
                        "qty": l["donate_qty"], "reason": l["reason"]})
        if l["dispose_qty"]:
            out.append({**base, "action": DISPOSE, "target_id": "IMHA", "target_name": "İmha",
                        "qty": l["dispose_qty"], "reason": l["reason"]})
    return out
