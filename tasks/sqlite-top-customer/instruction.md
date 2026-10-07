`/app/shop.db` is a SQLite database of customers and their orders.

Which customer spent the most money in calendar year 2025? Only count orders
whose status is `paid`. An order's value is the sum of `price_cents × quantity`
over its items.

Write just that customer's name to `/app/answer.txt`.
