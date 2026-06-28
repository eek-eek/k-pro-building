"use strict";
/* Yale Building Calculator — vanilla hash-router SPA */

const APP = () => document.getElementById("app");

// ───────────────────────── utils ─────────────────────────
const money = (v) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(v || 0);
const qty = (v) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(v || 0);
function escapeHtml(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[c]));
}
const escapeAttr = escapeHtml;

let toastTimer = null;
function toast(message, isError = false) {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.className = "show" + (isError ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ""; }, 3000);
}

// ───────────────────────── api ─────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(`/api${path}`, opts);
  if (resp.status === 204) return null;
  let data = null;
  try { data = await resp.json(); } catch (e) { /* empty */ }
  if (!resp.ok) {
    const detail = (data && data.detail) ? data.detail : `HTTP ${resp.status}`;
    throw { status: resp.status, detail };
  }
  return data;
}
const Api = {
  listEstimates: () => api("GET", "/estimates"),
  createEstimate: (name, input) => api("POST", "/estimates", { name, input }),
  getEstimate: (id) => api("GET", `/estimates/${id}`),
  patchEstimate: (id, patch) => api("PATCH", `/estimates/${id}`, patch),
  deleteEstimate: (id) => api("DELETE", `/estimates/${id}`),
  calc: (id, input) => api("POST", `/estimates/${id}/calc`, input),
  manualEdit: (id, lines) => api("POST", `/estimates/${id}/manual-edit`, { lines }),
  listVersions: (id) => api("GET", `/estimates/${id}/versions`),
  rollback: (id, version_number) => api("POST", `/estimates/${id}/rollback`, { version_number }),
  listChat: (id) => api("GET", `/estimates/${id}/chat`),
  postChat: (id, message) => api("POST", `/estimates/${id}/chat`, { message }),
  getSettings: () => api("GET", "/settings"),
  putSettings: (b) => api("PUT", "/settings", b),
  testConn: (b) => api("POST", "/settings/test", b),
  listPrompts: () => api("GET", "/prompts"),
  putPrompt: (key, body) => api("PUT", `/prompts/${key}`, { body }),
  resetPrompt: (key) => api("POST", `/prompts/${key}/reset`),
};

// ───────────────── building-input form schema ─────────────────
const SELECTS = {
  object_type: ["Жилой дом", "Коммерческое помещение", "Склад", "Офис", "Производственный объект", "Реконструкция / ремонт"],
  structure_type: ["Монолитный железобетон", "Каркас + заполнение", "Кирпич/газоблок", "Металлокаркас", "Сборный железобетон"],
  foundation_type: ["Плита", "Ленточный", "Свайный", "Столбчатый", "Определить по проекту"],
  finish_level: ["Черновая", "White box", "Стандарт", "Бизнес", "Без отделки"],
  engineering_level: ["Базовая", "Стандарт", "Повышенная", "Определить по проекту"],
};
const DEFAULT_INPUT = {
  project_name: "Черновая смета объекта", city: "Астана / Казахстан", object_type: "Жилой дом",
  floors: 5, total_area: 2500, building_length: 50, building_width: 20, floor_height: 3,
  structure_type: "Монолитный железобетон", foundation_type: "Плита", finish_level: "Черновая",
  engineering_level: "Базовая", basement: false, parking: false, use_search: false, demo_mode: false,
  overhead_pct: 8, contingency_pct: 5, vat_pct: 12, works: [], assumptions: "",
};

