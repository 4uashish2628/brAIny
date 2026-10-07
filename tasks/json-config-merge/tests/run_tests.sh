#!/bin/sh
# Traps: a shallow merge loses service.name / database.pool.min;
# merging lists would give tags ["core", "payments", "payments-eu"].
python3 - <<'PY'
import json, sys
expected = {
    "service": {"name": "billing", "port": 9090, "debug": False, "tags": ["payments-eu"]},
    "database": {"host": "db.internal", "port": 5432, "pool": {"min": 1, "max": 50}},
    "features": {"new_ui": True, "audit_log": True},
    "region": "eu-west-1",
}
try:
    actual = json.load(open("/app/config.json"))
except Exception as e:
    sys.exit(f"FAIL: cannot read /app/config.json: {e}")
if actual != expected:
    sys.exit(f"FAIL: wrong merge result\n--- expected\n{json.dumps(expected, indent=2)}\n--- actual\n{json.dumps(actual, indent=2)}")
print("PASS")
PY
