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
const KIND_LABEL = { material: "матер.", labor: "труд", machine: "машина" };
function statusBadge(status) {
  return status === "calculated"
    ? `<span class="sbadge ok">рассчитана</span>`
    : `<span class="sbadge draft">черновик</span>`;
}

let toastTimer = null;
function toast(message, isError = false) {
  const t = document.getElementById("toast");
  t.textContent = message;
  t.className = "show" + (isError ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ""; }, 3000);
}

// ───────────────────────── api ─────────────────────────
let ADMIN_AUTH = sessionStorage.getItem("adminAuth") || null; // base64(login:pароль) для Настроек

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (ADMIN_AUTH) opts.headers["Authorization"] = "Basic " + ADMIN_AUTH;
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
  recommendations: (id) => api("GET", `/estimates/${id}/recommendations`),
  addRecommendation: (id, key) => api("POST", `/estimates/${id}/recommendations`, { key }),
  suggestPrices: (id, source) => api("POST", `/estimates/${id}/suggest-material-prices`, { source }),
  listObjects: () => api("GET", "/objects"),
  createObject: (body) => api("POST", "/objects", body),
  getObject: (id) => api("GET", `/objects/${id}`),
  patchObject: (id, patch) => api("PATCH", `/objects/${id}`, patch),
  deleteObject: (id) => api("DELETE", `/objects/${id}`),
  objectConcept: (id, object_type, floors, form) =>
    api("GET", `/objects/${id}/concept?object_type=${encodeURIComponent(object_type)}` +
      (floors ? `&floors=${floors}` : "") + (form ? `&form=${encodeURIComponent(form)}` : "")),
  objectCreateEstimate: (id, input) => api("POST", `/objects/${id}/estimate`, input),
  generateForm: (description, base) => api("POST", "/building-form/generate", { description, base }),
  checkZone: (id) => api("POST", `/objects/${id}/check-zone`),
  zoningWms: (city) => api("GET", `/zoning/wms?city=${encodeURIComponent(city)}`),
  zoningFaults: () => api("GET", "/zoning/faults"),
  verifyNorms: (id) => api("POST", `/estimates/${id}/verify-norms`),
  auditEstimate: (id) => api("POST", `/estimates/${id}/audit`),
  listVersions: (id) => api("GET", `/estimates/${id}/versions`),
  rollback: (id, version_number) => api("POST", `/estimates/${id}/rollback`, { version_number }),
  listChat: (id) => api("GET", `/estimates/${id}/chat`),
  postChat: (id, message) => api("POST", `/estimates/${id}/chat`, { message }),
  health: () => api("GET", "/health"),
  getSettings: () => api("GET", "/settings"),
  putSettings: (b) => api("PUT", "/settings", b),
  testConn: (b) => api("POST", "/settings/test", b),
  listBenchmark: () => api("GET", "/benchmark"),
  addBenchmark: (b) => api("POST", "/benchmark", b),
  importBenchmark: (xlsx_b64) => api("POST", "/benchmark/import", { xlsx_b64 }),
  deleteBenchmark: (id) => api("DELETE", `/benchmark/${id}`),
  listPrompts: () => api("GET", "/prompts"),
  putPrompt: (key, body) => api("PUT", `/prompts/${key}`, { body }),
  resetPrompt: (key) => api("POST", `/prompts/${key}/reset`),
  searchMaterials: (q, opts = {}) => api("GET", `/materials?q=${encodeURIComponent(q)}` +
    `&limit=${opts.limit || 50}${opts.onlyPriced ? "&only_priced=true" : ""}` +
    `${opts.category ? "&category=" + encodeURIComponent(opts.category) : ""}`),
  materialCategories: () => api("GET", "/materials/categories"),
  tariffs: (region, kind) => api("GET", `/tariffs?region=${encodeURIComponent(region || "")}` +
    `${kind ? "&kind=" + encodeURIComponent(kind) : ""}`),
  tariffRegions: () => api("GET", "/tariffs/regions"),
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
  floors: 10, total_area: 1500, building_length: 10, building_width: 15, floor_height: 3, form: "box",
  structure_type: "Монолитный железобетон", foundation_type: "Плита", finish_level: "Черновая",
  engineering_level: "Базовая", basement: false, parking: false, use_search: false, demo_mode: false,
  overhead_pct: 8, contingency_pct: 5, vat_pct: 16, works: [], assumptions: "",
};

function inputsForm(inp) {
  const v = { ...DEFAULT_INPUT, ...(inp || {}) };
  const sel = (id, key) => `<div class="field"><label>${id}</label><select data-in="${key}">` +
    SELECTS[key].map((o) => `<option ${o === v[key] ? "selected" : ""}>${escapeHtml(o)}</option>`).join("") +
    `</select></div>`;
  const num = (label, key, step, min) => `<div class="field"><label>${label}</label>` +
    `<input type="number" step="${step || 1}"${min !== undefined ? ` min="${min}"` : ""} data-in="${key}" value="${escapeAttr(v[key])}"></div>`;
  const txt = (label, key) => `<div class="field"><label>${label}</label>` +
    `<input type="text" data-in="${key}" value="${escapeAttr(v[key])}"></div>`;
  const formSel = `<div class="field"><label>Форма здания</label><select data-in="form">` +
    BUILDING_FORMS.map((f) => `<option value="${f.key}" ${f.key === (v.form || "box") ? "selected" : ""}>${escapeHtml(f.label)}</option>`).join("") +
    `</select></div>`;
  return `
    <div class="grid">
      ${txt("Название проекта", "project_name")}
      ${txt("Город / регион РК", "city")}
      ${sel("Тип объекта", "object_type")}
      ${formSel}
      ${num("Этажность", "floors", 1, 1)}
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
    else if (el.type === "number")
      out[key] = key === "floors" ? Math.max(1, Math.round(Number(el.value || 0))) : Number(el.value || 0);
    else out[key] = el.value;
  });
  return out;
}

// Этажи — только целые: снап поля к целому ≥1 при изменении.
function snapFloorsToInt(el) {
  if (!el) return;
  el.addEventListener("change", () => {
    if (el.value !== "") el.value = Math.max(1, Math.round(Number(el.value) || 1));
  });
}

// ───────────────────────── router ─────────────────────────
function parseRoute() {
  const h = (location.hash || "#/").replace(/^#/, "");
  const m = h.match(/^\/estimate\/(\d+)/);
  if (m) return { name: "detail", id: Number(m[1]) };
  const mo = h.match(/^\/object\/(\d+)/);
  if (mo) return { name: "object", id: Number(mo[1]) };
  if (h.startsWith("/objects")) return { name: "objects" };
  if (h.startsWith("/estimates")) return { name: "estimates" };
  if (h.startsWith("/prices")) return { name: "prices" };
  if (h.startsWith("/materials")) return { name: "materials" };
  if (h.startsWith("/settings")) return { name: "settings" };
  return { name: "home" };
}
function setActiveNav(route) {
  const map = { home: "#/", estimates: "#/estimates", detail: "#/estimates",
    objects: "#/objects", object: "#/objects", materials: "#/materials", settings: "#/settings" };
  const target = map[route.name] || "#/";
  document.querySelectorAll(".nav a.link").forEach((a) =>
    a.classList.toggle("active", a.dataset.nav === target));
}
async function render() {
  const route = parseRoute();
  setActiveNav(route);
  try {
    if (route.name === "detail") await viewDetail(route.id);
    else if (route.name === "settings") await viewSettings();
    else if (route.name === "prices") await viewPrices();
    else if (route.name === "materials") await viewMaterials();
    else if (route.name === "objects") await viewObjects();
    else if (route.name === "object") await viewObject(route.id);
    else if (route.name === "estimates") await viewDashboard();
    else await viewHome();
  } catch (e) {
    APP().innerHTML = `<div class="page"><div class="empty">Ошибка: ${escapeHtml(e.detail || e.message || e)}</div></div>`;
  }
  refreshNavProvider();
}
window.addEventListener("hashchange", render);

async function refreshNavProvider() {
  const el = document.getElementById("navProvider");
  if (!el) return;
  try {
    const s = await Api.health();   // публичный: провайдер + has_key (без секретов)
    el.textContent = "Провайдер: " + s.llm_provider + (s.has_key || s.llm_provider === "demo" ? "" : " (нет ключа)");
  } catch (e) { el.textContent = ""; }
}

// ───────────────────────── home ─────────────────────────
// SVG-иллюстрация для hero: небоскрёб + музей (вместо самолёта из референса).
// Векторная, тематизирована под Yale Blue; окна башни генерируются циклом.
function heroIllustration() {
  const cols = [394, 410, 426, 442, 458];
  const rows = [];
  for (let y = 140; y <= 300; y += 20) rows.push(y);
  const lit = new Set(["410-160", "442-200", "394-240", "458-280", "426-140"]);
  let win = "";
  for (const x of cols) for (const y of rows) {
    const g = lit.has(`${x}-${y}`);
    win += `<rect x="${x}" y="${y}" width="10" height="12" rx="1.5" fill="${g ? "#F4B41A" : "#0A4C97"}" opacity="${g ? 1 : 0.8}"/>`;
  }
  return `<svg class="hero-svg" viewBox="0 0 560 380" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Небоскрёб и музей">
    <circle cx="452" cy="72" r="54" fill="#F4B41A" opacity="0.16"/>
    <ellipse cx="285" cy="350" rx="240" ry="18" fill="#00274D" opacity="0.30"/>
    <!-- Музей -->
    <rect x="70" y="314" width="212" height="10" rx="2" fill="#EAF0F7"/>
    <rect x="84" y="302" width="184" height="12" rx="2" fill="#fff"/>
    <rect x="94" y="216" width="164" height="88" fill="#fff"/>
    <rect x="94" y="216" width="164" height="88" fill="#00274D" opacity="0.05"/>
    <g fill="#fff">
      <rect x="106" y="224" width="16" height="80" rx="3"/><rect x="137" y="224" width="16" height="80" rx="3"/>
      <rect x="168" y="224" width="16" height="80" rx="3"/><rect x="199" y="224" width="16" height="80" rx="3"/>
      <rect x="230" y="224" width="16" height="80" rx="3"/>
    </g>
    <g fill="#00274D" opacity="0.10">
      <rect x="118" y="224" width="4" height="80"/><rect x="149" y="224" width="4" height="80"/>
      <rect x="180" y="224" width="4" height="80"/><rect x="211" y="224" width="4" height="80"/>
      <rect x="242" y="224" width="4" height="80"/>
    </g>
    <rect x="86" y="204" width="180" height="16" rx="2" fill="#EAF0F7"/>
    <path d="M176 150 L270 204 L82 204 Z" fill="#fff"/>
    <path d="M176 150 L270 204 L82 204 Z" fill="#00274D" opacity="0.05"/>
    <path d="M176 150 L270 204 L82 204" stroke="#F4B41A" stroke-width="3" stroke-linejoin="round"/>
    <circle cx="176" cy="180" r="7" fill="#F4B41A"/>
    <!-- Небоскрёб -->
    <rect x="422" y="66" width="4" height="40" fill="#EAF0F7"/>
    <circle cx="424" cy="62" r="5" fill="#F4B41A"/>
    <rect x="402" y="106" width="44" height="20" fill="#EAF0F7"/>
    <rect x="384" y="126" width="92" height="200" fill="#fff"/>
    ${win}
    <rect x="450" y="126" width="26" height="200" fill="#00274D" opacity="0.12"/>
  </svg>`;
}

