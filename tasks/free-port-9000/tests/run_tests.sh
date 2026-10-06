#!/bin/sh
body=$(python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9000/', timeout=3).read().decode())" 2>&1)
case "$body" in
    *"app ok"*) echo "PASS"; exit 0 ;;
    *) echo "FAIL: port 9000 is not served by /app/server.py"; echo "$body"; exit 1 ;;
esac
