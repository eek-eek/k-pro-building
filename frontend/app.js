"use strict";

const API = window.API_BASE || "";
const $ = (id) => document.getElementById(id);
const resultEl = $("result");
const statusEl = $("status");
const stepsEl = $("steps");

let lastResult = null;
let activeSource = null;

const defaultWorks = [
  "Подготовительные работы и временные сооружения",
  "Земляные работы и вывоз грунта",
  "Фундаменты и монолитные железобетонные конструкции",
  "Армирование конструкций",
  "Кладка наружных/внутренних стен и перегородок",
  "Гидроизоляция и теплоизоляция",
  "Кровля",
  "Фасадные работы",
  "Окна, витражи, наружные двери",
  "Черновая и чистовая отделка",
  "Внутренние сети ОВиК",
  "Водоснабжение и канализация",
  "Электромонтажные работы",
  "Слаботочные системы",
  "Благоустройство и наружные сети",
];

// ── Вкладки ──
document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".pane").forEach((x) => x.classList.remove("active"));
    button.classList.add("active");
    $(button.dataset.tab).classList.add("active");
  });
});

// ── Виды работ ──
function getWorks() {
  try {
    const saved = JSON.parse(localStorage.getItem("ai_smeta_works") || "null");
    if (Array.isArray(saved) && saved.length) return saved;
  } catch (e) { /* ignore */ }
  return [...defaultWorks];
}

function renderWorks() {
  const list = $("workList");
  list.innerHTML = "";
  getWorks().forEach((text, index) => {
    const item = document.createElement("div");
    item.className = "work-item";
    item.innerHTML =
      `<input type="checkbox" checked data-work-check="${index}">` +
      `<span>${escapeHtml(text)}</span>` +
      `<button type="button" data-remove-work="${index}">Удалить</button>`;
    list.appendChild(item);
  });
  list.querySelectorAll("[data-remove-work]").forEach((button) => {
    button.addEventListener("click", () => {
      const works = getWorks();
      works.splice(Number(button.dataset.removeWork), 1);
      localStorage.setItem("ai_smeta_works", JSON.stringify(works));
      renderWorks();
    });
  });
}

function selectedWorks() {
  const works = getWorks();
  return [...document.querySelectorAll("[data-work-check]")]
    .filter((x) => x.checked)
    .map((x) => works[Number(x.dataset.workCheck)]);
}

$("addWork").addEventListener("click", () => {
  const value = $("workInput").value.trim();
  if (!value) return;
  const works = getWorks();
  works.push(value);
  localStorage.setItem("ai_smeta_works", JSON.stringify(works));
  $("workInput").value = "";
  renderWorks();
});

// ── Сбор входных данных ──
function collectInput() {
  const numv = (id) => Number($(id).value || 0);
  return {
    project_name: $("projectName").value,
    city: $("city").value,
    object_type: $("objectType").value,
    floors: numv("floors"),
    total_area: numv("totalArea"),
    building_length: numv("buildingLength"),
    building_width: numv("buildingWidth"),
    floor_height: numv("floorHeight"),
    structure_type: $("structureType").value,
    foundation_type: $("foundationType").value,
    finish_level: $("finishLevel").value,
    engineering_level: $("engineeringLevel").value,
    basement: $("basement").checked,
    parking: $("parking").checked,
    use_search: $("useSearch").checked,
    demo_mode: $("demoMode").checked,
    overhead_pct: numv("overhead"),
    contingency_pct: numv("contingency"),
    vat_pct: numv("vat"),
    works: selectedWorks(),
    assumptions: $("assumptions").value,
  };
}

// ── Запуск расчёта ──
$("runButton").addEventListener("click", () => runEstimate(false));
$("demoButton").addEventListener("click", () => {
  $("demoMode").checked = true;
  runEstimate(true);
});
$("saveButton").addEventListener("click", saveResult);
$("copyButton").addEventListener("click", copyResult);

