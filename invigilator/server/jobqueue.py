"""A reliable job queue and live event stream on Redis.

Queue: trial ids wait in a list. A worker atomically moves one into its *own*
processing list (BLMOVE) and removes it only after the trial is saved. If the
worker dies mid-trial, the id is still in its processing list; the worker's
heartbeat key expires, and the next worker to start moves the id back onto
the queue. So a crash delays a trial but never loses it.

Events: workers publish trial updates and each agent step to a per-run
pub/sub channel, which the API streams to the dashboard. Steps of a running
trial are also kept in a short-lived list, so a page opened mid-trial can
catch up on what already happened.
"""

from __future__ import annotations

import json
from typing import Optional

import redis

from .config import REDIS_URL

QUEUE = "invig:queue"
PROCESSING = "invig:processing:{worker}"
HEARTBEAT = "invig:worker:{worker}"
HEARTBEAT_TTL = 30  # seconds; workers refresh every 10
CHANNEL = "invig:run:{run_id}"
LIVE_STEPS = "invig:trial:{trial_id}:steps"
LIVE_STEPS_TTL = 24 * 3600


def connect() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


# -- queue ----------------------------------------------------------------------

def enqueue(r: redis.Redis, trial_ids: list[str]) -> None:
    if trial_ids:
        r.lpush(QUEUE, *trial_ids)


def dequeue(r: redis.Redis, worker: str, timeout: int = 5) -> Optional[str]:
    """Block until a job is available, moving it to this worker's processing list."""
    return r.blmove(QUEUE, PROCESSING.format(worker=worker), timeout, "RIGHT", "LEFT")


def ack(r: redis.Redis, worker: str, trial_id: str) -> None:
    r.lrem(PROCESSING.format(worker=worker), 1, trial_id)


def remove_queued(r: redis.Redis, trial_ids: list[str]) -> None:
    for trial_id in trial_ids:
        r.lrem(QUEUE, 0, trial_id)


def heartbeat(r: redis.Redis, worker: str) -> None:
    r.set(HEARTBEAT.format(worker=worker), "1", ex=HEARTBEAT_TTL)


def dead_workers(r: redis.Redis) -> list[str]:
    """Workers that still hold jobs but whose heartbeat has expired."""
    workers = [key.rsplit(":", 1)[1] for key in r.scan_iter(PROCESSING.format(worker="*"))]
    return [w for w in workers if not r.exists(HEARTBEAT.format(worker=w))]


def requeue_orphans(r: redis.Redis, workers: Optional[list[str]] = None) -> int:
    """Move jobs held by dead workers back onto the queue."""
    moved = 0
    for worker in dead_workers(r) if workers is None else workers:
        # One at a time, so nothing is lost if we crash here too.
        while r.lmove(PROCESSING.format(worker=worker), QUEUE, "RIGHT", "RIGHT"):
            moved += 1
    return moved


def queue_length(r: redis.Redis) -> int:
    return r.llen(QUEUE)


# -- events -----------------------------------------------------------------------

def publish(r: redis.Redis, run_id: str, event: dict) -> None:
    r.publish(CHANNEL.format(run_id=run_id), json.dumps(event, default=str))


def record_step(r: redis.Redis, trial_id: str, step: dict) -> None:
    key = LIVE_STEPS.format(trial_id=trial_id)
    r.rpush(key, json.dumps(step))
    r.expire(key, LIVE_STEPS_TTL)


def live_steps(r: redis.Redis, trial_id: str) -> list[dict]:
    return [json.loads(s) for s in r.lrange(LIVE_STEPS.format(trial_id=trial_id), 0, -1)]


def clear_live_steps(r: redis.Redis, trial_id: str) -> None:
    r.delete(LIVE_STEPS.format(trial_id=trial_id))
