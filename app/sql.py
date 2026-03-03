# Raw SQL strings

SQL_CREATE_USER = """
INSERT INTO users (email, password_hash, role)
VALUES (%s, %s, %s)
RETURNING id, email, role;
"""

SQL_GET_USER_BY_EMAIL = """
SELECT id, email, password_hash, role, created_at
FROM users
WHERE email = %s;
"""

SQL_CREATE_CUSTOMER = """
INSERT INTO customers (full_name, email, phone, user_id)
VALUES (%s, %s, %s, %s)
RETURNING id;
"""

SQL_LINK_CUSTOMER_TO_USER = """
UPDATE customers
SET user_id = %s
WHERE email = %s AND user_id IS NULL
RETURNING id;
"""

SQL_LIST_CUSTOMERS = """
SELECT c.id, c.full_name, c.email, c.phone, c.created_at, c.user_id
FROM customers c
LEFT JOIN users u ON u.id = c.user_id
WHERE u.id IS NULL OR u.role <> 'admin'
ORDER BY c.created_at DESC;
"""

SQL_GET_CUSTOMER = """
SELECT id, full_name, email, phone, created_at, user_id
FROM customers
WHERE id = %s;
"""

SQL_GET_CUSTOMER_BY_USER_ID = """
SELECT id, full_name, email, phone, created_at, user_id
FROM customers
WHERE user_id = %s;
"""

SQL_LIST_ITEMS = """
SELECT
  i.id, i.sku, i.display_name, i.status, i.daily_rate, i.created_at,
  (t.item_id IS NOT NULL) AS is_tent,
  t.capacity, t.season_rating, t.estimated_build_time_minutes, t.construction_cost, t.deconstruction_cost,
  (f.item_id IS NOT NULL) AS is_furnishing,
  f.furnishing_kind, f.notes
FROM items i
LEFT JOIN tents t ON t.item_id = i.id
LEFT JOIN furnishings f ON f.item_id = i.id
ORDER BY i.created_at DESC;
"""

SQL_AVAILABLE_ITEMS = """
SELECT
  i.id, i.sku, i.display_name, i.daily_rate,
  (t.item_id IS NOT NULL) AS is_tent,
  t.capacity, t.season_rating, t.estimated_build_time_minutes, t.construction_cost, t.deconstruction_cost,
  (f.item_id IS NOT NULL) AS is_furnishing,
  f.furnishing_kind
FROM items i
LEFT JOIN tents t ON t.item_id = i.id
LEFT JOIN furnishings f ON f.item_id = i.id
WHERE i.status = 'active'
  AND NOT EXISTS (
    SELECT 1
    FROM booking_items bi
    JOIN bookings b ON b.id = bi.booking_id
    WHERE bi.item_id = i.id
      AND b.status <> 'cancelled'
      AND %s < b.end_date
      AND %s > b.start_date
  )
ORDER BY i.display_name;
"""

SQL_ADD_TENT_ITEM = """
SELECT add_tent_item(
  %s, %s, %s,
  %s, %s,
  %s, %s, %s,
  %s, %s
) AS new_item_id;
"""

SQL_ADD_FURNISHING_ITEM = """
SELECT add_furnishing_item(
  %s, %s, %s,
  %s, %s, %s
) AS new_item_id;
"""

SQL_ITEM_HAS_ACTIVE_OR_FUTURE_BOOKING = """
SELECT 1
FROM booking_items bi
JOIN bookings b ON b.id = bi.booking_id
WHERE bi.item_id = %s
  AND b.status <> 'cancelled'
  AND b.end_date > CURRENT_DATE
LIMIT 1;
"""

SQL_DELETE_BOOKING_ITEMS_FOR_ITEM = """
DELETE FROM booking_items WHERE item_id = %s;
"""

SQL_DELETE_ITEM = """
DELETE FROM items WHERE id = %s;
"""

SQL_CREATE_BOOKING = """
INSERT INTO bookings (customer_id, start_date, end_date, status)
VALUES (%s, %s, %s, 'pending')
RETURNING id;
"""

SQL_BOOKING_DETAIL = """
SELECT b.id, b.customer_id, c.full_name, c.email, c.phone,
       b.start_date, b.end_date, b.status, b.created_at
FROM bookings b
JOIN customers c ON c.id = b.customer_id
WHERE b.id = %s;
"""

SQL_BOOKING_DETAIL_FOR_CUSTOMER = """
SELECT b.id, b.customer_id, c.full_name, c.email, c.phone,
       b.start_date, b.end_date, b.status, b.created_at
FROM bookings b
JOIN customers c ON c.id = b.customer_id
WHERE b.id = %s AND b.customer_id = %s;
"""

SQL_BOOKING_ITEMS = """
SELECT
  i.id AS item_id, i.sku, i.display_name,
  COALESCE(bi.price_per_day, i.daily_rate) AS price_per_day,
  (t.item_id IS NOT NULL) AS is_tent,
  t.construction_cost, t.deconstruction_cost,
  (f.item_id IS NOT NULL) AS is_furnishing,
  f.furnishing_kind
FROM booking_items bi
JOIN items i ON i.id = bi.item_id
LEFT JOIN tents t ON t.item_id = i.id
LEFT JOIN furnishings f ON f.item_id = i.id
WHERE bi.booking_id = %s
ORDER BY i.display_name;
"""

SQL_BOOKING_TOTAL = """
SELECT
  b.id AS booking_id,
  (b.end_date - b.start_date) AS days,
  SUM( (b.end_date - b.start_date) * COALESCE(bi.price_per_day, i.daily_rate) ) AS rental_cost,
  SUM( COALESCE(t.construction_cost, 0) + COALESCE(t.deconstruction_cost, 0) ) AS tent_setup_cost,
  SUM( (b.end_date - b.start_date) * COALESCE(bi.price_per_day, i.daily_rate) )
  + SUM( COALESCE(t.construction_cost, 0) + COALESCE(t.deconstruction_cost, 0) ) AS total_cost
FROM bookings b
JOIN booking_items bi ON bi.booking_id = b.id
JOIN items i ON i.id = bi.item_id
LEFT JOIN tents t ON t.item_id = i.id
WHERE b.id = %s
GROUP BY b.id;
"""

SQL_LIST_BOOKINGS_FOR_CUSTOMER = """
SELECT id, start_date, end_date, status, created_at
FROM bookings
WHERE customer_id = %s
ORDER BY created_at DESC;
"""

SQL_LIST_ALL_BOOKINGS = """
SELECT b.id, b.start_date, b.end_date, b.status, b.created_at,
       c.id AS customer_id, c.full_name, c.email
FROM bookings b
JOIN customers c ON c.id = b.customer_id
ORDER BY b.created_at DESC;
"""

SQL_CONFIRM_BOOKING = "UPDATE bookings SET status='confirmed' WHERE id=%s;"
SQL_CANCEL_BOOKING = "UPDATE bookings SET status='cancelled' WHERE id=%s;"