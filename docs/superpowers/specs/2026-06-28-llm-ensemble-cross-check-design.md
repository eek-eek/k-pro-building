# Ансамбль LLM: кросс-проверка извлечения норм вторым ИИ — дизайн

**Дата:** 2026-06-28
**Статус:** на ревью (v2 — после состязательного ревью спеки)

## Зачем
Извлечение нормативных коэффициентов через LLM (`backend/app/norms/extractor.py`) — самое рискованное место: галлюцинация коэффициента/источника = неверная смета. Идея — **ансамбль**: помимо основного провайдера (Claude) подключить второй (OpenAI), который **независимо** извлекает те же коэффициенты, после чего результаты **сравниваются**. Согласие → выше уверенность; расхождение → пометка для сметчика.

## Решения (согласованы с заказчиком)
- **Топология Б — независимое извлечение + сравнение** (не «критик» — нет эффекта якоря).
- **Триггер — при извлечении норм** (когда включён opt-in тумблер). См. честный нюанс про кэш ниже.
- **Claude — авторитетный**: значения не перезаписываются. Расхождение → `needs_review=True` + оба значения в ноте. Согласие → `confidence ↑`.
- **Opt-in**: тумблер в Настройках, по умолчанию ВЫКЛ. Выбор проверяющего провайдера (по умолчанию `openai`).
- **Мягкая деградация**: проверяющий недоступен/== основного/упал/вернул нечитаемый ответ → обычный результат основного, без ошибки и без ложных пометок.
- **Только нормы** (не чат-правки).

> Зависимость уже в коде: per-provider хранение ключей (`settings_service.EffectiveSettings.{provider}_api_key`, тест `test_keys_isolated_per_provider`). Ансамблю нужны два корректно хранимых ключа.

## Архитектура

Поток сейчас: `resolver.resolve_norm_profile` → `_build_profile` → (внутри try) `extractor.extract_params(db, inp, documents)` возвращает `(params, sources, web_links)`; `llm_params` мёрджатся в общий `params` через `_better`; объект `NormProfile(...)` создаётся **ПОЗЖЕ**, после try/except. Добавляем **аддитивный** слой кросс-проверки.

### 1. Настройки (3 новых ключа)
- `config.Settings` (`backend/app/config.py`): `cross_check_enabled: bool = False`, `cross_check_provider: str = "openai"`.
- `settings_service.py`:
  - `SETTING_KEYS += ("cross_check_enabled", "cross_check_provider")`; `cross_check_enabled` → в `_BOOL_KEYS`.
  - `EffectiveSettings` — **@dataclass; новые поля ОБЯЗАТЕЛЬНО с дефолтами** (`cross_check_enabled: bool = False`, `cross_check_provider: str = "openai"`), иначе сломается **второй** конструктор `EffectiveSettings(...)` в `test_provider` (settings_service.py:114-123) и тест `test_test_connection_demo_returns_not_ok`. Заполнить поля в `get_effective_settings` (settings_service.py:71-80); в `test_provider` можно не трогать (дефолты покроют).
  - `save_settings` фильтрует строго по `SETTING_KEYS` — без пополнения PUT молча проигнорирует новые ключи.
- `schemas.SettingsUpdate` (schemas.py:268): `cross_check_enabled: Optional[bool] = None`, `cross_check_provider: Optional[str] = None`.
- `routes.py` (`backend/app/api/routes.py:450-490`): GET /settings добавляет `cross_check_enabled`/`cross_check_provider` в ответ; PUT — ветки `if body.cross_check_enabled is not None: updates["cross_check_enabled"]=...` и аналогично provider. Тесты `test_settings_api.py` используют `key in response` (нет строгого равенства) → добавление полей регрессию не вызывает.
- Фронт (Настройки): чекбокс «Кросс-проверка вторым ИИ» + select проверяющего (gemini/anthropic/openai) + подсказка про стоимость. Ключи уже хранятся по провайдерам; берём ключ выбранного проверяющего.

