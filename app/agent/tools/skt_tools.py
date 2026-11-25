"""TazeRota Strands tools. Thin wrappers over `engine.planner`: every number comes from code."""
from __future__ import annotations

from typing import Optional

from strands import tool

from engine.dispatch import NotApproved, create_orders, draft_orders, progress, short_name, summarize, workflow
from engine.planner import build_plan, daily_demand, find_lot
from engine.loader import get_repository


def _plan(risk_days: Optional[int], early_days: Optional[int]) -> dict:
    return build_plan(risk_days, early_days)


def _err(exc: Exception) -> dict:
    return {"error": str(exc)}


@tool
def get_overview(risk_days: Optional[int] = None, early_days: Optional[int] = None) -> dict:
    """Genel bakış KPI'ları: riskli lot sayısı ve miktarı, bayilere sevk, bağış, imha oranı (TazeRota planı ve
    müdahalesiz senaryo), erken uyarı lot sayısı ve tahmini fazla.

    Args:
        risk_days: Riskli lot eşiği (sakıncalı sevk tarihine kalan gün). Boşsa 60.
        early_days: Erken uyarı eşiği. Boşsa 180.
    """
    try:
        p = _plan(risk_days, early_days)
    except ValueError as exc:
        return _err(exc)
    return {"as_of_date": p["as_of_date"], "warehouse_id": p["warehouse_id"], "risk_days": p["risk_days"],
            "early_days": p["early_days"], **p["kpis"]}


@tool
def analyze_plan(risk_days: Optional[int] = None, early_days: Optional[int] = None) -> dict:
    """TEK ÇAĞRIDA tam analiz: KPI'lar, riskli lotlar (bayi bazında kapasite ve sevk önerisiyle), müdahalesiz senaryo
    ve erken uyarılar. "Riskli lotları analiz et", "öneri ver", "genel durum" gibi geniş sorularda yalnızca bunu çağır.

    Args:
        risk_days: Riskli lot eşiği. Boşsa 60.
        early_days: Erken uyarı eşiği. Boşsa 180.
    """
    try:
        p = _plan(risk_days, early_days)
    except ValueError as exc:
        return _err(exc)
    return {
        "as_of_date": p["as_of_date"], "risk_days": p["risk_days"], "early_days": p["early_days"],
        "kpis": p["kpis"],
        "risky_lots": [{
            **{k: l[k] for k in ("lot_id", "product_name", "risk_qty", "days_to_unsafe", "capacity_total",
                                 "ship_qty", "donate_qty", "dispose_qty", "no_action_disposed", "status")},
            "dealers": [{"dealer_name": d["dealer_name"], "capacity": d["capacity"], "recommended": d["recommended"]}
                        for d in l["dealers"]],
        } for l in p["risky"]],
        "early_warnings": [{k: l[k] for k in ("lot_id", "product_name", "product_group", "quantity", "days_to_unsafe",
                                               "daily_demand", "capacity", "surplus", "days_to_sell_out")}
                           for l in p["early"] if l["surplus"] > 0],
        "early_no_issue_count": p["kpis"]["early_window_no_issue_count"],
        "approval": _approval_state(p),
        "all_orders_if_every_lot_approved": summarize(draft_orders(p)),
    }


def _approval_state(plan: dict) -> dict:
    """Per-lot approval progress (approval is per lot)."""
    try:
        wf = workflow(plan)
    except Exception:  # approval store unavailable: analysis still works
        return {"error": "onay durumu okunamadı"}
    names = {l["lot_id"]: short_name(l["product_name"]) for l in plan["risky"]}
    pending = [lid for lid, st in wf["stages"].items() if st == "proposal"]
    return {**progress(wf["stages"]),
            "dispatched": [f"{names[l]} ({l})" for l, st in wf["stages"].items() if st == "dispatched"],
            "pending_order_count": len([o for o in wf["orders"] if o["lot_id"] in pending])}


