#!/bin/sh
[ -f /app/answer.txt ] || { echo "FAIL: /app/answer.txt does not exist"; exit 1; }
answer=$(tr -d ' \n' < /app/answer.txt)
if [ "$answer" = "37" ]; then echo "PASS"; exit 0; fi
echo "FAIL: expected 37, got '$answer'"; exit 1
