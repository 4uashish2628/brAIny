"""HTTP API and dashboard server.

    python -m invigilator serve            # http://127.0.0.1:8000

Binds to localhost by default: there is no authentication, and anyone who can
create runs can make this machine run containers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..llm import DEFAULT_BASE_URL, DEFAULT_MODEL
from ..sandbox import Limits
from ..task import TaskError, discover_tasks
from . import db, jobqueue
from .config import DASHBOARD_DIR, REDIS_URL, TASKS_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    yield


app = FastAPI(title="Invigilator", version="0.4.0", lifespan=lifespan)


class RunRequest(BaseModel):
    tasks: list[str] = Field(default_factory=list, description="task names; empty means all")
    trials: int = Field(1, ge=1, le=20)
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    max_steps: int = Field(30, ge=1, le=200)
    memory_mb: int = Field(Limits.memory_mb, ge=64, le=8192)
    cpus: float = Field(Limits.cpus, gt=0, le=8)
    disk_mb: int = Field(Limits.disk_mb, ge=10, le=20480)
    trial_timeout: int = Field(Limits.trial_timeout, ge=10, le=7200)


def _tasks() -> dict:
    try:
        return {t.name: t for t in discover_tasks(TASKS_DIR)}
    except (TaskError, FileNotFoundError) as e:
        raise HTTPException(500, f"cannot load tasks from {TASKS_DIR}: {e}")


@app.get("/api/health")
def health() -> dict:
    r = jobqueue.connect()
    return {"ok": True, "queued": jobqueue.queue_length(r)}


@app.get("/api/tasks")
def list_tasks() -> list[dict]:
    return [{"name": name, "instruction": t.instruction} for name, t in _tasks().items()]


@app.post("/api/runs", status_code=201)
def create_run(req: RunRequest) -> dict:
    available = _tasks()
    names = req.tasks or sorted(available)
    unknown = [n for n in names if n not in available]
    if unknown:
        raise HTTPException(400, f"unknown task(s): {', '.join(unknown)}")

    limits = asdict(Limits(memory_mb=req.memory_mb, cpus=req.cpus, disk_mb=req.disk_mb,
                           trial_timeout=req.trial_timeout))
    run_id, trial_ids = db.create_run(req.model, req.base_url, req.max_steps, limits, names, req.trials)
    jobqueue.enqueue(jobqueue.connect(), trial_ids)
    return {"id": run_id, "trials": len(trial_ids)}


@app.get("/api/runs")
def list_runs() -> list[dict]:
    return db.jsonable(db.list_runs())


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return db.jsonable(run)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    if not db.get_run(run_id):
        raise HTTPException(404, "run not found")
    cancelled = db.cancel_run(run_id)
    r = jobqueue.connect()
    jobqueue.remove_queued(r, cancelled)
    for trial_id in cancelled:
        jobqueue.publish(r, run_id, {"type": "trial", "id": trial_id, "status": "cancelled"})
    jobqueue.publish(r, run_id, {"type": "run", "id": run_id, "status": "cancelled"})
    return {"cancelled": len(cancelled)}


@app.get("/api/trials/{trial_id}")
def get_trial(trial_id: str) -> dict:
    trial = db.get_trial(trial_id)
    if not trial:
        raise HTTPException(404, "trial not found")
    if trial["status"] == "running":
        # Not saved yet: send the steps streamed so far.
        trial["live_steps"] = jobqueue.live_steps(jobqueue.connect(), trial_id)
    instruction = TASKS_DIR / trial["task"] / "instruction.md"
    trial["instruction"] = instruction.read_text() if instruction.is_file() else None
    return db.jsonable(trial)


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    """Server-Sent Events: trial status changes and agent steps, as they happen."""
    if not db.get_run(run_id):
        raise HTTPException(404, "run not found")

    async def stream():
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe(jobqueue.CHANNEL.format(run_id=run_id))
        try:
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if message:
                    yield f"data: {message['data']}\n\n"
                else:
                    yield ": keep-alive\n\n"  # stops proxies and browsers from timing out
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
            await r.aclose()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# The built dashboard (dashboard/dist), with index.html for every non-API path.
if DASHBOARD_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DASHBOARD_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def dashboard(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404)
        file = DASHBOARD_DIR / path
        if path and file.is_file() and DASHBOARD_DIR in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(DASHBOARD_DIR / "index.html")


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")
