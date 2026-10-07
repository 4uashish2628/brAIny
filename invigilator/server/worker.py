"""Workers: take trials off the queue, run them in sandboxes, save and stream results.

    python -m invigilator worker --concurrency 4
"""

from __future__ import annotations

import os
import socket
import threading
import uuid
from dataclasses import asdict
from typing import Optional

from ..agent import ChatFn, Step
from ..llm import LLMConfig, chat
from ..runner import run_trial
from ..sandbox import Limits, build_image, remove_containers, safe_parallelism
from ..task import Task, TaskError
from . import db, jobqueue
from .config import TASKS_DIR

_build_locks: dict[str, threading.Lock] = {}
_build_locks_guard = threading.Lock()


def _task_lock(name: str) -> threading.Lock:
    """One image build per task at a time, so worker threads don't race to build it."""
    with _build_locks_guard:
        return _build_locks.setdefault(name, threading.Lock())


def process_trial(r, trial_id: str, chat_fn: ChatFn = chat, owner: str = "") -> Optional[str]:
    """Run one trial end to end. Returns its final status, or None if it was
    cancelled before starting. chat_fn is injectable for tests."""
    info = db.start_trial(trial_id)
    if info is None:
        return None
    run_id = info["run_id"]
    jobqueue.clear_live_steps(r, trial_id)  # in case this is a retry after a crash
    jobqueue.publish(r, run_id, {"type": "trial", "id": trial_id, "status": "running"})

    def on_step(step: Step) -> None:
        data = asdict(step)
        jobqueue.record_step(r, trial_id, data)
        jobqueue.publish(r, run_id, {"type": "step", "trial_id": trial_id, "step": data})

    try:
        task = Task.load(TASKS_DIR / info["task"])
    except TaskError as e:
        db.finish_trial(trial_id, "ERROR", 0, 0.0, str(e), {"error": str(e)})
        status, steps, duration, detail = "ERROR", 0, 0.0, str(e)
    else:
        limits = Limits(**info["limits"])
        llm = LLMConfig(model=info["model"], base_url=info["base_url"],
                        api_key=os.environ.get("INVIG_API_KEY"))
        with _task_lock(task.name):
            build_image(task)  # cached after the first time
        result = run_trial(task, "agent", limits=limits, llm=llm, max_steps=info["max_steps"],
                           run_id=run_id, chat_fn=chat_fn, on_step=on_step, owner=owner)
        traj = result.trajectory or {}
        steps = len(traj.get("steps", []))
        if result.tampering:
            detail = "tampered: " + ", ".join(result.tampering[:3])
        else:
            detail = result.error or result.violation or traj.get("error") or traj.get("stop_reason", "")
        status, duration = result.status, round(result.duration, 1)
        db.finish_trial(trial_id, status, steps, duration, detail, asdict(result))

    jobqueue.clear_live_steps(r, trial_id)
    jobqueue.publish(r, run_id, {"type": "trial", "id": trial_id, "status": status,
                                 "steps": steps, "duration": duration, "detail": detail})
    if db.finish_run_if_complete(run_id):
        jobqueue.publish(r, run_id, {"type": "run", "id": run_id, "status": "done"})
    return status


def _record_crash(r, trial_id: str, error: Exception) -> None:
    trial = db.get_trial(trial_id)
    if not trial:
        return
    detail = f"worker error: {error!r}"
    db.finish_trial(trial_id, "ERROR", 0, 0.0, detail, {"error": detail})
    jobqueue.publish(r, trial["run_id"], {"type": "trial", "id": trial_id, "status": "ERROR", "detail": detail})
    if db.finish_run_if_complete(trial["run_id"]):
        jobqueue.publish(r, trial["run_id"], {"type": "run", "id": trial["run_id"], "status": "done"})


def run_worker(concurrency: int = 1) -> None:
    db.init()
    r = jobqueue.connect()
    worker = f"{socket.gethostname().replace(':', '-')}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    concurrency = safe_parallelism(concurrency, Limits())
    stop = threading.Event()

    jobqueue.heartbeat(r, worker)
    # Recover from workers that died mid-trial: remove their sandboxes, retry their trials.
    dead = jobqueue.dead_workers(r)
    removed = sum(remove_containers(owner=w) for w in dead)
    requeued = jobqueue.requeue_orphans(r, dead)
    print(f"worker {worker}: {concurrency} slot(s), tasks from {TASKS_DIR}"
          + (f", requeued {requeued} trial(s) and removed {removed} sandbox(es) from dead workers"
             if requeued or removed else ""), flush=True)

    def beat() -> None:
        while not stop.wait(10):
            jobqueue.heartbeat(r, worker)


    def slot(n: int) -> None:
        conn = jobqueue.connect()
        while not stop.is_set():
            trial_id = jobqueue.dequeue(conn, worker, timeout=2)
            if trial_id is None:
                continue
            print(f"  [{n}] trial {trial_id} started", flush=True)
            try:
                status = process_trial(conn, trial_id, owner=worker)
                print(f"  [{n}] trial {trial_id}: {status or 'cancelled'}", flush=True)
            except Exception as e:
                # Record it rather than retrying forever; keep the worker alive.
                print(f"  [{n}] trial {trial_id} crashed: {e!r}", flush=True)
                _record_crash(conn, trial_id, e)
            jobqueue.ack(conn, worker, trial_id)

    threads = [threading.Thread(target=beat, daemon=True)]
    threads += [threading.Thread(target=slot, args=(n,), daemon=True) for n in range(1, concurrency + 1)]
    for t in threads:
        t.start()
    try:
        while True:
            threads[1].join(1)
    except KeyboardInterrupt:
        print("\nstopping worker...", flush=True)
        stop.set()
        # In-flight trials stay in this worker's processing list. Drop the heartbeat
        # so the next worker to start requeues them right away, and remove sandboxes.
        r.delete(jobqueue.HEARTBEAT.format(worker=worker))
        remove_containers(owner=worker)
        os._exit(130)
