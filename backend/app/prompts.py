"""Code-default system prompts + DB read-through with reset support."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Prompt
from .norms.extractor import SYSTEM_PROMPT as NORM_EXTRACTION_PROMPT

ESTIMATE_EDIT_PROMPT = """Ты — помощник-сметчик Республики Казахстан. На вход даётся
текущая смета (разделы и строки) и просьба заказчика изменить её.

Каждая строка имеет поля: no, section, title, norm, unit, quantity,
material_price, labor_price, machine_price, needs_review, comment.

Жёсткие правила:
- Верни СТРОГО один JSON-объект и ничего вокруг.
- Формат: {"reply": "<короткий ответ заказчику по-русски>",
  "lines": [<полный изменённый список строк со ВСЕМИ полями>],
  "warnings_add": ["<новое предупреждение>"]}.
- Возвращай ВЕСЬ список строк, а не только изменённые.
- НЕ считай итоги, разделы и total строк — это делает система.
- НЕ выдумывай нормы; спорное помечай "needs_review": true и поясняй в "comment".
- Сохраняй схему строки точно (те же имена полей)."""

PROMPT_DEFAULTS: dict[str, dict[str, str]] = {
    "norm_extraction": {
        "title": "Извлечение норм РК",
        "description": "Используется при расчёте сметы (резолвер норм).",
        "body": NORM_EXTRACTION_PROMPT,
    },
    "estimate_edit": {
        "title": "Редактирование сметы (чат)",
        "description": "Используется в чате карточки сметы.",
        "body": ESTIMATE_EDIT_PROMPT,
    },
}


def seed_prompts(db: Session) -> None:
    existing = {p.key: p for p in db.scalars(select(Prompt)).all()}
    for key, meta in PROMPT_DEFAULTS.items():
        row = existing.get(key)
        if row is None:
            db.add(Prompt(key=key, title=meta["title"],
                          description=meta["description"], body=meta["body"],
                          is_custom=False))
        elif not row.is_custom:
            # Незаказные промпты держим синхронными с дефолтом в коде: правка дефолта
            # (новые нормы — напр. Строительный кодекс) применяется на следующем старте.
            # Промпты, отредактированные пользователем (is_custom=True), не трогаем.
            row.title, row.description, row.body = meta["title"], meta["description"], meta["body"]
    db.commit()


def get_prompt(db: Session, key: str) -> str:
    """DB body if present, else the code default, else empty string."""
    row = db.scalar(select(Prompt).where(Prompt.key == key))
    if row and row.body:
        return row.body
    default = PROMPT_DEFAULTS.get(key)
    return default["body"] if default else ""
