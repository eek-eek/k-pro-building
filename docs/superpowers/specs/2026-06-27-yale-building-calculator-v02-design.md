# Yale Building Calculator — v0.2 Design Spec

**Date:** 2026-06-27
**Status:** Approved for planning
**Supersedes:** the single-page "AI Smeta KZ" MVP (v0.1)

> Renames the product **AI Smeta KZ → Yale Building Calculator**. Keeps the Kazakhstan-norms preliminary cost-estimation engine intact; adds stored multi-version estimates, an AI chat editor, manual line editing, a settings screen (provider/key/model + system prompts), and a full visual redesign.

This spec is the canonical, reconciled design. It was produced from five parallel sub-designs plus an adversarial review; the conflicts and correctness landmines that review found are resolved here as explicit, locked decisions (see §13).

---

## 1. Goals

1. **Stored estimates.** Estimates are first-class entities created from a dashboard and opened as cards. Each holds its input, its computed result, a chat history, and an immutable version history.
2. **AI chat editor.** Inside an estimate, the user instructs an LLM ("убери раздел кровли", "пересчитай арматуру по 100 кг/м³"); the backend applies the change and snapshots a new version.
3. **Manual editing.** The user edits line prices/quantities (and the overhead/contingency/VAT %) directly; the backend recomputes and snapshots a new version.
4. **Settings screen.** Choose provider, enter API key (masked), choose model from a per-provider catalog, toggle web-grounding, test connection, and edit/reset all system prompts.
5. **Redesign.** Minimal editorial visual style across three screens (dashboard / estimate detail / settings).

**Non-goals (v0.2):** prompt version history/audit, multi-user concurrency/locking beyond last-write-wins, PDF/Excel export, encrypted-at-rest secrets, Alembic migrations, the "Сравнение с подрядчиком" module (stays a placeholder).

---

## 2. Information Architecture

Three screens, top navigation (**Сметы** / **Настройки**), brand wordmark `yale building calculator.`

1. **Dashboard `#/`** — list of estimate rows: name, meta (type · city · floors · area), grand total (right-aligned), status dot (● calculated / ○ draft), version + message counts, updated date. Search box, "Новая смета" button.
2. **Estimate detail `#/estimate/:id`** — breadcrumb, title, status, **version selector** (history + rollback), Export. Two columns:
   - **Left:** collapsible "Исходные данные" (BuildingInput) with "Изменить и пересчитать"; the estimate table (volumes, lines by section, totals) with **inline-editable** price/quantity cells; manual edits saved per "Save" submit.
   - **Right:** **AI chat** panel — message history + composer. Disabled with a hint when no real provider is configured.
3. **Settings `#/settings`** — provider selector, masked API-key field, model dropdown (from catalog), web-grounding toggle, Save + Test connection; system-prompt editor blocks with "Сбросить".

---

## 3. Visual Design System

Minimal editorial direction (reference: Оди/awdee). Implemented as CSS custom properties in a single shared stylesheet (replaces `frontend/styles.css`).

```
--bg:        #ffffff
--text:      #141414
--text-2:    #8a8a8a   /* secondary */
--line:      #ededed   /* hairline dividers/borders */
--accent:    #16A34A   /* green: action + status */
--accent-bg: #f1faf3
--danger:    #b42318
--warn-bg:   #fffaf0
--radius:    8px
--font: "Inter", -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
```

- Typography: grotesque sans; large tight-tracked headings (700), body 14–15px, secondary text in `--text-2`.
- Components: top nav (hairline bottom border, active item underlined), page header, list rows (hairline-separated), status dots, buttons (primary = solid black `#141414`; action = solid `--accent`; secondary = white + `--line` outline), form fields (underline or boxed), tables with editable cells (dashed underline affordance + hover state), totals box, chat bubbles, prompt editors, toast notifications.
- No heavy shadows; rely on whitespace and hairlines.
- Inter is loaded from a self-hosted/CDN webfont with a system fallback (no build step). Fallback must be acceptable on its own.

---

## 4. Data Model (single reconciled schema)

All ORM classes in `backend/app/models.py` (SQLAlchemy 2.0, `Mapped[...]`). New: `Estimate` (refactored), `EstimateVersion`, `ChatMessage`, `Prompt`, `AppSetting`. Unchanged: `NormDocument`, `NormRule`, `KnowledgeCache`, `PriceItem`, `Job`.

