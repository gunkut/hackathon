"""Data access. Reads lots, dealers (+ stock) and daily sales from DynamoDB.

Each table is scanned once per process and cached (the data set is small).
Tests inject another repository with `set_repository()`.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Protocol

from . import config


def plain(value: Any) -> Any:
    """DynamoDB Decimal -> int/float, recursively."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


class Repository(Protocol):
    def lots(self) -> list[dict]: ...
    def dealers(self) -> list[dict]: ...  # dealer_id, dealer_name, lead_time_days, stock={product_code: qty}
    def sales(self, dealer_id: str, product_code: str) -> list[int]: ...  # oldest -> newest


class DynamoRepository:
    def __init__(self) -> None:
        import boto3  # lazy: keeps runtime cold start light
        self._ddb = boto3.resource("dynamodb", region_name=config.REGION)
        self._lots: list[dict] | None = None
        self._dealers: list[dict] | None = None
        self._sales: dict[tuple[str, str], list[int]] | None = None

    def _scan(self, table: str) -> list[dict]:
        t = self._ddb.Table(table)
        resp = t.scan()
        items = list(resp["Items"])
        while "LastEvaluatedKey" in resp:
            resp = t.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
            items += resp["Items"]
        return [plain(i) for i in items]

    def lots(self) -> list[dict]:
        if self._lots is None:
            self._lots = self._scan(config.TABLE_LOTS)
        return self._lots

    def dealers(self) -> list[dict]:
        if self._dealers is None:
            by_id: dict[str, dict] = {}
            for item in self._scan(config.TABLE_DEALERS):
                d = by_id.setdefault(item["dealer_id"], {"dealer_id": item["dealer_id"], "stock": {}})
                if item["sk"] == "PROFILE":
                    d.update(dealer_name=item["dealer_name"], lead_time_days=int(item["lead_time_days"]))
                else:
                    d["stock"][item["product_code"]] = int(item["on_hand_qty"])
            self._dealers = sorted(by_id.values(), key=lambda d: d["dealer_id"])
        return self._dealers

    def sales(self, dealer_id: str, product_code: str) -> list[int]:
        if self._sales is None:
            grouped: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
            for item in self._scan(config.TABLE_SALES):
                grouped[(item["dealer_id"], item["product_code"])].append((item["sk"], int(item["qty_sold"])))
            self._sales = {k: [q for _, q in sorted(v)] for k, v in grouped.items()}
        return self._sales.get((dealer_id, product_code), [])


_repo: Repository | None = None


def get_repository() -> Repository:
    global _repo
    if _repo is None:
        _repo = DynamoRepository()
    return _repo


def set_repository(repo: Repository | None) -> None:
    """Inject a repository (tests) or reset to the default (None)."""
    global _repo
    _repo = repo