async function viewHome() {
  APP().innerHTML = `
    <section class="hero">
      <div class="hero-inner">
        ${heroIllustration()}
        <div class="hero-grid">
          <div class="hero-left">
            <h1 class="hero-title">Помогаем считать<br><span class="circled"><span class="ct">сметы строительства</span><svg class="scribble" viewBox="0 0 320 96" preserveAspectRatio="none" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M28 60 C 60 22, 150 14, 236 24 C 300 32, 316 58, 286 76 C 246 100, 92 96, 44 78 C 10 66, 10 34, 40 26" stroke="#F4B41A" stroke-width="4.5" stroke-linecap="round"/></svg></span><br>по нормам РК</h1>
            <p class="hero-sub">Сервис предварительной оценки стоимости и ресурсов строительства в Казахстане.</p>
            <div class="hero-cta">
              <a class="hero-btn primary" href="#/estimates">Создать смету</a>
              <a class="hero-btn ghost" href="#/objects">Подобрать участок</a>
            </div>
          </div>
          <div class="hero-stats">
            <div class="stat big"><div class="num">27 420</div><div class="lbl">материалов с ценами в справочнике РК</div></div>
            <div class="stat"><div class="num">60+</div><div class="lbl">нормативных документов РК</div></div>
            <div class="stat"><div class="num">16</div><div class="lbl">регионов — тарифные ставки труда</div></div>
            <div class="stat"><div class="num">10 мин</div><div class="lbl">смета вместо часов ручной работы</div></div>
            <div class="stat"><div class="num">№253-VIII</div><div class="lbl">Строительный кодекс РК с 01.07.2026</div></div>
          </div>
        </div>
      </div>
    </section>

    <section class="why">
      <h2>Почему выбирают Yale Building Calculator</h2>
      <p class="why-sub">От параметров участка до ресурсной сметы по нормам РК — с проверкой площадки и справочником цен.</p>
      <div class="why-grid">
        <div class="why-card">
          <div class="ic">🏙️</div>
          <h3>Форма здания за минуты</h3>
          <p>ИИ-генератор массинга по параметрам участка с нормо- и физ-контролем.</p>
        </div>
        <div class="why-card">
          <div class="ic">📐</div>
          <h3>Смета по нормам РК</h3>
          <p>Объёмы, ресурсы и стоимость: СН РК, СНиП, ТР и новый Строительный кодекс.</p>
        </div>
        <div class="why-card">
          <div class="ic">🗺️</div>
          <h3>Проверка участка</h3>
          <p>Кадастр и генплан, тектонические разломы и сейсмика прямо на карте.</p>
        </div>
        <div class="why-card">
          <div class="ic">📊</div>
          <h3>Цены и экспорт</h3>
          <p>Реальные цены материалов РК, бенчмаркинг и выгрузка сметы в Excel.</p>
        </div>
      </div>
    </section>

    <div class="home-steps"><div class="flow"><span>Как это работает:</span>
      <b>1.</b> объект или параметры → <b>2.</b> концепт и форма здания →
      <b>3.</b> ресурсная смета → <b>4.</b> экспорт.</div></div>`;
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
    listEl.innerHTML = `<div class="list">` + rows.map((it) => {
      const total = it.status === "calculated" ? `${money(it.total)} ₸` : "—";
      return `<div class="row" data-id="${it.id}">
        <div class="code">№ ${it.id}</div>
        <div class="main"><div class="name">${escapeHtml(it.name || "Без названия")}</div>
          <div class="meta">${escapeHtml(it.object_type || "—")} · ${escapeHtml(it.city || "—")}</div></div>
        <div class="amount"><div class="total">${total}</div>
          <div class="sub">v${it.version_count} · ${it.message_count} сообщ.</div></div>
        <div class="status">${statusBadge(it.status)}</div>
        <button class="del" data-del="${it.id}" title="Удалить">✕</button>
      </div>`;
    }).join("") + `</div>`;
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
  DETAIL = {
    id, data, result: null, expanded: new Set(),
    lines: cv ? cv.result.lines.map((l) => ({ ...l, resources: (l.resources || []).map((rr) => ({ ...rr })) })) : [],
  };
  const inp = cv ? cv.input : DEFAULT_INPUT;
  const calculated = !!cv;

  APP().innerHTML = `
    <div class="page">
      <div class="breadcrumb"><a href="#/estimates">Сметы</a> / ${escapeHtml(data.estimate.name)}</div>
      <div class="title-row">
        <input class="title-edit" id="titleEdit" value="${escapeAttr(data.estimate.name)}">
        ${statusBadge(calculated ? "calculated" : "draft")}
        <div class="toolbar">
          ${calculated ? `<select class="ver-select" id="verSel" title="Версии"></select>
          <button class="btn sm accent" id="auditBtn" title="Резервный провайдер проверяет цены, объёмы и полноту">Проверить смету</button>
          <button class="btn sm" id="exportBtn">Экспорт Word</button>
          <button class="btn sm" id="exportXlsxBtn">Экспорт Excel</button>` : ""}
        </div>
      </div>
      <div class="sub-mono">№ ${id} · ${escapeHtml((inp && inp.city) || data.estimate.city || "—")}${
        data.object_id ? ` · <a href="#/object/${data.object_id}" style="color:var(--accent)">Объект №${data.object_id}</a>` : ""}</div>
      <div class="detail">
        <div class="left">
          <details class="card" ${calculated ? "" : "open"}>
            <summary>Исходные данные</summary>
            <div class="collapsible-body">
              <div id="inputs">${inputsForm(inp)}</div>
              <div class="row-actions">
                <button class="btn accent" id="calcBtn">${calculated ? "Изменить и пересчитать" : "Рассчитать"}</button>
              </div>
            </div>
          </details>
          ${calculated ? `<div class="card"><h3>Макет здания</h3>
            ${(cv && cv.input && Array.isArray(cv.input.massing) && cv.input.massing.length)
              ? `<div class="zone-warn" style="margin-bottom:8px">Активна произвольная форма ИИ (${cv.input.massing.length} бл.). Правка габаритов/формы не применяется, пока форма не сброшена. <button class="btn sm" id="resetFormBtn">Сбросить форму</button></div>`
              : `<div class="hint" style="margin-bottom:8px">Меняется при правке исходных данных (форма, габарит, этажность). Или сгенерируйте произвольную форму по описанию — ИИ проверит её на нормы РК.</div>`}
            <div class="row-actions" style="margin-bottom:8px"><button class="btn" id="genFormBtn">✨ Сгенерировать форму (ИИ)</button></div>
            <div id="smetaMassing" class="massing"></div></div>` : ""}
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
  const auditTopBtn = document.getElementById("auditBtn");
  if (auditTopBtn) auditTopBtn.addEventListener("click", runAudit);
  if (calculated) {
    renderResult(cv.result);
    buildVersionSelector(id);
    document.getElementById("exportBtn").addEventListener("click", () => exportDocx(cv.result));
    document.getElementById("exportXlsxBtn").addEventListener("click", () => exportXlsx(cv.result));
    // редактируемый 3D-макет: обновляется при правке габарита/этажности/формы в исходных данных
    const drawSmetaMassing = async () => {
      await ensureThree();
      // Если у сметы есть произвольная форма (массинг) — рендерим её, а не форму-пресет.
      if (cv.input && Array.isArray(cv.input.massing) && cv.input.massing.length) {
        renderMassingBoxes(document.getElementById("smetaMassing"), cv.input.massing,
          cv.input.floor_height || 3);
        return;
      }
      const get = (k) => Number((document.querySelector(`#inputs [data-in="${k}"]`) || {}).value || 0);
      const formEl = document.querySelector(`#inputs [data-in="form"]`);
      renderMassing(document.getElementById("smetaMassing"), {
        length: get("building_length"), width: get("building_width"),
        floors: get("floors"), floor_height: get("floor_height") || 3,
        form: formEl ? formEl.value : (inp.form || "box"),
      });
    };
    document.getElementById("genFormBtn").addEventListener("click", () => openFormGenModal({
      base: collectInputs(document.getElementById("inputs")),
      onSave: (boxes, fh) => saveGeneratedForm(id, boxes, fh),
      onClose: drawSmetaMassing,
      saveLabel: "Сохранить форму и пересчитать",
    }));
    const resetFormBtn = document.getElementById("resetFormBtn");
    if (resetFormBtn) resetFormBtn.addEventListener("click", () => {
      if (!confirm("Сбросить произвольную форму и вернуться к габаритам из исходных данных?")) return;
      DETAIL.massingReset = true;   // не подмешивать массинг в этот пересчёт
      runCalc(id);
    });
    document.querySelectorAll('#inputs [data-in="building_length"], #inputs [data-in="building_width"], ' +
      '#inputs [data-in="floors"], #inputs [data-in="floor_height"], #inputs [data-in="form"]').forEach((el) => {
      el.addEventListener("input", drawSmetaMassing);
      el.addEventListener("change", drawSmetaMassing);
    });
    snapFloorsToInt(document.querySelector('#inputs [data-in="floors"]'));
    drawSmetaMassing();
  }
  renderChat(id, calculated);
}

let _calcTimer = null;

function showCalcOverlay() {
  hideCalcOverlay();
  const ov = document.createElement("div");
  ov.className = "calc-overlay";
  ov.id = "calcOverlay";
  ov.innerHTML = `
    <div class="calc-modal" role="dialog" aria-live="polite" aria-busy="true">
      <div class="spinner"></div>
      <div class="calc-title">Идёт расчёт сметы…</div>
      <div class="calc-hint">Подбор норм РК и извлечение через ИИ может занять до минуты.
        Не закрывайте страницу.</div>
      <div class="calc-elapsed" id="calcElapsed">прошло 0 с</div>
      <ul class="steps" id="ovSteps"></ul>
    </div>`;
  document.body.appendChild(ov);
  document.body.style.overflow = "hidden";
  const started = Date.now();
  const elapsedEl = ov.querySelector("#calcElapsed");
  _calcTimer = setInterval(() => {
    elapsedEl.textContent = `прошло ${Math.round((Date.now() - started) / 1000)} с`;
  }, 1000);
  return ov.querySelector("#ovSteps");
}

function hideCalcOverlay() {
  if (_calcTimer) { clearInterval(_calcTimer); _calcTimer = null; }
  const ov = document.getElementById("calcOverlay");
  if (ov) ov.remove();
  document.body.style.overflow = "";
}

async function runCalc(id) {
  const input = collectInputs(document.getElementById("inputs"));
  // Сохранить активную ИИ-форму (массинг) между пересчётами — collectInputs её не
  // содержит. Кнопка «Сбросить форму» выставляет massingReset → откат к габаритам.
  const savedMassing = DETAIL && DETAIL.data && DETAIL.data.current_version
    && DETAIL.data.current_version.input && DETAIL.data.current_version.input.massing;
  if (!(DETAIL && DETAIL.massingReset) && Array.isArray(savedMassing) && savedMassing.length) {
    input.massing = savedMassing;
  }
  const calcBtn = document.getElementById("calcBtn");
  calcBtn.disabled = true;
  const stepsEl = showCalcOverlay();
  stepsEl.innerHTML = `<li class="running"><span class="mark">…</span><span>Запуск расчёта…</span></li>`;
  try {
    const { job_id } = await Api.calc(id, input);
    listenJob(job_id, stepsEl,
      () => { hideCalcOverlay(); toast("Смета рассчитана"); render(); },
      () => { hideCalcOverlay(); calcBtn.disabled = false; });
  } catch (e) {
    hideCalcOverlay();
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
      // ошибка парсинга/рендера не должна оставить кнопку заблокированной / EventSource открытым
      toast(err.message || "Ошибка обработки статуса", true);
      src.close(); onEnd && onEnd();
    }
  });
  src.addEventListener("end", () => { src.close(); onEnd && onEnd(); });
  src.onerror = () => { src.close(); onEnd && onEnd(); };
}

// ── ИИ-генерация формы здания (массинг) ──
// opts: { base, onSave(boxes, fh), onClose, saveLabel } — переиспользуется на экране
// сметы (пересчёт) и на экране концепта объекта (запись формы в концепт).
function openFormGenModal({ base, onSave, onClose, saveLabel }) {
  let current = null;  // последняя валидная генерация {boxes, floor_height}
  const ov = document.createElement("div");
  ov.className = "form-modal-ov";
  ov.innerHTML = `
    <div class="form-modal" role="dialog" aria-modal="true">
      <div class="fm-head">Форма здания с помощью ИИ
        <button class="fm-x" id="fmClose" aria-label="Закрыть">×</button></div>
      <div class="fm-body">
        <label class="fm-label">Опишите форму здания</label>
        <textarea id="fmDesc" class="fm-desc" rows="3"
          placeholder="напр.: Г-образный жилой дом 12 этажей; или стилобат 3 этажа с башней 16 этажей сверху"></textarea>
        <div class="row-actions">
          <button class="btn primary" id="fmGen">Сгенерировать</button>
          <span class="fm-hint">Базовые габариты — из текущих параметров. ИИ проверит форму на нормы РК.</span>
        </div>
        <div id="fmMsg" class="fm-msg"></div>
        <div id="fmPreview" class="massing fm-preview"></div>
      </div>
      <div class="fm-foot">
        <button class="btn" id="fmCancel">Отмена</button>
        <button class="btn accent" id="fmSave" disabled>${saveLabel || "Сохранить форму"}</button>
      </div>
    </div>`;
  document.body.appendChild(ov);
  document.body.style.overflow = "hidden";

  const close = () => {
    disposeMassing();
    ov.remove();
    document.body.style.overflow = "";
    if (onClose) onClose();  // восстановить макет сметы
  };
  document.getElementById("fmClose").addEventListener("click", close);
  document.getElementById("fmCancel").addEventListener("click", close);

  const msgEl = document.getElementById("fmMsg");
  const saveBtn = document.getElementById("fmSave");

  document.getElementById("fmGen").addEventListener("click", async () => {
    const desc = document.getElementById("fmDesc").value.trim();
    if (!desc) { toast("Опишите форму", true); return; }
    const genBtn = document.getElementById("fmGen");
    genBtn.disabled = true; genBtn.textContent = "Генерация…";
    msgEl.className = "fm-msg"; msgEl.textContent = "";
    current = null; saveBtn.disabled = true;
    try {
      const r = await Api.generateForm(desc, base);
      msgEl.textContent = r.message || "";
      msgEl.className = "fm-msg " + (r.status === "rejected" ? "err" : r.status === "adjusted" ? "warn" : "ok");
      if (r.status === "rejected" || !r.boxes || !r.boxes.length) {
        disposeMassing();
        document.getElementById("fmPreview").innerHTML = "";
      } else {
        await ensureThree();
        renderMassingBoxes(document.getElementById("fmPreview"), r.boxes, r.floor_height || 3);
        current = { boxes: r.boxes, floor_height: r.floor_height || 3 };
        saveBtn.disabled = false;
      }
    } catch (e) {
      msgEl.className = "fm-msg err"; msgEl.textContent = e.detail || "Ошибка генерации";
    } finally {
      genBtn.disabled = false; genBtn.textContent = "Сгенерировать";
    }
  });

  saveBtn.addEventListener("click", () => {
    if (!current) return;
    ov.remove(); document.body.style.overflow = "";
    onSave(current.boxes, current.floor_height);
  });
}

