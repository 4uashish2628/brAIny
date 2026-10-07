import sqlite3

db = sqlite3.connect("/app/shop.db")
db.executescript("""
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
                     placed_at TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE order_items (order_id INTEGER NOT NULL REFERENCES orders(id), sku TEXT NOT NULL,
                          price_cents INTEGER NOT NULL, quantity INTEGER NOT NULL);
""")
db.executemany("INSERT INTO customers VALUES (?, ?)", [(1, "Asha"), (2, "Ravi"), (3, "Meera"), (4, "Kabir")])
db.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", [
    (1, 1, "2025-03-02 10:15:00", "paid"),
    (2, 1, "2025-07-19 18:40:00", "paid"),
    (3, 2, "2025-01-15 09:00:00", "paid"),
    (4, 2, "2025-11-30 12:00:00", "refunded"),
    (5, 2, "2024-12-31 23:59:00", "paid"),
    (6, 3, "2025-05-05 14:20:00", "paid"),
    (7, 3, "2025-06-06 08:05:00", "paid"),
    (8, 3, "2025-08-08 16:45:00", "paid"),
    (9, 4, "2025-02-02 11:11:00", "cancelled"),
    (10, 4, "2025-12-31 22:00:00", "paid"),
    (11, 4, "2026-01-01 00:30:00", "paid"),
])
db.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?)", [
    (1, "MUG", 1500, 2), (1, "LAMP", 4000, 1),
    (2, "BOOK", 2500, 1),
    (3, "CHAIR", 9000, 1),
    (4, "DESK", 20000, 1),
    (5, "SOFA", 30000, 1),
    (6, "CUP", 1200, 3),
    (7, "MUG", 1500, 2),
    (8, "RUG", 3200, 1),
    (9, "TV", 50000, 1),
    (10, "PEN", 1000, 1),
    (11, "BIKE", 40000, 1),
])
db.commit()