### 4.1 Estimate (container)
| field | type | notes |
|---|---|---|
| `id` | int PK | |
| `name` | str(256) | user-facing; default "Смета #<id>" if blank (stored, not computed) |
| `object_type` | str(64), index | denormalized from latest input for dashboard |
| `city` | str(128) | denormalized from latest input |
| `status` | str(16), index | `draft` \| `calculated` |
| `current_version_id` | int FK→estimate_versions.id, **use_alter=True**, ondelete SET NULL, nullable | active snapshot pointer |
| `created_at` / `updated_at` | datetime | `updated_at` has `onupdate` |

`object_type`/`city`/`name` are refreshed whenever input is (re)saved.

### 4.2 EstimateVersion (immutable snapshot)
| field | type | notes |
|---|---|---|
| `id` | int PK | |
| `estimate_id` | int FK→estimates.id, index, ondelete CASCADE | |
| `version_number` | int, index | sequential per estimate; `UniqueConstraint(estimate_id, version_number)` |
| `input` | JSON | snapshot of `BuildingInput` |
| `result` | JSON | snapshot of `EstimateResult` |
| `total` | float | `result.totals.grand_total` (for cheap dashboard reads) |
| `source` | str(16), index | `initial` \| `llm_edit` \| `manual_edit` \| `rollback` (`initial` = any full calc run — first calc or recalc after input change) |
| `summary` | text | auto-generated delta vs previous (see §5.4) |
| `created_at` | datetime, index | |

### 4.3 ChatMessage
| field | type | notes |
|---|---|---|
| `id` | int PK | |
| `estimate_id` | int FK→estimates.id, index, ondelete CASCADE | |
| `role` | str(16) | `user` \| `assistant` |
| `content` | text | |
| `version_id` | int FK→estimate_versions.id, ondelete SET NULL, nullable | version this assistant turn produced (null for user msgs / no-op replies) |
| `created_at` | datetime, index | ordering tiebreak by `id` |

### 4.4 Prompt
| field | type | notes |
|---|---|---|
| `id` | int PK | |
| `key` | str(64), unique, index | `norm_extraction`, `estimate_edit` |
| `title` | str(256) | |
| `description` | text | where it's used |
| `body` | text | active text |
| `is_custom` | bool, default False | True once user edits; reset → False + restore code default |
| `updated_at` | datetime | |

### 4.5 AppSetting
Key–value store, one row per setting: `key` str unique, `value` text (JSON-encoded for non-strings). Keys: `llm_provider`, `gemini_api_key`, `anthropic_api_key`, `openai_api_key`, `gemini_model`, `anthropic_model`, `openai_model`, `llm_use_search`.
**Empty/absent value = "unset" → fall through to `.env`** (never shadows a working `.env` key). Rows are created only when the user sets a value; seeding does **not** insert empty key rows.

### 4.6 SQLite integrity & migration
- Add a `connect` event listener in `backend/app/database.py` issuing `PRAGMA foreign_keys=ON` per connection.
- The `estimates.current_version_id ↔ estimate_versions.estimate_id` cycle is broken with `use_alter=True` on `current_version_id` so `create_all()` emits a separate `ALTER TABLE ADD CONSTRAINT`-style ordering.
- **Migration = drop & recreate** the dev DB (current DB holds only throwaway test estimates). `run_seed()` recreates schema and seeds prompts + norms/prices as today. Document the data-loss tradeoff in the migration step; production migration is out of scope for v0.2.

---

## 5. Estimate math integrity (server-authoritative)

The backend is the **only** component that computes money. The frontend and the LLM never supply authoritative totals.

### 5.1 Reusable recompute function
Factor a pure function out of `backend/app/calc/estimate.py`:

```
recompute_estimate(prev_result: EstimateResult, lines: list[EstimateLine], input: BuildingInput) -> EstimateResult
```

Rules (must match `build_estimate` exactly so an unedited round-trip is byte-identical):
1. For every line: `line.total = round(quantity * (material_price + labor_price + machine_price))`. Any client/LLM-supplied `total` is **ignored and overwritten**.
2. **Re-derive the prep line `1.1`** ("Подготовительные работы", 1.5% of direct-core) from the recomputed direct-core, then fold it back into direct exactly as `build_estimate` does.
3. `section_totals` = `round(sum)` per section (same rounding as `build_estimate`).
4. `totals` recomputed from direct using `input.overhead_pct / contingency_pct / vat_pct`.
5. **Carry forward** non-line fields from `prev_result`: `warnings`, `sources`, `volumes`, `clarifications`, `contractor_questions`, `precision_class`, `llm_narrative`. Refresh `generated_at`.

