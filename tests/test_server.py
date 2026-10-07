"""API, queue and worker tests against real Postgres and Redis.

Uses a separate database (invigilator_test) and Redis db 15, so real runs are
never touched. Skipped unless the server packages are installed and
`docker compose up -d` is running.

    .venv/bin/python -m unittest tests.test_server -v
"""

import json
import os
import unittest

os.environ.setdefault("INVIG_DATABASE_URL", "postgresql://invig:invig@localhost:5432/invigilator_test")
os.environ.setdefault("INVIG_REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("INVIG_TASKS_DIR", os.path.join(os.path.dirname(__file__), "..", "tasks"))


def services_available() -> bool:
    try:
        import psycopg
        import redis
        from fastapi.testclient import TestClient  # noqa: F401
    except ImportError:
        return False
    try:
        with psycopg.connect("postgresql://invig:invig@localhost:5432/invigilator", autocommit=True) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = 'invigilator_test'").fetchone():
                conn.execute("CREATE DATABASE invigilator_test")
        redis.Redis.from_url(os.environ["INVIG_REDIS_URL"]).ping()
        return True
    except Exception:
        return False


AVAILABLE = services_available()

if AVAILABLE:
    from fastapi.testclient import TestClient

    from invigilator.server import db, jobqueue, worker
    from invigilator.server.api import app


def scripted(*commands):
    """A fake model that runs the given commands, then calls finish."""
    def call(name, args):
        return {"content": "", "tool_calls": [{"id": "1", "type": "function",
                                               "function": {"name": name, "arguments": json.dumps(args)}}]}
    replies = [call("run_shell", {"command": c}) for c in commands] + [call("finish", {})]
    return lambda config, messages, tools: (replies.pop(0), {})


@unittest.skipUnless(AVAILABLE, "needs requirements-server.txt and `docker compose up -d`")
class ServerTest(unittest.TestCase):
    def setUp(self):
        db.init()
        db.delete_all()
        self.r = jobqueue.connect()
        self.r.flushdb()
        self.client = TestClient(app)

    def test_create_run_enqueues_one_job_per_trial(self):
        resp = self.client.post("/api/runs", json={"tasks": ["write-greeting", "count-lines"], "trials": 2})
        self.assertEqual(resp.status_code, 201)
        run_id = resp.json()["id"]
        self.assertEqual(resp.json()["trials"], 4)
        self.assertEqual(jobqueue.queue_length(self.r), 4)

        run = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(run["status"], "queued")
        self.assertEqual([t["status"] for t in run["trials"]], ["queued"] * 4)
        self.assertEqual(run["limits"]["memory_mb"], 512)

    def test_rejects_unknown_tasks_and_bad_input(self):
        self.assertEqual(self.client.post("/api/runs", json={"tasks": ["nope"]}).status_code, 400)
        self.assertEqual(self.client.post("/api/runs", json={"trials": 0}).status_code, 422)
        self.assertEqual(self.client.post("/api/runs", json={"memory_mb": 10}).status_code, 422)
        self.assertEqual(self.client.get("/api/runs/missing").status_code, 404)

    def test_cancel_removes_queued_trials(self):
        run_id = self.client.post("/api/runs", json={"tasks": ["write-greeting"], "trials": 3}).json()["id"]
        resp = self.client.post(f"/api/runs/{run_id}/cancel")
        self.assertEqual(resp.json()["cancelled"], 3)
        self.assertEqual(jobqueue.queue_length(self.r), 0)
        run = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(run["status"], "cancelled")
        self.assertTrue(all(t["status"] == "cancelled" for t in run["trials"]))

    def test_worker_runs_trial_saves_and_streams_it(self):
        run_id = self.client.post("/api/runs", json={"tasks": ["write-greeting"]}).json()["id"]
        pubsub = self.r.pubsub()
        pubsub.subscribe(jobqueue.CHANNEL.format(run_id=run_id))
        pubsub.get_message(timeout=1)  # subscribe confirmation

        trial_id = jobqueue.dequeue(self.r, "test-worker", timeout=1)
        status = worker.process_trial(self.r, trial_id,
                                      chat_fn=scripted("echo 'Hello, Invigilator!' > /app/greeting.txt"))
        jobqueue.ack(self.r, "test-worker", trial_id)
        self.assertEqual(status, "PASS")

        trial = self.client.get(f"/api/trials/{trial_id}").json()
        self.assertEqual(trial["status"], "PASS")
        self.assertEqual(trial["steps"], 1)
        self.assertEqual(trial["result"]["trajectory"]["steps"][0]["command"],
                         "echo 'Hello, Invigilator!' > /app/greeting.txt")
        self.assertEqual(self.client.get(f"/api/runs/{run_id}").json()["status"], "done")

        events = []
        while (message := pubsub.get_message(timeout=0.5)) is not None:
            events.append(json.loads(message["data"]))
        self.assertEqual([e["type"] for e in events], ["trial", "step", "trial", "run"])
        self.assertEqual(events[0]["status"], "running")
        self.assertEqual(events[2]["status"], "PASS")
        self.assertEqual(events[3]["status"], "done")

    def test_cancelled_trial_is_skipped_by_worker(self):
        run_id = self.client.post("/api/runs", json={"tasks": ["write-greeting"]}).json()["id"]
        trial_id = jobqueue.dequeue(self.r, "test-worker", timeout=1)  # worker took it just before cancel
        db.cancel_run(run_id)
        with db.connect() as conn:
            conn.execute("UPDATE trials SET status = 'cancelled' WHERE id = %s", (trial_id,))
        self.assertIsNone(worker.process_trial(self.r, trial_id, chat_fn=scripted()))


@unittest.skipUnless(AVAILABLE, "needs requirements-server.txt and `docker compose up -d`")
class QueueReliabilityTest(unittest.TestCase):
    def setUp(self):
        self.r = jobqueue.connect()
        self.r.flushdb()

    def test_jobs_of_a_dead_worker_are_requeued(self):
        jobqueue.enqueue(self.r, ["a", "b", "c"])
        jobqueue.heartbeat(self.r, "dead")
        self.assertEqual(jobqueue.dequeue(self.r, "dead", timeout=1), "a")
        self.assertEqual(jobqueue.dequeue(self.r, "dead", timeout=1), "b")

        self.assertEqual(jobqueue.requeue_orphans(self.r), 0)  # heartbeat still alive: leave it alone

        self.r.delete(jobqueue.HEARTBEAT.format(worker="dead"))  # worker crashed; heartbeat expired
        self.assertEqual(jobqueue.requeue_orphans(self.r), 2)
        self.assertEqual(jobqueue.queue_length(self.r), 3)
        taken = {jobqueue.dequeue(self.r, "new", timeout=1) for _ in range(3)}
        self.assertEqual(taken, {"a", "b", "c"})  # nothing lost, nothing duplicated

    def test_ack_removes_only_that_job(self):
        jobqueue.enqueue(self.r, ["x", "y"])
        jobqueue.dequeue(self.r, "w", timeout=1)
        jobqueue.dequeue(self.r, "w", timeout=1)
        jobqueue.ack(self.r, "w", "x")
        self.assertEqual(self.r.lrange(jobqueue.PROCESSING.format(worker="w"), 0, -1), ["y"])


if __name__ == "__main__":
    unittest.main()
