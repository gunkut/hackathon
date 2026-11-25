"use strict";

const dispatchMsg = (lot) => `${shortName(lot.product_name)} (lot ${lot.lot_id}) sevki onaylandı. Bu lotun sevk emirlerini oluştur ve bildir.`;
// A fresh agent session per page load: an AgentCore session stays on the runtime version it started on,
// so a reload after `agentcore deploy` must not reuse an old session.
const state = { plan: null, risk: 60, early: 180, selected: null, selectedOrder: null, view: "overview", busy: false,
  sessionId: "tazerota-panel-" + crypto.randomUUID() };

const $ = (id) => document.getElementById(id);
const nf = new Intl.NumberFormat("tr-TR");
const n = (x) => nf.format(x);
const pct = (x) => "%" + String(x).replace(".", ",");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const shortName = (s) => String(s).replace(/\s*\([^)]*\)\s*$/, "");
const trDate = (iso) => iso.split("-").reverse().join(".");
const trTime = (iso) => iso ? new Date(iso).toLocaleString("tr-TR", { dateStyle: "short", timeStyle: "short" }) : "–";
const statusChip = (s) => {
  const cls = ["Sorun yok", "Sorun beklenmiyor", "Sevk edildi", "Gönderildi"].includes(s) ? "chip-green"
    : s === "Onaylandı" ? "chip-purple"
    : s.includes("mha") ? "chip-red" : ["Bekliyor", "Taslak", "Gönderilmedi"].includes(s) ? "chip-gray" : "chip-orange";
  return `<span class="chip ${cls}">${esc(s)}${s === "Gönderildi" ? " ✓" : ""}</span>`;
};
const typeChip = (t) => `<span class="chip ${t === "Bayi" ? "chip-purple" : "chip-orange"} chip-sm">${esc(t)}</span>`;
// Approval is per lot: proposal | approved | dispatched
const lotStage = (lotId) => (state.plan.lot_stages || {})[lotId] || "proposal";
const selectedLot = () => state.plan.risky.find((l) => l.lot_id === state.selected);

// ------------------------------------------------------------------ data
async function loadPlan() {
  const res = await fetch(`api/plan?risk=${state.risk}&early=${state.early}`);
  if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
  state.plan = await res.json();
  const ids = state.plan.risky.map((l) => l.lot_id);
  if (!ids.includes(state.selected)) {
    const pick = state.plan.risky.find((l) => l.donate_qty > 0 && l.days_to_unsafe > 30) || state.plan.risky[0];
    state.selected = pick ? pick.lot_id : null;
    state.selectedOrder = null;
  }
  render();
}

// ------------------------------------------------------------------ render
function render() {
  const p = state.plan, k = p.kpis, s = p.order_summary, d = p.dispatched_summary;
  $("meta").textContent = `${trDate(p.as_of_date)} · Takım Wakanda`;
  $("k-risky").textContent = n(k.risky_lot_count);
  $("k-risky-sub").textContent = `${n(k.risky_qty)} adet · sevke ≤ ${p.risk_days} gün`;
  $("k-ship").textContent = n(k.shipped);
  $("k-ship-sub").textContent = d.ship_orders ? `${n(d.ship_orders)}/${n(s.ship_orders)} sevk emri · bildirildi`
    : `adet · riskli miktarın ${pct(k.shipped_pct)}'i`;
  $("k-donate").textContent = n(k.donated);
  $("k-donate-sub").textContent = d.donation_orders ? `${n(d.donation_orders)}/${n(s.donation_orders)} bağış emri · bildirildi`
    : `adet · ${pct(k.donated_pct)} · onay bekliyor`;
  $("k-dispose").textContent = pct(k.disposal_rate_pct);
  $("k-dispose-sub").textContent = `müdahalesiz senaryoda ${pct(k.no_action_disposal_rate_pct)}`;
  $("k-early").textContent = `${n(k.early_warning_lot_count)} lot`;
  $("k-early-sub").textContent = `~${n(k.early_warning_surplus)} adet fazla · ${p.early_days} gün`;
  $("early-title").textContent = `Erken uyarı · ${p.early_days} gün`;

  renderRiskyList();
  renderEarlyList();
  renderDetail();
  renderRiskyTable();
  renderOrdersTable();
  renderNotifyTable();
  renderEarlyTable();
  renderReports();
  renderPlanBox();
}

function lotStatus(l) {
  const st = lotStage(l.lot_id);
  return st === "dispatched" ? "Sevk edildi" : st === "approved" ? "Onaylandı" : l.status;
}

