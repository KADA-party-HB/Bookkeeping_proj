
# Auth / Users
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

# Customers
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
SELECT id, full_name, email, phone, created_at, user_id
FROM customers
ORDER BY created_at DESC;
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

# Booking: category availability
SQL_AVAILABLE_CATEGORIES = """
WITH available_items AS (
  SELECT i.id, i.category_id
  FROM items i
  WHERE i.is_active = TRUE
    AND NOT EXISTS (
      SELECT 1
      FROM booking_items bi
      JOIN bookings b ON b.id = bi.booking_id
      WHERE bi.item_id = i.id
        AND b.status <> 'cancelled'
        AND %s < b.end_date
        AND %s > b.start_date
    )
)
SELECT
  c.id,
  c.display_name,
  c.daily_rate,

  (tc.category_id IS NOT NULL) AS is_tent,
  tc.capacity,
  tc.season_rating,
  tc.estimated_build_time_minutes,
  tc.construction_cost,
  tc.deconstruction_cost,

  (fc.category_id IS NOT NULL) AS is_furnishing,
  fc.furnishing_kind,

  COUNT(ai.id) AS available_units
FROM categories c
LEFT JOIN available_items ai ON ai.category_id = c.id
LEFT JOIN tent_categories tc ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc ON fc.category_id = c.id
GROUP BY
  c.id, c.display_name, c.daily_rate,
  tc.category_id, tc.capacity, tc.season_rating, tc.estimated_build_time_minutes, tc.construction_cost, tc.deconstruction_cost,
  fc.category_id, fc.furnishing_kind
ORDER BY (COUNT(ai.id) = 0),
         (tc.category_id IS NOT NULL) DESC,
         c.id;
"""

SQL_CREATE_BOOKING_WITH_ALLOCATIONS = """
SELECT create_booking_with_allocations(%s, %s, %s, %s, %s) AS booking_id;
"""

# Units list
SQL_LIST_UNITS = """
SELECT
  i.id,
  i.sku,
  i.is_active,
  i.created_at,

  c.id AS category_id,
  c.display_name,
  c.daily_rate,

  (tc.category_id IS NOT NULL) AS is_tent,
  tc.capacity,
  tc.season_rating,
  tc.estimated_build_time_minutes,
  tc.construction_cost,
  tc.deconstruction_cost,

  (fc.category_id IS NOT NULL) AS is_furnishing,
  fc.furnishing_kind
FROM items i
JOIN categories c ON c.id = i.category_id
LEFT JOIN tent_categories tc ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc ON fc.category_id = c.id
ORDER BY c.id, i.id;
"""

SQL_LIST_CATEGORIES_FOR_DROPDOWN = """
SELECT
  c.id,
  c.display_name,
  c.daily_rate,
  (tc.category_id IS NOT NULL) AS is_tent,
  (fc.category_id IS NOT NULL) AS is_furnishing,
  tc.capacity,
  fc.furnishing_kind
FROM categories c
LEFT JOIN tent_categories tc ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc ON fc.category_id = c.id
ORDER BY c.display_name;
"""

# Unit edit
SQL_GET_UNIT_FOR_EDIT = """
SELECT
  i.id,
  i.sku,
  i.is_active,
  i.created_at,
  i.category_id,
  c.display_name
FROM items i
JOIN categories c ON c.id = i.category_id
WHERE i.id = %s;
"""

SQL_UPDATE_UNIT = """
UPDATE items
SET category_id = %s,
    sku = %s,
    is_active = %s
WHERE id = %s;
"""

# Unit create
SQL_ADD_ITEM_UNIT = """
SELECT add_item_unit(%s, %s, %s) AS new_item_id;
"""

# Unit delete safety
SQL_ITEM_HAS_ACTIVE_OR_FUTURE_BOOKING = """
SELECT 1
FROM booking_items bi
JOIN bookings b ON b.id = bi.booking_id
WHERE bi.item_id = %s
  AND b.status <> 'cancelled'
  AND b.end_date > CURRENT_DATE
LIMIT 1;
"""
SQL_DELETE_BOOKING_ITEMS_FOR_ITEM = "DELETE FROM booking_items WHERE item_id = %s;"
SQL_DELETE_ITEM = "DELETE FROM items WHERE id = %s;"

