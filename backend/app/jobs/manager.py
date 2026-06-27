"""Менеджер задач: запуск расчёта в потоке + публикация статусов через очередь."""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Optional

from ..calc import build_estimate
from ..calc.volumes import compute_volumes  # noqa: F401  (через build_estimate)
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


@dataclass
class JobRuntime:
    id: str
    steps: list[JobStep]
    status: str = "pending"
    progress: int = 0
    error: str = ""
    result: Optional[EstimateResult] = None
    estimate_id: Optional[int] = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    loop: Optional[asyncio.AbstractEventLoop] = None
    finished: bool = False

    def snapshot(self) -> JobStatus:
        return JobStatus(
            id=self.id,
            status=self.status,
            progress=self.progress,
            steps=self.steps,
            error=self.error,
            estimate_id=self.estimate_id,
            result=self.result,
        )


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRuntime] = {}

    def create(self) -> JobRuntime:
        job_id = str(uuid.uuid4())
        steps = [JobStep(key=k, label=l) for k, l in STEP_DEFS]
        runtime = JobRuntime(id=job_id, steps=steps)
        self._jobs[job_id] = runtime
        with SessionLocal() as db:
            db.add(Job(id=job_id, status="pending", steps=to_jsonable(steps)))
            db.commit()
        return runtime

    def get(self, job_id: str) -> Optional[JobRuntime]:
        return self._jobs.get(job_id)

    # ── публикация событий (вызывается из рабочего потока) ──
    def _publish(self, runtime: JobRuntime) -> None:
        snap = runtime.snapshot()
        if runtime.loop is not None:
            runtime.loop.call_soon_threadsafe(runtime.queue.put_nowait, snap)

    def _set_step(self, runtime: JobRuntime, key: str, status: str, detail: str = "") -> None:
        for i, step in enumerate(runtime.steps):
            if step.key == key:
                step.status = status
                if detail:
                    step.detail = detail
                # прогресс монотонно растёт, даже если шаги помечаются не по порядку
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
            self._set_step(runtime, "parse", "running")
            inp.signature()  # нормализация/проверка
            self._set_step(runtime, "parse", "done")

            def progress(key: str, detail: str) -> None:
                # резолвер шлёт ключи norms_cache / norms_llm
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

            # сохранить расчёт
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
        except Exception as exc:  # noqa: BLE001 — фиксируем любую ошибку в статус
            runtime.status = "error"
            runtime.error = f"{type(exc).__name__}: {exc}"
            self._publish(runtime)
            job_row = db.get(Job, runtime.id)
            if job_row:
                job_row.status = "error"
                job_row.error = runtime.error
                db.commit()
        finally:
            runtime.finished = True
            if runtime.loop is not None:
                runtime.loop.call_soon_threadsafe(runtime.queue.put_nowait, None)
            db.close()

    # ── стрим статусов (SSE) ──
    async def events(self, job_id: str) -> AsyncIterator[JobStatus]:
        runtime = self._jobs.get(job_id)
        if runtime is None:
            return
        # начальный снапшот
        yield runtime.snapshot()
        if runtime.finished:
            return
        while True:
            item = await runtime.queue.get()
            if item is None:
                break
            yield item


job_manager = JobManager()
