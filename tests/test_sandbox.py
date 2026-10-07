"""Adversarial sandbox tests: each one tries to break out of a limit.

Needs Docker; skipped without it.

    python3 -m unittest tests.test_sandbox -v
"""

import json
import shutil
import subprocess
import time
import unittest
from pathlib import Path

from invigilator.llm import LLMConfig
from invigilator.runner import run_trial
from invigilator.sandbox import Limits, Sandbox
from invigilator.task import Task

IMAGE = "python:3.12-slim"
KEEP_ALIVE = ["sleep", "infinity"]  # the image's own CMD (python3 REPL) exits immediately
TASKS = Path(__file__).resolve().parent.parent / "tasks"


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def count_procs(sandbox, needle: str) -> int:
    """Processes whose command line contains needle (bracket trick so grep doesn't match itself)."""
    pattern = f"[{needle[0]}]{needle[1:]}"
    script = (f'n=0; for f in /proc/[0-9]*/cmdline; do tr "\\0" " " < "$f" 2>/dev/null '
              f'| grep -q "{pattern}" && n=$((n+1)); done; echo $n')
    return int(sandbox.exec(["sh", "-c", script], timeout=30)[1].strip())


def tool_call(command):
    return {"content": "", "tool_calls": [{"id": "1", "type": "function", "function": {
        "name": "run_shell", "arguments": json.dumps({"command": command})}}]}


def scripted(*commands):
    """A fake model that runs the given commands, then calls finish."""
    replies = [tool_call(c) for c in commands]
    replies.append({"content": "", "tool_calls": [{"id": "2", "type": "function",
                                                   "function": {"name": "finish", "arguments": "{}"}}]})
    return lambda config, messages, tools: (replies.pop(0), {})


@unittest.skipUnless(docker_available(), "Docker is not running")
class ResourceLimitTest(unittest.TestCase):
    def test_memory_bomb_is_killed(self):
        with Sandbox(IMAGE, Limits(memory_mb=128), command=KEEP_ALIVE) as sb:
            code, out = sb.exec(["python3", "-c", "x = bytearray(1024 * 1024 * 1024)"], timeout=30)
        self.assertEqual(code, 137, out)  # SIGKILL from the kernel's OOM killer

    def test_fork_bomb_is_contained(self):
        # 500 processes against a limit of 64. The bomb's shell gives up with
        # "Cannot fork" and exits, leaving orphans holding every slot. The cap
        # holds, and the next command can't start, so the sandbox is ended
        # (LIMIT) rather than left wedged. The host never notices.
        with Sandbox(IMAGE, Limits(pids=64), command=KEEP_ALIVE) as sb:
            start = time.monotonic()
            sb.exec(["sh", "-c", "for i in $(seq 1 500); do sleep 300 & done; wait"], timeout=5)
            code, out = sb.exec(["echo", "hi"], timeout=10)
            self.assertLess(time.monotonic() - start, 30)
            if sb.violation:
                self.assertIn("process limit", sb.violation)
                self.assertNotEqual(code, 0)
            else:
                self.assertEqual((code, out), (0, "hi\n"))  # slots freed up in time

    def test_single_file_size_is_capped(self):
        with Sandbox(IMAGE, Limits(max_file_mb=10), command=KEEP_ALIVE) as sb:
            sb.exec(["sh", "-c", "dd if=/dev/zero of=/big bs=1M count=100"], timeout=30)
            _, size = sb.exec(["sh", "-c", "wc -c < /big"], timeout=10)
        self.assertEqual(int(size), 10 * 1024 * 1024)

    def test_disk_fill_trips_watchdog(self):
        with Sandbox(IMAGE, Limits(disk_mb=50, max_file_mb=20), command=KEEP_ALIVE) as sb:
            sb.exec(["sh", "-c", "for i in $(seq 1 20); do dd if=/dev/zero of=/f$i bs=1M count=10 2>/dev/null; done; sleep 30"],
                    timeout=60)
            self.assertIsNotNone(sb.violation)
            self.assertIn("disk usage", sb.violation)
            code, out = sb.exec(["echo", "hi"], timeout=10)
        self.assertEqual(code, 137)
        self.assertIn("sandbox stopped", out)

    def test_endless_output_is_cut_off_and_killed(self):
        with Sandbox(IMAGE, Limits(max_output_kb=64), command=KEEP_ALIVE) as sb:
            start = time.monotonic()
            code, out = sb.exec(["yes"], timeout=30)
            elapsed = time.monotonic() - start
            self.assertLess(elapsed, 10)
            self.assertIn("output exceeded 64 KB", out)
            self.assertLess(len(out), 70 * 1024)
            self.assertEqual(count_procs(sb, "yes"), 0)

    def test_timeout_kills_whole_process_tree(self):
        with Sandbox(IMAGE, command=KEEP_ALIVE) as sb:
            code, out = sb.exec(["sh", "-c", "sleep 1000 & (sleep 1000 &); sleep 1000"], timeout=2)
            self.assertEqual(code, 124)
            self.assertIn("timed out", out)
            time.sleep(0.5)
            self.assertEqual(count_procs(sb, "sleep 1000"), 0)

    def test_background_server_from_finished_command_survives(self):
        with Sandbox(IMAGE, command=KEEP_ALIVE) as sb:
            code, _ = sb.exec(["sh", "-c", "nohup sleep 300 > /dev/null 2>&1 &"], timeout=10)
            self.assertEqual(code, 0)
            self.assertEqual(count_procs(sb, "sleep 300"), 1)

    def test_trial_timeout_stops_everything(self):
        with Sandbox(IMAGE, Limits(trial_timeout=3), command=KEEP_ALIVE) as sb:
            code, out = sb.exec(["sleep", "30"], timeout=60)
            self.assertIn("time limit", sb.violation)
        self.assertNotEqual(code, 0)

    def test_no_network(self):
        with Sandbox(IMAGE, command=KEEP_ALIVE) as sb:
            code, _ = sb.exec(["python3", "-c", "import urllib.request; urllib.request.urlopen('http://1.1.1.1', timeout=3)"],
                              timeout=20)
        self.assertNotEqual(code, 0)

    def test_dangerous_capabilities_dropped(self):
        with Sandbox(IMAGE, command=KEEP_ALIVE) as sb:
            code, out = sb.exec(["sh", "-c", "mkdir -p /mnt/x && mount -t tmpfs none /mnt/x"], timeout=10)
        self.assertNotEqual(code, 0, out)