async function saveGeneratedForm(id, boxes, floor_height) {
  const input = collectInputs(document.getElementById("inputs"));
  input.massing = boxes;
  input.floor_height = floor_height || input.floor_height;
  const stepsEl = showCalcOverlay();
  stepsEl.innerHTML = `<li class="running"><span class="mark">…</span><span>Пересчёт сметы по новой форме…</span></li>`;
  try {
    const { job_id } = await Api.calc(id, input);
    listenJob(job_id, stepsEl,
      () => { hideCalcOverlay(); toast("Форма сохранена, смета пересчитана"); render(); },
      () => { hideCalcOverlay(); render(); });   // ошибка job → перерисовать макет
  } catch (e) {
    hideCalcOverlay();
    toast(e.detail || "Ошибка пересчёта", true);
    render();   // восстановить 3D-макет (превью забрало canvas из #smetaMassing)
  }
}

// ── estimate render (editable) ──
function renderResult(r) {
  DETAIL.result = r;
  const parts = [];
  // Аудит — вверху результата; запускается кнопкой «Проверить смету» в панели сверху.
  parts.push(`<div class="card" id="auditCard">
    <h3 style="margin:0 0 8px">Проверка сметы</h3>
    <div class="hint">Цены (отклонение от эталона) и объёмы (против нормы) — детерминированно; плюс резервный провайдер (рассуждающая модель) ищет любые расхождения: пропуски, лишнее, несоответствия типу, подозрительные объёмы/пропорции, ценовые аномалии.</div>
    <div id="auditResults"><div class="hint" style="margin-top:8px">Нажмите «Проверить смету» вверху страницы (рядом с кнопками экспорта).</div></div></div>`);
  if (r.warnings && r.warnings.length) {
    parts.push(`<div class="card"><h3>Предупреждения</h3><ul class="plain">` +
      r.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("") + `</ul></div>`);
  }
  if (r.sources && r.sources.length) {
    const unconf = r.sources.filter((s) => !s.confirmed).length;
    parts.push(`<div class="card">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
        <h3 style="margin:0">Нормативные источники РК</h3>
        <button class="btn sm" id="verifyNormsBtn" style="margin-left:auto" title="Проверить доступность ссылок и подтвердить через ИИ (нужен ключ)">Проверить нормы</button></div>
      <div class="hint">Сид-реестр норм РК, подобранный по типу объекта (${r.sources.length} док.).
      «не проверено» = не подтверждено онлайн-поиском${unconf ? ` (${unconf} из ${r.sources.length})` : ""}.
      «Проверить нормы» проверяет доступность ссылок и (при провайдере с ключом) подтверждает источники через ИИ.</div>
      <ul class="plain src">` +
      r.sources.map((s) => {
        const link = s.url ? `<a href="${escapeAttr(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.code)}</a>` : escapeHtml(s.code);
        const tag = s.confirmed
          ? ` <span class="sbadge ok" style="font-size:10px">проверено</span>`
          : ` <span class="badge">не проверено</span>`;
        const lk = s.link_ok === true ? ` <span style="color:var(--ok);font-size:12px">✓ ссылка ОК</span>`
          : s.link_ok === false ? ` <span style="color:var(--danger);font-size:12px">✗ ссылка не открылась</span>` : "";
        return `<li>${link} — ${escapeHtml(s.title)}${tag}${lk}</li>`;
      }).join("") + `</ul></div>`);
  }
  // editable smeta
  parts.push(`<div class="card"><h3>Смета</h3>
    <div class="table-wrap"><table class="est"><thead><tr>
      <th>№</th><th>Наименование</th><th>Ед.</th><th class="num">Кол-во</th>
      <th class="num">Материал</th><th class="num">Работа</th><th class="num">Машины</th><th class="num">Сумма ₸</th>
    </tr></thead><tbody id="smetaTbody">${renderLines(r)}</tbody></table></div>
    <div class="row-actions">
      <button class="btn accent" id="saveEditBtn">Сохранить правки</button>
      <button class="btn sm" id="satuBtn" title="Обновить цены материалов из Satu.kz (розница)">Цены материалов: Satu</button>
      <span class="hint">Раскройте строку (▸) — правьте ресурсы (расход/цена), добавляйте «+ ресурс». Сервер пересчитает итоги и создаст версию.</span>
    </div></div>`);
  parts.push(renderTotals(r.totals));
  parts.push(`<div id="recsCard"></div>`);
  document.getElementById("result").innerHTML = parts.join("");
  document.getElementById("saveEditBtn").addEventListener("click", saveManualEdit);
  const satuBtn = document.getElementById("satuBtn");
  if (satuBtn) satuBtn.addEventListener("click", suggestSatuPrices);
  const vnBtn = document.getElementById("verifyNormsBtn");
  if (vnBtn) vnBtn.addEventListener("click", verifyNorms);
  wireTable();
  loadRecs();
}

const AUDIT_CASE = { price: "цена", volume: "объём", completeness: "полнота" };
const AUDIT_SEV = { "высокий": "hi", "средний": "mid", "низкий": "lo" };

function renderAudit(rep) {
  const el = document.getElementById("auditResults");
  if (!el) return;
  if (!rep.findings.length) {
    el.innerHTML = `<div class="audit-ok">✓ ${escapeHtml(rep.summary)}</div>`;
    return;
  }
  const meta = rep.llm_used ? ` · анализ ИИ: ${escapeHtml(rep.llm_provider)}`
    : (rep.note ? ` · анализ ИИ пропущен: ${escapeHtml(rep.note)}` : "");
  el.innerHTML = `<div class="hint" style="margin:10px 0 6px">${escapeHtml(rep.summary)}${meta}</div>` +
    `<ul class="audit-list">` + rep.findings.map((f) => `<li class="af ${AUDIT_SEV[f.severity] || "lo"}">
      <span class="af-sev">${escapeHtml(f.severity)}</span>
      <div class="af-body">
        <div class="af-title"><span class="af-case">${escapeHtml(AUDIT_CASE[f.case] || f.case)}</span> ${escapeHtml(f.title)}</div>
        ${f.detail ? `<div class="af-detail">${escapeHtml(f.detail)}</div>` : ""}
        ${f.recommendation ? `<div class="af-rec">→ ${escapeHtml(f.recommendation)}</div>` : ""}
      </div></li>`).join("") + `</ul>`;
}

