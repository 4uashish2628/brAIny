"""Isolated, resource-capped Docker containers for running untrusted code.

An agent (or a buggy task) can do anything a root shell can: fork-bomb, fill
the disk, print forever, allocate all memory, or hang. Every sandbox is
hardened in layers so one bad trial can't slow down or break the host:

    what could go wrong          cap                                  enforced by
    ---------------------------  -----------------------------------  -------------------
    memory blow-up               512 MB RAM, no swap                  cgroup (kernel)
    CPU hog / infinite loop      1 CPU                                cgroup (kernel)
    fork bomb                    256 processes                        cgroup (kernel)
    one giant file               256 MB per file                      ulimit fsize
    many files / disk fill       1 GB writable layer                  watchdog thread
    hung command                 60 s per command, process tree       exec timeout
                                 killed
    endless output               1 MB captured per command            exec reader
    trial never ends             15 min wall clock                    watchdog thread
    escaping / attacking host    no network, dropped capabilities,    Docker
                                 no-new-privileges

Docker's own disk quota (--storage-opt size) is silently ignored on Docker
Desktop's overlay storage, which is why disk usage is polled by a watchdog.
"""

from __future__ import annotations

import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .task import Task

IMAGE_PREFIX = "invigilator-task"
LABEL = "invigilator"

# Capabilities root keeps inside the sandbox: enough to chown files, kill its
# own processes, and let daemons like nginx drop to an unprivileged user.
# Everything else (mount, ptrace, raw sockets, kernel modules, ...) is dropped.
KEEP_CAPS = ["CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID", "SETUID", "SETGID", "KILL", "NET_BIND_SERVICE"]

# Kill every process in process group $PG. Each `docker exec` starts its own
# process group, so this takes out a timed-out command and everything it spawned.
# Plain POSIX sh: dash's `kill` can't target a group, and awk/pkill aren't in
# every image. Uses only shell builtins (no $(...), no external commands), so
# once it starts it needs no new processes - important after a fork bomb.
KILL_GROUP = r"""
for s in /proc/[0-9]*/stat; do
  { read -r line < "$s"; } 2>/dev/null || continue
  set -- ${line##*) }
  if [ "$3" = "$PG" ]; then p=${s#/proc/}; kill -9 "${p%/stat}" 2>/dev/null; fi
done
"""


class SandboxError(Exception):
    """Raised when Docker itself fails (as opposed to a task failing)."""


@dataclass
class Limits:
    memory_mb: int = 512
    cpus: float = 1.0
    pids: int = 256
    disk_mb: int = 1024        # writable layer, checked every second
    max_file_mb: int = 256     # largest single file
    open_files: int = 1024
    command_timeout: int = 60  # each agent command
    step_timeout: int = 120    # solution.sh and the test run
    trial_timeout: int = 900   # the whole trial, wall clock
    max_output_kb: int = 1024  # output kept per command
    network: bool = False