def _compact(o: dict) -> dict:
    return {"order_id": o["order_id"], "type": o["type"], "recipient_name": o["recipient_name"],
            "product_name": short_name(o["product_name"]), "lot_id": o["lot_id"], "qty": o["qty"],
            "delivery_date": o["delivery_date"], "status": o["status"],
            "notification": o["notification"]["status"]}


@tool
def create_dispatch_orders(lot: str, risk_days: Optional[int] = None, early_days: Optional[int] = None) -> dict:
    """Onaylanmış TEK bir riskli lotun sevk emirlerini (bayi) ve bağış emrini oluşturur, alıcılara bildirim kaydeder.

    Onay lot bazındadır: YALNIZCA kullanıcı panelde bu lotu seçip 'Onayla'ya bastıktan sonra çalışır; onay yoksa
    hata döner. Tekrar çağrılırsa mevcut emirleri döner, çift emir oluşturmaz. Diğer lotlara dokunmaz.

    Args:
        lot: Lot ID (ör. '75129043-20270106'). Panel mesajındaki lot ID'yi aynen kullan.
        risk_days: Riskli lot eşiği. Boşsa 60.
        early_days: Erken uyarı eşiği. Boşsa 180.
    """
    if not lot or not lot.strip():
        return {"error": "lot boş olamaz."}
    try:
        p = _plan(risk_days, early_days)
        found = find_lot(p, lot)
        if not found or found not in p["risky"]:
            return {"error": f"'{lot}' riskli lotlar arasında bulunamadı."}
        orders, created = create_orders(p, found["lot_id"])
        wf = workflow(p)
    except ValueError as exc:
        return _err(exc)
    except NotApproved as exc:
        return {"error": str(exc), "approved": False}
    return {"lot_id": found["lot_id"], "product_name": found["product_name"], "created_now": created,
            "summary": summarize(orders), "orders": [_compact(o) for o in orders],
            "plan_progress": progress(wf["stages"])}


@tool
def list_dispatch_orders(lot: Optional[str] = None, risk_days: Optional[int] = None,
                         early_days: Optional[int] = None) -> dict:
    """Lot bazında iş akışı durumunu (proposal/approved/dispatched) ve sevk/bağış emirlerini listeler.
    Onaylanmamış lotların emirleri taslaktır (draft=true).

    Args:
        lot: Verilirse yalnızca bu lotun emirleri (lot ID baş kısmı veya ürün adından parça).
        risk_days: Riskli lot eşiği. Boşsa 60.
        early_days: Erken uyarı eşiği. Boşsa 180.
    """
    try:
        p = _plan(risk_days, early_days)
        wf = workflow(p)
    except ValueError as exc:
        return _err(exc)
    orders = wf["orders"]
    if lot and lot.strip():
        found = find_lot(p, lot)
        if not found:
            return {"error": f"'{lot}' riskli lotlar arasında bulunamadı."}
        orders = [o for o in orders if o["lot_id"] == found["lot_id"]]
    return {"progress": progress(wf["stages"]),
            "lot_stages": {l: st for l, st in wf["stages"].items() if not lot or any(o["lot_id"] == l for o in orders)},
            "summary": summarize(orders), "orders": [{**_compact(o), "draft": o["draft"]} for o in orders]}


@tool
def list_risky_lots(risk_days: Optional[int] = None) -> dict:
    """Riskli lotları sevke kalan güne göre sıralı listeler (sevk, bağış, imha miktarları ve durum).

    Args:
        risk_days: Riskli lot eşiği. Boşsa 60.
    """
    try:
        p = _plan(risk_days, None if risk_days is None else max(risk_days, 180))
    except ValueError as exc:
        return _err(exc)
    return {"risk_days": p["risk_days"], "lots": [
        {k: l[k] for k in ("lot_id", "product_name", "risk_qty", "days_to_unsafe", "days_to_expiry", "location",
                           "capacity_total", "ship_qty", "donate_qty", "dispose_qty", "no_action_disposed", "status")}
        for l in p["risky"]]}