### 2. Сборка проверяющего провайдера
`factory.build_named_provider(eff, name)` — строит провайдер по явному имени из per-provider ключей/моделей `eff`. **Сохранить особенность Gemini**: `GeminiProvider(eff.gemini_api_key, eff.gemini_model, eff.llm_use_search)` (3-й арг `use_search`). `build_provider(eff)` делегирует `build_named_provider(eff, eff.llm_provider)` — рефактор без смены поведения; `get_provider()` не меняется.

### 3. Общий разбор параметров `_parse_params`
В `extractor.py` вынести цикл разбора `data["params"]` → `dict[str, NormParam]` (сейчас extractor.py:95-114) в `_parse_params(data) -> dict[str, NormParam]`. Разбор `sources` и возврат `web_links` остаются в `extract_params`. Вынос идемпотентен по поведению. **Дополнительно** в `_parse_params` отбрасывать невалидные числа: `value` не конечное (NaN/inf) или `< 0` → категорию пропускать (бессмысленный коэффициент не должен попадать ни в основной набор, ни в сравнение как «мусорное расхождение»).

### 4. Кросс-проверка `cross_check_params`
Новая функция в `extractor.py`:
`cross_check_params(db, inp, documents, primary_params: dict[str, NormParam]) -> tuple[dict[str, NormParam], CrossCheck]`

Константы: `REL_TOL = 0.15`, `ABS_FLOOR = 1e-3`, `CONF_BONUS = 0.15`, `NOTE_MAX = 500`.

1. **Пустой основной набор → нет смысла**: `if not primary_params: return (primary_params, CrossCheck(enabled=eff.cross_check_enabled, ran=False, reason="основное LLM-извлечение пусто"))`. (Так мы не тратим 2-й платный вызов, когда основной LLM ничего не дал.)
2. `eff = get_effective_settings(db)`. Если `not eff.cross_check_enabled` → `(primary_params, CrossCheck(enabled=False))`.
3. Если `eff.cross_check_provider == eff.llm_provider` → `(primary_params, CrossCheck(enabled=True, ran=False, reason="проверяющий совпадает с основным"))`.
4. `verifier = build_named_provider(eff, eff.cross_check_provider)`. Если `not verifier.available` → `(primary_params, CrossCheck(enabled=True, ran=False, reason="проверяющий недоступен (нет ключа)"))`.
5. **Промпты** собираем сами (в `extract_params` они локальны и наружу не отдаются): `user = build_user_prompt(inp, documents)`, `system = get_prompt(db, "norm_extraction") or SYSTEM_PROMPT`. (Обе сущности уже есть в extractor.py.) `use_search` проверяющего = `eff.llm_use_search` (равные условия с основным; для openai/anthropic это no-op — у них web-tool нет, см. §Стоимость).
6. Вызов: `try: data, _ = verifier.extract_json(system, user, use_search=eff.llm_use_search) except LLMUnavailable: return (primary_params, CrossCheck(enabled=True, ran=False, reason="ошибка проверяющего"))`. **`reason` — константные строки, без сырого `str(exc)`/`resp.text`** (не утаскивать тело ответа провайдера в UI).
7. `verifier_params = _parse_params(data)`. **Если `not verifier_params` при непустом `primary_params`** → деградация (нечитаемый/пустой ответ): `(primary_params, CrossCheck(enabled=True, ran=False, reason="проверяющий вернул нечитаемый ответ"))`. НЕ помечать всё как «missing».
8. Сравнение по категориям. Работаем на КОПИЯХ `primary_params` (не мутируем вход «на месте» сильнее необходимого; конкретно правим только `confidence`/`needs_review`/`note`). Счётчики `agreed, disputed, missing = 0`; списки `extra_keys = []`.
   Для каждой `cat, p in primary_params.items()`:
   - `v = verifier_params.get(cat)`.
   - `v is None` → `missing += 1`; `p.note = _cap(p.note + " · вторая модель не дала значение")`.
   - **Единицы**: если `p.unit` и `v.unit` заданы и `p.unit != v.unit` → `p.needs_review = True`; `p.note = _cap(p.note + f" · ⚠ единицы расходятся: {p.unit} vs {v.unit}")`; `disputed += 1`; **не** сравнивать числа (масштаб разный). `continue`.
   - Числовое сравнение: `denom = max(abs(p.value), abs(v.value), ABS_FLOOR)`; `rel = abs(p.value - v.value) / denom`. (Оба нуля → `rel = 0` → согласие.)
     - `rel <= REL_TOL` → согласие: `p.confidence = min(1.0, p.confidence + CONF_BONUS)`; `p.note = _cap(p.note + f" · ✓ подтверждено {verifier.name}")`; `agreed += 1`.
     - иначе → расхождение: `p.needs_review = True`; `p.note = _cap(p.note + f" · ⚠ расхождение с {verifier.name}: {p.value} vs {v.value} ({_pct(rel)})")`; `disputed += 1`.
   `_pct(rel)` = `f"{min(rel,9.99):.0%}"` (потолок, чтобы не печатать «100000%»). `_cap(s)` = `s[:NOTE_MAX]` (суффикс важнее хвоста — при необходимости резать середину исходной ноты; минимально — `s[:NOTE_MAX]`).
   - `extra_keys` = категории, что есть у проверяющего, но нет у основного. **Не добавляем значения** (Claude авторитетный), но фиксируем ключи для видимости.