# Categories list + edit
SQL_LIST_CATEGORIES = """
SELECT
  c.id,
  c.display_name,
  c.daily_rate,
  c.created_at,

  (tc.category_id IS NOT NULL) AS is_tent,
  tc.capacity,
  tc.season_rating,
  tc.estimated_build_time_minutes,
  tc.construction_cost,
  tc.deconstruction_cost,

  (fc.category_id IS NOT NULL) AS is_furnishing,
  fc.furnishing_kind,
  fc.weight_kg,
  fc.notes,

  COUNT(i.id) AS total_units,
  SUM(CASE WHEN i.is_active THEN 1 ELSE 0 END) AS active_units
FROM categories c
LEFT JOIN items i ON i.category_id = c.id
LEFT JOIN tent_categories tc ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc ON fc.category_id = c.id
GROUP BY
  c.id, c.display_name, c.daily_rate, c.created_at,
  tc.category_id, tc.capacity, tc.season_rating, tc.estimated_build_time_minutes, tc.construction_cost, tc.deconstruction_cost,
  fc.category_id, fc.furnishing_kind, fc.weight_kg, fc.notes
ORDER BY (tc.category_id IS NOT NULL) DESC, c.id;
"""

SQL_GET_CATEGORY_FOR_EDIT = """
SELECT
  c.id,
  c.display_name,
  c.daily_rate,
  c.created_at,

  (tc.category_id IS NOT NULL) AS is_tent,
  tc.capacity,
  tc.season_rating,
  tc.packed_weight_kg,
  tc.floor_area_m2,
  tc.estimated_build_time_minutes,
  tc.construction_cost,
  tc.deconstruction_cost,

  (fc.category_id IS NOT NULL) AS is_furnishing,
  fc.furnishing_kind,
  fc.weight_kg,
  fc.notes
FROM categories c
LEFT JOIN tent_categories tc ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc ON fc.category_id = c.id
WHERE c.id = %s;
"""

SQL_CREATE_CATEGORY = """
INSERT INTO categories (display_name, daily_rate)
VALUES (%s, %s)
RETURNING id;
"""

SQL_CREATE_TENT_CATEGORY_ROW = """
INSERT INTO tent_categories (
  category_id, capacity, season_rating, packed_weight_kg, floor_area_m2,
  estimated_build_time_minutes, construction_cost, deconstruction_cost
)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s);
"""

SQL_CREATE_FURN_CATEGORY_ROW = """
INSERT INTO furnishing_categories (category_id, furnishing_kind, weight_kg, notes)
VALUES (%s,%s,%s,%s);
"""

SQL_UPDATE_CATEGORY_BASE = """
UPDATE categories
SET display_name = %s,
    daily_rate = %s
WHERE id = %s;
"""

SQL_UPDATE_TENT_CATEGORY = """
UPDATE tent_categories
SET capacity = %s,
    season_rating = %s,
    packed_weight_kg = %s,
    floor_area_m2 = %s,
    estimated_build_time_minutes = %s,
    construction_cost = %s,
    deconstruction_cost = %s
WHERE category_id = %s;
"""

SQL_UPDATE_FURN_CATEGORY = """
UPDATE furnishing_categories
SET furnishing_kind = %s,
    weight_kg = %s,
    notes = %s
WHERE category_id = %s;
"""

# Bookings
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
  i.id AS item_id,
  i.sku,
  c.display_name,
  COALESCE(bi.price_per_day, c.daily_rate) AS price_per_day,

  (tc.category_id IS NOT NULL) AS is_tent,
  tc.construction_cost,
  tc.deconstruction_cost,

  (fc.category_id IS NOT NULL) AS is_furnishing,
  fc.furnishing_kind
FROM booking_items bi
JOIN items i ON i.id = bi.item_id
JOIN categories c ON c.id = i.category_id
LEFT JOIN tent_categories tc ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc ON fc.category_id = c.id
WHERE bi.booking_id = %s
ORDER BY c.display_name, i.sku;
"""

SQL_BOOKING_TOTAL = """
SELECT
  b.id AS booking_id,
  (b.end_date - b.start_date) AS days,
  SUM( (b.end_date - b.start_date) * COALESCE(bi.price_per_day, c.daily_rate) ) AS rental_cost,
  SUM( COALESCE(tc.construction_cost, 0) + COALESCE(tc.deconstruction_cost, 0) ) AS tent_setup_cost,
  SUM( (b.end_date - b.start_date) * COALESCE(bi.price_per_day, c.daily_rate) )
  + SUM( COALESCE(tc.construction_cost, 0) + COALESCE(tc.deconstruction_cost, 0) ) AS total_cost
FROM bookings b
JOIN booking_items bi ON bi.booking_id = b.id
JOIN items i ON i.id = bi.item_id
JOIN categories c ON c.id = i.category_id
LEFT JOIN tent_categories tc ON tc.category_id = c.id
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