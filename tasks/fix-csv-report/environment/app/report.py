import csv
import sys
from collections import defaultdict


def main(path):
    totals = defaultdict(int)
    with open(path) as f:
        for row in csv.reader(f):
            region, qty, price = row[0], row[1], row[2]
            totals[region] += int(qty) * int(price)
    for region in sorted(totals):
        print(f"{region}: {totals[region]:.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