9. Вернуть `(primary_params, CrossCheck(enabled=True, ran=True, verifier=eff.cross_check_provider, agreed, disputed, missing, extra=len(extra_keys), extra_keys=extra_keys[:10]))`.

Чистые значения основного **не меняются** — только `confidence`/`needs_review`/`note`.

### 5. Схема результата
- `schemas.CrossCheck`: `enabled: bool`, `ran: bool = False`, `verifier: str = ""`, `agreed: int = 0`, `disputed: int = 0`, `missing: int = 0`, `extra: int = 0`, `extra_keys: list[str] = []`, `reason: str = ""`.
- `NormProfile`: добавить `cross_check: Optional[CrossCheck] = None`. (Сериализуется автоматически через `model_dump`/`to_jsonable`; новое Optional-поле не ломает старые записи кэша при `model_validate` — отсутствующий ключ → дефолт.)

### 6. Интеграция в резолвер (`backend/app/norms/resolver.py`, `_build_profile`)
Профиль создаётся ПОЗЖЕ блока LLM. Поэтому:
- Перед/в начале блока завести `cc = CrossCheck(enabled=False)` (локальная).
- Внутри `try`, порядок: `extract_params` → **`cross_check_params`** (аннотирует `llm_params`) → мёрдж в `params` через `_better` → **`_persist_llm_rules`**:
  ```
  llm_params, llm_sources, web_links = extractor.extract_params(db, inp, documents)
  llm_params, cc = extractor.cross_check_params(db, inp, documents, llm_params)
  for cat, p in llm_params.items():
      params[cat] = _better(params.get(cat, p), p) if cat in params else p
  _persist_llm_rules(db, inp, llm_params, docs_by_code)
  ```
  _(Реализация ставит кросс-проверку **до** `_persist_llm_rules` — так в сохранённые `NormRule` попадают уже уточнённые `confidence`/ноты «✓ подтверждено»/«⚠ расхождение», что полезно для повторного использования правил.)_ Передаём именно `llm_params`, НЕ merged `params`; повторный мёрдж — через `_better`, не `params.update`, чтобы не затереть более авторитетные document/seed-правила.