async function runAudit() {
  const btn = document.getElementById("auditBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Проверяю…"; }
  try {
    const rep = await Api.auditEstimate(DETAIL.id);
    renderAudit(rep);
    const hi = rep.findings.filter((f) => f.severity === "высокий").length;
    toast(rep.findings.length ? `Аудит: ${rep.findings.length} замечаний${hi ? `, высокий риск: ${hi}` : ""}`
      : "Аудит: существенных отклонений не найдено", hi > 0);
  } catch (e) {
    toast(e.detail || "Ошибка аудита сметы", true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Проверить смету"; }
  }
}

async function verifyNorms() {
  const btn = document.getElementById("verifyNormsBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Проверяю…"; }
  try {
    const r = await Api.verifyNorms(DETAIL.id);
    const llmMsg = r.llm_available
      ? `, ИИ подтвердил: ${r.confirmed}`
      : `, ИИ-подтверждение недоступно (нужен провайдер с ключом)`;
    toast(`Ссылок доступно ${r.links_ok}/${r.checked}${llmMsg}`);
    render();
  } catch (e) {
    toast(e.detail || "Ошибка проверки норм", true);
    if (btn) { btn.disabled = false; btn.textContent = "Проверить нормы"; }
  }
}

async function suggestSatuPrices() {
  syncEdits();
  const btn = document.getElementById("satuBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Запрос к Satu…"; }
  let data;
  try {
    data = await Api.suggestPrices(DETAIL.id, "satu");
  } catch (e) {
    toast(e.detail || "Источник цен недоступен", true);
    return;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Цены материалов: Satu"; }
  }
  const sugg = (data && data.suggestions) || {};
  let applied = 0, fromSatu = 0;
  DETAIL.lines.forEach((ln) => (ln.resources || []).forEach((res) => {
    const q = sugg[res.code];
    if (q && res.kind === "material") {
      if (Number(res.price) !== Number(q.price)) applied += 1;
      res.price = q.price;
      if (q.source === "satu") fromSatu += 1;
    }
  }));
  rerenderTbody();
  toast(`Цены материалов обновлены: изменено ${applied} (из Satu ${fromSatu}). Проверьте и сохраните.`);
}

// ── recommendations (типовые позиции по нормам РК, считает сервер) ──
async function loadRecs() {
  const el = document.getElementById("recsCard");
  if (!el) return;
  let recs = [];
  try { recs = await Api.recommendations(DETAIL.id); } catch (e) { el.innerHTML = ""; return; }
  if (!recs.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<div class="card"><h3>Рекомендации — что может быть не учтено</h3>
    <div class="hint">Типовые позиции по нормам РК (СН РК/ГОСТ), часто отсутствующие в предварительной смете.
    «Добавить в смету» сразу создаёт строку с рассчитанной стоимостью (укрупнённо) — её можно уточнить.</div>
    <ul class="rec-list">${recs.map((r) => `<li>
      <div><strong>${escapeHtml(r.title)}</strong>
        <span class="nrm">· ${escapeHtml(r.norm)} · ${money(r.quantity)} ${escapeHtml(r.unit)} · ≈ ${money(r.estimated_total)} ₸</span>
        <div class="hint">${escapeHtml(r.basis)}</div></div>
      <button class="btn sm" data-reckey="${escapeAttr(r.key)}">Добавить в смету</button></li>`).join("")}</ul></div>`;
  el.querySelectorAll("[data-reckey]").forEach((b) =>
    b.addEventListener("click", () => addRec(b.dataset.reckey)));
}
async function addRec(key) {
  if (!key) return;
  try {
    await Api.addRecommendation(DETAIL.id, key);
    toast("Добавлено в смету — стоимость рассчитана, можно уточнить");
    render();
  } catch (e) { toast(e.detail || "Ошибка", true); }
}
function previewTotal(ln) {
  const unit = (ln.resources || []).reduce(
    (s, res) => s + (Number(res.consumption) || 0) * (Number(res.price) || 0), 0);
  return Math.round((Number(ln.quantity) || 0) * unit);
}
function resRow(i, j, ln, res) {
  const q = (Number(res.consumption) || 0) * (Number(ln.quantity) || 0);
  const total = Math.round(q * (Number(res.price) || 0));
  const kindSel = ["material", "labor", "machine"].map((k) =>
    `<option value="${k}" ${k === res.kind ? "selected" : ""}>${KIND_LABEL[k]}</option>`).join("");
  const ed = (key, cls) => `<input class="res-edit ${cls || ""}" data-li="${i}" data-ri="${j}" data-key="${key}" value="${escapeAttr(res[key])}">`;
  return `<tr class="res-row"><td></td><td colspan="7"><div class="res-cell">
    <select class="res-edit rkindsel" data-li="${i}" data-ri="${j}" data-key="kind">${kindSel}</select>
    ${ed("name", "rname-in")}
    <span class="rsub">расход ${ed("consumption")} ${ed("unit", "unit-in")}/${escapeHtml(ln.unit)}
      · объём <b>${money(q)}</b>
      · цена ${ed("price", "wide")} ₸
      · = <span class="rsum">${money(total)} ₸</span></span>
    <button class="res-del" data-del-res="${i}:${j}" title="Удалить ресурс">✕</button>
  </div></td></tr>`;
}
function resAddRow(i) {
  return `<tr class="res-add"><td></td><td colspan="7"><div class="res-add-bar">
    <button class="btn sm tint" data-add-res="${i}">+ ресурс</button>
    <span class="hint" style="margin:0">сумма строки = объём × Σ(расход × цена)</span>
  </div></td></tr>`;
}
const SRC_LABEL = { seed: "сид", ndcs: "НДЦС", erer: "ЕРЕР", ssc: "ССЦ",
  manual: "вручную", llm: "ИИ", benchmark: "бенчмарк", import: "импорт" };
// Источник и дата актуализации цен строки + флаг несвежести (≥6 мес).
function priceMeta(ln) {
  if (!ln || (!ln.price_date && !ln.price_source)) return "";
  const src = ln.price_source ? escapeHtml(SRC_LABEL[ln.price_source] || ln.price_source) : "";
  const date = ln.price_date ? (src ? ", " : "") + escapeHtml(ln.price_date) : "";
  const meta = (src || date) ? ` <span class="pmeta" title="Источник и дата актуализации цен">[${src}${date}]</span>` : "";
  const stale = ln.price_stale
    ? ` <span class="badge stale" title="Цены не обновлялись ≥6 мес — актуализировать">≥6 мес</span>` : "";
  return meta + stale;
}
function renderLines(r) {
  const rows = [];
  const sectionTotals = r.section_totals || {};
  let section = null;
  let sIdx = 0;
  DETAIL.lines.forEach((ln, i) => {
    if (ln.section !== section) {
      section = ln.section; sIdx += 1;
      const sub = sectionTotals[ln.section];
      rows.push(`<tr class="section-row"><td class="snum">${sIdx}</td><td colspan="6">${escapeHtml(ln.section)}</td>
        <td class="num">${sub != null ? money(sub) + " ₸" : ""}</td></tr>`);
    }
    const hasRes = !!(ln.resources && ln.resources.length);
    const expanded = DETAIL.expanded.has(i);
    const qtyCell = `<input class="cell-edit" data-li="${i}" data-key="quantity" value="${escapeAttr(ln.quantity)}">`;
    const priceCell = (key) => hasRes
      ? `<span class="price">${money(ln[key])}</span>`
      : `<input class="cell-edit" data-li="${i}" data-key="${key}" value="${escapeAttr(ln[key])}">`;
    const tog = hasRes ? `<span class="tog" data-tog="${i}">${expanded ? "▾" : "▸"}</span> ` : "";
    const lineTotal = hasRes ? previewTotal(ln)
      : Math.round((Number(ln.quantity) || 0) *
          ((Number(ln.material_price) || 0) + (Number(ln.labor_price) || 0) + (Number(ln.machine_price) || 0)));
    rows.push(`<tr class="${ln.needs_review ? "review" : ""}">
      <td class="no">${escapeHtml(ln.no)}</td>
      <td>${tog}${escapeHtml(ln.title)}${ln.needs_review ? ' <span class="badge">проверить</span>' : ""}${priceMeta(ln)}</td>
      <td>${escapeHtml(ln.unit)}</td>
      <td class="num">${qtyCell}</td>
      <td class="num">${priceCell("material_price")}</td>
      <td class="num">${priceCell("labor_price")}</td>
      <td class="num">${priceCell("machine_price")}</td>
      <td class="num sum">${money(lineTotal)}</td></tr>`);
    if (hasRes && expanded) {
      ln.resources.forEach((res, j) => rows.push(resRow(i, j, ln, res)));
      rows.push(resAddRow(i));
    }
  });
  return rows.join("");
}
function syncEdits() {
  document.querySelectorAll("#smetaTbody .cell-edit").forEach((el) => {
    const ln = DETAIL.lines[Number(el.dataset.li)];
    if (ln) ln[el.dataset.key] = Number(el.value || 0);
  });
  document.querySelectorAll("#smetaTbody .res-edit").forEach((el) => {
    const ln = DETAIL.lines[Number(el.dataset.li)];
    const res = ln && ln.resources && ln.resources[Number(el.dataset.ri)];
    if (!res) return;
    const k = el.dataset.key;
    res[k] = (k === "consumption" || k === "price") ? Number(el.value || 0) : el.value;
  });
}
function rerenderTbody() {
  const tb = document.getElementById("smetaTbody");
  if (!tb || !DETAIL.result) return;
  tb.innerHTML = renderLines(DETAIL.result);
  wireTable();
}
function wireTable() {
  const tb = document.getElementById("smetaTbody");
  if (!tb) return;
  tb.querySelectorAll("[data-tog]").forEach((el) => el.addEventListener("click", () => {
    const i = Number(el.dataset.tog);
    if (DETAIL.expanded.has(i)) DETAIL.expanded.delete(i); else DETAIL.expanded.add(i);
    rerenderTbody();
  }));
  tb.querySelectorAll("[data-add-res]").forEach((b) => b.addEventListener("click", () => {
    syncEdits();
    const i = Number(b.dataset.addRes);
    const ln = DETAIL.lines[i];
    ln.resources = ln.resources || [];
    ln.resources.push({ code: "res_" + Date.now(), name: "Новый ресурс", kind: "material",
                        unit: ln.unit || "ед", consumption: 0, price: 0 });
    DETAIL.expanded.add(i);
    rerenderTbody();
  }));
  tb.querySelectorAll("[data-del-res]").forEach((b) => b.addEventListener("click", () => {
    syncEdits();
    const parts = b.dataset.delRes.split(":");
    const ln = DETAIL.lines[Number(parts[0])];
    if (ln && ln.resources) { ln.resources.splice(Number(parts[1]), 1); rerenderTbody(); }
  }));
  tb.querySelectorAll(".cell-edit, .res-edit").forEach((el) =>
    el.addEventListener("change", () => { syncEdits(); rerenderTbody(); }));
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
  syncEdits();
  try {
    const r = await Api.manualEdit(DETAIL.id, DETAIL.lines);
    if (r && r.unchanged) { toast("Изменений нет — новая версия не создана"); return; }
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
// Подгоняем высоту чат-панели под видимую область, чтобы поле ввода всегда было
// видно (sticky-панель при скролле «прилипает», JS держит её в пределах экрана).
let _chatFitBound = false;
function fitChatPanel() {
  const el = document.getElementById("chatPanel");
  if (!el) return;
  const top = el.getBoundingClientRect().top;
  const h = Math.min(window.innerHeight - top - 12, window.innerHeight - 72);
  el.style.height = Math.max(320, h) + "px";
}
function bindChatFit() {
  fitChatPanel();
  if (_chatFitBound) return;
  _chatFitBound = true;
  let raf = 0;
  const onScroll = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; fitChatPanel(); }); };
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
}

async function renderChat(id, calculated) {
  const panel = document.getElementById("chatPanel");
  let settings = null;
  try { settings = await Api.health(); } catch (e) { /* ignore */ }
  const usable = settings && settings.llm_provider !== "demo" && settings.has_key;
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
  bindChatFit();
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
  const rows = (r.lines || []).map((l) => {
    let h = `<tr>
      <td>${escapeHtml(l.no)}</td><td>${escapeHtml(l.title)}</td><td>${escapeHtml(l.norm || "")}</td>
      <td>${escapeHtml(l.unit)}</td><td class="n">${qty(l.quantity)}</td>
      <td class="n">${money(l.material_price)}</td><td class="n">${money(l.labor_price)}</td>
      <td class="n">${money(l.machine_price)}</td><td class="n">${money(l.total)}</td></tr>`;
    (l.resources || []).forEach((res) => {
      const q = (Number(res.consumption) || 0) * (Number(l.quantity) || 0);
      const tot = Math.round(q * (Number(res.price) || 0));
      h += `<tr class="res"><td></td>
        <td class="ri">${escapeHtml(res.name)} — <i>${escapeHtml(KIND_LABEL[res.kind] || res.kind)}</i>, ${money(res.price)} ₸/${escapeHtml(res.unit)}</td>
        <td></td><td>${escapeHtml(res.unit)}</td><td class="n">${qty(q)}</td>
        <td></td><td></td><td></td><td class="n">${money(tot)}</td></tr>`;
    });
    return h;
  }).join("");
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
      tr.res td { color: #555; font-size: 8.5pt; }
      td.ri { padding-left: 14pt; }
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

// ── Excel export — настоящий .xlsx (OOXML), без предупреждения «файл повреждён» ──
const _CRC_T = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1); t[n] = c >>> 0; }
  return t;
})();
function _crc32(b) { let c = 0xFFFFFFFF; for (let i = 0; i < b.length; i++) c = _CRC_T[(c ^ b[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
function _zipStore(files) {  // ZIP без сжатия (store) — достаточно для xlsx
  const enc = new TextEncoder();
  const u16 = (n) => [n & 0xFF, (n >>> 8) & 0xFF];
  const u32 = (n) => [n & 0xFF, (n >>> 8) & 0xFF, (n >>> 16) & 0xFF, (n >>> 24) & 0xFF];
  const parts = [], central = []; let offset = 0;
  for (const f of files) {
    const name = enc.encode(f.name), data = enc.encode(f.data), crc = _crc32(data), sz = data.length;
    parts.push(Uint8Array.from([0x50, 0x4b, 3, 4, ...u16(20), ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(crc), ...u32(sz), ...u32(sz), ...u16(name.length), ...u16(0)]), name, data);
    central.push(Uint8Array.from([0x50, 0x4b, 1, 2, ...u16(20), ...u16(20), ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(crc), ...u32(sz), ...u32(sz), ...u16(name.length), ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(0), ...u32(offset)]), name);
    offset += 30 + name.length + sz;
  }
  let cenLen = 0; central.forEach((c) => cenLen += c.length);
  const eocd = Uint8Array.from([0x50, 0x4b, 5, 6, ...u16(0), ...u16(0), ...u16(files.length), ...u16(files.length), ...u32(cenLen), ...u32(offset), ...u16(0)]);
  const all = [...parts, ...central, eocd]; let total = 0; all.forEach((a) => total += a.length);
  const out = new Uint8Array(total); let p = 0; for (const a of all) { out.set(a, p); p += a.length; } return out;
}
function _xlEsc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function _xlGuard(s) { return /^[=+\-@]/.test(s) ? "'" + s : s; }  // защита от формул-инъекций
function _xlCol(i) { let s = "", n = i + 1; while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); } return s; }

// rows: массив строк; ячейка — строка (текст) или {v, n:true} (число).
function _xlsxBlob(rows) {
  const cell = (ci, ri, c) => {
    const ref = _xlCol(ci) + ri;
    if (c && c.n) return `<c r="${ref}"><v>${Number(c.v) || 0}</v></c>`;
    const v = (c && typeof c === "object") ? c.v : c;
    return (v === "" || v == null) ? "" : `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${_xlEsc(_xlGuard(String(v)))}</t></is></c>`;
  };
  const sheetData = rows.map((cells, i) => `<row r="${i + 1}">${cells.map((c, ci) => cell(ci, i + 1, c)).join("")}</row>`).join("");
  const sheet = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${sheetData}</sheetData></worksheet>`;
  const files = [
    { name: "[Content_Types].xml", data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>` },
    { name: "_rels/.rels", data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>` },
    { name: "xl/workbook.xml", data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Лист1" sheetId="1" r:id="rId1"/></sheets></workbook>` },
    { name: "xl/_rels/workbook.xml.rels", data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>` },
    { name: "xl/worksheets/sheet1.xml", data: sheet },
  ];
  return new Blob([_zipStore(files)], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
}
function _download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; a.click(); URL.revokeObjectURL(a.href);
}

function exportXlsx(r) {
  const t = r.totals || {};
  const num = (v) => (Number(v) || 0);
  const S = (v) => ({ v }); const N = (v) => ({ v, n: true });
  const rows = [];
  rows.push([S(r.project_name)]);
  rows.push([S(`${r.object_type} · ${r.city} · ${r.precision_class} · ${r.generated_at}`)]);
  rows.push(["№", "Конструктив", "Работа / ресурс", "Норма", "Ед.", "Объём", "Материал", "Работа", "Машины", "Итого ₸", "Источник", "Дата цен"].map(S));
  (r.lines || []).forEach((l) => {
    rows.push([S(l.no), S(l.section), S(l.title), S(l.norm), S(l.unit), N(l.quantity), N(l.material_price), N(l.labor_price), N(l.machine_price), N(l.total),
      S((SRC_LABEL && SRC_LABEL[l.price_source]) || l.price_source || ""), S((l.price_date || "") + (l.price_stale ? " ≥6мес" : ""))]);
    (l.resources || []).forEach((res) => {
      const q = num(res.consumption) * num(l.quantity);
      rows.push([S(""), S(""), S(`${res.name} (${KIND_LABEL[res.kind] || res.kind})`), S(""), S(res.unit), N(q), N(res.price), S(""), S(""), N(Math.round(q * num(res.price))), S(res.source || ""), S(res.updated_at || "")]);
    });
  });
  const tot = (label, val) => rows.push([S(label), S(""), S(""), S(""), S(""), S(""), S(""), S(""), S(""), N(val)]);
  tot("Прямые затраты", t.direct); tot(`Накладные (${num(t.overhead_pct)}%)`, t.overhead);
  tot(`Резерв (${num(t.contingency_pct)}%)`, t.contingency); tot(`НДС (${num(t.vat_pct)}%)`, t.vat);
  tot("ИТОГО с НДС", t.grand_total);
  _download(_xlsxBlob(rows), "smeta_" + (r.project_name || "obj").replace(/[^\wа-яё-]+/gi, "_").slice(0, 40) +
    "_" + new Date().toISOString().slice(0, 10) + ".xlsx");
}

// Шаблон справочника цен (.xlsx): заголовки + примеры строк.
function downloadPriceTemplate() {
  const rows = [
    ["work_key", "code", "name", "kind", "unit", "consumption", "price", "region"],
    ["frame_concrete", "concrete_b25", "Бетон B25", "material", "м³", "1.02", "32000", "KZ"],
    ["frame_concrete", "concreter", "Бетонщик", "labor", "чел-ч", "2.9", "3800", "KZ"],
    ["roof", "membrane", "Кровельная мембрана", "material", "м²", "1.05", "9000", "KZ"],
  ];
  _download(_xlsxBlob(rows), "shablon_spravochnik_cen.xlsx");
}

// ───────────────────── справочник цен (бенчмаркинг) ─────────────────────
async function viewPrices() {
  let rows = [];
  try { rows = await Api.listBenchmark(); } catch (e) { /* ignore */ }
  APP().innerHTML = `
    <div class="page">
      <h1 class="title">Справочник цен (внутренний бенчмаркинг)</h1>
      <p class="subtitle">Свои цены имеют приоритет над сидовыми/рыночными в расчёте — по ключу работы и коду ресурса. Частичный справочник переопределяет только свои позиции, остальной состав работы сохраняется.</p>
      <div class="card">
        <div class="row-actions" style="margin-bottom:10px">
          <button class="btn" id="tplBtn">⬇ Скачать шаблон (.xlsx)</button>
          <label class="btn accent" style="cursor:pointer">⬆ Загрузить .xlsx с ценами<input type="file" id="bmXlsx" accept=".xlsx" style="display:none"></label>
        </div>
        <div class="hint" style="margin-bottom:10px">Колонки: <b>work_key</b>, <b>code</b>, name, <b>kind</b> (material/labor/machine), <b>unit</b>, consumption, <b>price</b>, region. work_key — ключ работы (frame_concrete, roof, hvac …). Скачайте шаблон, заполните в Excel, загрузите обратно.</div>
        <div id="bmList">${benchmarkRows(rows)}</div>
      </div>
      <details class="card"><summary>Добавить одну позицию вручную</summary>
        <div class="grid bm-form" style="margin-top:10px">
          <div class="field"><label>work_key</label><input id="bmWorkKey" placeholder="frame_concrete"></div>
          <div class="field"><label>Код ресурса</label><input id="bmCode" placeholder="concrete_b25"></div>
          <div class="field"><label>Название</label><input id="bmName" placeholder="Бетон B25"></div>
          <div class="field"><label>Вид</label><select id="bmKind"><option value="material">материал</option><option value="labor">труд</option><option value="machine">машины</option></select></div>
          <div class="field"><label>Ед.</label><input id="bmUnit" placeholder="м³"></div>
          <div class="field"><label>Расход на ед.</label><input id="bmCons" type="number" step="0.01" value="1"></div>
          <div class="field"><label>Цена, ₸</label><input id="bmPrice" type="number" step="1" value="0"></div>
          <div class="field"><label>Регион</label><input id="bmRegion" value="KZ"></div>
        </div>
        <div class="row-actions"><button class="btn accent" id="bmAdd">Добавить в справочник</button></div>
      </details>
    </div>`;

  document.getElementById("tplBtn").addEventListener("click", downloadPriceTemplate);
  const bmXlsx = document.getElementById("bmXlsx");
  bmXlsx.addEventListener("change", async () => {
    const file = bmXlsx.files && bmXlsx.files[0];
    if (!file) return;
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let bin = "";
      for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
      const rep = await Api.importBenchmark(btoa(bin));
      toast(`Загружено: +${rep.inserted}, обновлено ${rep.updated}, брак ${rep.skipped}`, rep.skipped > 0);
      viewPrices();
    } catch (e) { toast(e.detail || "Ошибка загрузки .xlsx", true); }
  });
  document.getElementById("bmAdd").addEventListener("click", async () => {
    const g = (id) => (document.getElementById(id).value || "").trim();
    const body = {
      work_key: g("bmWorkKey"), code: g("bmCode"), name: g("bmName"),
      kind: document.getElementById("bmKind").value, unit: g("bmUnit"),
      consumption: Number(document.getElementById("bmCons").value || 1),
      price: Number(document.getElementById("bmPrice").value || 0), region: g("bmRegion") || "KZ",
    };
    if (!body.work_key || !body.code || !body.unit) { toast("Заполните work_key, код и единицу", true); return; }
    try { await Api.addBenchmark(body); toast("Добавлено в справочник"); viewPrices(); }
    catch (e) { toast(e.detail || "Ошибка", true); }
  });
  document.querySelectorAll("[data-bm-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Удалить позицию из справочника?")) return;
    try { await Api.deleteBenchmark(b.dataset.bmDel); toast("Удалено"); viewPrices(); }
    catch (e) { toast(e.detail || "Ошибка", true); }
  }));
}

// ───────────────────────── settings ─────────────────────────
function renderSettingsLogin(msg) {
  APP().innerHTML = `
    <div class="page settings" style="max-width:420px">
      <h1 class="title">Настройки</h1>
      <p class="subtitle">Раздел защищён — войдите, чтобы продолжить.</p>
      ${msg ? `<div class="zone-warn">${escapeHtml(msg)}</div>` : ""}
      <div class="card">
        <div class="field"><label>Логин</label><input id="loginUser" type="text" value="admin"></div>
        <div class="field"><label>Пароль</label><input id="loginPass" type="password" placeholder="пароль"></div>
        <div class="row-actions"><button class="btn accent" id="loginBtn">Войти</button></div>
      </div>
    </div>`;
  const doLogin = async () => {
    const u = document.getElementById("loginUser").value;
    const p = document.getElementById("loginPass").value;
    ADMIN_AUTH = btoa(unescape(encodeURIComponent(u + ":" + p)));   // utf-8-safe base64
    try {
      await Api.listPrompts();                 // проверка по защищённому эндпоинту
      sessionStorage.setItem("adminAuth", ADMIN_AUTH);
      toast("Вход выполнен");
      viewSettings();
    } catch (e) {
      ADMIN_AUTH = null;
      toast("Неверный логин или пароль", true);
    }
  };
  document.getElementById("loginBtn").addEventListener("click", doLogin);
  document.getElementById("loginPass").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
}

// ───────────────────── справочник материалов + тарифы (SADI) ─────────────────────
function materialRows(items) {
  if (!items.length) return `<div class="empty">Ничего не найдено. Уточните запрос.</div>`;
  return `<table class="mat-table"><thead><tr>
      <th>Код</th><th>Наименование</th><th>Ед.</th><th class="r">Цена, ₸</th><th>Отдел</th></tr></thead><tbody>` +
    items.map((m) => `<tr>
      <td class="code">${escapeHtml(m.code)}</td>
      <td>${escapeHtml(m.name)}</td>
      <td class="mut">${escapeHtml(m.unit || "—")}</td>
      <td class="r">${m.price != null ? money(m.price) : "<span class='mut'>—</span>"}</td>
      <td class="mut sm">${escapeHtml((m.category || "").replace(/^Отдел\s+/, ""))}</td>
    </tr>`).join("") + `</tbody></table>`;
}

async function viewMaterials() {
  let cats = [], regions = [];
  try { cats = await Api.materialCategories(); } catch (e) { /* ignore */ }
  try { regions = await Api.tariffRegions(); } catch (e) { /* ignore */ }
  APP().innerHTML = `
    <div class="page">
      <h1 class="title">Справочник материалов и тарифов</h1>
      <p class="subtitle">Каталог материалов РК (коды НДЦС, наименования, ориентировочные цены) и
        сметные тарифные ставки труда по регионам. Источник: sadi.kz. Справочно — для подбора цен и кодов.</p>

      <div class="card">
        <div class="mat-controls">
          <input id="matQ" type="text" placeholder="Поиск: бетон, арматура, кирпич, код 21-020101…" autofocus>
          <select id="matCat"><option value="">Все отделы</option>${
            cats.map((c) => `<option value="${escapeAttr(c.category)}">${escapeHtml(c.category.replace(/^Отдел\s+/, ""))} (${c.count})</option>`).join("")}</select>
          <label class="chk"><input type="checkbox" id="matPriced" checked> только с ценой</label>
        </div>
        <div id="matMeta" class="hint" style="margin:4px 0 10px"></div>
        <div id="matResults"><div class="hint">Введите запрос — покажем до 50 позиций.</div></div>
      </div>

      <div class="card">
        <h3 style="margin:0 0 10px">Тарифные ставки труда по регионам <span class="mut sm">(ред. 2016)</span></h3>
        <div class="mat-controls">
          <select id="tarRegion">${regions.map((r) => `<option ${r === "Астана" ? "selected" : ""}>${escapeHtml(r)}</option>`).join("")}</select>
          <select id="tarKind">
            <option value="рабочие-строители/машинисты">рабочие-строители / машинисты</option>
            <option value="ИТР">инженерное звено (ИТР)</option></select>
        </div>
        <div id="tarResults" class="hint" style="margin-top:10px">Выберите регион.</div>
      </div>
    </div>`;

  const qEl = document.getElementById("matQ");
  const catEl = document.getElementById("matCat");
  const pricedEl = document.getElementById("matPriced");
  const results = document.getElementById("matResults");
  const meta = document.getElementById("matMeta");
  let timer = null;
  async function runSearch() {
    const q = qEl.value.trim();
    if (!q && !catEl.value) { results.innerHTML = `<div class="hint">Введите запрос — покажем до 50 позиций.</div>`; meta.textContent = ""; return; }
    try {
      const r = await Api.searchMaterials(q, { onlyPriced: pricedEl.checked, category: catEl.value, limit: 50 });
      meta.textContent = `Найдено ${r.total}; показаны первые ${Math.min(r.total, r.limit)}.`;
      results.innerHTML = materialRows(r.items);
    } catch (e) { results.innerHTML = `<div class="empty">Ошибка поиска.</div>`; }
  }
  const debounced = () => { clearTimeout(timer); timer = setTimeout(runSearch, 220); };
  qEl.addEventListener("input", debounced);
  catEl.addEventListener("change", runSearch);
  pricedEl.addEventListener("change", runSearch);

  const tarRegion = document.getElementById("tarRegion");
  const tarKind = document.getElementById("tarKind");
  const tarResults = document.getElementById("tarResults");
  async function runTariffs() {
    if (!tarRegion.value) return;
    try {
      const r = await Api.tariffs(tarRegion.value, tarKind.value);
      if (!r.items.length) { tarResults.innerHTML = `<div class="empty">Нет данных.</div>`; return; }
      tarResults.innerHTML = `<table class="mat-table"><thead><tr>
          <th>Разряд/должность</th><th class="r">Коэф.</th><th class="r">Ставка, ₸</th></tr></thead><tbody>` +
        r.items.map((t) => `<tr>
          <td>${escapeHtml(t.name || t.category)}</td>
          <td class="r mut">${t.coef != null ? t.coef : "—"}</td>
          <td class="r">${money(t.rate)}</td></tr>`).join("") + `</tbody></table>`;
    } catch (e) { tarResults.innerHTML = `<div class="empty">Ошибка загрузки.</div>`; }
  }
  tarRegion.addEventListener("change", runTariffs);
  tarKind.addEventListener("change", runTariffs);
  if (regions.length) runTariffs();
}

async function viewSettings() {
  if (!ADMIN_AUTH) return renderSettingsLogin();
  let s, prompts;
  try {
    s = await Api.getSettings();
    prompts = await Api.listPrompts();
  } catch (e) {
    if (e.status === 401) {
      ADMIN_AUTH = null; sessionStorage.removeItem("adminAuth");
      return renderSettingsLogin("Сессия не подтверждена — войдите снова.");
    }
    throw e;
  }
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
            <input type="text" id="apiKey" value="" autocomplete="off">
            <div class="hint" id="keyHint"></div></div>
          <div class="field"><label>Модель</label><select id="model"></select></div>
        </div>
        <div class="checks"><label><input type="checkbox" id="useSearch" ${s.use_search ? "checked" : ""}> Искать актуальные нормы РК (web-grounding)</label></div>
        <div class="checks"><label><input type="checkbox" id="crossCheck" ${s.cross_check_enabled ? "checked" : ""}> Кросс-проверка норм вторым ИИ (ансамбль) — дороже: 2 вызова</label></div>
        <div class="field"><label>Проверяющий провайдер</label>
          <select id="crossProvider">${["gemini", "anthropic", "openai"].map((p) =>
            `<option value="${p}" ${p === s.cross_check_provider ? "selected" : ""}>${p}</option>`).join("")}</select>
          <div class="hint">Должен отличаться от основного, иначе проверка не выполнится.</div></div>
        <div class="field"><label>Годовая инфляция для устаревших цен, %</label>
          <input type="number" step="0.5" min="0" id="inflation" value="${escapeAttr(s.price_inflation_annual_pct ?? 0)}">
          <div class="hint">0 = выкл. Цены старше 6 мес индексируются на этот коэффициент (НДЦС РК).</div></div>
        <div class="checks"><label><input type="checkbox" id="laborTariff" ${s.labor_tariff_enabled ? "checked" : ""}> Ставки труда по сметным тарифам SADI (регион + разряд)</label></div>
        <div class="field"><label>Индекс тарифов труда (2016 → сейчас)</label>
          <input type="number" step="0.05" min="0.1" id="laborTariffIndex" value="${escapeAttr(s.labor_tariff_index ?? 1)}">
          <div class="hint">Труд считается по тарифной ставке ₸/чел-ч региона × индекс. 1.0 — шкала 2016 ≈ рынок 2026. Выкл — цены труда из сид-каталога.</div></div>
        <div class="checks"><label><input type="checkbox" id="materialRevision" ${s.material_revision_enabled ? "checked" : ""}> Ревизия цен материалов по SADI (заниженные — до SADI; без цены — ×2.41)</label></div>
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
  const apiKeyEl = document.getElementById("apiKey");
  const keyHint = document.getElementById("keyHint");
  const maskedFor = (p) => (s.keys && s.keys[p]) || "";
  const modelFor = (p) => (s.models && s.models[p]) || s.model;
  const fillModels = () => {
    const sel = modelFor(provider);
    modelSel.innerHTML = modelsFor(provider).map((m) =>
      `<option value="${escapeAttr(m.id)}" ${m.id === sel ? "selected" : ""}>${escapeHtml(m.label)}</option>`).join("")
      || `<option value="">(нет моделей)</option>`;
  };
  // НЕ подставляем masked-ключ в редактируемое поле (иначе при смене провайдера
  // он мог бы сохраниться как чужой ключ). Поле всегда пустое; masked — в подсказке.
  const fillKeyField = () => {
    apiKeyEl.value = "";
    const masked = maskedFor(provider);
    apiKeyEl.placeholder = masked ? "ключ задан — оставьте пустым, чтобы не менять" : "вставьте ключ";
    keyHint.textContent = masked
      ? `Текущий ключ ${provider}: ${masked}. Хранится на сервере; в браузер не возвращается.`
      : `Ключ для «${provider}» не задан.`;
  };
  fillModels();
  fillKeyField();
  document.querySelectorAll("#chips .chip").forEach((c) => c.addEventListener("click", () => {
    provider = c.dataset.p;
    document.querySelectorAll("#chips .chip").forEach((x) => {
      x.classList.toggle("active", x.dataset.p === provider);
      x.textContent = x.dataset.p + (x.dataset.p === provider ? " ✓" : "");
    });
    fillModels();
    fillKeyField();
  }));

  document.getElementById("saveSettings").addEventListener("click", async () => {
    const body = {
      provider,
      model: modelSel.value || undefined,
      use_search: document.getElementById("useSearch").checked,
      cross_check_enabled: document.getElementById("crossCheck").checked,
      cross_check_provider: document.getElementById("crossProvider").value || undefined,
      price_inflation_annual_pct: Math.max(0, Number(document.getElementById("inflation").value || 0)),
      labor_tariff_enabled: document.getElementById("laborTariff").checked,
      labor_tariff_index: Math.max(0.1, Number(document.getElementById("laborTariffIndex").value || 1)),
      material_revision_enabled: document.getElementById("materialRevision").checked,
    };
    const key = apiKeyEl.value.trim();
    if (key) body.api_key = key;   // шлём только реальный новый ключ (никогда masked)
    try {
      s = await Api.putSettings(body);   // ответ содержит обновлённые per-provider карты
      fillKeyField();                    // очистить поле + показать новый masked
      toast("Настройки сохранены");
      refreshNavProvider();
    } catch (e) { toast(e.detail || "Ошибка", true); }
  });

  document.getElementById("testConn").addEventListener("click", async () => {
    const st = document.getElementById("testStatus");
    st.textContent = "Проверка…"; st.className = "test-status";
    const key = apiKeyEl.value.trim();
    const body = { provider, model: modelSel.value || undefined };
    if (key) body.api_key = key;
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

function benchmarkRows(rows) {
  if (!rows || !rows.length)
    return `<div class="hint">Справочник пуст — добавьте свои цены ниже.</div>`;
  return `<table class="bm-table"><thead><tr><th>work_key</th><th>Код</th><th>Название</th>
    <th>Вид</th><th>Ед.</th><th class="num">Расход</th><th class="num">Цена ₸</th><th>Регион</th><th></th></tr></thead><tbody>` +
    rows.map((r) => `<tr><td>${escapeHtml(r.work_key)}</td><td>${escapeHtml(r.code)}</td>
      <td>${escapeHtml(r.name)}</td><td>${escapeHtml(KIND_LABEL[r.kind] || r.kind)}</td>
      <td>${escapeHtml(r.unit)}</td><td class="num">${escapeHtml(r.consumption)}</td>
      <td class="num">${money(r.price)}</td><td>${escapeHtml(r.region)}</td>
      <td><button class="btn danger sm" data-bm-del="${r.id}">✕</button></td></tr>`).join("") +
    `</tbody></table>`;
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

// ───────────────────────── objects (SP1) ─────────────────────────
const CITY_CENTER = { "Алматы": [43.238, 76.889], "Астана": [51.128, 71.430], "Шымкент": [42.317, 69.587] };

// Leaflet подключён через <script defer>, а app.js исполняется раньше него.
// При прямом заходе/обновлении на #/objects карта рендерится до загрузки L —
// ждём, пока Leaflet и leaflet-draw станут доступны.
function ensureLeaflet() {
  return new Promise((resolve) => {
    const ready = () => window.L && window.L.map && window.L.Control && window.L.Control.Draw;
    if (ready()) return resolve();
    const t = setInterval(() => { if (ready()) { clearInterval(t); resolve(); } }, 30);
  });
}

// Three.js (3D-макет) подключён через <script defer> — ждём его перед использованием.
function ensureThree() {
  return new Promise((resolve) => {
    const ready = () => window.THREE && window.THREE.WebGLRenderer;
    if (ready()) return resolve();
    const t = setInterval(() => { if (ready()) { clearInterval(t); resolve(); } }, 30);
  });
}

function baseLayers() {
  const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "© OpenStreetMap" });
  const sat = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "© Esri" });
  return { "Схема": osm, "Спутник": sat };
}

let DRAWN = null; // {polygon, lat, lon}

async function viewObjects() {
  await ensureLeaflet();
  APP().innerHTML = `
    <div class="page">
      <div class="page-head"><h1 class="title">Объекты</h1>
        <select id="citySel" class="ver-select" style="margin-left:auto;width:160px">
          <option>Алматы</option><option>Астана</option><option>Шымкент</option></select></div>
      <div class="subtitle">Нарисуйте контур участка на карте (инструмент «прямоугольник»), затем создайте объект.</div>
      <div id="map" class="map"></div>
      <div id="objForm"></div>
      <div id="objList"></div>
    </div>`;
  const layers = baseLayers();
  const map = L.map("map", { layers: [layers["Схема"]] }).setView(CITY_CENTER["Алматы"], 12);
  L.control.layers(layers).addTo(map);
  const drawn = new L.FeatureGroup().addTo(map);
  map.addControl(new L.Control.Draw({
    draw: { polygon: false, polyline: false, circle: false, marker: false,
            circlemarker: false, rectangle: {} },
    edit: { featureGroup: drawn, edit: false, remove: true },
  }));
  map.on(L.Draw.Event.CREATED, (e) => {
    drawn.clearLayers(); drawn.addLayer(e.layer);
    const gj = e.layer.toGeoJSON().geometry;       // Polygon
    const c = e.layer.getBounds().getCenter();
    DRAWN = { polygon: gj, lat: c.lat, lon: c.lng };
    renderObjForm();
  });
  document.getElementById("citySel").addEventListener("change", (ev) =>
    map.setView(CITY_CENTER[ev.target.value] || CITY_CENTER["Алматы"], 12));
  // контейнер получает финальную ширину после вставки в DOM — пересчитываем размер,
  // иначе тайлы не покрывают карту (серая полоса справа, «уехавшая» карта)
  setTimeout(() => map.invalidateSize(), 0);
  renderObjForm();
  await drawObjList();
}

function renderObjForm() {
  const el = document.getElementById("objForm");
  if (!DRAWN) { el.innerHTML = `<div class="hint">Участок ещё не нарисован.</div>`; return; }
  el.innerHTML = `<div class="obj-form">
    <div class="field"><label>Название</label><input id="objName" type="text" value="Новый объект"></div>
    <div class="field"><label>Город</label><select id="objCity"><option>Алматы</option><option>Астана</option><option>Шымкент</option></select></div>
    <button class="btn primary" id="objSave">Создать объект</button>
    <span class="hint">центр: ${DRAWN.lat.toFixed(5)}, ${DRAWN.lon.toFixed(5)}</span></div>`;
  document.getElementById("objCity").value = document.getElementById("citySel").value;
  document.getElementById("objSave").addEventListener("click", async () => {
    const { id } = await Api.createObject({
      name: document.getElementById("objName").value,
      city: document.getElementById("objCity").value,
      lat: DRAWN.lat, lon: DRAWN.lon, polygon: DRAWN.polygon });
    DRAWN = null;
    toast("Объект создан");
    location.hash = `#/object/${id}`;
  });
}

async function drawObjList() {
  const items = await Api.listObjects();
  const el = document.getElementById("objList");
  if (!items.length) { el.innerHTML = `<div class="empty">Объектов пока нет.</div>`; return; }
  el.innerHTML = `<div class="list">` + items.map((o) => `<div class="row" data-id="${o.id}">
    <div class="code">№ ${o.id}</div>
    <div class="main"><div class="name">${escapeHtml(o.name)}</div>
      <div class="meta">${escapeHtml(o.city)} · ${money(o.area_m2)} м² · смет: ${o.estimate_count}</div></div>
    <div class="status">${statusBadge(o.status === "selected" ? "calculated" : "draft")}</div>
    <button class="del" data-del="${o.id}" title="Удалить">✕</button></div>`).join("") + `</div>`;
  el.querySelectorAll(".row").forEach((r) => r.addEventListener("click", (ev) => {
    if (ev.target.dataset.del) return;
    location.hash = `#/object/${r.dataset.id}`;
  }));
  el.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    if (!confirm("Удалить объект? Привязанные сметы останутся.")) return;
    await Api.deleteObject(b.dataset.del); toast("Объект удалён"); drawObjList();
  }));
}