function renderRiskyList() {
  $("risky-list").innerHTML = state.plan.risky.map((l) => `
    <tr data-lot="${esc(l.lot_id)}" class="${l.lot_id === state.selected ? "selected" : ""}">
      <td class="name" title="${esc(l.product_name)}">${esc(shortName(l.product_name))}</td>
      <td class="num">${n(l.risk_qty)}</td>
      <td class="num ${l.days_to_unsafe <= 14 ? "day-hot" : ""}">${l.days_to_unsafe}</td>
      <td>${statusChip(lotStatus(l))}</td></tr>`).join("")
    || `<tr><td colspan="4" class="empty">Bu eşikte riskli lot yok.</td></tr>`;
}

function renderEarlyList() {
  const warn = state.plan.early.filter((l) => l.surplus > 0);
  $("early-list").innerHTML = warn.map((l) => `
    <div class="early-row" title="${esc(l.product_name)}" data-ask="${esc(shortName(l.product_name))} için erken uyarı önerin nedir?">
      <span class="name">${esc(shortName(l.product_name))}</span>
      <span class="qty">${n(l.quantity)} adet</span>
      <span class="chip chip-orange">~${n(l.surplus)}</span></div>`).join("")
    || `<div class="empty">Tahmini fazla olan lot yok.</div>`;
}

function renderDetail() {
  const lot = state.plan.risky.find((l) => l.lot_id === state.selected);
  if (!lot) {
    $("d-title").textContent = "Lot seçin";
    ["d-chip", "d-sub", "d-qty", "d-note", "flow-hint"].forEach((id) => { $(id).textContent = ""; });
    ["d-dealers", "d-dist", "stepper", "o-rows", "o-card", "n-card"].forEach((id) => { $(id).innerHTML = ""; });
    return;
  }
  $("d-title").textContent = lot.product_name;
  $("d-chip").textContent = `Sevke ${lot.days_to_unsafe} gün`;
  $("d-sub").textContent = `Lot ${lot.lot_id} · ${n(lot.risk_qty)} adet · SKT ${trDate(lot.expiry_date)} · Raf ${lot.location}`;
  const maxSales = Math.max(1, ...lot.dealers.map((d) => d.sales_15d));
  const topCap = Math.max(...lot.dealers.map((d) => d.capacity));
  $("d-dealers").innerHTML = lot.dealers.map((d) => `
    <tr><td>${esc(d.dealer_name)}</td>
      <td><div class="bar-cell"><span class="bar ${d.capacity === topCap && topCap > 0 ? "top" : ""}" style="width:${Math.round(110 * d.sales_15d / maxSales)}px"></span><b>${d.sales_15d}</b></div></td>
      <td class="num">${d.stock}</td><td class="num">${d.capacity}</td>
      <td class="num">${d.recommended ? `<span class="chip chip-purple">${d.recommended} adet</span>` : `<span class="chip chip-gray">–</span>`}</td></tr>`).join("");
  $("d-qty").textContent = `${n(lot.risk_qty)} adet`;
  const seg = (cls, label, q) => q ? `<div class="seg ${cls}" style="flex:${Math.max(q, lot.risk_qty * 0.12)}">${label} · ${n(q)}</div>` : "";
  $("d-dist").innerHTML = seg("ship", "Bayilere sevk", lot.ship_qty) + seg("donate", "Bağış", lot.donate_qty) + seg("dispose", "İmha", lot.dispose_qty);
  const rest = lot.risk_qty - lot.ship_qty;
  $("d-note").textContent = "Kapasite = günlük talep × (SKT'ye kalan gün − teslim süresi) − bayi stoğu. " +
    `Bayilerin toplam kapasitesi ${n(lot.capacity_total)} adet` +
    (rest > 0 ? `; kalan ${n(rest)} adet ${lot.donate_qty ? "bağışa önerilir" : "imha edilir"}.` : "; lotun tamamı bayilere sevk edilir.") +
    ` İmha: ${n(lot.dispose_qty)}.`;
  renderFlow(lot);
}