function inputsForm(inp) {
  const v = { ...DEFAULT_INPUT, ...(inp || {}) };
  const sel = (id, key) => `<div class="field"><label>${id}</label><select data-in="${key}">` +
    SELECTS[key].map((o) => `<option ${o === v[key] ? "selected" : ""}>${escapeHtml(o)}</option>`).join("") +
    `</select></div>`;
  const num = (label, key, step) => `<div class="field"><label>${label}</label>` +
    `<input type="number" step="${step || 1}" data-in="${key}" value="${escapeAttr(v[key])}"></div>`;
  const txt = (label, key) => `<div class="field"><label>${label}</label>` +
    `<input type="text" data-in="${key}" value="${escapeAttr(v[key])}"></div>`;
  return `
    <div class="grid">
      ${txt("Название проекта", "project_name")}
      ${txt("Город / регион РК", "city")}
      ${sel("Тип объекта", "object_type")}
      ${num("Этажность", "floors")}
      ${num("Общая площадь, м²", "total_area")}
      ${num("Габарит длина, м", "building_length", "0.1")}
      ${num("Габарит ширина, м", "building_width", "0.1")}
      ${num("Высота этажа, м", "floor_height", "0.1")}
      ${sel("Конструктив", "structure_type")}
      ${sel("Фундамент", "foundation_type")}
      ${sel("Класс отделки", "finish_level")}
      ${sel("Класс инженерии", "engineering_level")}
    </div>
    <div class="checks">
      <label><input type="checkbox" data-in="basement" ${v.basement ? "checked" : ""}> Подвал</label>
      <label><input type="checkbox" data-in="parking" ${v.parking ? "checked" : ""}> Паркинг</label>
      <label><input type="checkbox" data-in="use_search" ${v.use_search ? "checked" : ""}> Искать актуальные нормы РК</label>
      <label><input type="checkbox" data-in="demo_mode" ${v.demo_mode ? "checked" : ""}> Демо без LLM</label>
    </div>
    <div class="grid">
      ${num("Накладные/админ., %", "overhead_pct")}
      ${num("Резерв/риски, %", "contingency_pct")}
      ${num("НДС, %", "vat_pct")}
      <div class="field span-2"><label>Что нужно учесть</label>
        <textarea data-in="assumptions">${escapeHtml(v.assumptions)}</textarea></div>
    </div>`;
}
function collectInputs(root) {
  const out = { ...DEFAULT_INPUT };
  root.querySelectorAll("[data-in]").forEach((el) => {
    const key = el.dataset.in;
    if (el.type === "checkbox") out[key] = el.checked;
    else if (el.type === "number") out[key] = Number(el.value || 0);
    else out[key] = el.value;
  });
  return out;
}

// ───────────────────────── router ─────────────────────────
function parseRoute() {
  const h = (location.hash || "#/").replace(/^#/, "");
  const m = h.match(/^\/estimate\/(\d+)/);
  if (m) return { name: "detail", id: Number(m[1]) };
  if (h.startsWith("/settings")) return { name: "settings" };
  return { name: "dashboard" };
}
function setActiveNav(route) {
  const target = route.name === "settings" ? "#/settings" : "#/";
  document.querySelectorAll(".nav a.link").forEach((a) =>
    a.classList.toggle("active", a.dataset.nav === target));
}
async function render() {
  const route = parseRoute();
  setActiveNav(route);
  try {
    if (route.name === "detail") await viewDetail(route.id);
    else if (route.name === "settings") await viewSettings();
    else await viewDashboard();
  } catch (e) {
    APP().innerHTML = `<div class="page"><div class="empty">Ошибка: ${escapeHtml(e.detail || e.message || e)}</div></div>`;
  }
  refreshNavProvider();
}
window.addEventListener("hashchange", render);

async function refreshNavProvider() {
  try {
    const s = await Api.getSettings();
    document.getElementById("navProvider").textContent =
      "Провайдер: " + s.provider + (s.has_key || s.provider === "demo" ? "" : " (нет ключа)");
  } catch (e) { /* ignore */ }
}

// ───────────────────────── dashboard ─────────────────────────
async function viewDashboard() {
  const items = await Api.listEstimates();
  APP().innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <h1 class="title">Сметы</h1>
          <p class="subtitle">${items.length} ${plural(items.length, "проект", "проекта", "проектов")}</p>
        </div>
        <button class="btn primary" id="newBtn" style="margin-left:auto">Новая смета</button>
      </div>
      <div class="search"><input type="text" id="search" placeholder="Поиск по проектам…"></div>
      <div id="list"></div>
    </div>`;
  const listEl = document.getElementById("list");
  const draw = (filter) => {
    const f = (filter || "").toLowerCase();
    const rows = items.filter((it) =>
      !f || `${it.name} ${it.object_type} ${it.city}`.toLowerCase().includes(f));
    if (!rows.length) { listEl.innerHTML = `<div class="empty">Ничего нет. Создайте новую смету.</div>`; return; }
    listEl.innerHTML = rows.map((it) => {
      const dot = it.status === "calculated"
        ? `<span class="dot-ok">● рассчитана</span>` : `<span class="dot-draft">○ черновик</span>`;
      const total = it.status === "calculated" ? `${money(it.total)} ₸` : "—";
      return `<div class="row" data-id="${it.id}">
        <div class="main"><div class="name">${escapeHtml(it.name || "Без названия")}</div>
          <div class="meta">${escapeHtml(it.object_type || "—")} · ${escapeHtml(it.city || "—")}</div></div>
        <div class="amount"><div class="total">${total}</div>
          <div class="sub">v${it.version_count} · ${it.message_count} сообщ.</div></div>
        <div class="status">${dot}</div>
        <button class="del" data-del="${it.id}" title="Удалить">✕</button>
      </div>`;
    }).join("");
    listEl.querySelectorAll(".row").forEach((r) => r.addEventListener("click", (ev) => {
      if (ev.target.dataset.del) return;
      location.hash = `#/estimate/${r.dataset.id}`;
    }));
    listEl.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm("Удалить смету безвозвратно?")) return;
      await Api.deleteEstimate(b.dataset.del);
      toast("Смета удалена");
      render();
    }));
  };
  draw("");
  document.getElementById("search").addEventListener("input", (e) => draw(e.target.value));
  document.getElementById("newBtn").addEventListener("click", async () => {
    const { id } = await Api.createEstimate("Новая смета", DEFAULT_INPUT);
    location.hash = `#/estimate/${id}`;
  });
}
function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
  return many;
}