async function viewObject(id) {
  await ensureLeaflet();
  const data = await Api.getObject(id);
  const o = data.object;
  APP().innerHTML = `
    <div class="page">
      <div class="breadcrumb"><a href="#/objects">Объекты</a> / ${escapeHtml(o.name)}</div>
      <div class="title-row"><input class="title-edit" id="objTitle" value="${escapeAttr(o.name)}">
        ${statusBadge(o.status === "selected" ? "calculated" : "draft")}</div>
      <div class="sub-mono">№ ${o.id} · ${escapeHtml(o.city)} · ${money(o.area_m2)} м²</div>
      <div class="detail"><div class="left">
        <div id="omap" class="map-mini"></div>
        <div id="zoneBox"></div>
        <div id="faultBox"></div>
        <div id="conceptBox"></div>
        <div class="card"><h3>Сметы объекта</h3><div id="objEsts"></div></div>
      </div></div>
    </div>`;
  // зональные поля приходят на верхнем уровне ответа — сводим в объект для рендера
  Object.assign(o, {
    zone_status: data.zone_status, zone_land_use: data.zone_land_use,
    zone_kad_nomer: data.zone_kad_nomer, zone_note: data.zone_note,
    zone_checked_at: data.zone_checked_at,
  });
  // карта с контуром + слой кадастра/зон (WMS, переключаемый)
  const layers = baseLayers();
  const map = L.map("omap", { layers: [layers["Спутник"]] }).setView([o.lat, o.lon], 16);
  try {
    const wms = await Api.zoningWms(o.city);
    const overlay = L.tileLayer.wms(wms.url, {
      layers: wms.layers, format: wms.format, transparent: true, opacity: 0.5, attribution: "© map.gov.kz",
    });
    L.control.layers(layers, { "Кадастр/зоны": overlay }).addTo(map);
  } catch (e) { L.control.layers(layers).addTo(map); /* нет слоя — не критично */ }
  if (data.polygon) {
    const gj = L.geoJSON(data.polygon, { style: { color: "#2C5BA8", weight: 2 } }).addTo(map);
    map.fitBounds(gj.getBounds(), { padding: [20, 20] });
  } else { L.marker([o.lat, o.lon]).addTo(map); }
  // ориентировочный слой тектонических разломов (красный пунктир)
  try {
    const faultsGj = await Api.zoningFaults();
    L.geoJSON(faultsGj, {
      style: { color: "#C0392B", weight: 3, dashArray: "6 5", opacity: 0.85 },
      onEachFeature: (f, layer) => layer.bindTooltip(f.properties && f.properties.name || "разлом"),
    }).addTo(map);
  } catch (e) { /* слой разломов не критичен */ }
  // пересчёт размера после вставки в DOM — тайлы иначе съезжают (серые поля)
  setTimeout(() => map.invalidateSize(), 0);

  document.getElementById("objTitle").addEventListener("change", async (ev) => {
    await Api.patchObject(id, { name: ev.target.value }); toast("Сохранено");
  });

  // список смет объекта
  const estsEl = document.getElementById("objEsts");
  estsEl.innerHTML = data.estimates.length
    ? data.estimates.map((e) => `<div class="row" data-eid="${e.id}">
        <div class="main"><div class="name">${escapeHtml(e.name)}</div></div>
        <div class="amount"><div class="total">${e.status === "calculated" ? money(e.total) + " ₸" : "—"}</div></div>
      </div>`).join("")
    : `<div class="hint">Смет ещё нет — создайте из концепта ниже.</div>`;
  estsEl.querySelectorAll("[data-eid]").forEach((r) =>
    r.addEventListener("click", () => { location.hash = `#/estimate/${r.dataset.eid}`; }));

  renderZone(id, o);
  renderFaults(data.faults);
  await renderConcept(id, o.city, data.estimates, data.faults);
}