`build_estimate` keeps its name, signature, and `EstimateResult` return type (so `calc/__init__.py` export and `tests/test_calc.py` stay green). The initial `EstimateVersion` is created by the **caller** (job manager / sync route), not inside `build_estimate`.

### 5.2 Golden test
`build_estimate(input) == recompute_estimate(that_result, that_result.lines, input)` — identical `lines` totals, `section_totals`, and `totals`. A no-op edit must produce an empty/zero diff.

### 5.3 Manual edit path
`POST /api/estimates/{id}/manual-edit` accepts edited `lines` and optional `input` (the %s). Backend runs `recompute_estimate`, snapshots `source=manual_edit`. Trust boundary: only `quantity` and the three prices per line are read from the client; `total` is always recomputed.

### 5.4 Version summary
Auto-generated by the backend by diffing previous vs new `lines` + grand_total: line add/remove counts and `Δgrand_total` formatted in ₸ (e.g. "−1 строка, −4,5 млн ₸"). No user input required.

---

## 6. LLM edit pipeline

New module `backend/app/chat/editor.py`.

1. Build a user payload from the **current** `EstimateResult` (sections + full lines: `no, section, title, unit, quantity, material_price, labor_price, machine_price, needs_review, comment`) + the user instruction + the last N chat messages (N≈6; older truncated).
2. Call the provider via the **`estimate_edit`** system prompt. The model must return **strict JSON**:
   ```json
   { "reply": "<short Russian reply>", "lines": [ <full revised line objects> ], "warnings_add": ["…"] }
   ```
   It must return the **entire** revised line list (all fields incl. `section`/`unit`/`title`), must not compute totals, must not invent norms (mark `needs_review`).
3. Parse with `parse_json_block` (reuse `llm/base.py`); validate each line against `EstimateLine` (Pydantic). To be robust, **merge** LLM line fields onto the previous line keyed by `no` before validation, so a model that omits `section`/`unit` doesn't 400.
4. Run `recompute_estimate`; snapshot `source=llm_edit`; create the `user` + `assistant` `ChatMessage` (assistant linked to the new version); append `warnings_add` to result warnings.
5. **Failure safety:** `LLMUnavailable`, empty/invalid JSON, or lines failing validation → return an error and **do not** create a version or mutate the current estimate. The user message may still be stored; the assistant turn reports the failure (no `version_id`).

**Async:** all blocking provider calls run via `await asyncio.to_thread(...)` (mirrors `jobs/manager.py`), so async route handlers never block the event loop. `use_search=False` for estimate edits.

### 6.1 `estimate_edit` system prompt (seed, Russian)
Drafted in code defaults: instructs role (помощник-сметчик РК), input shape, strict-JSON output contract with an example, "не выдумывай нормы — помечай needs_review", "не считай итоги — это делает система", "сохраняй схему строки точно".

---

## 7. Settings, provider, prompts, model catalog

New module `backend/app/settings_service.py`.

- **Effective settings** = `.env` defaults (`config.Settings`) overlaid with `AppSetting` rows, with **empty DB value = unset**. Computed by opening a **short-lived** `SessionLocal()`, reading rows, closing it; cache the resulting plain `EffectiveSettings` object (never cache a Session).
- **Hot reload:** saving settings invalidates both the settings cache and `get_provider` (`cache_clear()`), so the next request uses new values without restart. Document the two-step invalidation.
- **Provider factory** (`llm/factory.py`) builds from effective settings (provider, key, model, use_search).
- **Key masking:** `GET /api/settings` returns `masked_key` (first4…last4) + `has_key: bool`, never the full key. On save, if the submitted key equals the masked form (or is empty), keep the existing key.
- **Test connection:** cheap one-shot call per provider via `asyncio.to_thread`; returns `{ok, message}` with the provider's exact error string. `demo` → `{ok: false, message: "Demo-режим: настройте реальный провайдер"}` (nudge).
- **Model catalog:** static `MODEL_CATALOG: dict[provider, list[{id,label}]]` in code; source for the dropdown. Gemini/OpenAI seeded from current defaults (`gemini-2.5-flash`, `gpt-4o`). Anthropic seeded with current IDs — **verify exact IDs against the `claude-api` skill at implementation** (known: Opus 4.8 `claude-opus-4-8`, Sonnet 4.6 `claude-sonnet-4-6`, Haiku 4.5 `claude-haiku-4-5-20251001`).
- **Prompt store:** `Prompt` rows seeded from code defaults (`norm_extraction` ← current `extractor.SYSTEM_PROMPT`; `estimate_edit` ← §6.1). A read-through helper `get_prompt(key) -> str` returns DB body, falling back to the code default if the row is missing. `extractor.extract_params` reads `get_prompt("norm_extraction")` instead of the module constant (no signature change to extractor needed beyond the lookup). "Reset" restores code default and sets `is_custom=False`.

