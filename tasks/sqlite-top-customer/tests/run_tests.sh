#!/bin/sh
# Meera 9800, Asha 9500, Ravi 9000, Kabir 1000. Each mistake picks someone else:
# counting refunds or 2024 -> Ravi; ignoring status or counting 2026 -> Kabir;
# ignoring quantity -> Ravi.
[ -f /app/answer.txt ] || { echo "FAIL: /app/answer.txt does not exist"; exit 1; }
answer=$(tr -d '\r' < /app/answer.txt | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
if [ "$answer" = "Meera" ]; then echo "PASS"; exit 0; fi
echo "FAIL: expected Meera, got '$answer'"; exit 1