function faultBadge(status) {
  const map = { ok: ["ok", "разломов нет"], caution: ["draft", "повышенный риск"], avoid: ["rejected", "не рекомендуется"] };
  const [cls, label] = map[status] || map.ok;
  return `<span class="sbadge ${cls}">${label}</span>`;
}

function renderFaults(f) {
  const box = document.getElementById("faultBox");
  if (!box) return;
  if (!f) { box.innerHTML = ""; return; }
  const rows = [];
  if (f.nearest_fault)
    rows.push(`<div class="meta">Ближайший разлом: <b>${escapeHtml(f.nearest_fault)}</b> · ~${money(f.distance_m)} м</div>`);
  rows.push(`<div class="meta">Сейсмичность: <b>${f.intensity} баллов</b>${
    f.max_floors ? ` · рекоменд. этажность ≤ <b>${f.max_floors}</b>` : " · ограничений по высоте нет"}</div>`);
  if (f.note) rows.push(`<div class="zone-warn">⚠ ${escapeHtml(f.note)}</div>`);
  rows.push(`<div class="meta muted">Источник: ${escapeHtml(f.source || "")}</div>`);
  box.innerHTML = `<div class="concept-panel"><h3>Сейсмика и разломы</h3>
    <div class="zone-line">${faultBadge(f.status)}</div>
    <div>${rows.join("")}</div></div>`;
}

