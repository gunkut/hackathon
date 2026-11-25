"""Golden tests: the engine, fed with the RAW sheets of dataa.xlsx, must reproduce the
derived sheets Riskli_Lot_Kontrol and Erken_Uyari. No AWS calls."""
import re

import pytest

from engine.loader import set_repository
from engine.planner import build_plan, find_lot, plan_rows
from excel_source import ExcelRepository, read_expected


@pytest.fixture(scope="module")
def expected():
    return read_expected()


@pytest.fixture(scope="module")
def plan():
    set_repository(ExcelRepository())
    yield build_plan()
    set_repository(None)


def _dist(text: str) -> dict[str, int]:
    return {m.group(1).strip(): int(m.group(2)) for m in re.finditer(r"([^,]+?)\s+(\d+)(?:,|$)", text or "")}


def test_risky_lot_set_matches(plan, expected):
    assert [l["lot_id"] for l in plan["risky"]] == [str(r["Lot ID"]) for r in expected["risky"]]


def test_each_risky_lot_matches_sheet(plan, expected):
    by_id = {l["lot_id"]: l for l in plan["risky"]}
    for r in expected["risky"]:
        lot = by_id[str(r["Lot ID"])]
        assert lot["risk_qty"] == r["Riskli Miktar"]
        assert lot["days_to_unsafe"] == r["Sakıncalı Sevke Kalan Gün"]
        assert lot["days_to_expiry"] == r["SKT'ye Kalan Gün"]
        assert lot["capacity_total"] == r["Bayilerin Tahmini Satış Kapasitesi"], lot["lot_id"]
        assert lot["ship_qty"] == r["Bayilere Sevk"], lot["lot_id"]
        assert lot["donate_qty"] == r["Bağış"], lot["lot_id"]
        assert lot["no_action_disposed"] == r["Müdahalesiz İmha"], lot["lot_id"]
        got = {d["dealer_name"]: d["recommended"] for d in lot["dealers"] if d["recommended"]}
        assert got == _dist(r["Bayi Dağılımı"]), lot["lot_id"]


def test_totals_and_kpis(plan, expected):
    k, t = plan["kpis"], expected["risky_total"]
    assert (k["risky_qty"], k["shipped"], k["donated"], k["no_action_disposed"]) == (
        t["Riskli Miktar"], t["Bayilere Sevk"], t["Bağış"], t["Müdahalesiz İmha"])
    assert k["disposed"] == 0
    assert k["no_action_disposal_rate_pct"] == 15.6
    # Accepted rounding difference: sheet total is 274.
    assert k["early_warning_lot_count"] == 3 and abs(k["early_warning_surplus"] - 274) <= 3


def test_sum_qty_equals_risk_qty(plan):
    rows = plan_rows(plan)
    for lot in plan["risky"]:
        assert sum(r["qty"] for r in rows if r["lot_id"] == lot["lot_id"]) == lot["risk_qty"]


def test_early_warning_matches_sheet(plan, expected):
    by_id = {l["lot_id"]: l for l in plan["early"]}
    assert set(by_id) == {str(r["Lot ID"]) for r in expected["early"]}
    for r in expected["early"]:
        lot = by_id[str(r["Lot ID"])]
        # Accepted: the sheet's capacity rounding differs by up to 2 units (and so the surplus).
        assert abs(lot["surplus"] - r["Tahmini Fazla"]) <= 2, lot["lot_id"]
        assert lot["status"] == r["Durum"], lot["lot_id"]
        assert lot["days_to_sell_out"] == r["Stok Kaç Günde Biter"], lot["lot_id"]
        assert lot["daily_demand"] == pytest.approx(r["Bayilerin Günlük Talebi"], abs=0.01)
        # Accepted: the sheet's capacity rounding differs by up to 2 units.
        assert abs(lot["capacity"] - r["Bayilerin SKT'ye Kadar Satış Kapasitesi"]) <= 2, lot["lot_id"]


def test_screenshot_detail_pinar_hindi(plan):
    lot = find_lot(plan, "75129043")
    caps = {d["dealer_name"]: (d["sales_15d"], d["stock"], d["capacity"], d["recommended"]) for d in lot["dealers"]}
    assert caps == {"Çınar Bayi": (11, 4, 25, 25), "Yıldız Bayi": (8, 1, 18, 18), "Lale Bayi": (4, 2, 9, 9),
                    "Mavi Bayi": (6, 0, 9, 9), "Ege Bayi": (2, 1, 4, 4)}
    assert (lot["ship_qty"], lot["donate_qty"], lot["status"]) == (65, 19, "Kısmi bağış")


def test_thresholds_change_plan():
    set_repository(ExcelRepository())
    try:
        wide = build_plan(risk_days=120, early_days=180)
        assert wide["kpis"]["risky_lot_count"] > 6
        with pytest.raises(ValueError):
            build_plan(risk_days=200, early_days=100)
    finally:
        set_repository(None)


def test_draft_orders_match_mock(plan):
    from engine.dispatch import draft_orders, summarize
    set_repository(ExcelRepository())
    try:
        orders = draft_orders(plan)
    finally:
        set_repository(None)
    s = summarize(orders)
    assert (s["ship_orders"], s["ship_qty"], s["donation_orders"], s["donation_qty"], s["dealers_notified"]) == (
        22, 885, 4, 82, 5)
    hindi = [(o["order_id"], o["recipient_name"], o["qty"]) for o in orders if o["lot_id"] == "75129043-20270106"]
    assert hindi == [("SE-20261125-009", "Çınar Bayi", 25), ("SE-20261125-010", "Yıldız Bayi", 18),
                     ("SE-20261125-011", "Lale Bayi", 9), ("SE-20261125-012", "Mavi Bayi", 9),
                     ("SE-20261125-013", "Ege Bayi", 4), ("BG-20261125-003", "Umut Gıda Bankası", 19)]
    first = next(o for o in orders if o["order_id"] == "SE-20261125-009")
    assert first["delivery_date"] == "2026-11-26" and first["notification"]["title"] == "Sevk edildi: Pınar Hindi Uzun Sosis"
    # every lot's orders add up to its shipped + donated quantity
    for lot in plan["risky"]:
        assert sum(o["qty"] for o in orders if o["lot_id"] == lot["lot_id"]) == lot["ship_qty"] + lot["donate_qty"]