def docker(args: list[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    """Run a docker CLI command. A timeout is reported as exit code 124 rather
    than raised, so a slow Docker daemon can't crash a run or the watchdog."""
    try:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        raise SandboxError("docker CLI not found - is Docker installed?")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["docker", *args], 124, "", f"docker {args[0]} timed out after {timeout}s")


def build_image(task: Task) -> str:
    """Build the task's environment image and return its tag. Docker caches layers."""
    tag = f"{IMAGE_PREFIX}-{task.name}"
    proc = docker(["build", "-q", "-t", tag, str(task.environment_dir)], timeout=900)
    if proc.returncode != 0:
        raise SandboxError(f"failed to build image for '{task.name}':\n{proc.stderr.strip()}")
    return tag


def safe_parallelism(requested: int, limits: Limits) -> int:
    """Cap concurrent sandboxes so their combined limits fit inside Docker's VM:
    at most 75% of its memory and one sandbox per CPU it has."""
    proc = docker(["info", "--format", "{{.MemTotal}} {{.NCPU}}"], timeout=30)
    try:
        mem_bytes, ncpu = (int(x) for x in proc.stdout.split())
    except ValueError:
        return 1
    by_memory = int(mem_bytes * 0.75 / (limits.memory_mb * 1024 * 1024))
    by_cpu = int(ncpu / limits.cpus)
    return max(1, min(requested, by_memory, by_cpu))


def remove_containers(run_id: Optional[str] = None, owner: Optional[str] = None) -> int:
    """Remove sandboxes left behind by an interrupted run, a dead worker, or everything."""
    label = f"{LABEL}.run={run_id}" if run_id else f"{LABEL}.owner={owner}" if owner else LABEL
    ids = docker(["ps", "-aq", "--filter", f"label={label}"], timeout=30).stdout.split()
    if ids:
        docker(["rm", "-f", *ids], timeout=120)
    return len(ids)


class Sandbox:
    """A throwaway, resource-capped container. Use as a context manager; the
    container is always removed on exit. The image's CMD must keep it alive.

    If a hard limit is crossed (disk or trial time), the watchdog kills the
    container and records why in `violation`.
    """

    def __init__(self, image: str, limits: Optional[Limits] = None, run_id: str = "",
                 command: Optional[list[str]] = None, owner: str = ""):
        self.image = image
        self.owner = owner  # e.g. the worker running it, so its sandboxes can be found if it dies
        self.command = command or []  # overrides the image's CMD
        self.limits = limits or Limits()
        self.run_id = run_id
        self.name = f"invig-{uuid.uuid4().hex[:10]}"
        self.violation: Optional[str] = None
        self.peak_disk_mb = 0.0
        self._baseline: set[tuple[str, str]] = set()
        self._deadline = 0.0
        self._stop = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None

    def __enter__(self) -> Sandbox:
        lim = self.limits
        args = [
            "run", "-d", "--name", self.name, "--init",
            "--label", LABEL, "--label", f"{LABEL}.run={self.run_id}", "--label", f"{LABEL}.owner={self.owner}",
            "--memory", f"{lim.memory_mb}m", "--memory-swap", f"{lim.memory_mb}m",
            "--cpus", str(lim.cpus),
            "--pids-limit", str(lim.pids),
            "--ulimit", f"nofile={lim.open_files}:{lim.open_files}",
            "--ulimit", f"fsize={lim.max_file_mb * 1024 * 1024}:{lim.max_file_mb * 1024 * 1024}",
            "--cap-drop", "ALL", *[a for cap in KEEP_CAPS for a in ("--cap-add", cap)],
            "--security-opt", "no-new-privileges",
        ]
        if not lim.network:
            args += ["--network", "none"]
        proc = docker([*args, self.image, *self.command], timeout=60)
        if proc.returncode != 0:
            raise SandboxError(f"failed to start container:\n{proc.stderr.strip()}")

        self._deadline = time.monotonic() + lim.trial_timeout
        self._watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)
        self._watchdog_thread.start()
        time.sleep(0.5)  # let the image's startup processes come up
        # Changes that exist before anyone works on the task: Docker's own init
        # binary (/sbin/docker-init), files written by the image's startup command.
        self._baseline = set(self._raw_diff())
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=5)
        docker(["rm", "-f", self.name], timeout=60)

    # -- limits -------------------------------------------------------------

    def time_left(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

    def disk_usage_mb(self) -> Optional[float]:
        proc = docker(["container", "inspect", "--size", "--format", "{{.SizeRw}}", self.name], timeout=10)
        try:
            return int(proc.stdout.strip()) / (1024 * 1024)
        except ValueError:
            return None

    def _watchdog(self) -> None:
        while not self._stop.wait(1.0):
            if self.time_left() <= 0:
                self._kill(f"trial exceeded the {self.limits.trial_timeout}s time limit")
                return
            used = self.disk_usage_mb()
            if used is not None:
                self.peak_disk_mb = max(self.peak_disk_mb, used)
                if used > self.limits.disk_mb:
                    self._kill(f"disk usage reached {used:.0f} MB (limit {self.limits.disk_mb} MB)")
                    return

    def _kill(self, reason: str) -> None:
        self.violation = reason
        docker(["kill", self.name], timeout=30)

    # -- running things -----------------------------------------------------

    def copy_in(self, src: Path, dest: str) -> None:
        proc = docker(["cp", str(src), f"{self.name}:{dest}"], timeout=60)
        if proc.returncode != 0:
            raise SandboxError(f"failed to copy {src} into sandbox:\n{proc.stderr.strip()}")

    def exec(self, command: list[str], timeout: float) -> tuple[int, str]:
        """Run a command. Returns (exit_code, output with stdout and stderr interleaved).

        On timeout or runaway output, the command's whole process tree is killed.
        Background processes from commands that finish normally are left running,
        since starting servers is often part of a task.
        """
        if self.violation:
            return 137, f"[invigilator] sandbox stopped: {self.violation}"

        marker = f"/tmp/.invig_pg_{uuid.uuid4().hex[:8]}"
        wrapped = ["sh", "-c", f'echo $$ > {marker}; exec "$@"', "sh", *command]
        proc = subprocess.Popen(
            ["docker", "exec", self.name, *wrapped],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        limit = self.limits.max_output_kb * 1024
        buf = bytearray()
        overflow = threading.Event()

        def read_output() -> None:
            # Past the cap, keep draining and discarding so Docker isn't left
            # blocked on a full pipe while the command is being killed.
            while True:
                chunk = proc.stdout.read1(65536)
                if not chunk:
                    return
                room = limit - len(buf)
                if room > 0:
                    buf.extend(chunk[:room])
                if len(chunk) > room:
                    overflow.set()

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()

        deadline = time.monotonic() + timeout
        stopped_because = None
        while proc.poll() is None:
            if overflow.is_set():
                stopped_because = f"output exceeded {self.limits.max_output_kb} KB"
            elif time.monotonic() > deadline:
                stopped_because = f"command timed out after {timeout:.0f}s"
            elif self.violation:
                stopped_because = f"sandbox stopped: {self.violation}"
            if stopped_because:
                self._kill_group(marker)
                proc.kill()
                proc.wait()
                break
            time.sleep(0.05)
        reader.join(timeout=2)
        proc.stdout.close()

        output = buf.decode("utf-8", errors="replace")
        if proc.returncode != 0 and "OCI runtime exec failed" in output and not stopped_because:
            # Docker couldn't start the command at all: typically every process
            # slot is taken (fork bomb). Nothing can run in here any more.
            self._kill("sandbox can't start new processes (process limit reached)")
        if stopped_because:
            code = 124 if "timed out" in stopped_because else 137
            return code, f"{output}\n[invigilator] {stopped_because}; the command was killed"
        return proc.returncode, output

    def _kill_group(self, marker: str) -> None:
        if self.violation:
            return  # container is already dead
        script = f'{{ read -r PG < {marker}; }} 2>/dev/null; [ -n "$PG" ] && {{ {KILL_GROUP} }}; true'
        proc = docker(["exec", self.name, "sh", "-c", script], timeout=15)
        if proc.returncode != 0:
            # The kill script couldn't even start (e.g. a fork bomb filled every
            # process slot), so the sandbox can't be recovered: end it.
            self._kill("sandbox can't start new processes (process limit reached)")

    def diff(self) -> list[tuple[str, str]]:
        """Files changed since the sandbox started, as (kind, path) with kind
        A(dded), C(hanged) or D(eleted). Comes from `docker diff`, which compares
        against the image from outside, so nothing inside the container can hide
        from it."""
        return [c for c in self._raw_diff() if c not in self._baseline]

    def _raw_diff(self) -> list[tuple[str, str]]:
        proc = docker(["diff", self.name], timeout=60)
        changes = []
        for line in proc.stdout.splitlines():
            kind, _, path = line.partition(" ")
            if kind in ("A", "C", "D") and path:
                changes.append((kind, path))
        return changes
