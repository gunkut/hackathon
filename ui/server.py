"""TazeRota demo panel server.

Panels (KPIs, risky lots, lot detail, early warning, reports) come straight from the deterministic
engine. The chat panel streams answers from the TazeRota agent:
  CHAT_MODE=runtime (default): the deployed AgentCore runtime (AGENT_RUNTIME_ARN, else `agentcore status`)
  CHAT_MODE=local:             an in-process agent with the same tools (fallback if the runtime is down)

Run:  cd app/agent && uv run python ../../ui/server.py      (port: UI_PORT, default 8090)
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "app" / "agent"
sys.path.insert(0, str(AGENT_DIR))

import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from engine import config  # noqa: E402
from engine.approvals import approve_lot  # noqa: E402
from engine.dispatch import draft_orders, find_risky_lot, progress, reset, summarize, workflow  # noqa: E402
from engine.planner import PLAN_CSV_FIELDS, build_plan, plan_rows  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
CHAT_MODE = os.getenv("CHAT_MODE", "runtime")
app = FastAPI(title="TazeRota")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# Optional password gate for the public deployment (enabled when PANEL_PASSWORD is set).
# A login page sets an HttpOnly cookie. (HTTP Basic Auth is not used: Lambda Function URLs rename the
# WWW-Authenticate header, so browsers would never show the login prompt.)
PANEL_USER = os.getenv("PANEL_USER", "tazerota")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD")
AUTH_COOKIE = "tazerota_auth"
LOGIN_HTML = """<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width, initial-scale=1"><title>TazeRota · Giriş</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f3f2fa;font:15px system-ui,sans-serif;color:#1c1b2e}
form{background:#fff;padding:32px;border-radius:18px;box-shadow:0 6px 24px rgba(40,30,90,.08);width:320px}
h1{font-size:22px;margin:0 0 4px}p{color:#7a7891;margin:0 0 18px}
input{width:100%;box-sizing:border-box;border:1px solid #e3e1ee;border-radius:12px;padding:11px 14px;margin-bottom:12px;font:inherit}
button{width:100%;border:0;border-radius:999px;padding:11px;font-weight:700;color:#fff;cursor:pointer;
background:linear-gradient(90deg,#6d28d9,#c026d3);font:inherit;font-weight:700}.err{color:#dc2626;font-size:13px}
</style></head><body><form method="post" action="login"><h1>TazeRota</h1><p>SKT Kurtarma Paneli</p>
__ERR__<input type="password" name="password" placeholder="Şifre" autofocus required><button>Giriş</button></form></body></html>"""

if PANEL_PASSWORD:
    import hashlib
    import secrets
    from urllib.parse import parse_qs

    from fastapi import Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    _token = hashlib.sha256(f"tazerota:{PANEL_USER}:{PANEL_PASSWORD}".encode()).hexdigest()

    class _PasswordGate(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path
            if path in ("/healthz", "/login") or secrets.compare_digest(
                    request.cookies.get(AUTH_COOKIE, ""), _token):
                return await call_next(request)
            if path == "/":
                return HTMLResponse(LOGIN_HTML.replace("__ERR__", ""))
            return JSONResponse({"detail": "Giriş gerekli"}, status_code=401)

    app.add_middleware(_PasswordGate)

    @app.post("/login")
    async def login(request: Request):
        form = parse_qs((await request.body()).decode("utf-8", "replace"))
        if not secrets.compare_digest(form.get("password", [""])[0], PANEL_PASSWORD):
            return HTMLResponse(LOGIN_HTML.replace("__ERR__", '<p class="err">Şifre hatalı.</p>'), status_code=401)
        resp = RedirectResponse("./", status_code=303)
        resp.set_cookie(AUTH_COOKIE, _token, max_age=7 * 24 * 3600, httponly=True, secure=True, samesite="lax")
        return resp


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


def _plan(risk: int | None, early: int | None) -> dict:
    try:
        return build_plan(risk, early)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/plan")
def api_plan(risk: int | None = None, early: int | None = None) -> JSONResponse:
    plan = _plan(risk, early)
    try:
        wf = workflow(plan)
    except Exception as exc:  # workflow tables unavailable: panel still shows the proposal
        wf = {"approvals": {}, "stages": {l["lot_id"]: "proposal" for l in plan["risky"]},
              "orders": [{**o, "draft": True} for o in draft_orders(plan)], "dispatched_summary": summarize([])}
        plan["approval_error"] = str(exc)
    plan.update(lot_stages=wf["stages"], approvals=wf["approvals"], orders=wf["orders"],
                order_summary=summarize(wf["orders"]), dispatched_summary=wf["dispatched_summary"],
                progress=progress(wf["stages"]), chat_mode=CHAT_MODE)
    return JSONResponse(plan)


class PlanIn(BaseModel):
    risk: int | None = None
    early: int | None = None


class LotIn(PlanIn):
    lot_id: str = Field(min_length=1, max_length=60)


class ApproveIn(LotIn):
    approved_by: str = Field(default="planlama", max_length=60)


class ResetIn(PlanIn):
    lot_id: str | None = Field(default=None, max_length=60)


@app.post("/api/approve")
def api_approve(body: ApproveIn) -> dict:
    """Human approval of ONE lot. Its orders are created afterwards by the agent (create_dispatch_orders)."""
    plan = _plan(body.risk, body.early)
    try:
        lot = find_risky_lot(plan, body.lot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return approve_lot(plan, lot, body.approved_by)


@app.post("/api/reset")
def api_reset(body: ResetIn) -> dict:
    """Demo reset: delete approvals, orders and notifications of one lot (lot_id) or of all lots."""
    return reset(_plan(body.risk, body.early), body.lot_id)


@app.get("/api/export/recommendations.csv")
def export_csv(risk: int | None = None, early: int | None = None) -> Response:
    plan = _plan(risk, early)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=PLAN_CSV_FIELDS)
    w.writeheader()
    w.writerows(plan_rows(plan))
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=tazerota_oneriler.csv"})


@app.get("/api/export/plan.json")
def export_json(risk: int | None = None, early: int | None = None) -> Response:
    plan = _plan(risk, early)
    body = {"as_of_date": plan["as_of_date"], "risk_days": plan["risk_days"], "early_days": plan["early_days"],
            "kpis": plan["kpis"], "recommendations": plan_rows(plan),
            "early_warning": [{k: l[k] for k in ("lot_id", "product_name", "quantity", "days_to_unsafe",
                                                 "daily_demand", "capacity", "surplus", "status")}
                              for l in plan["early"]]}
    return Response(json.dumps(body, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=tazerota_plan.json"})


# ---------------------------------------------------------------- chat
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(min_length=33, max_length=100)
    risk: int | None = None
    early: int | None = None


_runtime_arn: str | None = os.getenv("AGENT_RUNTIME_ARN")


def runtime_arn() -> str:
    global _runtime_arn
    if not _runtime_arn:
        out = subprocess.run(["agentcore", "status", "--json"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        status = json.loads(out.stdout[out.stdout.index("{"):])
        _runtime_arn = next(r["arn"] for r in status["resources"] if r["resourceType"] == "runtime")
    return _runtime_arn


# Chat stream = NDJSON lines: {"t":"status","text":...} while tools run, {"t":"text","text":...} answer deltas.
TOOL_STATUS = {
    "analyze_plan": "Plan ve KPI'lar hesaplanıyor…",
    "get_overview": "Genel bakış alınıyor…",
    "list_risky_lots": "Riskli lotlar listeleniyor…",
    "get_lot_plan": "Lot planı inceleniyor…",
    "list_early_warnings": "Erken uyarılar kontrol ediliyor…",
    "get_product_demand": "Bayi satışları inceleniyor…",
    "create_dispatch_orders": "Sevk emirleri oluşturuluyor, bildirimler gönderiliyor…",
    "list_dispatch_orders": "Sevk emirleri inceleniyor…",
}
STREAM_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def _line(kind: str, text: str) -> str:
    return json.dumps({"t": kind, "text": text}, ensure_ascii=False) + "\n"


def _status_for(tool_name: str) -> str:
    return TOOL_STATUS.get(tool_name, "Veri inceleniyor…")


def _events_from_sse(lines):
    for raw in lines:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
        if not line.startswith("data:"):
            continue
        try:
            data = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if "error" in data:
            yield _line("text", f"\n\n⚠️ Ajan hatası: {data['error']}")
            continue
        ev = data.get("event", {})
        tool_use = ev.get("contentBlockStart", {}).get("start", {}).get("toolUse")
        if tool_use:
            yield _line("status", _status_for(tool_use.get("name", "")))
            continue
        text = ev.get("contentBlockDelta", {}).get("delta", {}).get("text")
        if text:
            yield _line("text", text)


def _chat_runtime(prompt: str, session_id: str):
    import boto3
    client = boto3.client("bedrock-agentcore", region_name=config.REGION)
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn(), runtimeSessionId=session_id, qualifier="DEFAULT",
        payload=json.dumps({"prompt": prompt, "actorId": "tazerota-panel"}).encode("utf-8"))
    # chunk_size=1: hand every line to the browser as soon as it arrives
    yield from _events_from_sse(resp["response"].iter_lines(chunk_size=1))


async def _chat_local(prompt: str, session_id: str):
    from main import _get_agent  # same agent, tools and prompt as the runtime
    seen: set[str] = set()
    async for event in _get_agent(session_id, "tazerota-panel").stream_async(prompt):
        if not isinstance(event, dict):
            continue
        tool = event.get("current_tool_use")
        if isinstance(tool, dict) and tool.get("toolUseId") and tool["toolUseId"] not in seen:
            seen.add(tool["toolUseId"])
            yield _line("status", _status_for(tool.get("name", "")))
        elif isinstance(event.get("data"), str):
            yield _line("text", event["data"])


@app.post("/api/chat")
def api_chat(body: ChatIn) -> StreamingResponse:
    risk = config.RISK_DAYS if body.risk is None else body.risk
    early = config.EARLY_DAYS if body.early is None else body.early
    prompt = f"[Panel eşikleri: riskli ≤{risk} gün, erken uyarı ≤{early} gün]\n{body.message}"

    if CHAT_MODE == "local":
        async def gen():
            yield _line("status", "Ajan düşünüyor…")
            try:
                async for chunk in _chat_local(prompt, body.session_id):
                    yield chunk
            except Exception as exc:
                yield _line("text", f"⚠️ Ajan hatası: {exc}")
    else:
        def gen():
            yield _line("status", "Ajan düşünüyor…")
            try:
                yield from _chat_runtime(prompt, body.session_id)
            except Exception as exc:
                yield _line("text", f"⚠️ Ajana ulaşılamadı: {exc}")
    return StreamingResponse(gen(), media_type="application/x-ndjson; charset=utf-8", headers=STREAM_HEADERS)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("UI_PORT", "8090")))