function renderFlow(lot) {
  const p = state.plan, st = lotStage(lot.lot_id);
  const working = st === "approved" && state.busy;
  const steps = [
    { label: "Öneri", done: true },
    { label: st === "proposal" ? "Onay bekliyor" : "Onaylandı", done: st !== "proposal" },
    { label: "Sevk emri", done: st === "dispatched" },
    { label: "Bildirim", done: st === "dispatched" },
  ];
  const current = steps.findIndex((s) => !s.done);
  $("stepper").innerHTML = steps.map((s, i) => `
    <li class="step ${s.done ? "done" : ""} ${i === current ? "current" : ""} ${i === current && working ? "working" : ""}">
      <span class="circle">${s.done ? "✓" : i + 1}</span><span class="label">${s.label}</span></li>`).join("");

  const orders = p.orders.filter((o) => o.lot_id === lot.lot_id);
  const draft = orders.some((o) => o.draft);
  const total = orders.length;
  $("flow-hint").textContent = st === "dispatched" ? `${n(total)} emir oluşturuldu · bildirimler gönderildi`
    : st === "approved" ? (working ? "Ajan sevk emirlerini oluşturuyor…" : "Onaylandı · sevk emirleri bekleniyor")
    : `Onaydan sonra ${n(total)} emir oluşturulur`;
  if (!orders.length) {
    $("o-rows").innerHTML = `<tr><td colspan="5" class="empty">Bu lot için sevk emri yok.</td></tr>`;
    $("o-card").innerHTML = ""; $("n-card").innerHTML = "";
    return;
  }
  if (!orders.some((o) => o.order_id === state.selectedOrder)) state.selectedOrder = orders[0].order_id;
  $("o-rows").innerHTML = orders.map((o) => `
    <tr data-order="${esc(o.order_id)}" class="${o.order_id === state.selectedOrder ? "selected" : ""}">
      <td>${draft ? `<i class="muted">Taslak</i>` : `<b>${esc(o.order_id)}</b>`}</td>
      <td><b>${esc(o.recipient_name)}</b></td><td>${typeChip(o.type)}</td>
      <td class="num"><b>${n(o.qty)}</b></td><td>${statusChip(draft ? "Bekliyor" : o.status)}</td></tr>`).join("");

  const o = orders.find((x) => x.order_id === state.selectedOrder);
  const don = orders.find((x) => x.type === "Bağış");
  $("o-card").innerHTML = `
    <div class="card-head"><span class="muted small">${o.type === "Bayi" ? "Sevk emri" : "Bağış emri"}</span>
      ${statusChip(draft ? "Taslak" : o.status)}</div>
    <div class="order-no">${draft ? "No onayda atanır" : esc(o.order_id)}</div>
    <dl><dt>Sipariş</dt><dd>${trDate(o.order_date)}</dd><dt>Miktar</dt><dd>${n(o.qty)} adet</dd>
      <dt>Alıcı</dt><dd>${esc(o.recipient_name)}</dd><dt>Teslim</dt><dd>${trDate(o.delivery_date)}</dd></dl>`;
  const nt = o.notification;
  $("n-card").innerHTML = `
    <div class="card-head"><span class="small purple strong">Bildirim · ${esc(o.recipient_name)}</span>
      <span class="chip ${draft ? "chip-white" : "chip-green"}">${draft ? "Gönderilmedi" : "Gönderildi ✓"}</span></div>
    <div class="n-title">${esc(nt.title)}</div>
    <div class="n-body">${draft ? "Onaydan sonra gönderilir · " : esc(o.order_id) + " · "}${esc(nt.body)}</div>
    ${don && o.type === "Bayi" ? `<div class="n-donation">Bağış: ${draft ? `${n(don.qty)} adet` : esc(don.order_id)} → ${esc(don.recipient_name)}${draft ? "" : " ✓"}</div>` : ""}`;
}

function renderRiskyTable() {
  const p = state.plan;
  $("risky-scope").textContent = `sakıncalı sevke ≤ ${p.risk_days} gün kalan ${p.risky.length} lot`;
  $("risky-table").innerHTML = p.risky.map((l) => `
    <tr><td>${esc(l.lot_id)}</td><td>${esc(l.product_name)}</td><td>${esc(l.location)}</td><td>${trDate(l.expiry_date)}</td>
    <td class="num ${l.days_to_unsafe <= 14 ? "day-hot" : ""}">${l.days_to_unsafe}</td><td class="num">${n(l.risk_qty)}</td>
    <td class="num">${n(l.capacity_total)}</td><td class="num">${n(l.ship_qty)}</td><td class="num">${n(l.donate_qty)}</td>
    <td class="num">${n(l.dispose_qty)}</td><td class="num">${n(l.no_action_disposed)}</td><td>${statusChip(lotStatus(l))}</td></tr>`).join("")
    || `<tr><td colspan="12" class="empty">Riskli lot yok.</td></tr>`;
}

