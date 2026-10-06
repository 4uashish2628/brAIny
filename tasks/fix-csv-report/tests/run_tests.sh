#!/bin/sh
# Uses a CSV the agent has never seen, so a hardcoded answer can't pass.
cat > /tmp/hidden.csv <<'CSV'
region,quantity,price
West,2,1.25
Central,10,0.10
West,1,3.00
CSV

check() {
    file="$1"; expected="$2"
    actual=$(python3 /app/report.py "$file" 2>&1)
    if [ $? -ne 0 ]; then
        echo "FAIL: report.py crashed on $file"; echo "$actual"; exit 1
    fi
    if [ "$actual" != "$expected" ]; then
        echo "FAIL: wrong output for $file"
        echo "--- expected"; echo "$expected"
        echo "--- actual";   echo "$actual"
        exit 1
    fi
}

check /app/sales.csv "East: 9.00
North: 79.97
South: 5.50"

check /tmp/hidden.csv "Central: 1.00
West: 5.50"

echo "PASS"