// ───────────────────────── detail ─────────────────────────
let DETAIL = null; // {id, data, lines}

async function viewDetail(id) {
  const data = await Api.getEstimate(id);
  const cv = data.current_version;
  DETAIL = { id, data, lines: cv ? cv.result.lines.map((l) => ({ ...l })) : [] };
  const inp = cv ? cv.input : DEFAULT_INPUT;
  const calculated = !!cv;

  APP().innerHTML = `
    <div class="page">
      <div class="breadcrumb"><a href="#/">Сметы</a> / ${escapeHtml(data.estimate.name)}</div>
      <div class="title-row">
        <input class="title-edit" id="titleEdit" value="${escapeAttr(data.estimate.name)}">
        ${calculated ? `<span class="dot-ok" style="font-size:13px;font-weight:600">● рассчитана</span>`
                     : `<span class="dot-draft" style="font-size:13px;font-weight:600">○ черновик</span>`}
        <div class="toolbar">
          ${calculated ? `<select class="ver-select" id="verSel" title="Версии"></select>
          <button class="btn sm" id="exportBtn">Экспорт Word</button>` : ""}
        </div>
      </div>
      <div class="detail">
        <div class="left">
          <details class="card" ${calculated ? "" : "open"}>
            <summary>Исходные данные</summary>
            <div class="collapsible-body">
              <div id="inputs">${inputsForm(inp)}</div>
              <div class="row-actions">
                <button class="btn accent" id="calcBtn">${calculated ? "Изменить и пересчитать" : "Рассчитать"}</button>
              </div>
              <ul class="steps" id="steps"></ul>
            </div>
          </details>
          <div id="result"></div>
        </div>
        <div class="right" id="chatPanel"></div>
      </div>
    </div>`;

  // title edit
  const titleEl = document.getElementById("titleEdit");
  titleEl.addEventListener("change", async () => {
    await Api.patchEstimate(id, { name: titleEl.value });
    toast("Название сохранено");
  });

  document.getElementById("calcBtn").addEventListener("click", () => runCalc(id));
  if (calculated) {
    renderResult(cv.result);
    buildVersionSelector(id);
    document.getElementById("exportBtn").addEventListener("click", () => exportDocx(cv.result));
  }
  renderChat(id, calculated);
}

async function runCalc(id) {
  const input = collectInputs(document.getElementById("inputs"));
  const stepsEl = document.getElementById("steps");
  const calcBtn = document.getElementById("calcBtn");
  calcBtn.disabled = true;
  stepsEl.innerHTML = `<li class="running"><span class="mark">…</span><span>Запуск расчёта…</span></li>`;
  try {
    const { job_id } = await Api.calc(id, input);
    listenJob(job_id, stepsEl, () => { toast("Смета рассчитана"); render(); }, () => { calcBtn.disabled = false; });
  } catch (e) {
    toast(e.detail || "Ошибка запуска", true);
    calcBtn.disabled = false;
  }
}