---

## 8. API contract (single source of truth)

Base `/api`. New/changed endpoints; existing `health`, `norms`, `prices`, and the async `POST /estimate` + SSE `GET /estimate/{job_id}/events` calc flow are retained (jobs now attach to an estimate and create its `initial` version).

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/estimates` | — | `[EstimateCard]` (id, name, object_type, city, status, total, version_count, message_count, updated_at) |
| POST | `/estimates` | `{name?, input?}` | `{id}` (creates draft) |
| GET | `/estimates/{id}` | — | `{estimate, current_version:{version_number,input,result,source}, version_count, message_count}` |
| PATCH | `/estimates/{id}` | `{name?, input?}` | updated estimate (input save refreshes denorm fields) |
| DELETE | `/estimates/{id}` | — | `204` |
| POST | `/estimates/{id}/calc` | — | `{job_id}`; client subscribes to existing SSE `GET /api/estimate/{job_id}/events`; on completion the job creates an `initial` version (reuse `resolve_norm_profile`+`build_estimate`) and sets `current_version_id` |
| GET | `/estimates/{id}/versions` | — | `[{version_number, source, summary, total, created_at}]` |
| GET | `/estimates/{id}/versions/{n}` | — | full version |
| POST | `/estimates/{id}/rollback` | `{version_number}` | creates **new** version (`source=rollback`) cloning the target snapshot, updates pointer → `{version_number}` |
| POST | `/estimates/{id}/manual-edit` | `{lines, input?}` | new `manual_edit` version `{version_number, result}` |
| GET | `/estimates/{id}/chat` | — | `[ChatMessage]` |
| POST | `/estimates/{id}/chat` | `{message}` | `{reply, version_number?, result?}` — `version_number`/`result` present only if a version was created; `409` when no real provider |
| GET | `/settings` | — | `{provider, masked_key, has_key, model, use_search, catalog}` |
| PUT | `/settings` | `{provider?, api_key?, model?, use_search?}` | saved settings (masked) |
| POST | `/settings/test` | `{provider?, api_key?, model?}` | `{ok, message}` |
| GET | `/prompts` | — | `[{key, title, description, body, is_custom}]` |
| PUT | `/prompts/{key}` | `{body}` | updated prompt |
| POST | `/prompts/{key}/reset` | — | prompt restored to default |

**Conventions:** prompts addressed by `key` (string); chat error when provider unavailable = **409** with `detail`. Errors use FastAPI `HTTPException` with Russian `detail`. Pydantic request/response models added to `schemas.py`.

### 8.1 Concurrency
`version_number` allocated as `max(version_number)+1` then insert; on `IntegrityError` against `UniqueConstraint(estimate_id, version_number)`, retry once. Otherwise last-write-wins (single-user assumption).

---

## 9. Frontend architecture (vanilla, no build step)

- **Routing:** tiny hash-router in `app.js` (`#/`, `#/estimate/:id`, `#/settings`); FastAPI serves `index.html` for `/` and static assets (current `main.py` mount stays). Deep links work via hash.
- **Modules** (plain ES, `<script type="module">` or concatenated files, no bundler): `api.js` (fetch wrappers matching §8), `router.js`, `views/dashboard.js`, `views/estimate.js`, `views/settings.js`, `components/estimate-table.js`, `components/chat.js`, `components/toast.js`. Reuse existing render logic (`renderEstimate`, `renderLines`, `renderTotals`, `buildText`) refactored into `components/estimate-table.js`.
- **Initial calc UX:** creating/recalculating shows the existing SSE step list, then renders the editable table on completion (reuses current EventSource flow against `/estimates/{id}/calc`).
- **Manual edit:** inline-editable cells with a clear affordance (dashed underline + hover); a "Сохранить правки" action POSTs the lines and reloads the version.
- **Chat:** message list + composer; disabled state ("настройте провайдера в Настройках") when `GET /settings` reports no usable provider; on reply, refresh estimate + versions.
- **Settings:** provider selector, masked key field, model **dropdown from catalog**, web-grounding toggle, Save + Test (shows live status), prompt editor blocks with Reset (confirm before reset).
- **State:** fetch-on-navigate; no long-lived stale caches; reload estimate after any edit (simple over optimistic).