@tool
def get_lot_plan(lot: str, risk_days: Optional[int] = None) -> dict:
    """Tek bir lotun bayi bazında planı: 15 günlük satış, stok, kapasite, önerilen sevk; bağış/imha ve gerekçe.
    Erken uyarı lotu ise kapasite ve tahmini fazlayı döner.

    Args:
        lot: Lot ID (veya baş kısmı, ör. '75129043') ya da ürün adından bir parça (ör. 'hindi sosis').
        risk_days: Riskli lot eşiği. Boşsa 60.
    """
    if not lot or not lot.strip():
        return {"error": "lot boş olamaz."}
    try:
        p = _plan(risk_days, None if risk_days is None else max(risk_days, 180))
    except ValueError as exc:
        return _err(exc)
    found = find_lot(p, lot)
    if not found:
        return {"error": f"'{lot}' riskli veya erken uyarı lotları arasında bulunamadı."}
    keys = ("lot_id", "product_code", "product_name", "product_group", "expiry_date", "unsafe_ship_date",
            "days_to_unsafe", "days_to_expiry", "location", "quantity", "donation_eligible", "status")
    out = {k: found[k] for k in keys}
    if "dealers" in found:
        out.update({k: found[k] for k in ("risk_qty", "capacity_total", "ship_qty", "donate_qty", "dispose_qty",
                                          "no_action_disposed", "reason")})
        out["dealers"] = found["dealers"]
        out["formula"] = ("Kapasite = günlük talep × (SKT'ye kalan gün − teslim süresi) − bayi stoğu; "
                          "günlük talep = 0,6 × son 7 gün ort. + 0,4 × 15 gün ort.")
    else:
        out.update({k: found[k] for k in ("daily_demand", "capacity", "surplus", "days_to_sell_out")})
        out["type"] = "erken_uyari"
    return out


@tool
def list_early_warnings(risk_days: Optional[int] = None, early_days: Optional[int] = None) -> dict:
    """Erken uyarı listesi: riskli eşiği ile erken uyarı eşiği arasındaki lotlar, bayilerin günlük talebi,
    SKT'ye kadar satış kapasitesi, tahmini fazla ve stokun kaç günde biteceği.

    Args:
        risk_days: Riskli lot eşiği. Boşsa 60.
        early_days: Erken uyarı eşiği. Boşsa 180.
    """
    try:
        p = _plan(risk_days, early_days)
    except ValueError as exc:
        return _err(exc)
    return {"risk_days": p["risk_days"], "early_days": p["early_days"], "lots": [
        {k: l[k] for k in ("lot_id", "product_name", "product_group", "quantity", "days_to_unsafe", "days_to_expiry",
                           "daily_demand", "capacity", "surplus", "days_to_sell_out", "status")}
        for l in p["early"]]}


@tool
def get_product_demand(product_query: str) -> dict:
    """Bir ürünün bayilerdeki 15 ve 7 günlük satışını, günlük talebini, stoğunu ve teslim süresini gösterir.

    Args:
        product_query: Ürün adından bir parça veya ürün kodu (ör. 'sosis', 'P040').
    """
    q = (product_query or "").strip().lower()
    if not q:
        return {"error": "product_query boş olamaz."}
    repo = get_repository()
    products = {}
    for l in repo.lots():
        if q == l["product_code"].lower() or q in l["product_name"].lower():
            products.setdefault(l["product_code"], l["product_name"])
    if not products:
        return {"error": f"'{product_query}' ile eşleşen ürün bulunamadı."}
    out = []
    for code, name in list(products.items())[:3]:
        rows = []
        for d in repo.dealers():
            s = repo.sales(d["dealer_id"], code)
            rows.append({"dealer_name": d["dealer_name"], "lead_time_days": d["lead_time_days"],
                         "sales_15d": sum(s[-15:]), "sales_7d": sum(s[-7:]),
                         "daily_demand": round(daily_demand(s), 2), "stock": d["stock"].get(code, 0)})
        out.append({"product_code": code, "product_name": name, "dealers": rows})
    return {"products": out}


ALL_TOOLS = [analyze_plan, create_dispatch_orders, list_dispatch_orders, get_overview, list_risky_lots,
             get_lot_plan, list_early_warnings, get_product_demand]