function listenJob(jobId, stepsEl, onDone, onEnd) {
  const src = new EventSource(`/api/estimate/${jobId}/events`);
  src.addEventListener("status", (ev) => {
    try {
      const st = JSON.parse(ev.data);
      stepsEl.innerHTML = (st.steps || []).map((s) => {
        const mark = s.status === "done" ? "✓" : s.status === "error" ? "!" : s.status === "running" ? "…" : "·";
        return `<li class="${s.status}"><span class="mark">${mark}</span><span>${escapeHtml(s.label)}` +
          (s.detail ? ` — <span class="muted">${escapeHtml(s.detail)}</span>` : "") + `</span></li>`;
      }).join("");
      if (st.status === "error") { toast(st.error || "Ошибка расчёта", true); src.close(); onEnd && onEnd(); }
      else if (st.status === "done") { src.close(); onDone && onDone(); }
    } catch (err) {
      // ошибка парсинга/рендера не должна оставить кнопку заблокированной и ES открытым
      toast("Ошибка обработки статуса", true);
      src.close();
      onEnd && onEnd();
    }
  });
  src.addEventListener("end", () => { src.close(); onEnd && onEnd(); });
  src.onerror = () => { src.close(); onEnd && onEnd(); };
}

// ── estimate render (editable) ──
function renderResult(r) {
  const parts = [];
  if (r.warnings && r.warnings.length) {
    parts.push(`<div class="card"><h3>Предупреждения</h3><ul class="plain">` +
      r.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("") + `</ul></div>`);
  }
  if (r.sources && r.sources.length) {
    parts.push(`<div class="card"><h3>Нормативные источники РК</h3><ul class="plain src">` +
      r.sources.map((s) => {
        const link = s.url ? `<a href="${escapeAttr(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.code)}</a>` : escapeHtml(s.code);
        const tag = s.confirmed ? "" : ` <span class="badge">не подтверждено</span>`;
        return `<li>${link} — ${escapeHtml(s.title)}${tag}</li>`;
      }).join("") + `</ul></div>`);
  }
  // editable smeta
  parts.push(`<div class="card"><h3>Смета</h3>
    <div class="table-wrap"><table class="est"><thead><tr>
      <th>№</th><th>Работа/ресурс</th><th>Ед.</th><th class="num">Объём</th>
      <th class="num">Материал</th><th class="num">Работа</th><th class="num">Машины</th><th class="num">Итого ₸</th>
    </tr></thead><tbody>${renderLines(r)}</tbody></table></div>
    <div class="row-actions">
      <button class="btn accent" id="saveEditBtn">Сохранить правки</button>
      <span class="hint">Поля «Объём» и цены редактируются — итоги пересчитает сервер, создаст новую версию.</span>
    </div></div>`);
  parts.push(renderTotals(r.totals));
  parts.push(renderRecs());
  document.getElementById("result").innerHTML = parts.join("");
  document.getElementById("saveEditBtn").addEventListener("click", saveManualEdit);
  document.querySelectorAll("[data-rec]").forEach((b) => b.addEventListener("click",
    () => addRec(getRecommendations()[Number(b.dataset.rec)])));
}