---

## 10. Backward compatibility
- Calc engine (`resolve_norm_profile`, `build_estimate`, defaults, norms/prices, SSE jobs) unchanged in behavior; only the **caller** wraps results into `EstimateVersion`.
- `POST /api/estimate/sync` retained for integrations/tests; now also creates an `Estimate`+`initial` version.
- `tests/test_calc.py` / `test_resolver.py` remain valid; add new tests (§11).

---

## 11. Testing
1. **Golden recompute** (§5.2): build == recompute round-trip identical.
2. **Manual edit**: editing a price changes only affected line/section/grand totals; `total` recomputed server-side even if client sends a wrong `total`.
3. **LLM edit** (provider mocked): valid JSON → new `llm_edit` version + chat messages; invalid JSON / `LLMUnavailable` → no version created, previous intact.
4. **Settings precedence**: `.env` key present, no `AppSetting` row → effective uses `.env`; empty `AppSetting` value does not shadow `.env`.
5. **Hot reload**: change provider via API → next `get_provider()` reflects it.
6. **FK cascade**: delete an `Estimate` → its versions & chat are gone (PRAGMA on).
7. **Migration smoke**: fresh DB → calc → version → dashboard list → detail → chat edit → rollback.

---

## 12. Build / run notes
- Requires **Python 3.11** (system has 3.9; `run.sh` should target `python3.11`). venv already built on 3.11 during setup.
- New frontend has no build step. Inter webfont self-hosted/CDN with system fallback.

---

## 13. Resolved decisions (from adversarial review)
1. **One schema** — §4 is canonical; field names `version_number`, source enum `initial|llm_edit|manual_edit|rollback`; `ChatMessage` links by `estimate_id` (+ nullable `version_id`); `Estimate` is a pure container (no legacy input/result/total); no `edited_lines`/`edited_pcts`/`chat_*` columns.
2. **Server-authoritative totals** — recompute line totals from qty×prices, ignore client/LLM totals (§5.1).
3. **Atomic migration** — model change + the two write sites (`jobs/manager`, sync route) + dashboard serializer change together; drop & recreate dev DB.
4. **Secret precedence** — empty/absent `AppSetting` = unset, never shadows `.env` (§4.5/§7).
5. **Async offload** — all sync LLM calls via `asyncio.to_thread` (§6).
6. **FK enforcement** — `PRAGMA foreign_keys=ON` + `use_alter` on circular FK (§4.6).
7. **Chat prompt = full lines** + server-side merge-by-`no` before validation (§6).
8. **Carry-forward** warnings/sources/volumes/clarifications/precision_class on recompute (§5.1).
9. **Rounding parity** + prep-line re-derivation so no-op edits diff to zero (§5.1/§5.2).
10. **Rollback = create new version** cloning the target (§8).
11. **One API/prompt contract**, prompts by `key`, chat-unavailable = 409, frontend aligned (§8).
12. **Keep `build_estimate`** name/return; version created by caller; tests stay green (§5.1/§10).
13. **`version_number` collision** → catch IntegrityError + retry once (§8.1).

## 14. Accepted / deferred
- Prompt version history/audit → **deferred to v0.3** (v0.2 = body + reset only).
- No version cap; paginate version list at >10. Acceptable at MVP scale.
- Plaintext API keys in local SQLite — acceptable for single-machine MVP; encryption/vault deferred.
- Single-user assumption; last-write-wins on `current_version_id`.
- Model catalog static; runtime fetch from provider APIs deferred.
