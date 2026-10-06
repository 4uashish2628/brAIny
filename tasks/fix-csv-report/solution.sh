#!/bin/sh
# Bugs: the header row is parsed as data, and prices are parsed with int().
cat > /app/report.py <<'PY'
import csv
import sys
from collections import defaultdict


def main(path):
    totals = defaultdict(float)
    with open(path) as f:
        for row in csv.DictReader(f):
            totals[row["region"]] += int(row["quantity"]) * float(row["price"])
    for region in sorted(totals):
        print(f"{region}: {totals[region]:.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
PY
