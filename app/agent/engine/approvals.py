"""Lot approvals (tazerota-approvals). Human in the loop: only the panel button approves, one lot at a time.

Key: plan_key = "<as_of>|r<risk>|e<early>#<lot_id>". Status: APPROVED -> DISPATCHED.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import config
from .loader import plain

APPROVED, DISPATCHED = "APPROVED", "DISPATCHED"


def plan_key(risk_days: int, early_days: int) -> str:
    return f"{config.AS_OF_DATE.isoformat()}|r{risk_days}|e{early_days}"


def base_key(plan: dict) -> str:
    return plan_key(plan["risk_days"], plan["early_days"])


def approval_key(plan: dict, lot_id: str) -> str:
    return f"{base_key(plan)}#{lot_id}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table():
    import boto3
    return boto3.resource("dynamodb", region_name=config.REGION).Table(config.TABLE_APPROVALS)


def _clean(item: dict) -> dict:
    item = plain(item)
    item.setdefault("status", APPROVED)
    return item


def get_approval_by_key(key: str) -> dict | None:
    item = _table().get_item(Key={"plan_key": key}, ConsistentRead=True).get("Item")
    return _clean(item) if item else None


def list_approvals(plan: dict) -> dict[str, dict]:
    """All lot approvals of this plan, by lot_id."""
    from boto3.dynamodb.conditions import Attr
    t = _table()
    kwargs = {"FilterExpression": Attr("plan_key").begins_with(base_key(plan) + "#"), "ConsistentRead": True}
    resp = t.scan(**kwargs)
    items = list(resp["Items"])
    while "LastEvaluatedKey" in resp:
        resp = t.scan(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
        items += resp["Items"]
    return {i["lot_id"]: _clean(i) for i in items if "lot_id" in i}


def approve_lot(plan: dict, lot: dict, approved_by: str) -> dict:
    """Record the human approval of one lot. Idempotent: an existing approval is returned unchanged."""
    from botocore.exceptions import ClientError

    item = {
        "plan_key": approval_key(plan, lot["lot_id"]), "lot_id": lot["lot_id"],
        "product_name": lot["product_name"], "status": APPROVED,
        "approved_at": now_iso(), "approved_by": approved_by or "planlama",
        "risk_qty": lot["risk_qty"], "ship_qty": lot["ship_qty"], "donate_qty": lot["donate_qty"],
        "dispose_qty": lot["dispose_qty"],
    }
    try:
        _table().put_item(Item=item, ConditionExpression="attribute_not_exists(plan_key)")
        return item
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return get_approval_by_key(item["plan_key"])


def mark_dispatched(key: str, order_count: int) -> None:
    _table().update_item(
        Key={"plan_key": key},
        UpdateExpression="SET #s = :s, dispatched_at = :t, order_count = :n",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": DISPATCHED, ":t": now_iso(), ":n": order_count})


def delete_approval(key: str) -> None:
    _table().delete_item(Key={"plan_key": key})
