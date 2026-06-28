"""Отчёт об импорте."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportReport:
    target: str
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.target}: +{self.inserted} новых, ~{self.updated} обновлено, "
                f"{self.skipped} пропущено, ошибок {len(self.errors)}")
