"""Dispatch workflow: Öneri -> Onay (human) -> Sevk emri -> Bildirim.

Approval is PER LOT. Orders are derived from the plan: one dealer order (SE-<date>-<nnn>) per dealer shipment
and one donation order (BG-<date>-<nnn>) per lot with a donation; numbering is fixed by the plan, not by the
approval order. Before a lot is approved its orders are drafts (not stored). After the human approves the lot,
`create_orders(plan, lot_id)` stores that lot's orders in tazerota-orders together with their notification.
Notifications are records shown in the panel; no e-mail or SMS is sent.
"""
from __future__ import annotations

import re
from datetime import timedelta

from . import config
from .approvals import (DISPATCHED, approval_key, base_key, delete_approval, get_approval_by_key, list_approvals,
                        mark_dispatched, now_iso)
from .loader import get_repository, plain
from .planner import DONATE, SHIP, plan_rows

SHIPPED, DRAFT = "Sevk edildi", "Taslak"
SENT, NOT_SENT = "Gönderildi", "Gönderilmedi"


class NotApproved(Exception):
    """Raised when orders are requested for a plan the human has not approved."""


def short_name(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()


def tr_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def draft_orders(plan: dict) -> list[dict]:
    """Orders the plan would create. Numbering is deterministic and equals the final numbering."""
    lead = {d["dealer_id"]: int(d["lead_time_days"]) for d in get_repository().dealers()}
    stamp = config.AS_OF_DATE.strftime("%Y%m%d")
    seq = {SHIP: 0, DONATE: 0}
    out = []
    for row in plan_rows(plan):
        if row["action"] not in seq:
            continue  # DISPOSE needs no dispatch order
        seq[row["action"]] += 1
        ship = row["action"] == SHIP
        days = lead.get(row["target_id"], 1) if ship else config.DONATION_LEAD_DAYS
        delivery = (config.AS_OF_DATE + timedelta(days=days)).isoformat()
        name = config.DONATION_PARTNER_NAME if not ship else row["target_name"]
        product = short_name(row["product_name"])
        out.append({
            "seq": len(out) + 1,
            "order_id": f"{'SE' if ship else 'BG'}-{stamp}-{seq[row['action']]:03d}",
            "type": "Bayi" if ship else "Bağış",
            "lot_id": row["lot_id"], "product_code": row["product_code"], "product_name": row["product_name"],
            "expiry_date": row["expiry_date"], "location": row["location"],
            "recipient_id": row["target_id"] if ship else config.DONATION_PARTNER_ID, "recipient_name": name,
            "qty": int(row["qty"]), "order_date": config.AS_OF_DATE.isoformat(), "delivery_date": delivery,
            "status": DRAFT,
            "notification": {
                "status": NOT_SENT, "sent_at": None,
                "title": f"Sevk edildi: {product}" if ship else f"Bağış sevk emri: {product}",
                "body": f"{int(row['qty'])} adet · SKT {tr_date(row['expiry_date'])} · Teslim {tr_date(delivery)}",
            },
        })
    return out


def summarize(orders: list[dict]) -> dict:
    ship = [o for o in orders if o["type"] == "Bayi"]
    don = [o for o in orders if o["type"] == "Bağış"]
    return {"total_orders": len(orders), "ship_orders": len(ship), "ship_qty": sum(o["qty"] for o in ship),
            "donation_orders": len(don), "donation_qty": sum(o["qty"] for o in don),
            "dealers_notified": len({o["recipient_id"] for o in ship}),
            "donation_recipients": sorted({o["recipient_name"] for o in don})}


def _table():
    import boto3
    return boto3.resource("dynamodb", region_name=config.REGION).Table(config.TABLE_ORDERS)


def get_orders(key: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key
    t = _table()
    resp = t.query(KeyConditionExpression=Key("plan_key").eq(key), ConsistentRead=True)
    items = list(resp["Items"])
    while "LastEvaluatedKey" in resp:
        resp = t.query(KeyConditionExpression=Key("plan_key").eq(key), ConsistentRead=True,
                       ExclusiveStartKey=resp["LastEvaluatedKey"])
        items += resp["Items"]
    return sorted((plain(i) for i in items), key=lambda o: o.get("seq", 0))


def find_risky_lot(plan: dict, lot_id: str) -> dict:
    lot = next((l for l in plan["risky"] if l["lot_id"] == lot_id), None)
    if not lot:
        raise ValueError(f"'{lot_id}' bu eşiklerde riskli lotlar arasında değil.")
    return lot


def workflow(plan: dict) -> dict:
    """Per-lot stage (proposal | approved | dispatched) and the merged order list (stored or draft)."""
    key = base_key(plan)
    approvals = list_approvals(plan)
    stored = get_orders(key)
    by_id = {o["order_id"]: o for o in stored}
    orders = [{**by_id[d["order_id"]], "draft": False} if d["order_id"] in by_id else {**d, "draft": True}
              for d in draft_orders(plan)]
    shipped_lots = {o["lot_id"] for o in stored}
    stages = {l["lot_id"]: "dispatched" if l["lot_id"] in shipped_lots
              else ("approved" if l["lot_id"] in approvals else "proposal") for l in plan["risky"]}
    return {"plan_key": key, "approvals": approvals, "stages": stages, "orders": orders,
            "dispatched_summary": summarize(stored)}


def progress(stages: dict[str, str]) -> dict:
    vals = list(stages.values())
    return {"lot_count": len(vals), "dispatched_lots": vals.count("dispatched"),
            "approved_waiting_lots": vals.count("approved"), "pending_lots": vals.count("proposal")}


def create_orders(plan: dict, lot_id: str) -> tuple[list[dict], bool]:
    """Create and store the orders + notifications of ONE approved lot. Returns (orders, created_now)."""
    lot = find_risky_lot(plan, lot_id)
    akey = approval_key(plan, lot_id)
    approval = get_approval_by_key(akey)
    if not approval:
        raise NotApproved(f"'{short_name(lot['product_name'])}' (lot {lot_id}) henüz onaylanmadı. Sevk emri için "
                          "kullanıcının panelde bu lotu seçip 'Onayla' butonuna basması gerekir.")
    key = base_key(plan)
    existing = [o for o in get_orders(key) if o["lot_id"] == lot_id]
    if existing:  # idempotent: never create the same orders twice
        if approval["status"] != DISPATCHED:
            mark_dispatched(akey, len(existing))
        return existing, False
    now = now_iso()
    orders = [o for o in draft_orders(plan) if o["lot_id"] == lot_id]
    for o in orders:
        o.update(plan_key=key, status=SHIPPED, created_at=now, approved_by=approval.get("approved_by", ""))
        o["notification"].update(status=SENT, sent_at=now)
    with _table().batch_writer() as bw:
        for o in orders:
            bw.put_item(Item=o)
    mark_dispatched(akey, len(orders))
    return orders, True


def reset(plan: dict, lot_id: str | None = None) -> dict:
    """Demo reset: delete approvals and orders of one lot, or of the whole plan."""
    key = base_key(plan)
    orders = [o for o in get_orders(key) if lot_id is None or o["lot_id"] == lot_id]
    with _table().batch_writer() as bw:
        for o in orders:
            bw.delete_item(Key={"plan_key": key, "order_id": o["order_id"]})
    lots = [lot_id] if lot_id else list(list_approvals(plan))
    for lid in lots:
        delete_approval(approval_key(plan, lid))
    return {"plan_key": key, "deleted_orders": len(orders), "deleted_approvals": len(lots)}