// ── recommendations (типовые позиции по нормам РК, часто не учтённые) ──
const REC_SECTION = "Дополнительные позиции (рекомендации)";
const REC_LIBRARY = [
  { kw: ["геодез"], title: "Геодезические разбивочные работы", unit: "усл.", norm: "СН РК 1.02-03" },
  { kw: ["временны", "подготов"], title: "Временные здания, дороги и площадки", unit: "усл.", norm: "СН РК 8.02-05" },
  { kw: ["вертикальн", "планировк", "благоустр"], title: "Вертикальная планировка территории", unit: "м²", norm: "СН РК 3.01-01" },
  { kw: ["лифт", "подъём"], title: "Лифты и подъёмное оборудование", unit: "шт", norm: "СН РК 3.02-01", floorsMin: 5 },
  { kw: ["пожарн", "сигнал", "пожаротуш"], title: "Пожарная сигнализация и пожаротушение", unit: "усл.", norm: "СН РК 2.02-15" },
  { kw: ["молниез", "заземл"], title: "Молниезащита и заземление", unit: "усл.", norm: "СО 153-34.21.122" },
  { kw: ["пусконал", "наладк"], title: "Пусконаладочные работы инженерных систем", unit: "усл.", norm: "СН РК 8.02-05" },
  { kw: ["надзор", "авторск"], title: "Авторский и технический надзор", unit: "усл.", norm: "СН РК 1.02-03" },
];
function getRecommendations() {
  const lines = DETAIL.lines || [];
  const hay = lines.map((l) => `${l.title} ${l.section}`.toLowerCase()).join(" | ");
  const cv = DETAIL.data.current_version;
  const floors = (cv && cv.input && cv.input.floors) || 0;
  return REC_LIBRARY.filter((r) => {
    if (r.floorsMin && floors < r.floorsMin) return false;
    return !r.kw.some((k) => hay.includes(k));
  });
}
function renderRecs() {
  const recs = getRecommendations();
  if (!recs.length) return "";
  return `<div class="card"><h3>Рекомендации — что может быть не учтено</h3>
    <div class="hint">Типовые позиции по нормам РК (СН РК/ГОСТ), часто отсутствующие в предварительной смете.
    «Добавить в смету» создаёт строку с нулевой ценой — уточните объём и стоимость.</div>
    <ul class="rec-list">${recs.map((r, i) => `<li>
      <div><strong>${escapeHtml(r.title)}</strong> <span class="nrm">· ${escapeHtml(r.norm)} · ${escapeHtml(r.unit)}</span></div>
      <button class="btn sm" data-rec="${i}">Добавить в смету</button></li>`).join("")}</ul></div>`;
}
async function addRec(rec) {
  if (!rec) return;
  const n = DETAIL.lines.filter((l) => l.section === REC_SECTION).length + 1;
  DETAIL.lines.push({
    no: `15.${n}`, section: REC_SECTION, title: rec.title, norm: rec.norm, unit: rec.unit,
    quantity: 1, material_price: 0, labor_price: 0, machine_price: 0, total: 0,
    needs_review: true, comment: "добавлено из рекомендаций — уточнить объём и цену",
  });
  try {
    await Api.manualEdit(DETAIL.id, DETAIL.lines);
    toast("Добавлено в смету — уточните цену");
    render();
  } catch (e) { toast(e.detail || "Ошибка", true); }
}
function renderLines(r) {
  const rows = [];
  let section = null;
  const sectionTotals = r.section_totals || {};
  DETAIL.lines.forEach((ln, i) => {
    if (ln.section !== section) {
      section = ln.section;
      const sub = sectionTotals[ln.section];
      rows.push(`<tr class="section-row"><td></td><td colspan="6">${escapeHtml(ln.section)}</td>
        <td class="num">${sub != null ? money(sub) : ""}</td></tr>`);
    }
    const cell = (key, w) => `<input class="cell-edit" data-li="${i}" data-key="${key}" value="${escapeAttr(ln[key])}">`;
    rows.push(`<tr class="${ln.needs_review ? "review" : ""}">
      <td>${escapeHtml(ln.no)}</td>
      <td>${escapeHtml(ln.title)}${ln.needs_review ? ' <span class="badge">проверить</span>' : ""}</td>
      <td>${escapeHtml(ln.unit)}</td>
      <td class="num">${cell("quantity")}</td>
      <td class="num">${cell("material_price")}</td>
      <td class="num">${cell("labor_price")}</td>
      <td class="num">${cell("machine_price")}</td>
      <td class="num">${money(ln.total)}</td></tr>`);
  });
  return rows.join("");
}
function renderTotals(t) {
  if (!t) return "";
  const row = (label, val, cls = "") => `<div class="t-row ${cls}"><span>${label}</span><span>${money(val)} ₸</span></div>`;
  return `<div class="card"><h3>Итоги</h3><div class="totals">
    ${row("Прямые затраты", t.direct)}
    ${row(`Накладные (${t.overhead_pct}%)`, t.overhead)}
    ${row(`Резерв (${t.contingency_pct}%)`, t.contingency)}
    ${row(`НДС (${t.vat_pct}%)`, t.vat)}
    ${row("ИТОГО с НДС", t.grand_total, "grand")}
  </div></div>`;
}
async function saveManualEdit() {
  document.querySelectorAll(".cell-edit").forEach((el) => {
    const ln = DETAIL.lines[Number(el.dataset.li)];
    if (ln) ln[el.dataset.key] = Number(el.value || 0);
  });
  try {
    await Api.manualEdit(DETAIL.id, DETAIL.lines);
    toast("Правки сохранены — создана новая версия");
    render();
  } catch (e) { toast(e.detail || "Ошибка сохранения", true); }
}