async function runEstimate() {
  setBusy(true);
  resultEl.innerHTML = '<div class="placeholder">Идёт расчёт…</div>';
  if (activeSource) { activeSource.close(); activeSource = null; }
  try {
    const input = collectInput();
    const resp = await fetch(`${API}/api/estimate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!resp.ok) throw new Error(await resp.text());
    const { job_id } = await resp.json();
    listen(job_id);
  } catch (error) {
    showError(error);
    setBusy(false);
  }
}

function listen(jobId) {
  const source = new EventSource(`${API}/api/estimate/${jobId}/events`);
  activeSource = source;
  let gotResult = false; // успех именно этого запуска (не глобальный lastResult)

  source.addEventListener("status", (event) => {
    try {
      const status = JSON.parse(event.data);
      renderSteps(status.steps || []);
      if (status.status === "error") {
        showError(new Error(status.error || "Ошибка расчёта"));
        finish(source);
      } else if (status.status === "done" && status.result) {
        lastResult = status.result;
        gotResult = true;
        renderEstimate(status.result);
        setStatus("Смета сформирована.");
        finish(source);
      }
    } catch (err) {
      // ошибка парсинга/рендера не должна оставить кнопки заблокированными
      showError(err);
      finish(source);
    }
  });

  source.addEventListener("end", () => finish(source));
  source.onerror = () => {
    // соединение закрыто — если результат этого запуска уже есть, просто выходим
    if (!gotResult) setStatus("Соединение со статусами прервано.", true);
    finish(source);
  };
}

function finish(source) {
  source.close();
  if (activeSource === source) activeSource = null;
  setBusy(false);
}

// ── Рендер шагов ──
function renderSteps(steps) {
  stepsEl.innerHTML = "";
  steps.forEach((step) => {
    const li = document.createElement("li");
    li.className = step.status;
    const mark = step.status === "done" ? "✓" : step.status === "error" ? "!" : "";
    li.innerHTML =
      `<span class="dot">${mark}</span>` +
      `<span>${escapeHtml(step.label)}` +
      (step.detail ? ` <span class="detail">— ${escapeHtml(step.detail)}</span>` : "") +
      `</span>`;
    stepsEl.appendChild(li);
  });
}

// ── Рендер сметы ──
function money(value) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value || 0);
}
function qty(value) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value || 0);
}

function renderEstimate(r) {
  const parts = [];

  parts.push(`<div class="est-block"><h3>${escapeHtml(r.project_name)}</h3>
    <div class="hint">${escapeHtml(r.object_type)} · ${escapeHtml(r.city)} ·
    класс точности: ${escapeHtml(r.precision_class)} · сформировано ${escapeHtml(r.generated_at)}</div></div>`);

  if (r.warnings && r.warnings.length) {
    parts.push(`<div class="est-block"><h3>Предупреждения</h3><ul class="plain">` +
      r.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("") + `</ul></div>`);
  }

  if (r.sources && r.sources.length) {
    parts.push(`<div class="est-block"><h3>Нормативные источники РК</h3><ul class="src-list">` +
      r.sources.map((s) => {
        const link = s.url ? `<a href="${escapeAttr(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.code)}</a>` : escapeHtml(s.code);
        const tag = s.confirmed ? "" : ` <span class="badge">не подтверждено</span>`;
        return `<li>${link} — ${escapeHtml(s.title)}${tag}</li>`;
      }).join("") + `</ul></div>`);
  }

  if (r.volumes && r.volumes.length) {
    parts.push(`<div class="est-block"><h3>Расчёт объёмов</h3>
      <table class="est"><thead><tr><th>Позиция</th><th>Ед.</th><th>Объём</th><th>Формула</th><th>Норма</th></tr></thead><tbody>` +
      r.volumes.map((v) => `<tr class="${v.needs_review ? "review" : ""}">
        <td>${escapeHtml(v.title)}</td><td>${escapeHtml(v.unit)}</td>
        <td class="num">${qty(v.quantity)}</td><td>${escapeHtml(v.formula)}</td>
        <td>${escapeHtml(v.norm)}</td></tr>`).join("") +
      `</tbody></table></div>`);
  }

  // Таблица сметы с разделами
  parts.push(`<div class="est-block"><h3>Смета</h3>
    <table class="est"><thead><tr>
      <th>№</th><th>Работа/ресурс</th><th>Норма/документ</th><th>Ед.</th><th>Объём</th>
      <th>Материал</th><th>Работа</th><th>Машины</th><th>Итого KZT</th><th>Комментарий</th>
    </tr></thead><tbody>${renderLines(r)}</tbody></table></div>`);

  parts.push(renderTotals(r.totals));

  if (r.clarifications && r.clarifications.length) {
    parts.push(`<div class="est-block"><h3>Что уточнить у проектировщика/подрядчика</h3><ul class="plain">` +
      r.clarifications.map((c) => `<li>${escapeHtml(c)}</li>`).join("") + `</ul></div>`);
  }
  if (r.contractor_questions && r.contractor_questions.length) {
    parts.push(`<div class="est-block"><h3>Вопросы к подрядчику</h3><ul class="plain">` +
      r.contractor_questions.map((c) => `<li>${escapeHtml(c)}</li>`).join("") + `</ul></div>`);
  }

  resultEl.innerHTML = parts.join("");
}

function renderLines(r) {
  const rows = [];
  const sectionTotals = r.section_totals || {};
  let currentSection = null;
  (r.lines || []).forEach((ln) => {
    if (ln.section !== currentSection) {
      currentSection = ln.section;
      const sub = sectionTotals[ln.section];
      rows.push(`<tr class="section-row"><td></td><td colspan="7">${escapeHtml(ln.section)}</td>
        <td class="num">${sub != null ? money(sub) : ""}</td><td></td></tr>`);
    }
    rows.push(`<tr class="${ln.needs_review ? "review" : ""}">
      <td>${escapeHtml(ln.no)}</td><td>${escapeHtml(ln.title)}</td>
      <td>${escapeHtml(ln.norm)}</td><td>${escapeHtml(ln.unit)}</td>
      <td class="num">${qty(ln.quantity)}</td>
      <td class="num">${money(ln.material_price)}</td>
      <td class="num">${money(ln.labor_price)}</td>
      <td class="num">${money(ln.machine_price)}</td>
      <td class="num">${money(ln.total)}</td>
      <td>${escapeHtml(ln.comment)}</td></tr>`);
  });
  return rows.join("");
}