function zoneBadge(status) {
  const map = { allowed: ["ok", "разрешено"], restricted: ["rejected", "ограничено"], unknown: ["draft", "не проверено"] };
  const [cls, label] = map[status] || map.unknown;
  return `<span class="sbadge ${cls}">${label}</span>`;
}

function zoneDetails(o) {
  if (!o.zone_status) return "";
  const rows = [];
  if (o.zone_kad_nomer) rows.push(`<div class="meta">Кад. номер: <b>${escapeHtml(o.zone_kad_nomer)}</b></div>`);
  if (o.zone_land_use) rows.push(`<div class="meta">Назначение: ${escapeHtml(o.zone_land_use)}</div>`);
  if (o.zone_note) rows.push(`<div class="zone-warn">⚠ ${escapeHtml(o.zone_note)}</div>`);
  rows.push(`<div class="meta muted">Источник: map.gov.kz (WFS)${o.zone_checked_at ? " · " + escapeHtml(o.zone_checked_at) : ""}</div>`);
  return rows.join("");
}

function renderZone(id, o) {
  const box = document.getElementById("zoneBox");
  const has = o.zone_status;
  box.innerHTML = `<div class="concept-panel"><h3>Генплан / кадастр</h3>
    <div class="zone-line">${has ? zoneBadge(o.zone_status) : `<span class="hint">Участок ещё не проверялся.</span>`}
      <button class="btn ${has ? "" : "accent"}" id="zoneBtn" style="margin-left:auto">${has ? "Перепроверить" : "Проверить участок"}</button></div>
    <div id="zoneDetails">${zoneDetails(o)}</div></div>`;
  document.getElementById("zoneBtn").addEventListener("click", async () => {
    const btn = document.getElementById("zoneBtn"); btn.disabled = true; btn.textContent = "Проверяю…";
    try {
      const v = await Api.checkZone(id);
      Object.assign(o, { zone_status: v.status, zone_land_use: v.land_use,
        zone_kad_nomer: v.kad_nomer, zone_note: v.note, zone_checked_at: v.checked_at });
      toast("Проверка выполнена");
      renderZone(id, o);
    } catch (e) { toast(e.detail || "Ошибка проверки", true); btn.disabled = false; btn.textContent = "Проверить участок"; }
  });
}

async function renderConcept(id, city, estimates, faults) {
  const box = document.getElementById("conceptBox");
  const has = estimates && estimates.length ? estimates[0] : null;
  const floorCap = faults && faults.max_floors ? faults.max_floors : null;
  const formOpts = BUILDING_FORMS.map((f) => `<option value="${f.key}">${f.label}</option>`).join("");
  box.innerHTML = `<div class="concept-panel"><h3>Концепт здания</h3>
    ${has ? `<div class="zone-warn">Для объекта уже создана смета «${escapeHtml(has.name)}» (№${has.id}).
      <a href="#/estimate/${has.id}">Открыть</a> — повторное создание заблокировано.</div>` : ""}
    <div class="obj-form">
      <div class="field"><label>Тип объекта</label><select id="cType">
        <option>Жилой дом</option><option>Общественное здание</option><option>Промышленное здание</option></select></div>
      <div class="field"><label>Форма</label><select id="cForm">${formOpts}</select></div>
      <button class="btn" id="cReload">Предложить</button>
    </div>
    <div id="cFields" class="hint">Нажмите «Предложить», чтобы система рассчитала параметры под участок.</div>
    <div id="faultFloorWarn"></div>
    <div class="row-actions" style="margin-bottom:8px"><button class="btn" id="cGenForm" disabled>✨ Сгенерировать форму (ИИ)</button></div>
    <div id="massing" class="massing"></div>
    <div class="row-actions"><button class="btn accent" id="cToEstimate" disabled>Создать смету</button></div>
  </div>`;
  let concept = null;
  // Физический максимум площади = габариты × коэф.формы × этажность (как в propose_concept).
  const maxTotal = () => {
    const get = (k) => Number((document.querySelector(`#cFields [data-ck="${k}"]`) || {}).value || 0);
    return Math.round(get("building_length") * get("building_width")
      * footprintFactor(document.getElementById("cForm").value) * get("floors"));
  };
  const totalField = () => document.querySelector('#cFields [data-ck="total_area"]');
  const usingMassing = () => concept && Array.isArray(concept.massing) && concept.massing.length;
  // Правка габаритов/формы/этажности → площадь = максимум (отражает форму).
  const recomputeTotal = () => {
    const el = totalField();
    if (el && !usingMassing()) el.value = maxTotal();
  };
  // Предупреждение по этажности от сейсмо/разломного скрининга (мягкое — не блокируем).
  const checkFloorLimit = () => {
    const warn = document.getElementById("faultFloorWarn");
    if (!warn) return;
    const el = document.querySelector('#cFields [data-ck="floors"]');
    const floors = Number((el || {}).value || 0);
    if (floorCap && floors > floorCap) {
      warn.innerHTML = `<div class="zone-warn">⚠ Этажность ${floors} превышает рекомендованный
        по сейсмике/разломам предел (${floorCap} эт.). Это повышает сейсмориск — снизьте высоту
        или предусмотрите усиленную сейсмозащиту.</div>`;
    } else { warn.innerHTML = ""; }
  };
  // Ручная правка площади — можно занизить, но не выше максимума.
  const clampTotal = () => {
    const el = totalField();
    if (el && !usingMassing() && Number(el.value || 0) > maxTotal()) el.value = maxTotal();
  };
  const drawMassing = async () => {
    await ensureThree();
    // Если для концепта сгенерирована ИИ-форма — рендерим её, а не пресет.
    if (concept && Array.isArray(concept.massing) && concept.massing.length) {
      renderMassingBoxes(document.getElementById("massing"), concept.massing,
        concept.floor_height || 3);
      return;
    }
    const get = (k) => Number((document.querySelector(`#cFields [data-ck="${k}"]`) || {}).value || 0);
    renderMassing(document.getElementById("massing"), {
      length: get("building_length"), width: get("building_width"),
      floors: get("floors"), floor_height: (concept && concept.floor_height) || 3,
      form: document.getElementById("cForm").value,
    });
  };
  const load = async () => {
    try {
      concept = await Api.objectConcept(id, document.getElementById("cType").value, null,
        document.getElementById("cForm").value);
      document.getElementById("cFields").innerHTML = `<div class="grid">
        ${cField("Этажность", "floors", concept.floors)}
        ${cField("Габарит длина, м", "building_length", concept.building_length)}
        ${cField("Габарит ширина, м", "building_width", concept.building_width)}
        ${cField("Общая площадь, м²", "total_area", concept.total_area)}
      </div>`;
      document.getElementById("cToEstimate").disabled = !!has;
      document.getElementById("cGenForm").disabled = !!has;
      // площадь: правка габаритов/этажности → максимум; ручная правка площади → зажать ≤ максимума
      document.querySelectorAll("#cFields [data-ck]").forEach((el) => {
        if (el.dataset.ck === "total_area") {
          el.addEventListener("input", clampTotal);
        } else if (el.dataset.ck === "floors") {
          el.addEventListener("input", () => { recomputeTotal(); drawMassing(); checkFloorLimit(); });
        } else {
          el.addEventListener("input", () => { recomputeTotal(); drawMassing(); });
        }
      });
      snapFloorsToInt(document.querySelector('#cFields [data-ck="floors"]'));
      clampTotal();   // на загрузке: если предложенная площадь выше максимума — поджать
      checkFloorLimit();
      drawMassing();
    } catch (e) {
      document.getElementById("cFields").innerHTML =
        `<div class="zone-warn">Не удалось рассчитать концепт: ${escapeHtml(e.detail || e.message || e)}</div>`;
      toast("Ошибка концепта: " + (e.detail || "см. сообщение"), true);
    }
  };
  document.getElementById("cReload").addEventListener("click", load);
  // смена формы — перезапрос концепта (форма меняет площадь) + перерисовка макета
  document.getElementById("cForm").addEventListener("change", load);
  document.getElementById("cGenForm").addEventListener("click", () => {
    if (!concept) return;
    const get = (k) => Number((document.querySelector(`#cFields [data-ck="${k}"]`) || {}).value || 0);
    openFormGenModal({
      base: {
        object_type: document.getElementById("cType").value,
        building_length: get("building_length"), building_width: get("building_width"),
        floors: get("floors"), floor_height: concept.floor_height || 3,
      },
      onSave: (boxes, fh) => {
        concept.massing = boxes;
        concept.floor_height = fh;
        const totalEl = document.querySelector('#cFields [data-ck="total_area"]');
        if (totalEl) totalEl.value = Math.round(boxes.reduce((s, b) => s + b.w * b.d * b.floors, 0));
        drawMassing();
        toast("Форма ИИ применена — нажмите «Создать смету»");
      },
      onClose: drawMassing,
      saveLabel: "Применить форму",
    });
  });
  document.getElementById("cToEstimate").addEventListener("click", async () => {
    // одна смета на объект: если уже есть — предложить перейти, не плодить дубли
    if (has) {
      if (confirm(`У объекта уже есть смета «${has.name}» (№${has.id}). Перейти к ней?`))
        location.hash = `#/estimate/${has.id}`;
      return;
    }
    document.querySelectorAll("#cFields [data-ck]").forEach((el) => {
      const val = Number(el.value || 0);
      concept[el.dataset.ck] = el.dataset.ck === "floors" ? Math.max(1, Math.round(val)) : val;
    });
    const btn = document.getElementById("cToEstimate");
    btn.disabled = true;
    const stepsEl = showCalcOverlay();
    stepsEl.innerHTML = `<li class="running"><span class="mark">…</span><span>Запуск расчёта…</span></li>`;
    try {
      const { job_id, estimate_id } = await Api.objectCreateEstimate(id, concept);
      listenJob(job_id, stepsEl,
        () => { hideCalcOverlay(); toast("Смета создана из концепта"); location.hash = `#/estimate/${estimate_id}`; },
        () => { hideCalcOverlay(); btn.disabled = false; });
    } catch (e) {
      hideCalcOverlay();
      btn.disabled = false;
      toast("Не удалось создать смету: " + (e.detail || ""), true);
    }
  });
  await load();
}
function cField(label, key, val) {
  // total_area — редактируема, но не выше физического максимума (габариты×форма×этажность);
  // при правке габаритов/формы пересчитывается автоматически.
  if (key === "total_area")
    return `<div class="field"><label>${label}</label>
      <input type="number" step="1" min="0" data-ck="${key}" value="${escapeAttr(val)}"
        title="не больше габариты × форма × этажность; можно занизить вручную"></div>`;
  const attrs = key === "floors" ? `step="1" min="1"` : `step="0.1"`;  // этажи — целые
  return `<div class="field"><label>${label}</label>
    <input type="number" ${attrs} data-ck="${key}" value="${escapeAttr(val)}"></div>`;
}

