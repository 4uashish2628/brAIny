Running `python3 /app/report.py /app/sales.csv` crashes.

Fix `/app/report.py` so that it prints the total revenue (quantity × price) for
each region, one line per region, sorted alphabetically by region name, in this
exact format:

```
East: 9.00
North: 79.97
```

The script must work for any CSV file with the same columns, not just
`/app/sales.csv`. Do not modify `/app/sales.csv`.
