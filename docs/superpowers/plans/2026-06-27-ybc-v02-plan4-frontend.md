# YBC v0.2 — Plan 4: Frontend Redesign (vanilla SPA)

> Visual/iterative work — verified by running the app and reviewing in a browser, not pytest. Built as a cohesive deliverable, then refined against user feedback.

**Goal:** Replace the single-page MVP UI with a three-screen vanilla hash-router SPA in the minimal editorial style (Оди/awdee reference): dashboard of estimates, estimate detail (inputs + editable table + AI chat), settings.

**Style tokens (locked):** white `#fff` bg, text `#141414`, secondary `#8a8a8a`, hairline `#ededed`, accent green `#16A34A`, primary button black, radius 8px, grotesque sans (Inter/system), generous whitespace, flat (no heavy shadows). Wordmark `yale building calculator.`

**No build step.** FastAPI serves `frontend/` (StaticFiles + index at `/`). Hash routing (`#/`, `#/estimate/:id`, `#/settings`) — all served by `index.html`, routed client-side, so deep links work.

---

## File Structure
- `frontend/index.html` — **rewrite**: app shell (top nav + `#app` mount) + `<script type="module" src="app.js">`.
- `frontend/styles.css` — **rewrite**: design tokens + component styles.
- `frontend/app.js` — **rewrite**: hash router, `api` client, three views, shared render helpers, chat, manual edit, settings, toasts. (Single module file to keep no-build simplicity; internally organized by section.)
- `backend/app/main.py` — **verify** it still serves `frontend/` for `/` and assets (no change expected; hash routes need no server route).

---

## API map (endpoints the SPA calls — all exist from Plans 1–3)
| Screen | Calls |
|---|---|
| Dashboard `#/` | `GET /api/estimates`; `POST /api/estimates`; `DELETE /api/estimates/{id}` |
| Detail `#/estimate/:id` | `GET /api/estimates/{id}`; `PATCH /api/estimates/{id}`; `POST /api/estimates/{id}/calc` + SSE `GET /api/estimate/{job_id}/events`; `POST /api/estimates/{id}/manual-edit`; `GET/POST /api/estimates/{id}/chat`; `GET /api/estimates/{id}/versions`; `POST /api/estimates/{id}/rollback` |
| Settings `#/settings` | `GET/PUT /api/settings`; `POST /api/settings/test`; `GET /api/prompts`; `PUT /api/prompts/{key}`; `POST /api/prompts/{key}/reset` |

---

## Screens & behaviors

### Dashboard `#/`
- Top nav (Сметы active / Настройки), big "Сметы" heading, "Новая смета" black button, search input (client-side filter by name/type/city).
- List rows (hairline-separated): name, meta (`object_type · city · floors? · area`), grand total right-aligned (`—` for drafts), status dot (● green calculated / ○ grey draft), `v{n} · {msg} сообщений`, updated date. Row click → `#/estimate/:id`. Row delete (✕, confirm).
- "Новая смета" → creates a draft (`POST /estimates` with default input) → navigates to its detail (inputs expanded for editing).

### Estimate detail `#/estimate/:id`
- Breadcrumb `Сметы / {name}`, editable title (PATCH name on blur), status dot, **version selector** (dropdown of versions with source+summary; selecting a past version → rollback confirm → `POST /rollback`), Export (TXT via existing `buildText`).
- **Left column:** collapsible "Исходные данные" form (BuildingInput fields — reuse the field set from the old UI) + "Изменить и пересчитать" (green) → `POST /calc` → SSE step list → reload on done. Then the estimate render: warnings, sources, volumes, **editable** line table (price/qty cells `contenteditable`/inputs; "Сохранить правки" → `POST /manual-edit` → reload), totals box.
- **Right column:** chat panel — message list (user right/dark, assistant left/light), composer. If `GET /settings` reports no usable provider (`has_key` false or provider demo), disable composer with hint "Настройте провайдера в Настройках". On send → `POST /chat` → append messages, reload estimate + versions; 409 → show the hint.

### Settings `#/settings`
- Provider selector (gemini/anthropic/openai/demo chips). API-key field (shows masked value; editing + Save sends new key; resending masked keeps existing). Model **dropdown** populated from `catalog[provider]`. Web-grounding toggle. Save (black) + Test connection (shows live ok/error). 
- System prompts: one block per prompt (`title`, `description`, textarea bound to `body`), Save (PUT) + "Сбросить" (reset, confirm).

---

## Shared helpers (adapt from old app.js)
`money`, `qty` (Intl ru-RU), `escapeHtml`/`escapeAttr`, `renderEstimate`/`renderLines`/`renderTotals`, `buildText` (TXT export), `setStatus`/toast. SSE listen loop (`EventSource`) reused for calc.

---

## Acceptance / verification (manual, in browser)
1. App loads at `http://127.0.0.1:8000`, dashboard lists estimates (empty state if none).
2. Create estimate → edit inputs → Рассчитать → SSE steps → smeta renders with totals.
3. Edit a price cell → Сохранить правки → totals update, new version appears in selector.
4. Settings: set provider+key+model, Save → masked key shown; Test connection returns a result; edit a prompt + reset.
5. Chat: with demo/no key → composer disabled + hint; (with a real key, a message edits the estimate and adds a version).
6. Version selector: rollback to v1 → new version with v1 totals.
7. Visual: matches the editorial mockups (white, hairlines, green accent, black buttons, Inter); responsive enough at ~1280px.

Verified by running uvicorn and reviewing in the browser; iterate on styling per user feedback.

## Deferred
- Контрактор-сравнение модуль (placeholder stays/removed). PDF/Excel export. Mobile layout polish.