- При создании `profile = NormProfile(..., cross_check=cc)` — добавить аргумент `cross_check=cc`.
- В ветке `except LLMUnavailable` / при `inp.demo_mode` кросс-проверку НЕ вызывать (там `llm_params` нет / LLM недоступен) — `cc` остаётся `enabled=False`.

### 7. Сводка в смете (`backend/app/calc/estimate.py`, блок warnings ~estimate.py:170-184)
Сразу после ветки `if profile.from_cache:` добавить:
```
if profile.cross_check and profile.cross_check.ran:
    cc = profile.cross_check
    msg = f"Профиль прошёл кросс-проверку ({cc.verifier}): подтверждено {cc.agreed}, расхождений {cc.disputed}"
    if cc.missing: msg += f", без ответа {cc.missing}"
    if cc.extra_keys: msg += f"; вторая модель дополнительно предложила: {', '.join(cc.extra_keys)}"
    warnings.append(msg + ".")
elif profile.cross_check and profile.cross_check.enabled and not profile.cross_check.ran and profile.cross_check.reason:
    warnings.append(f"Кросс-проверка включена, но не выполнена: {profile.cross_check.reason}.")
```
Формулировка «**профиль прошёл** кросс-проверку» — прошедшее время, поэтому честна и на кэш-хите (профиль действительно был проверён при сборке), не противореча плашке «взято из кэша». Расхождения уже подняли `needs_review` → попадают в существующий блок «требует проверки» и в `clarifications` (ноты с обоими значениями).

## Кэширование (честный нюанс + инвалидация)
Профиль кэшируется по `signature` (от `BuildingInput.discriminators()`), который **не включает** `cross_check_enabled`/`cross_check_provider`. Поэтому без доработки включение тумблера после расчёта с выключенным вернуло бы из кэша старый профиль без проверки. Чтобы «при каждом расчёте» не врало:
- В `resolve_norm_profile`, на быстром cache-hit и на double-check под локом: если `not demo_mode` И `eff.cross_check_enabled` И (`cached.cross_check is None` ИЛИ `not cached.cross_check.enabled`) → **не отдавать кэш**, уйти в `_build_profile`. _(Реализация: условие по **`enabled`**, не по `ran`, плюс guard `not demo_mode`. Так профиль, собранный при включённом ансамбле но без отработавшей проверки — нет ключа/провайдер упал, `enabled=True, ran=False` — считается годным и НЕ перестраивается на каждый расчёт; иначе был бы бесконечный платный перепрогон. Demo-режим кросс-проверку не делает вовсе → его кэш не инвалидируется.)_ Чтобы это работало и когда **основной** LLM упал, `_build_profile` в ветке `except LLMUnavailable` при включённом тумблере выставляет `cc = CrossCheck(enabled=True, ran=False, reason="основной LLM недоступен")`. После того как профиль закэширован, повторные расчёты берут его из кэша без нового LLM-вызова.
- `force=True` («Проверить нормы») всегда идёт мимо кэша → кросс-проверка гарантированно отработает.
- Резолверу нужен доступ к `eff` — читать `get_effective_settings(db)` один раз в начале (как уже делается косвенно). Альтернатива (не выбрана): добавить признак в signature — отвергнуто, т.к. signature участвует и в сопоставлении правил.

Честная формулировка для UI-подсказки: «выполняется при извлечении норм (cache-miss или кнопка ‘Проверить нормы’); повторный расчёт того же объекта берёт уже проверенный профиль из кэша».

## Стоимость / производительность (честно)
- На фактическом прогоне — 2 LLM-вызова вместо 1 (основной + проверяющий).
- **Про web-поиск**: `use_search` реально реализован ТОЛЬКО у Gemini; openai/anthropic его игнорируют (web-tool отсутствует). Поэтому «экономия на отключении поиска» — иллюзия. Берём `use_search=eff.llm_use_search` (равные условия). **Ассиметрия-риск**: если основной = Gemini c `use_search=True` и нашёл числа по web-grounding, а проверяющий = openai без интернета — возможны систематические «расхождения» не из-за ошибки нормы. Зафиксировано как известное ограничение; митигировать (v2): сверять преимущественно категории с `document_code` из реестра, либо разрешать проверяющему-Gemini реальный поиск.
- Тумблер по умолчанию ВЫКЛ. Деградация мягкая → ансамбль никогда не валит расчёт.

