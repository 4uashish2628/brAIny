#!/bin/sh
python3 - <<'PY'
import sqlite3
row = sqlite3.connect("/app/shop.db").execute("""
    SELECT c.name, SUM(i.price_cents * i.quantity) AS total
    FROM customers c
    JOIN orders o ON o.customer_id = c.id
    JOIN order_items i ON i.order_id = o.id
    WHERE o.status = 'paid' AND o.placed_at >= '2025-01-01' AND o.placed_at < '2026-01-01'
    GROUP BY c.id ORDER BY total DESC LIMIT 1
""").fetchone()
open("/app/answer.txt", "w").write(row[0] + "\n")
PY
