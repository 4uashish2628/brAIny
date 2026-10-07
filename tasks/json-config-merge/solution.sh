#!/bin/sh
python3 - <<'PY'
import json

def merge(base, override):
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out

base = json.load(open("/app/base.json"))
override = json.load(open("/app/override.json"))
json.dump(merge(base, override), open("/app/config.json", "w"), indent=2)
PY