async function buildVersionSelector(id) {
  const sel = document.getElementById("verSel");
  if (!sel) return;
  const versions = await Api.listVersions(id);
  const cur = DETAIL.data.current_version.version_number;
  const SRC = { initial: "расчёт", llm_edit: "правка ИИ", manual_edit: "ручная правка", rollback: "откат" };
  sel.innerHTML = versions.slice().reverse().map((v) =>
    `<option value="${v.version_number}" ${v.version_number === cur ? "selected" : ""}>` +
    `Версия ${v.version_number} · ${escapeHtml(SRC[v.source] || v.source)}</option>`).join("");
  sel.addEventListener("change", async () => {
    const vn = Number(sel.value);
    if (vn === cur) return;
    if (!confirm(`Откатиться к версии ${vn}? Будет создана новая версия с этими данными.`)) { sel.value = cur; return; }
    await Api.rollback(id, vn);
    toast(`Откат к версии ${vn}`);
    render();
  });
}

// ── chat ──
async function renderChat(id, calculated) {
  const panel = document.getElementById("chatPanel");
  let settings = null;
  try { settings = await Api.getSettings(); } catch (e) { /* ignore */ }
  const usable = settings && settings.provider !== "demo" && settings.has_key;
  const msgs = calculated ? await Api.listChat(id) : [];
  panel.innerHTML = `
    <div class="chat-head">💬 Чат с ИИ</div>
    <div class="chat-body" id="chatBody">${msgs.map(bubble).join("") || `<div class="muted">Опишите, что изменить в смете.</div>`}</div>
    ${!calculated ? `<div class="chat-disabled">Сначала рассчитайте смету.</div>`
      : !usable ? `<div class="chat-disabled">ИИ-чат недоступен: настройте провайдера и ключ в <a href="#/settings">Настройках</a>.</div>`
      : `<div class="chat-foot"><div class="chat-compose">
          <input type="text" id="chatInput" placeholder="Что изменить в смете?">
          <button class="btn accent send" id="chatSend">↑</button></div></div>`}`;
  const body = document.getElementById("chatBody");
  body.scrollTop = body.scrollHeight;
  if (calculated && usable) {
    const send = async () => {
      const inputEl = document.getElementById("chatInput");
      const text = inputEl.value.trim();
      if (!text) return;
      inputEl.value = "";
      inputEl.disabled = true;
      body.insertAdjacentHTML("beforeend", bubble({ role: "user", content: text }));
      body.insertAdjacentHTML("beforeend", `<div class="bubble assistant" id="pending"></div>`);
      body.scrollTop = body.scrollHeight;
      startThinking(document.getElementById("pending"));
      try {
        await Api.postChat(id, text);
        stopThinking();
        toast("Смета обновлена");
        render();
      } catch (e) {
        stopThinking();
        const p = document.getElementById("pending");
        if (p) p.remove();
        toast(e.detail || "Ошибка чата", true);
        inputEl.disabled = false;
      }
    };
    document.getElementById("chatSend").addEventListener("click", send);
    document.getElementById("chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  }
}
let thinkTimer = null;
function startThinking(el) {
  if (!el) return;
  let n = 1;
  const tick = () => { el.textContent = "Думаю над вашим вопросом" + ".".repeat(n); n = (n % 3) + 1; };
  tick();
  thinkTimer = setInterval(tick, 1000); // 1→2→3 точки, полный цикл ~3 с
}
function stopThinking() { if (thinkTimer) { clearInterval(thinkTimer); thinkTimer = null; } }

function bubble(m) {
  const ver = m.version_number ? ` <span class="ver">· v${m.version_number}</span>` : "";
  return `<div class="bubble ${m.role}">${escapeHtml(m.content)}${m.role === "assistant" ? ver : ""}</div>`;
}

// ── Word export (landscape .doc via Office-HTML) ──
function exportDocx(r) {
  const t = r.totals || {};
  const rows = (r.lines || []).map((l) => `<tr>
    <td>${escapeHtml(l.no)}</td><td>${escapeHtml(l.title)}</td><td>${escapeHtml(l.norm || "")}</td>
    <td>${escapeHtml(l.unit)}</td><td class="n">${qty(l.quantity)}</td>
    <td class="n">${money(l.material_price)}</td><td class="n">${money(l.labor_price)}</td>
    <td class="n">${money(l.machine_price)}</td><td class="n">${money(l.total)}</td></tr>`).join("");
  const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office"
    xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
    <head><meta charset="utf-8">
    <!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View><w:Zoom>100</w:Zoom></w:WordDocument></xml><![endif]-->
    <style>
      @page Section1 { size: 841.95pt 595.35pt; mso-page-orientation: landscape; margin: 1.4cm 1.6cm; }
      div.Section1 { page: Section1; }
      body { font-family: "Times New Roman", serif; font-size: 11pt; color: #000; }
      h1 { font-size: 16pt; margin: 0 0 4pt; }
      .meta { font-size: 10pt; color: #333; margin: 0 0 12pt; }
      table { border-collapse: collapse; width: 100%; }
      th, td { border: 0.5pt solid #777; padding: 3pt 5pt; font-size: 9.5pt; vertical-align: top; }
      th { background: #eee; font-weight: bold; }
      td.n, th.n { text-align: right; mso-number-format: "\\#\\,\\#\\#0"; }
      .tot { margin-top: 12pt; font-size: 11pt; }
    </style></head>
    <body><div class="Section1">
      <h1>${escapeHtml(r.project_name)}</h1>
      <p class="meta">${escapeHtml(r.object_type)} · ${escapeHtml(r.city)} · ${escapeHtml(r.precision_class)}<br>
        Сформировано: ${escapeHtml(r.generated_at)}</p>
      <table><thead><tr>
        <th>№</th><th>Работа / ресурс</th><th>Норма</th><th>Ед.</th><th class="n">Объём</th>
        <th class="n">Материал</th><th class="n">Работа</th><th class="n">Машины</th><th class="n">Итого, ₸</th>
      </tr></thead><tbody>${rows}</tbody></table>
      <p class="tot"><b>Прямые затраты:</b> ${money(t.direct)} ₸ &nbsp;·&nbsp;
        <b>Накладные (${t.overhead_pct}%):</b> ${money(t.overhead)} ₸ &nbsp;·&nbsp;
        <b>Резерв (${t.contingency_pct}%):</b> ${money(t.contingency)} ₸ &nbsp;·&nbsp;
        <b>НДС (${t.vat_pct}%):</b> ${money(t.vat)} ₸ &nbsp;·&nbsp;
        <b>ИТОГО с НДС:</b> ${money(t.grand_total)} ₸</p>
    </div></body></html>`;
  const blob = new Blob(["﻿", html], { type: "application/msword" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "smeta_" + (r.project_name || "obj").replace(/[^\wа-яё-]+/gi, "_").slice(0, 40) +
    "_" + new Date().toISOString().slice(0, 10) + ".doc";
  a.click();
  URL.revokeObjectURL(a.href);
}

// ───────────────────────── settings ─────────────────────────
async function viewSettings() {
  const s = await Api.getSettings();
  const prompts = await Api.listPrompts();
  let provider = s.provider;
  const modelsFor = (p) => (s.catalog[p] || []);
  APP().innerHTML = `
    <div class="page settings">
      <h1 class="title">Настройки</h1>
      <div class="section-h">Провайдер ИИ</div>
      <div class="card">
        <div class="chips" id="chips">
          ${["gemini", "anthropic", "openai", "demo"].map((p) =>
            `<span class="chip ${p === provider ? "active" : ""}" data-p="${p}">${p}${p === provider ? " ✓" : ""}</span>`).join("")}
        </div>
        <div class="grid">
          <div class="field"><label>API-ключ</label>
            <input type="text" id="apiKey" value="${escapeAttr(s.masked_key)}" placeholder="вставьте ключ">
            <div class="hint">Хранится на сервере; полностью в браузер не возвращается.</div></div>
          <div class="field"><label>Модель</label><select id="model"></select></div>
        </div>
        <div class="checks"><label><input type="checkbox" id="useSearch" ${s.use_search ? "checked" : ""}> Искать актуальные нормы РК (web-grounding)</label></div>
        <div class="row-actions">
          <button class="btn primary" id="saveSettings">Сохранить</button>
          <button class="btn" id="testConn">Проверить соединение</button>
          <span class="test-status" id="testStatus"></span>
        </div>
      </div>

      <div class="section-h">Системные промпты</div>
      <div id="prompts">${prompts.map(promptBlock).join("")}</div>
    </div>`;

  const modelSel = document.getElementById("model");
  const fillModels = () => {
    modelSel.innerHTML = modelsFor(provider).map((m) =>
      `<option value="${escapeAttr(m.id)}" ${m.id === s.model ? "selected" : ""}>${escapeHtml(m.label)}</option>`).join("")
      || `<option value="">(нет моделей)</option>`;
  };
  fillModels();
  document.querySelectorAll("#chips .chip").forEach((c) => c.addEventListener("click", () => {
    provider = c.dataset.p;
    document.querySelectorAll("#chips .chip").forEach((x) => {
      x.classList.toggle("active", x.dataset.p === provider);
      x.textContent = x.dataset.p + (x.dataset.p === provider ? " ✓" : "");
    });
    fillModels();
  }));

  document.getElementById("saveSettings").addEventListener("click", async () => {
    const body = {
      provider,
      model: modelSel.value || undefined,
      use_search: document.getElementById("useSearch").checked,
    };
    const key = document.getElementById("apiKey").value;
    if (key && key !== s.masked_key) body.api_key = key;
    try {
      const upd = await Api.putSettings(body);
      document.getElementById("apiKey").value = upd.masked_key;
      toast("Настройки сохранены");
      refreshNavProvider();
    } catch (e) { toast(e.detail || "Ошибка", true); }
  });

  document.getElementById("testConn").addEventListener("click", async () => {
    const st = document.getElementById("testStatus");
    st.textContent = "Проверка…"; st.className = "test-status";
    const key = document.getElementById("apiKey").value;
    const body = { provider, model: modelSel.value || undefined };
    if (key && key !== s.masked_key) body.api_key = key;
    try {
      const r = await Api.testConn(body);
      st.textContent = (r.ok ? "● " : "● ") + r.message;
      st.className = "test-status " + (r.ok ? "ok" : "err");
    } catch (e) { st.textContent = e.detail || "Ошибка"; st.className = "test-status err"; }
  });

  document.querySelectorAll("[data-save-prompt]").forEach((b) => b.addEventListener("click", async () => {
    const key = b.dataset.savePrompt;
    const ta = document.querySelector(`textarea[data-prompt="${key}"]`);
    try { await Api.putPrompt(key, ta.value); toast("Промпт сохранён"); viewSettings(); }
    catch (e) { toast(e.detail || "Ошибка", true); }
  }));
  document.querySelectorAll("[data-reset-prompt]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Сбросить промпт к заводскому?")) return;
    await Api.resetPrompt(b.dataset.resetPrompt); toast("Промпт сброшен"); viewSettings();
  }));
}
function promptBlock(p) {
  return `<div class="prompt-block">
    <div class="ph"><div style="font-weight:600">${escapeHtml(p.title)}</div>
      <div class="desc">${escapeHtml(p.description)}${p.is_custom ? " · изменён" : ""}</div>
      <div class="right">
        <button class="btn sm" data-save-prompt="${escapeAttr(p.key)}">Сохранить</button>
        <button class="btn ghost sm" data-reset-prompt="${escapeAttr(p.key)}">Сбросить</button>
      </div></div>
    <textarea data-prompt="${escapeAttr(p.key)}" style="min-height:140px">${escapeHtml(p.body)}</textarea>
  </div>`;
}

// ───────────────────────── init ─────────────────────────
render();
