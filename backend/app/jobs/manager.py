"""Менеджер задач: запуск расчёта в потоке + публикация статусов (fan-out SSE)."""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Optional

from ..calc import build_estimate
from ..database import SessionLocal
from ..models import Estimate, Job
from ..norms import resolve_norm_profile
from ..schemas import BuildingInput, EstimateResult, JobStatus, JobStep, to_jsonable

# Канонические шаги пайплайна (отображаются на фронте).
STEP_DEFS: list[tuple[str, str]] = [
    ("parse", "Разбор введённых атрибутов"),
    ("norms_cache", "Поиск нормативных требований в БД"),
    ("norms_llm", "Извлечение норм ГОСТ/СНиП (LLM)"),
    ("volumes", "Расчёт объёмов материалов"),
    ("estimate", "Формирование сметы и итогов"),
    ("done", "Готово"),
]

# Сколько держать завершённую задачу в памяти (для SSE и поллинга статуса).
JOB_RETENTION_SECONDS = 600


@dataclass
class JobRuntime:
    id: str
    steps: list[JobStep]
    status: str = "pending"
    progress: int = 0
    error: str = ""
    result: Optional[EstimateResult] = None
    estimate_id: Optional[int] = None
    loop: Optional[asyncio.AbstractEventLoop] = None
    finished: bool = False
    # Каждый SSE-подписчик получает собственную очередь (fan-out).
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    latest: Optional[JobStatus] = None

    def snapshot(self) -> JobStatus:
        return JobStatus(
            id=self.id,
            status=self.status,
            progress=self.progress,
            steps=[s.model_copy() for s in self.steps],
            error=self.error,
            estimate_id=self.estimate_id,
            result=self.result,
        )


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRuntime] = {}

    def create(self) -> JobRuntime:
        """Только in-memory (без блокирующей записи в БД на event loop)."""
        job_id = str(uuid.uuid4())
        steps = [JobStep(key=k, label=l) for k, l in STEP_DEFS]
        runtime = JobRuntime(id=job_id, steps=steps)
        self._jobs[job_id] = runtime
        return runtime

    def get(self, job_id: str) -> Optional[JobRuntime]:
        return self._jobs.get(job_id)

    # ── публикация событий ──
    def _broadcast(self, runtime: JobRuntime, item: Optional[JobStatus]) -> None:
        """Выполняется на loop-потоке: рассылает событие всем подписчикам."""
        if isinstance(item, JobStatus):
            runtime.latest = item
        for q in list(runtime.subscribers):
            q.put_nowait(item)

    def _publish(self, runtime: JobRuntime) -> None:
        snap = runtime.snapshot()
        if runtime.loop is not None:
            runtime.loop.call_soon_threadsafe(self._broadcast, runtime, snap)

    def _set_step(self, runtime: JobRuntime, key: str, status: str, detail: str = "") -> None:
        for i, step in enumerate(runtime.steps):
            if step.key == key:
                step.status = status
                if detail:
                    step.detail = detail
                runtime.progress = max(
                    runtime.progress, int((i + 1) / len(runtime.steps) * 100)
                )
                break
        self._publish(runtime)

    # ── запуск ──
    async def start(self, runtime: JobRuntime, inp: BuildingInput) -> None:
        runtime.loop = asyncio.get_running_loop()
        runtime.status = "running"
        asyncio.create_task(self._run(runtime, inp))

    async def _run(self, runtime: JobRuntime, inp: BuildingInput) -> None:
        await asyncio.to_thread(self._execute, runtime, inp)

    def _execute(self, runtime: JobRuntime, inp: BuildingInput) -> None:
        db = SessionLocal()
        try:
            # Запись pending-строки в БД — уже в рабочем потоке, не на loop.
            db.add(Job(id=runtime.id, status="running", steps=to_jsonable(runtime.steps)))
            db.commit()

            self._set_step(runtime, "parse", "running")
            inp.signature()  # нормализация/проверка
            self._set_step(runtime, "parse", "done")

            def progress(key: str, detail: str) -> None:
                self._set_step(runtime, key, "running", detail)

            profile = resolve_norm_profile(db, inp, progress)
            self._set_step(runtime, "norms_cache", "done")
            self._set_step(runtime, "norms_llm", "done")

            self._set_step(runtime, "volumes", "running")
            self._set_step(runtime, "volumes", "done",
                           "Объёмы рассчитаны по геометрии и нормам")

            self._set_step(runtime, "estimate", "running")
            result = build_estimate(db, inp, profile)
            self._set_step(runtime, "estimate", "done")

            est = Estimate(
                input=to_jsonable(inp),
                result=to_jsonable(result),
                total=result.totals.grand_total,
            )
            db.add(est)
            db.commit()
            runtime.estimate_id = est.id
            runtime.result = result
            runtime.status = "done"
            self._set_step(runtime, "done", "done")

            job_row = db.get(Job, runtime.id)
            if job_row:
                job_row.status = "done"
                job_row.estimate_id = est.id
                job_row.progress = 100
                job_row.steps = to_jsonable(runtime.steps)
                db.commit()
        except Exception as exc:  # noqa: BLE001 — любую ошибку фиксируем в статус
            runtime.status = "error"
            runtime.error = f"{type(exc).__name__}: {exc}"
            self._publish(runtime)
            self._persist_error(runtime)
        finally:
            runtime.finished = True
            if runtime.loop is not None:
                runtime.loop.call_soon_threadsafe(self._finalize, runtime)
            db.close()

    def _persist_error(self, runtime: JobRuntime) -> None:
        """Записать статус ошибки в свежей сессии (исходная могла «отравиться»)."""
        try:
            with SessionLocal() as edb:
                row = edb.get(Job, runtime.id)
                if row is None:
                    row = Job(id=runtime.id)
                    edb.add(row)
                row.status = "error"
                row.error = runtime.error
                edb.commit()
        except Exception:  # noqa: BLE001 — не даём вторичной ошибке всплыть
            pass

    def _finalize(self, runtime: JobRuntime) -> None:
        """На loop-потоке: терминальный сигнал подписчикам + отложенная очистка."""
        self._broadcast(runtime, None)
        if runtime.loop is not None:
            runtime.loop.call_later(
                JOB_RETENTION_SECONDS, self._jobs.pop, runtime.id, None
            )

    # ── стрим статусов (SSE) ──
    async def events(self, job_id: str) -> AsyncIterator[JobStatus]:
        runtime = self._jobs.get(job_id)
        if runtime is None:
            return

        queue: asyncio.Queue = asyncio.Queue()
        runtime.subscribers.append(queue)
        try:
            # начальный снапшот (текущее состояние)
            yield runtime.latest or runtime.snapshot()
            if runtime.finished:
                return
            while True:
                item = await queue.get()
                if item is None:  # терминальный сигнал
                    break
                yield item
        finally:
            if queue in runtime.subscribers:
                runtime.subscribers.remove(queue)


job_manager = JobManager()