function renderOrdersTable() {
  const p = state.plan, s = p.order_summary, d = p.dispatched_summary, g = p.progress;
  $("orders-scope").textContent = `${n(s.ship_orders)} bayi sevk emri (${n(s.ship_qty)} adet) · ${n(s.donation_orders)} bağış emri (${n(s.donation_qty)} adet)` +
    ` · ${n(d.total_orders)} emir sevk edildi (${n(g.dispatched_lots)}/${n(g.lot_count)} lot), kalanı onay bekliyor`;
  $("orders-table").innerHTML = p.orders.map((o) => `
    <tr><td>${o.draft ? `<i class="muted">Taslak</i>` : `<b>${esc(o.order_id)}</b>`}</td><td>${esc(o.lot_id)}</td>
    <td>${esc(shortName(o.product_name))}</td><td>${esc(o.recipient_name)}</td><td>${typeChip(o.type)}</td>
    <td class="num">${n(o.qty)}</td><td>${trDate(o.order_date)}</td><td>${trDate(o.delivery_date)}</td>
    <td>${esc(o.location)}</td><td>${statusChip(o.draft ? "Bekliyor" : o.status)}</td></tr>`).join("")
    || `<tr><td colspan="10" class="empty">Sevk emri yok.</td></tr>`;
}

function renderNotifyTable() {
  const p = state.plan, s = p.order_summary, d = p.dispatched_summary;
  $("notify-scope").textContent = `${n(d.total_orders)} bildirim gönderildi · ${n(s.total_orders - d.total_orders)} bildirim lot onayından sonra gönderilir`;
  $("notify-table").innerHTML = p.orders.map((o) => { const draft = o.draft; return `
    <tr><td><b>${esc(o.recipient_name)}</b></td><td>${esc(o.notification.title)}</td>
    <td>${draft ? "Onaydan sonra gönderilir · " : esc(o.order_id) + " · "}${esc(o.notification.body)}</td>
    <td>${trTime(o.notification.sent_at)}</td><td>${statusChip(o.notification.status)}</td></tr>`; }).join("")
    || `<tr><td colspan="5" class="empty">Bildirim yok.</td></tr>`;
}

function renderEarlyTable() {
  const p = state.plan;
  $("early-scope").textContent = `sakıncalı sevke ${p.risk_days + 1}–${p.early_days} gün kalan ${p.early.length} lot`;
  $("early-table").innerHTML = p.early.map((l) => `
    <tr><td>${esc(l.lot_id)}</td><td>${esc(l.product_name)}</td><td>${esc(l.product_group)}</td><td class="num">${n(l.quantity)}</td>
    <td class="num">${l.days_to_unsafe}</td><td class="num">${l.days_to_expiry}</td><td class="num">${String(l.daily_demand).replace(".", ",")}</td>
    <td class="num">${n(l.capacity)}</td><td class="num">${l.surplus ? `<b class="warn">${n(l.surplus)}</b>` : "0"}</td>
    <td class="num">${l.days_to_sell_out ?? "–"}</td><td>${statusChip(l.status)}</td></tr>`).join("")
    || `<tr><td colspan="11" class="empty">Bu aralıkta lot yok.</td></tr>`;
}

function renderReports() {
  const p = state.plan, k = p.kpis, g = p.progress;
  $("report-scope").textContent = `${trDate(p.as_of_date)} · riskli ≤ ${p.risk_days} gün · erken uyarı ≤ ${p.early_days} gün`;
  $("scenario-table").innerHTML = `
    <tr><td><b>TazeRota planı</b></td><td class="num">${n(k.shipped)}</td><td class="num">${n(k.donated)}</td><td class="num">${n(k.disposed)}</td><td class="num"><b>${pct(k.disposal_rate_pct)}</b></td></tr>
    <tr><td>Müdahalesiz (normal ikmal)</td><td class="num">${n(k.risky_qty - k.no_action_disposed)}</td><td class="num">0</td><td class="num">${n(k.no_action_disposed)}</td><td class="num">${pct(k.no_action_disposal_rate_pct)}</td></tr>`;
  const q = `risk=${p.risk_days}&early=${p.early_days}`;
  $("dl-csv").href = `api/export/recommendations.csv?${q}`;
  $("dl-json").href = `api/export/plan.json?${q}`;
  const approved = Object.values(p.approvals || {});
  $("approval-status").innerHTML = `${n(g.dispatched_lots)}/${n(g.lot_count)} lot sevk edildi · ${n(g.pending_lots)} lot onay bekliyor` +
    (approved.length ? "<br>" + approved.map((a) => `${esc(shortName(a.product_name))}: onay ${trTime(a.approved_at)}` +
      (a.dispatched_at ? `, sevk ${trTime(a.dispatched_at)} (${n(a.order_count)} emir)` : ", sevk emri bekleniyor")).join("<br>") : "");
}

