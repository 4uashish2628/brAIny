"""PostgreSQL storage for runs and trials.

A run is one evaluation request (model + tasks + trials per task). Each trial
is one agent attempt at one task, and is also the unit of work on the queue.
The full TrialResult, including the trajectory, is stored as JSONB.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import DATABASE_URL

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    max_steps   INT NOT NULL,
    limits      JSONB NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | cancelled
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS trials (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    task        TEXT NOT NULL,
    trial_no    INT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',   -- queued | running | cancelled | PASS | FAIL | TAMPER | LIMIT | ERROR
    steps       INT,
    duration    REAL,
    detail      TEXT,
    result      JSONB,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    UNIQUE (run_id, task, trial_no)
);

CREATE INDEX IF NOT EXISTS trials_run_id ON trials (run_id);
"""

FINISHED = ("PASS", "FAIL", "TAMPER", "LIMIT", "ERROR", "cancelled")


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)


def init() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)


def create_run(model: str, base_url: str, max_steps: int, limits: dict,
               tasks: list[str], trials: int) -> tuple[str, list[str]]:
    run_id = uuid.uuid4().hex[:12]
    trial_ids = []
    with connect() as conn, conn.transaction():
        conn.execute(
            "INSERT INTO runs (id, model, base_url, max_steps, limits) VALUES (%s, %s, %s, %s, %s)",
            (run_id, model, base_url, max_steps, Jsonb(limits)),
        )
        for task in tasks:
            for n in range(1, trials + 1):
                trial_id = uuid.uuid4().hex[:12]
                conn.execute(
                    "INSERT INTO trials (id, run_id, task, trial_no) VALUES (%s, %s, %s, %s)",
                    (trial_id, run_id, task, n),
                )
                trial_ids.append(trial_id)
    return run_id, trial_ids


_RUN_SUMMARY = """
    SELECT r.id, r.model, r.status, r.created_at, r.finished_at,
           count(t.id)                                       AS total,
           count(t.id) FILTER (WHERE t.status = 'PASS')      AS passed,
           count(t.id) FILTER (WHERE t.status IN ('FAIL', 'TAMPER', 'LIMIT', 'ERROR')) AS failed,
           count(t.id) FILTER (WHERE t.status = 'TAMPER')    AS tampered,
           count(t.id) FILTER (WHERE t.status = 'running')   AS running,
           array_agg(DISTINCT t.task)                        AS tasks
    FROM runs r LEFT JOIN trials t ON t.run_id = r.id
"""


def list_runs(limit: int = 50) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            _RUN_SUMMARY + " GROUP BY r.id ORDER BY r.created_at DESC LIMIT %s", (limit,)
        ).fetchall()


def get_run(run_id: str) -> Optional[dict]:
    with connect() as conn:
        run = conn.execute(_RUN_SUMMARY + " WHERE r.id = %s GROUP BY r.id", (run_id,)).fetchone()
        if not run:
            return None
        extra = conn.execute("SELECT base_url, max_steps, limits FROM runs WHERE id = %s", (run_id,)).fetchone()
        run.update(extra)
        run["trials"] = conn.execute(
            """SELECT id, task, trial_no, status, steps, duration, detail, started_at, finished_at
               FROM trials WHERE run_id = %s ORDER BY task, trial_no""",
            (run_id,),
        ).fetchall()
        return run


def get_trial(trial_id: str) -> Optional[dict]:
    with connect() as conn:
        return conn.execute(
            """SELECT t.*, r.model FROM trials t JOIN runs r ON r.id = t.run_id WHERE t.id = %s""",
            (trial_id,),
        ).fetchone()


def start_trial(trial_id: str) -> Optional[dict]:
    """Claim a trial for running. Returns what the worker needs, or None if the
    trial was cancelled or already finished. 'running' is accepted too, so a
    trial orphaned by a crashed worker can be picked up again."""
    with connect() as conn, conn.transaction():
        trial = conn.execute(
            """UPDATE trials SET status = 'running', started_at = now()
               WHERE id = %s AND status IN ('queued', 'running')
               RETURNING id, run_id, task, trial_no""",
            (trial_id,),
        ).fetchone()
        if not trial:
            return None
        conn.execute("UPDATE runs SET status = 'running' WHERE id = %s AND status = 'queued'", (trial["run_id"],))
        trial.update(conn.execute(
            "SELECT model, base_url, max_steps, limits FROM runs WHERE id = %s", (trial["run_id"],)
        ).fetchone())
        return trial


def finish_trial(trial_id: str, status: str, steps: int, duration: float, detail: str, result: dict) -> None:
    with connect() as conn:
        conn.execute(
            """UPDATE trials SET status = %s, steps = %s, duration = %s, detail = %s,
                                 result = %s, finished_at = now()
               WHERE id = %s""",
            (status, steps, duration, detail, Jsonb(result), trial_id),
        )


def finish_run_if_complete(run_id: str) -> bool:
    """Mark the run done once no trial is queued or running. Returns True if it just finished."""
    with connect() as conn:
        row = conn.execute(
            """UPDATE runs SET status = 'done', finished_at = now()
               WHERE id = %s AND status IN ('queued', 'running')
                 AND NOT EXISTS (SELECT 1 FROM trials WHERE run_id = %s AND status IN ('queued', 'running'))
               RETURNING id""",
            (run_id, run_id),
        ).fetchone()
        return row is not None


def cancel_run(run_id: str) -> list[str]:
    """Cancel the run's queued trials (running ones finish). Returns their ids."""
    with connect() as conn, conn.transaction():
        rows = conn.execute(
            """UPDATE trials SET status = 'cancelled', finished_at = now()
               WHERE run_id = %s AND status = 'queued' RETURNING id""",
            (run_id,),
        ).fetchall()
        conn.execute(
            """UPDATE runs SET status = 'cancelled', finished_at = now()
               WHERE id = %s AND status IN ('queued', 'running')""",
            (run_id,),
        )
    return [r["id"] for r in rows]


def delete_all() -> None:
    """For tests."""
    with connect() as conn:
        conn.execute("TRUNCATE runs CASCADE")


def jsonable(row: Any) -> Any:
    """datetimes -> ISO strings, recursively, for JSON responses and events."""
    if isinstance(row, dict):
        return {k: jsonable(v) for k, v in row.items()}
    if isinstance(row, list):
        return [jsonable(v) for v in row]
    if hasattr(row, "isoformat"):
        return row.isoformat()
    return row