function renderTotals(t) {
  if (!t) return "";
  const row = (label, value, cls = "") =>
    `<div class="totals-row ${cls}"><span>${label}</span><span>${money(value)} KZT</span></div>`;
  return `<div class="est-block"><h3>Итоги</h3><div class="totals-box">
    ${row("Прямые затраты", t.direct)}
    ${row(`Накладные и админ. (${t.overhead_pct}%)`, t.overhead)}
    ${row("Итого с накладными", t.subtotal_with_overhead)}
    ${row(`Резерв на риски (${t.contingency_pct}%)`, t.contingency)}
    ${row("Итого с резервом", t.subtotal_with_contingency)}
    ${row(`НДС (${t.vat_pct}%)`, t.vat)}
    ${row("ОБЩИЙ ИТОГ (с НДС)", t.grand_total, "grand")}
  </div></div>`;
}

// ── Экспорт ──
function buildText(r) {
  if (!r) return "";
  const L = [];
  L.push(`AI SMETA KZ — ${r.project_name}`);
  L.push(`${r.object_type} · ${r.city} · ${r.precision_class}`);
  L.push(`Сформировано: ${r.generated_at}`);
  L.push("");
  L.push("ПРЕДУПРЕЖДЕНИЯ:");
  (r.warnings || []).forEach((w) => L.push(" - " + w));
  L.push("");
  L.push("НОРМАТИВНЫЕ ИСТОЧНИКИ:");
  (r.sources || []).forEach((s) =>
    L.push(` - ${s.code} — ${s.title}${s.confirmed ? "" : " [не подтверждено]"} ${s.url || ""}`));
  L.push("");
  L.push("РАСЧЁТ ОБЪЁМОВ:");
  (r.volumes || []).forEach((v) =>
    L.push(` - ${v.title}: ${qty(v.quantity)} ${v.unit} (${v.formula}) [${v.norm}]`));
  L.push("");
  L.push("СМЕТА:");
  (r.lines || []).forEach((ln) =>
    L.push(` ${ln.no} | ${ln.title} | ${ln.norm} | ${ln.unit} | ${qty(ln.quantity)} | ` +
      `${money(ln.total)} KZT${ln.comment ? " | " + ln.comment : ""}`));
  L.push("");
  const t = r.totals || {};
  L.push("ИТОГИ:");
  L.push(` Прямые затраты: ${money(t.direct)} KZT`);
  L.push(` Накладные (${t.overhead_pct}%): ${money(t.overhead)} KZT`);
  L.push(` Резерв (${t.contingency_pct}%): ${money(t.contingency)} KZT`);
  L.push(` НДС (${t.vat_pct}%): ${money(t.vat)} KZT`);
  L.push(` ОБЩИЙ ИТОГ: ${money(t.grand_total)} KZT`);
  L.push("");
  L.push("ЧТО УТОЧНИТЬ:");
  (r.clarifications || []).forEach((c) => L.push(" - " + c));
  L.push("");
  L.push("ВОПРОСЫ К ПОДРЯДЧИКУ:");
  (r.contractor_questions || []).forEach((c, i) => L.push(` ${i + 1}. ${c}`));
  return L.join("\n");
}

function saveResult() {
  if (!lastResult) { setStatus("Нет данных для сохранения.", true); return; }
  const blob = new Blob([buildText(lastResult)], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "ai_smeta_kz_" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "") + ".txt";
  a.click();
  URL.revokeObjectURL(url);
}

async function copyResult() {
  if (!lastResult) { setStatus("Нет данных для копирования.", true); return; }
  await navigator.clipboard.writeText(buildText(lastResult));
  setStatus("Смета скопирована.");
}

// ── Утилиты UI ──
function setBusy(isBusy) {
  $("runButton").disabled = isBusy;
  $("demoButton").disabled = isBusy;
  setStatus(isBusy ? "Идёт расчёт…" : "Готово.");
}
function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.style.color = isError ? "var(--danger)" : "var(--muted)";
}
function showError(error) {
  const msg = error && error.message ? error.message : String(error);
  resultEl.innerHTML = `<div class="warning">Ошибка формирования сметы:\n\n${escapeHtml(msg)}</div>`;
  setStatus("Ошибка.", true);
}
function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[c]));
}
function escapeAttr(value) {
  return escapeHtml(value);
}

renderWorks();