function renderPlanBox() {
  const lot = selectedLot();
  const st = lot ? lotStage(lot.lot_id) : "proposal", working = st === "approved" && state.busy;
  $("box-proposal").classList.toggle("hidden", st !== "proposal");
  $("box-status").classList.toggle("hidden", st === "proposal");
  $("btn-approve").disabled = state.busy || !lot;
  $("btn-approve").textContent = "Onayla";
  $("approve-q").textContent = !lot ? "Onaylamak için bir riskli lot seçin."
    : `${shortName(lot.product_name)} sevkini onaylıyor musunuz?` + (state.plan.approval_error ? " (Onay kaydı şu an okunamıyor.)" : "");
  const pill = $("status-pill");
  pill.className = "status-pill " + (st === "dispatched" ? "ok" : "wait");
  pill.textContent = st === "dispatched" ? "Onaylandı ✓ · Sevk edildi"
    : working ? "Onaylandı ✓ · Sevk emirleri oluşturuluyor…" : "Onaylandı ✓ · Sevk emri bekleniyor";
  $("status-label").textContent = lot ? `${shortName(lot.product_name)} · lot durumu` : "Lot durumu";
  $("btn-dispatch").classList.toggle("hidden", !(st === "approved" && !state.busy));
  const anyApproved = Object.keys(state.plan.approvals || {}).length > 0;
  $("btn-reset").classList.toggle("hidden", !anyApproved);
  $("btn-reset").disabled = state.busy;
  $("chat-mode").textContent = state.plan.chat_mode === "local" ? "Bedrock · yerel" : "Bedrock";
}

function scrollToFlow() {
  const body = $("detail-body");
  body.scrollTo({ top: $("flow").offsetTop - body.offsetTop - 4, behavior: "smooth" });
}

// ------------------------------------------------------------------ chat
function md(text) {
  const lines = esc(text).split("\n");
  let html = "", list = false, table = [];
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const flushTable = () => {
    if (!table.length) return;
    const rows = table.filter((r) => !/^\|?\s*:?-{2,}/.test(r));
    html += "<table>" + rows.map((r, i) => "<tr>" + r.replace(/^\||\|$/g, "").split("|")
      .map((c) => `<${i ? "td" : "th"}>${inline(c.trim())}</${i ? "td" : "th"}>`).join("") + "</tr>").join("") + "</table>";
    table = [];
  };
  for (const raw of lines) {
    const line = raw.trim();
    if (line.startsWith("|")) { if (list) { html += "</ul>"; list = false; } table.push(line); continue; }
    flushTable();
    const li = line.match(/^(?:[-*•]|\d+\.)\s+(.*)/);
    if (li) { if (!list) { html += "<ul>"; list = true; } html += `<li>${inline(li[1])}</li>`; continue; }
    if (list) { html += "</ul>"; list = false; }
    const h = line.match(/^#{1,4}\s+(.*)/);
    if (h) html += `<p><b>${inline(h[1])}</b></p>`;
    else if (line && !/^-{3,}$/.test(line)) html += `<p>${inline(line)}</p>`;
  }
  flushTable();
  if (list) html += "</ul>";
  return html;
}

function addMsg(cls, html) {
  const el = document.createElement("div");
  el.className = `msg ${cls}`;
  el.innerHTML = html;
  $("messages").appendChild(el);
  $("messages").scrollTop = $("messages").scrollHeight;
  return el;
}

async function ask(message) {
  message = message.trim();
  if (!message || state.busy) return;
  state.busy = true;
  const lotAtStart = state.selected, before = lotStage(lotAtStart);
  renderPlanBox();
  renderDetail();
  $("suggestions")?.remove();
  addMsg("user", esc(message));
  const out = addMsg("agent", `<span class="typing">Ajan düşünüyor…</span>`);
  const t0 = performance.now();
  let text = "", status = "Ajan düşünüyor…", buf = "", frame = 0;
  const paint = () => {
    frame = 0;
    const secs = Math.round((performance.now() - t0) / 1000);
    out.innerHTML = (text ? md(text) : "") +
      (status ? `<p class="typing">${esc(status)} <span class="secs">${secs} sn</span></p>` : "");
    $("messages").scrollTop = $("messages").scrollHeight;
  };
  const tick = setInterval(() => { if (status) paint(); }, 1000);
  try {
    const res = await fetch("api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: state.sessionId, risk: state.risk, early: state.early }) });
    if (!res.ok || !res.body) throw new Error(res.statusText);
    const reader = res.body.getReader(), dec = new TextDecoder();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line); } catch { continue; }
        if (ev.t === "status") status = ev.text;
        else if (ev.t === "text") { text += ev.text; status = ""; }
      }
      if (!frame) frame = requestAnimationFrame(paint);
    }
    status = "";
    paint();
    if (!text) out.innerHTML = `<span class="typing">Yanıt alınamadı.</span>`;
  } catch (e) {
    out.innerHTML = `<p>⚠️ Ajana ulaşılamadı: ${esc(e.message)}</p>`;
  } finally {
    clearInterval(tick);
    state.busy = false;
  }
  // The agent may have created orders: refresh the workflow state.
  try { await loadPlan(); } catch { renderPlanBox(); }
  if (state.selected === lotAtStart && before !== "dispatched" && lotStage(lotAtStart) === "dispatched") scrollToFlow();
}

