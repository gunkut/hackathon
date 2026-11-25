"""Read the RAW sheets of data/input/dataa.xlsx.

Raw sheets: Urunler (input columns only), Bayiler, Bayi_Stok, Satis_15G.
Ürün Grubu comes from Satis_ve_Stok (the only non-derived column there).
Derived sheets (Satis_ve_Stok totals, Riskli_Lot_Kontrol, Erken_Uyari) are NOT loaded:
the engine recomputes them, and tests use them as the expected answer.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
DATA_XLSX = ROOT / "data" / "input" / "dataa.xlsx"


def _d(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value).strip(), "%d.%m.%Y").date()


def _rows(wb, name: str) -> list[dict]:
    it = wb[name].iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(it)]
    return [dict(zip(header, r)) for r in it if any(v is not None for v in r)]


def read_workbook(path: Path = DATA_XLSX) -> dict:
    wb = load_workbook(path, data_only=True)

    groups = {r["Ürün Kodu"]: r["Ürün Grubu"] for r in _rows(wb, "Satis_ve_Stok")}

    lots = []
    for r in _rows(wb, "Urunler"):
        expiry = _d(r["SKT"])
        lots.append({
            "lot_id": str(r["Lot ID"]),
            "product_id": str(r["Ürün ID"]),
            "product_code": str(r["Ürün Kodu"]),
            "product_name": " ".join(str(r["Ürün Adı"]).split()),
            "food_type": str(r["Gıda Türü"]),
            "product_group": groups.get(r["Ürün Kodu"], ""),
            "expiry_date": expiry.isoformat(),
            "location": str(r["Adres"]),
            "quantity": int(r["Depo Miktarı"]),
            "unsafe_ship_days": int(r["Sakıncalı Sevk Süresi (gün)"]),
            "donation_eligible": str(r["Bağışa Uygun"]).strip().lower() == "evet",
        })

    dealers = {r["Bayi ID"]: {"dealer_id": r["Bayi ID"], "dealer_name": r["Bayi Adı"],
                              "lead_time_days": int(r["Teslim Süresi (gün)"]), "stock": {}}
               for r in _rows(wb, "Bayiler")}
    for r in _rows(wb, "Bayi_Stok"):
        dealers[r["Bayi ID"]]["stock"][r["Ürün Kodu"]] = int(r["Bayi Stoğu"])

    sales: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for r in _rows(wb, "Satis_15G"):
        sales[(r["Bayi ID"], r["Ürün Kodu"])].append((_d(r["Tarih"]).isoformat(), int(r["Satış Adedi"])))
    for key in sales:
        sales[key].sort()

    return {"lots": lots, "dealers": sorted(dealers.values(), key=lambda d: d["dealer_id"]),
            "sales": dict(sales)}


def read_expected(path: Path = DATA_XLSX) -> dict:
    """Derived sheets, used only as the expected answer in tests."""
    wb = load_workbook(path, data_only=True)
    risky = [r for r in _rows(wb, "Riskli_Lot_Kontrol") if r.get("Ürün Adı") and r.get("Riskli Miktar") is not None
             and str(r["Lot ID"]) != "TOPLAM"]
    total = next(r for r in _rows(wb, "Riskli_Lot_Kontrol") if str(r["Lot ID"]) == "TOPLAM")
    early = [r for r in _rows(wb, "Erken_Uyari") if r.get("Ürün Adı")]
    return {"risky": risky, "risky_total": total, "early": early}


class ExcelRepository:
    """Repository backed by the workbook (tests and offline use)."""

    def __init__(self, path: Path = DATA_XLSX) -> None:
        self._data = read_workbook(path)

    def lots(self) -> list[dict]:
        return self._data["lots"]

    def dealers(self) -> list[dict]:
        return self._data["dealers"]

    def sales(self, dealer_id: str, product_code: str) -> list[int]:
        return [q for _, q in self._data["sales"].get((dealer_id, product_code), [])]