// ── 3D-макет здания (массинг) на Three.js ──
// Ключи форм синхронны с backend app/calc/forms.py
// fp — коэффициент застройки (доля от bbox), синхронно с backend app/calc/forms.py
const BUILDING_FORMS = [
  { key: "box", label: "Брусок", fp: 1.00 },
  { key: "tower", label: "Башня", fp: 0.70 },
  { key: "court", label: "L / П-двор", fp: 0.72 },
  { key: "stepped", label: "Ступенчатое", fp: 0.90 },
  { key: "dome", label: "Купол (hi-fi)", fp: 0.85 },
  { key: "gable", label: "Дом со скатной крышей", fp: 1.00 },
  { key: "podium", label: "Стилобат + башня", fp: 0.85 },
  { key: "cylinder", label: "Цилиндр", fp: 0.80 },
];
function footprintFactor(form) {
  const f = BUILDING_FORMS.find((x) => x.key === form);
  return f ? f.fp : 1.0;
}

let _massing = null;  // активный рендер-цикл, чтобы переиспользовать/гасить

function disposeMassing() {
  if (_massing) { try { _massing.dispose(); } catch (e) { /* ignore */ } _massing = null; }
}

// один прямоугольный корпус: стены + рёбра + линии этажей (как полосы окон)
function _massBlock(T, group, mats, b) {
  const geo = new T.BoxGeometry(b.w, b.h, b.d);
  const m = new T.Mesh(geo, mats.wall);
  m.castShadow = true; m.receiveShadow = true;
  m.position.set(b.x0 || 0, b.y0 + b.h / 2, b.z0 || 0);
  group.add(m);
  const e = new T.LineSegments(new T.EdgesGeometry(geo), mats.edge);
  e.position.copy(m.position); group.add(e);
  const fl = Math.max(1, Math.round(b.floors || (b.h / (b.fh || 3))));
  const x = b.x0 || 0, z = b.z0 || 0, w = b.w / 2, d = b.d / 2;
  for (let i = 1; i < fl; i++) {
    const y = b.y0 + i * (b.h / fl);
    const pts = [new T.Vector3(x - w, y, z - d), new T.Vector3(x + w, y, z - d),
      new T.Vector3(x + w, y, z + d), new T.Vector3(x - w, y, z + d), new T.Vector3(x - w, y, z - d)];
    group.add(new T.Line(new T.BufferGeometry().setFromPoints(pts), mats.floor));
  }
}

// вальмовая (скатная) крыша L×D высотой h над уровнем baseY
function _roofMesh(T, mat, L, D, baseY, h) {
  const hx = L / 2, hz = D / 2, ay = baseY + h;
  const v = [-hx, baseY, -hz, hx, baseY, -hz, hx, baseY, hz, -hx, baseY, hz, 0, ay, 0];
  const geo = new T.BufferGeometry();
  geo.setAttribute("position", new T.Float32BufferAttribute(v, 3));
  geo.setIndex([0, 1, 4, 1, 2, 4, 2, 3, 4, 3, 0, 4]);
  geo.computeVertexNormals();
  const m = new T.Mesh(geo, mat); m.castShadow = true;
  return m;
}

// вертикальный цилиндр с кольцами-этажами (для «цилиндр»/тела купола)
function _cylinder(T, g, mats, r, h, n) {
  const cyl = new T.Mesh(new T.CylinderGeometry(r, r, h, 48), mats.wall);
  cyl.position.y = h / 2; cyl.castShadow = true; cyl.receiveShadow = true; g.add(cyl);
  const ringMat = new T.MeshBasicMaterial({ color: 0x2C5BA8 });
  for (let i = 1; i < n; i++) {
    const ring = new T.Mesh(new T.TorusGeometry(r * 1.002, r * 0.01, 8, 48), ringMat);
    ring.position.y = i * (h / n); ring.rotation.x = Math.PI / 2; g.add(ring);
  }
}

// строим группу здания нужной формы; возвращаем {group, height}
function _massMats(T) {
  return {
    wall: new T.MeshStandardMaterial({ color: 0x9DB4D4, roughness: 0.62, metalness: 0.05 }),
    edge: new T.LineBasicMaterial({ color: 0x2C5BA8 }),
    floor: new T.LineBasicMaterial({ color: 0x2C5BA8, transparent: true, opacity: 0.28 }),
    roof: new T.MeshStandardMaterial({ color: 0x6E8CB8, roughness: 0.6, metalness: 0.05 }),
  };
}

// Произвольный массинг: набор блоков {x,y,w,d,floors,base}, центрированный в сцене.
function buildBoxes(T, boxes, fh) {
  const g = new T.Group();
  if (!boxes || !boxes.length) return { group: g, height: Math.max(1, fh || 3) };
  const mats = _massMats(T);
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, top = 0;
  boxes.forEach((b) => {
    minX = Math.min(minX, b.x); maxX = Math.max(maxX, b.x + b.w);
    minY = Math.min(minY, b.y); maxY = Math.max(maxY, b.y + b.d);
    top = Math.max(top, (b.base + b.floors) * fh);
  });
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  boxes.forEach((b) => _massBlock(T, g, mats, {
    w: b.w, d: b.d, h: b.floors * fh, y0: b.base * fh,
    x0: (b.x + b.w / 2) - cx, z0: (b.y + b.d / 2) - cy, floors: b.floors, fh,
  }));
  return { group: g, height: top, span: Math.max(maxX - minX, maxY - minY) };
}

function buildBuilding(T, form, L, D, n, fh) {
  const g = new T.Group();
  const mats = _massMats(T);
  const Ht = n * fh;
  if (form === "tower") {
    _massBlock(T, g, mats, { w: L * 0.78, d: D * 0.78, h: Ht, y0: 0, floors: n, fh });
    return { group: g, height: Ht };
  }
  if (form === "stepped") {
    const hp = Ht / 3, fp = Math.max(1, Math.round(n / 3));
    [[1.0, 0], [0.72, 1], [0.48, 2]].forEach(([s, i]) =>
      _massBlock(T, g, mats, { w: L * s, d: D * s, h: hp, y0: i * hp, floors: fp, fh }));
    return { group: g, height: Ht };
  }
  if (form === "court") {
    const t = Math.min(L, D) * 0.28;           // толщина корпуса
    const ox = (L - t) / 2, oz = (D - t) / 2;
    _massBlock(T, g, mats, { w: L, d: t, h: Ht, y0: 0, z0: -oz, floors: n, fh });
    _massBlock(T, g, mats, { w: L, d: t, h: Ht, y0: 0, z0: oz, floors: n, fh });
    _massBlock(T, g, mats, { w: t, d: D - 2 * t, h: Ht, y0: 0, x0: -ox, floors: n, fh });
    _massBlock(T, g, mats, { w: t, d: D - 2 * t, h: Ht, y0: 0, x0: ox, floors: n, fh });
    return { group: g, height: Ht };
  }
  if (form === "dome") {
    const r = Math.min(L, D) / 2, bodyH = Ht * 0.82;
    _cylinder(T, g, mats, r, bodyH, n);
    const dome = new T.Mesh(new T.SphereGeometry(r, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2), mats.wall);
    dome.position.y = bodyH; dome.castShadow = true; g.add(dome);
    return { group: g, height: bodyH + r };
  }
  if (form === "cylinder") {
    const r = Math.min(L, D) / 2;
    _cylinder(T, g, mats, r, Ht, n);
    return { group: g, height: Ht };
  }
  if (form === "gable") {
    _massBlock(T, g, mats, { w: L, d: D, h: Ht, y0: 0, floors: n, fh });
    g.add(_roofMesh(T, mats.roof, L, D, Ht, Math.max(2, Math.min(L, D) * 0.45)));
    return { group: g, height: Ht + Math.min(L, D) * 0.45 };
  }
  if (form === "podium") {
    const podFloors = Math.max(1, Math.round(n * 0.3)), podH = podFloors * fh;
    _massBlock(T, g, mats, { w: L, d: D, h: podH, y0: 0, floors: podFloors, fh });
    const towF = Math.max(1, n - podFloors);
    _massBlock(T, g, mats, { w: L * 0.55, d: D * 0.55, h: towF * fh, y0: podH, floors: towF, fh });
    return { group: g, height: podH + towF * fh };
  }
  // box (по умолчанию)
  _massBlock(T, g, mats, { w: L, d: D, h: Ht, y0: 0, floors: n, fh });
  return { group: g, height: Ht };
}

function renderMassing(container, dims) {
  if (!container || !window.THREE) return;
  const T = window.THREE;
  const L = Math.max(1, dims.length || 1), D = Math.max(1, dims.width || 1);
  const n = Math.max(1, Math.round(dims.floors || 1));
  const fh = dims.floor_height || 3;
  const built = buildBuilding(T, dims.form || "box", L, D, n, fh);
  _mountMassing(container, built, Math.max(L, D, built.height));
}

// Рендер произвольного массинга (JSON-рецепт из блоков) — та же геометрия, что и в смете.
function renderMassingBoxes(container, boxes, floor_height) {
  if (!container || !window.THREE) return;
  const T = window.THREE;
  const built = buildBoxes(T, boxes, floor_height || 3);
  _mountMassing(container, built, Math.max(built.span || 1, built.height || 1));
}

function _mountMassing(container, built, maxDim) {
  disposeMassing();
  const T = window.THREE;
  const W = container.clientWidth || 360, H = container.clientHeight || 240;
  maxDim = Math.max(maxDim || 1, 1);

  const scene = new T.Scene();
  scene.background = new T.Color(0xEFEEEA);
  const camera = new T.PerspectiveCamera(45, W / H, 0.1, 100000);
  const renderer = new T.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  renderer.setSize(W, H);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFSoftShadowMap;
  container.innerHTML = "";
  container.appendChild(renderer.domElement);

  scene.add(built.group);
  const height = built.height;

  // площадка-участок (принимает тень)
  const pad = new T.Mesh(new T.PlaneGeometry(maxDim * 2.4, maxDim * 2.4),
    new T.MeshStandardMaterial({ color: 0xE2E0DA, roughness: 1 }));
  pad.rotation.x = -Math.PI / 2; pad.receiveShadow = true; scene.add(pad);

  // свет: небо-земля + солнце с мягкой тенью
  scene.add(new T.HemisphereLight(0xffffff, 0xb9b6ad, 0.85));
  const sun = new T.DirectionalLight(0xffffff, 0.75);
  sun.position.set(maxDim * 0.8, maxDim * 1.7, maxDim * 0.9);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  const sc = sun.shadow.camera;
  sc.left = -maxDim; sc.right = maxDim; sc.top = maxDim; sc.bottom = -maxDim;
  sc.near = 0.5; sc.far = maxDim * 6; sc.updateProjectionMatrix();
  scene.add(sun);

  camera.position.set(maxDim * 1.5, maxDim * 1.15, maxDim * 1.85);
  camera.lookAt(0, height / 2, 0);

  let controls = null;
  if (T.OrbitControls) {
    controls = new T.OrbitControls(camera, renderer.domElement);
    controls.target.set(0, height / 2, 0);
    controls.enablePan = false;
    controls.minDistance = maxDim * 0.7;
    controls.maxDistance = maxDim * 5;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 1.1;
    controls.update();
  }

  let raf = 0;
  const animate = () => {
    if (!document.body.contains(renderer.domElement)) { disposeMassing(); return; }
    raf = requestAnimationFrame(animate);
    if (controls) controls.update();
    else { built.group.rotation.y += 0.005; }
    renderer.render(scene, camera);
  };
  animate();

  const onResize = () => {
    const w = container.clientWidth || W, h = container.clientHeight || H;
    camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.setSize(w, h);
  };
  window.addEventListener("resize", onResize);

  _massing = {
    dispose() {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      if (controls) controls.dispose();
      renderer.dispose();
      if (renderer.domElement && renderer.domElement.parentNode) renderer.domElement.remove();
    },
  };
}

// ───────────────────────── init ─────────────────────────
render();