// ------------------------------------------------------------------ events
function setView(view) {
  state.view = view;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${view}`));
  document.querySelector(".grid").classList.toggle("wide-view", view !== "overview");
}

async function approveLot() {
  const lot = selectedLot();
  if (!lot) return;
  const btn = $("btn-approve");
  btn.disabled = true; btn.textContent = "Kaydediliyor…";
  try {
    const res = await fetch("api/approve", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ risk: state.risk, early: state.early, lot_id: lot.lot_id, approved_by: "Takım Wakanda" }) });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    await loadPlan();
  } catch (e) {
    alert("Onay kaydedilemedi: " + e.message);
    renderPlanBox();
    return;
  }
  scrollToFlow();
  await ask(dispatchMsg(lot)); // the agent creates this lot's orders and notifications
}

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setView(t.dataset.view)));
$("risky-list").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-lot]");
  if (!tr) return;
  state.selected = tr.dataset.lot;
  state.selectedOrder = null;
  renderRiskyList();
  renderDetail();
  renderPlanBox();
});
$("o-rows").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-order]");
  if (!tr) return;
  state.selectedOrder = tr.dataset.order;
  renderDetail();
});
$("to-flow").addEventListener("click", scrollToFlow);
$("early-list").addEventListener("click", (e) => {
  const row = e.target.closest(".early-row");
  if (row) ask(row.dataset.ask);
});
$("messages").addEventListener("click", (e) => {
  if (e.target.classList.contains("suggest")) ask(e.target.textContent);
});
$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("chat-input").value;
  $("chat-input").value = "";
  ask(v);
});
$("btn-approve").addEventListener("click", approveLot);
$("btn-dispatch").addEventListener("click", () => { const lot = selectedLot(); if (lot) ask(dispatchMsg(lot)); });
$("btn-reset").addEventListener("click", async () => {
  if (!confirm("Tüm lotların onayları, sevk emirleri ve bildirimleri silinecek. Demo baştan başlasın mı?")) return;
  const res = await fetch("api/reset", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ risk: state.risk, early: state.early }) });
  if (!res.ok) { alert("Sıfırlanamadı: " + res.statusText); return; }
  await loadPlan();
  $("detail-body").scrollTo({ top: 0 });
});
$("btn-threshold").addEventListener("click", () => {
  $("t-risk").value = state.risk; $("t-early").value = state.early; $("t-error").textContent = "";
  $("threshold-dialog").showModal();
});
$("threshold-form").addEventListener("submit", async (e) => {
  const action = e.submitter?.value;
  if (action === "cancel") return;
  e.preventDefault();
  let risk = Number($("t-risk").value), early = Number($("t-early").value);
  if (action === "reset") { risk = 60; early = 180; }
  if (!(risk >= 0 && early >= risk)) { $("t-error").textContent = "Erken uyarı eşiği, riskli eşiğinden küçük olamaz."; return; }
  const prev = [state.risk, state.early];
  [state.risk, state.early] = [risk, early];
  try {
    await loadPlan();
    $("threshold-dialog").close();
  } catch (err) {
    [state.risk, state.early] = prev;
    $("t-error").textContent = err.message;
  }
});

loadPlan().catch((e) => { document.body.insertAdjacentHTML("afterbegin", `<p style="padding:12px;color:#dc2626">Veri yüklenemedi: ${esc(e.message)}</p>`); });
