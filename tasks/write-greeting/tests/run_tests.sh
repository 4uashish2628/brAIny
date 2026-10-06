#!/bin/sh
[ -f /app/greeting.txt ] || { echo "FAIL: /app/greeting.txt does not exist"; exit 1; }
content=$(cat /app/greeting.txt)
if [ "$content" = "Hello, Invigilator!" ]; then echo "PASS"; exit 0; fi
echo "FAIL: unexpected content: $content"; exit 1