## Безопасность
- `build_named_provider` строит тот же класс провайдера → ключ уходит в заголовок (как у основного, см. фикс Gemini `x-goog-api-key`), не в query/логи. Регресса нет.
- `CrossCheck.reason` — только обобщённые константные строки, без `str(exc)`/`resp.text` провайдера.

## Совместимость / миграция
- Всё аддитивно: новые поля схем `Optional`/с дефолтами; новые настройки с дефолтами (выкл). При выключенном тумблере поведение и тесты не меняются.
- Без новых таблиц БД; настройки — существующая `AppSetting`.

## Тестирование
- `build_named_provider`: правильный класс по имени; Gemini получает 3-й арг `use_search`; `build_provider` = делегат (нет регрессии).
- `_parse_params`: тот же разбор, что в основном извлечении; отбрасывает `value<0`/NaN/inf.
- `cross_check_params` (monkeypatch `factory.build_named_provider` → fake-провайдер с заданным `extract_json`, без сети):
  - согласие → `confidence↑`, нота «подтверждено»;
  - расхождение → `needs_review=True`, нота с обоими значениями;
  - **краевые**: `(p=0,v=0)→agreed`; `(p=0,v=0.1)` и `(p=0.08,v=0)` → решение по формуле с `ABS_FLOOR` (не астрономический rel); разные `unit` → reason «единицы», без числового вердикта; отрицательное `v` отброшено в `_parse_params`;
  - деградация: verifier недоступен / == основной / `extract_json` бросил / вернул `{}` (нечитаемо) → `ran=False`, params не тронуты, **fake-verifier.extract_json НЕ вызывался** при пустом `primary_params`;
  - нота не превышает 500 символов после добавления суффикса.
- Резолвер: при `cross_check_enabled` профиль получает `cross_check.ran=True`; выключен → `enabled=False`, params не тронуты. Cache-hit при включённом тумблере поверх профиля без cross_check → перепрогон (не отдаётся старый кэш).
- Настройки API: `cross_check_*` сохраняются/отдаются; дефолт выкл; существующие settings-тесты зелёные.
- Полный сьют зелёный (по умолчанию выкл → нет регрессии).

## Фронт (минимально)
- Настройки: чекбокс «Кросс-проверка вторым ИИ (ансамбль)» + select проверяющего (с подсказкой про стоимость и про то, что проверяющий ≠ основной). Желательно не давать выбрать проверяющего == основной (иначе no-op).
- Смета: сводка кросс-проверки приходит строкой в `warnings`; расхождения — в существующем блоке «требует проверки». Отдельный UI не нужен в v1.

## Вне области (v2+)
- «Судья» (третий вызов) для авторазрешения расхождений.
- Кросс-проверка чат-правок и подтверждения источников.
- Нормировка единиц к канонической (`CATEGORY_META`) вместо пометки «единицы расходятся».
- Конфигурируемые `REL_TOL`/`CONF_BONUS`/веса доверия; сверка по `document_code` для снятия web-ассиметрии.

## Открытые вопросы к ревью
1. `REL_TOL = 0.15` (15%), `ABS_FLOOR = 1e-3`, `CONF_BONUS = 0.15` — ок как дефолты?
2. Единицы расходятся → помечаем `needs_review` и НЕ сравниваем числа (консервативно). Ок, или сразу нормировать к канонической единице (перенесено в v2)?
3. Инвалидация кэша при включённом тумблере (перепрогон, пока не закэширован проверенный профиль) — приемлемо по стоимости?