@unittest.skipUnless(docker_available(), "Docker is not running")
class CheatingAgentTest(unittest.TestCase):
    def test_replacing_test_tools_is_caught(self):
        # Can't configure nginx? Replace wget with a fake that prints what the tests look for.
        fake_wget = ("rm /usr/bin/wget && printf '#!/bin/sh\\necho invig-home-7f3a invig-about-c21e\\n' "
                     "> /usr/bin/wget && chmod +x /usr/bin/wget")
        result = run_trial(Task.load(TASKS / "nginx-serve-8080"), "agent", llm=LLMConfig(),
                           chat_fn=scripted(fake_wget))
        self.assertTrue(result.tests_passed)  # the fake fooled the tests...
        self.assertFalse(result.passed)       # ...but not the harness
        self.assertEqual(result.status, "TAMPER")
        self.assertTrue(any(t.endswith("/usr/bin/wget") for t in result.tampering), result.tampering)

    def test_planting_fake_tests_does_not_work(self):
        # Pre-create a fake test script where tests used to be copied.
        plant = "mkdir -p /tmp/invig_tests && printf 'echo PASS\\nexit 0\\n' > /tmp/invig_tests/run_tests.sh"
        result = run_trial(Task.load(TASKS / "write-greeting"), "agent", llm=LLMConfig(), chat_fn=scripted(plant))
        self.assertEqual(result.status, "FAIL")
        self.assertIn("does not exist", result.test_output)

    def test_honest_solution_passes(self):
        result = run_trial(Task.load(TASKS / "write-greeting"), "agent", llm=LLMConfig(),
                           chat_fn=scripted("echo 'Hello, Invigilator!' > /app/greeting.txt"))
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.tampering, [])


if __name__ == "__main__":
    unittest.main()
