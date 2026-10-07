#!/bin/sh
# Trap: killing only collector.py doesn't work, because run-collector.sh restarts it.
sleep 3
python3 - <<'PY'
import os, sys

def running(needle):
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
        except OSError:
            continue
        if needle in cmd and "run_tests" not in cmd:
            return True
    return False

if running("collector.py"):
    sys.exit("FAIL: the collector is still running (or was restarted)")
if os.path.exists("/var/log/app/collector.log"):
    sys.exit(f"FAIL: /var/log/app/collector.log still exists ({os.path.getsize('/var/log/app/collector.log')} bytes)")
if open("/var/log/app/audit.log").read() != "2026-09-01 login admin\n2026-09-02 export report\n":
    sys.exit("FAIL: audit.log was modified")
if not running("heartbeat.py"):
    sys.exit("FAIL: the heartbeat service is not running")
print("PASS")
PY
