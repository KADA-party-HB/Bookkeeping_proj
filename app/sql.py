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
INSERT INTO customers (full_name, email, phone, address, user_id)
VALUES (%s, %s, %s, %s, %s)
RETURNING id;
"""

SQL_LINK_CUSTOMER_TO_USER = """
UPDATE customers
SET user_id = %s
WHERE email = %s AND user_id IS NULL
RETURNING id;
"""

SQL_LIST_CUSTOMERS = """
SELECT id, full_name, email, phone, address, created_at, user_id
FROM customers
ORDER BY created_at DESC;
"""

SQL_GET_CUSTOMER = """
SELECT id, full_name, email, phone, address, user_id, created_at
FROM customers
WHERE id = %s;
"""

SQL_GET_CUSTOMER_BY_USER_ID = """
SELECT id, full_name, email, phone, address, created_at, user_id
FROM customers
WHERE user_id = %s;
"""

# Rental periods
SQL_LIST_RENTAL_PERIODS = """
SELECT id, label, min_days, max_days, created_at
FROM rental_periods
ORDER BY min_days, max_days, label;
"""

SQL_GET_RENTAL_PERIOD = """
SELECT id, label, min_days, max_days, created_at
FROM rental_periods
WHERE id = %s;
"""

SQL_CREATE_RENTAL_PERIOD = """
INSERT INTO rental_periods (label, min_days, max_days)
VALUES (%s, %s, %s)
RETURNING id;
"""

SQL_UPDATE_RENTAL_PERIOD = """
UPDATE rental_periods
SET label = %s,
    min_days = %s,
    max_days = %s
WHERE id = %s;
"""

SQL_DELETE_RENTAL_PERIOD = """
DELETE FROM rental_periods
WHERE id = %s;
"""

SQL_RENTAL_PERIOD_IN_USE = """
SELECT 1
FROM category_rental_period_prices
WHERE rental_period_id = %s
LIMIT 1;
"""

SQL_RENTAL_PERIOD_USAGE_COUNT = """
SELECT COUNT(*) AS usage_count
FROM category_rental_period_prices
WHERE rental_period_id = %s;
"""

# Booking: category availability + matching rental price for requested date range
SQL_AVAILABLE_CATEGORIES = """
WITH rental_input AS (
  SELECT (%s::date - %s::date + 1) AS rental_days
),
available_items AS (
  SELECT i.id, i.category_id
  FROM items i
  WHERE i.is_active = TRUE
    AND NOT EXISTS (
      SELECT 1
      FROM booking_items bi
      JOIN bookings b ON b.id = bi.booking_id
      WHERE bi.item_id = i.id
        AND b.status <> 'cancelled'
        AND %s <= b.end_date
        AND %s >= b.start_date
    )
),
matching_period AS (
  SELECT
    crpp.category_id,
    rp.id AS rental_period_id,
    rp.label AS rental_period_label,
    rp.min_days,
    rp.max_days,
    crpp.price,
    crpp.sort_order,
    ROW_NUMBER() OVER (
      PARTITION BY crpp.category_id
      ORDER BY crpp.sort_order, rp.min_days, rp.max_days, rp.id
    ) AS rn
  FROM category_rental_period_prices crpp
  JOIN rental_periods rp ON rp.id = crpp.rental_period_id
  CROSS JOIN rental_input ri
  WHERE ri.rental_days BETWEEN rp.min_days AND rp.max_days
)
SELECT
  c.id,
  c.display_name,

  mp.rental_period_id,
  mp.rental_period_label,
  mp.min_days AS rental_period_min_days,
  mp.max_days AS rental_period_max_days,
  mp.price AS quoted_period_price,
  (mp.rental_period_id IS NOT NULL) AS has_standard_price,

  (tc.category_id IS NOT NULL) AS is_tent,
  tc.capacity,
  tc.season_rating,
  tc.estimated_build_time_minutes,
  tc.setup_service_fee,
  tc.packed_weight_kg,
  tc.floor_area_m2,

  (fc.category_id IS NOT NULL) AS is_furnishing,
  fc.furnishing_kind,
  fc.weight_kg,
  fc.notes,

  COUNT(ai.id) AS available_items
FROM categories c
LEFT JOIN available_items ai
  ON ai.category_id = c.id
LEFT JOIN tent_categories tc
  ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc
  ON fc.category_id = c.id
LEFT JOIN matching_period mp
  ON mp.category_id = c.id
 AND mp.rn = 1
GROUP BY
  c.id, c.display_name,
  mp.rental_period_id, mp.rental_period_label, mp.min_days, mp.max_days, mp.price,
  tc.category_id, tc.capacity, tc.season_rating, tc.estimated_build_time_minutes,
  tc.setup_service_fee, tc.packed_weight_kg, tc.floor_area_m2,
  fc.category_id, fc.furnishing_kind, fc.weight_kg, fc.notes
ORDER BY
  (COUNT(ai.id) = 0),
  (mp.rental_period_id IS NULL),
  (tc.category_id IS NOT NULL) DESC,
  c.display_name;
"""

SQL_CREATE_BOOKING_WITH_ALLOCATIONS = """
SELECT create_booking_with_allocations(
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
) AS booking_id;
"""

# Items list
SQL_LIST_ITEMS = """
SELECT
  i.id,
  i.sku,
  i.is_active,
  i.created_at,

  c.id AS category_id,
  c.display_name,

  (tc.category_id IS NOT NULL) AS is_tent,
  tc.capacity,
  tc.season_rating,
  tc.estimated_build_time_minutes,
  tc.setup_service_fee,
  tc.packed_weight_kg,
  tc.floor_area_m2,

  (fc.category_id IS NOT NULL) AS is_furnishing,
  fc.furnishing_kind,
  fc.weight_kg,
  fc.notes
FROM items i
JOIN categories c ON c.id = i.category_id
LEFT JOIN tent_categories tc ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc ON fc.category_id = c.id
ORDER BY c.display_name, i.id;
"""

SQL_LIST_CATEGORIES_FOR_DROPDOWN = """
SELECT
  c.id,
  c.display_name,
  (tc.category_id IS NOT NULL) AS is_tent,
  (fc.category_id IS NOT NULL) AS is_furnishing,
  tc.capacity,
  fc.furnishing_kind
FROM categories c
LEFT JOIN tent_categories tc ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc ON fc.category_id = c.id
ORDER BY c.display_name;
"""

# Item edit
SQL_GET_ITEM_FOR_EDIT = """
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

SQL_UPDATE_ITEM = """
UPDATE items
SET category_id = %s,
    sku = %s,
    is_active = %s
WHERE id = %s;
"""

# Item create
SQL_ADD_ITEM_UNIT = """
SELECT add_item_unit(%s, %s, %s) AS new_item_id;
"""

# Item delete safety
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
DELETE FROM booking_items
WHERE item_id = %s;
"""

SQL_DELETE_ITEM = """
DELETE FROM items
WHERE id = %s;
"""

# Categories list + edit
SQL_LIST_CATEGORIES = """
SELECT
  c.id,
  c.display_name,
  c.created_at,

  (tc.category_id IS NOT NULL) AS is_tent,
  tc.capacity,
  tc.season_rating,
  tc.packed_weight_kg,
  tc.floor_area_m2,
  tc.estimated_build_time_minutes,
  tc.setup_service_fee,

  (fc.category_id IS NOT NULL) AS is_furnishing,
  fc.furnishing_kind,
  fc.weight_kg,
  fc.notes,

  COUNT(i.id) AS total_items,
  COALESCE(SUM(CASE WHEN i.is_active THEN 1 ELSE 0 END), 0) AS active_items
FROM categories c
LEFT JOIN items i ON i.category_id = c.id
LEFT JOIN tent_categories tc ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc ON fc.category_id = c.id
GROUP BY
  c.id, c.display_name, c.created_at,
  tc.category_id, tc.capacity, tc.season_rating, tc.packed_weight_kg,
  tc.floor_area_m2, tc.estimated_build_time_minutes, tc.setup_service_fee,
  fc.category_id, fc.furnishing_kind, fc.weight_kg, fc.notes
ORDER BY (tc.category_id IS NOT NULL) DESC, c.display_name;
"""

SQL_GET_CATEGORY_FOR_EDIT = """
SELECT
  c.id,
  c.display_name,
  c.created_at,

  (tc.category_id IS NOT NULL) AS is_tent,
  tc.capacity,
  tc.season_rating,
  tc.packed_weight_kg,
  tc.floor_area_m2,
  tc.estimated_build_time_minutes,
  tc.setup_service_fee,

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
INSERT INTO categories (display_name)
VALUES (%s)
RETURNING id;
"""

SQL_CREATE_TENT_CATEGORY_ROW = """
INSERT INTO tent_categories (
  category_id,
  capacity,
  season_rating,
  packed_weight_kg,
  floor_area_m2,
  estimated_build_time_minutes,
  setup_service_fee
)
VALUES (%s, %s, %s, %s, %s, %s, %s);
"""

SQL_CREATE_FURN_CATEGORY_ROW = """
INSERT INTO furnishing_categories (
  category_id,
  furnishing_kind,
  weight_kg,
  notes
)
VALUES (%s, %s, %s, %s);
"""

SQL_UPDATE_CATEGORY_BASE = """
UPDATE categories
SET display_name = %s
WHERE id = %s;
"""

SQL_UPDATE_TENT_CATEGORY = """
UPDATE tent_categories
SET capacity = %s,
    season_rating = %s,
    packed_weight_kg = %s,
    floor_area_m2 = %s,
    estimated_build_time_minutes = %s,
    setup_service_fee = %s
WHERE category_id = %s;
"""

SQL_UPDATE_FURN_CATEGORY = """
UPDATE furnishing_categories
SET furnishing_kind = %s,
    weight_kg = %s,
    notes = %s
WHERE category_id = %s;
"""

# Category rental period pricing
SQL_LIST_CATEGORY_RENTAL_PERIOD_PRICES = """
SELECT
  crpp.category_id,
  rp.id AS rental_period_id,
  rp.label,
  rp.min_days,
  rp.max_days,
  crpp.price,
  crpp.sort_order,
  crpp.created_at
FROM category_rental_period_prices crpp
JOIN rental_periods rp ON rp.id = crpp.rental_period_id
WHERE crpp.category_id = %s
ORDER BY crpp.sort_order, rp.min_days, rp.max_days, rp.label;
"""

SQL_GET_CATEGORY_RENTAL_PERIOD_PRICE = """
SELECT
  crpp.category_id,
  crpp.rental_period_id,
  crpp.price,
  crpp.sort_order,
  rp.label,
  rp.min_days,
  rp.max_days
FROM category_rental_period_prices crpp
JOIN rental_periods rp ON rp.id = crpp.rental_period_id
WHERE crpp.category_id = %s
  AND crpp.rental_period_id = %s;
"""

SQL_CREATE_CATEGORY_RENTAL_PERIOD_PRICE = """
INSERT INTO category_rental_period_prices (
  category_id,
  rental_period_id,
  price,
  sort_order
)
VALUES (%s, %s, %s, %s);
"""

SQL_UPSERT_CATEGORY_RENTAL_PERIOD_PRICE = """
INSERT INTO category_rental_period_prices (
  category_id,
  rental_period_id,
  price,
  sort_order
)
VALUES (%s, %s, %s, %s)
ON CONFLICT (category_id, rental_period_id)
DO UPDATE SET
  price = EXCLUDED.price,
  sort_order = EXCLUDED.sort_order;
"""

SQL_UPDATE_CATEGORY_RENTAL_PERIOD_PRICE = """
UPDATE category_rental_period_prices
SET price = %s,
    sort_order = %s
WHERE category_id = %s
  AND rental_period_id = %s;
"""

SQL_DELETE_CATEGORY_RENTAL_PERIOD_PRICE = """
DELETE FROM category_rental_period_prices
WHERE category_id = %s
  AND rental_period_id = %s;
"""

# Bookings
SQL_CREATE_BOOKING = """
INSERT INTO bookings (
  customer_id,
  start_date,
  end_date,
  status,
  include_delivery,
  delivery_fee,
  include_setup_service,
  custom_total_price,
  custom_price_note,
  booking_note,
  admin_note
)
VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s)
RETURNING id;
"""

SQL_BOOKING_DETAIL = """
SELECT
  b.id,
  b.customer_id,
  c.full_name,
  c.email,
  c.phone,
  b.start_date,
  b.end_date,
  b.status,
  b.include_delivery,
  b.delivery_fee,
  b.include_setup_service,
  b.custom_total_price,
  b.custom_price_note,
  b.booking_note,
  b.admin_note,
  b.created_at
FROM bookings b
JOIN customers c ON c.id = b.customer_id
WHERE b.id = %s;
"""

SQL_BOOKING_DETAIL_FOR_CUSTOMER = """
SELECT
  b.id,
  b.customer_id,
  c.full_name,
  c.email,
  c.phone,
  b.start_date,
  b.end_date,
  b.status,
  b.include_delivery,
  b.delivery_fee,
  b.include_setup_service,
  b.custom_total_price,
  b.custom_price_note,
  b.booking_note,
  b.admin_note,
  b.created_at
FROM bookings b
JOIN customers c ON c.id = b.customer_id
WHERE b.id = %s
  AND b.customer_id = %s;
"""

SQL_BOOKING_ITEMS = """
SELECT
  i.id AS item_id,
  i.sku,
  c.id AS category_id,
  c.display_name,

  bi.rental_period_id,
  bi.quoted_period_label,
  bi.quoted_period_price,
  bi.setup_service_fee,
  bi.custom_total_price,
  bi.custom_price_note,
  bi.line_note,

  COALESCE(bi.custom_total_price, bi.quoted_period_price) AS effective_rental_price,

  CASE
    WHEN b.include_setup_service THEN COALESCE(bi.setup_service_fee, 0)
    ELSE 0
  END AS effective_setup_fee,

  COALESCE(bi.custom_total_price, bi.quoted_period_price)
  + CASE
      WHEN b.include_setup_service THEN COALESCE(bi.setup_service_fee, 0)
      ELSE 0
    END AS effective_line_total,

  (tc.category_id IS NOT NULL) AS is_tent,
  tc.capacity,
  tc.season_rating,
  tc.setup_service_fee AS current_setup_service_fee,

  (fc.category_id IS NOT NULL) AS is_furnishing,
  fc.furnishing_kind
FROM booking_items bi
JOIN bookings b ON b.id = bi.booking_id
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
  (b.end_date - b.start_date + 1) AS days,
  (b.custom_total_price IS NOT NULL) AS has_booking_override,
  b.custom_total_price AS booking_custom_total_price,
  b.custom_price_note AS booking_custom_price_note,

  COALESCE(SUM(COALESCE(bi.custom_total_price, bi.quoted_period_price)), 0) AS rental_cost,

  COALESCE(
    CASE
      WHEN b.include_setup_service
      THEN SUM(COALESCE(bi.setup_service_fee, 0))
      ELSE 0
    END,
    0
  ) AS setup_cost,

  COALESCE(
    CASE
      WHEN b.include_delivery
      THEN COALESCE(b.delivery_fee, 0)
      ELSE 0
    END,
    0
  ) AS delivery_cost,

  CASE
    WHEN b.custom_total_price IS NOT NULL THEN b.custom_total_price
    ELSE
      COALESCE(SUM(COALESCE(bi.custom_total_price, bi.quoted_period_price)), 0)
      + COALESCE(
          CASE
            WHEN b.include_setup_service
            THEN SUM(COALESCE(bi.setup_service_fee, 0))
            ELSE 0
          END,
          0
        )
      + COALESCE(
          CASE
            WHEN b.include_delivery
            THEN COALESCE(b.delivery_fee, 0)
            ELSE 0
          END,
          0
        )
  END AS total_cost
FROM bookings b
JOIN booking_items bi ON bi.booking_id = b.id
WHERE b.id = %s
GROUP BY
  b.id,
  b.start_date,
  b.end_date,
  b.include_setup_service,
  b.include_delivery,
  b.delivery_fee,
  b.custom_total_price,
  b.custom_price_note;
"""

SQL_LIST_BOOKINGS_FOR_CUSTOMER = """
SELECT
  id,
  start_date,
  end_date,
  status,
  include_delivery,
  delivery_fee,
  include_setup_service,
  custom_total_price,
  custom_price_note,
  booking_note,
  admin_note,
  created_at
FROM bookings
WHERE customer_id = %s
ORDER BY created_at DESC;
"""

SQL_LIST_ALL_BOOKINGS = """
SELECT
  b.id,
  b.start_date,
  b.end_date,
  b.status,
  EXISTS (
    SELECT 1
    FROM booking_items bi2
    JOIN items i2 ON i2.id = bi2.item_id
    JOIN tent_categories tc2 ON tc2.category_id = i2.category_id
    WHERE bi2.booking_id = b.id
  ) AS has_tent,
  CASE
    WHEN (
      SELECT COUNT(DISTINCT c2.id)
      FROM booking_items bi3
      JOIN items i3 ON i3.id = bi3.item_id
      JOIN categories c2 ON c2.id = i3.category_id
      JOIN tent_categories tc3 ON tc3.category_id = c2.id
      WHERE bi3.booking_id = b.id
    ) = 1 THEN (
      SELECT MIN(c3.display_name)
      FROM booking_items bi4
      JOIN items i4 ON i4.id = bi4.item_id
      JOIN categories c3 ON c3.id = i4.category_id
      JOIN tent_categories tc4 ON tc4.category_id = c3.id
      WHERE bi4.booking_id = b.id
    )
    WHEN (
      SELECT COUNT(DISTINCT c4.id)
      FROM booking_items bi5
      JOIN items i5 ON i5.id = bi5.item_id
      JOIN categories c4 ON c4.id = i5.category_id
      JOIN tent_categories tc5 ON tc5.category_id = c4.id
      WHERE bi5.booking_id = b.id
    ) >= 2 THEN '2+'
    ELSE NULL
  END AS tent_summary,
  CASE
    WHEN b.custom_total_price IS NOT NULL THEN b.custom_total_price
    ELSE
      COALESCE((
        SELECT SUM(COALESCE(bi6.custom_total_price, bi6.quoted_period_price))
        FROM booking_items bi6
        WHERE bi6.booking_id = b.id
      ), 0)
      + CASE
          WHEN b.include_setup_service THEN COALESCE((
            SELECT SUM(COALESCE(bi7.setup_service_fee, 0))
            FROM booking_items bi7
            WHERE bi7.booking_id = b.id
          ), 0)
          ELSE 0
        END
      + CASE
          WHEN b.include_delivery THEN COALESCE(b.delivery_fee, 0)
          ELSE 0
        END
  END AS total_cost,
  b.include_delivery,
  b.delivery_fee,
  b.include_setup_service,
  b.custom_total_price,
  b.custom_price_note,
  b.booking_note,
  b.admin_note,
  b.created_at,
  c.id AS customer_id,
  c.full_name,
  c.email
FROM bookings b
JOIN customers c ON c.id = b.customer_id
ORDER BY b.created_at DESC;
"""

SQL_CONFIRM_BOOKING = """
UPDATE bookings
SET status = 'confirmed'
WHERE id = %s;
"""

SQL_CANCEL_BOOKING = """
UPDATE bookings
SET status = 'cancelled'
WHERE id = %s;
"""

SQL_BOOKING_ITEM_DATE_CONFLICT = """
SELECT
  i.id AS item_id,
  i.sku,
  c.display_name,
  b2.id AS conflicting_booking_id,
  b2.start_date,
  b2.end_date
FROM booking_items current_bi
JOIN items i ON i.id = current_bi.item_id
JOIN categories c ON c.id = i.category_id
JOIN booking_items other_bi ON other_bi.item_id = current_bi.item_id
JOIN bookings b2 ON b2.id = other_bi.booking_id
WHERE current_bi.booking_id = %s
  AND other_bi.booking_id <> %s
  AND b2.status <> 'cancelled'
  AND %s <= b2.end_date
  AND %s >= b2.start_date
LIMIT 1;
"""

# Optional booking item edits / overrides
SQL_UPDATE_BOOKING_ITEM_OVERRIDE = """
UPDATE booking_items
SET custom_total_price = %s,
    custom_price_note = %s,
    line_note = %s
WHERE booking_id = %s
  AND item_id = %s;
"""

SQL_CLEAR_BOOKING_ITEM_OVERRIDE = """
UPDATE booking_items
SET custom_total_price = NULL,
    custom_price_note = NULL
WHERE booking_id = %s
  AND item_id = %s;
"""

SQL_UPDATE_BOOKING_ADMIN_FIELDS = """
UPDATE bookings
SET customer_id = %s,
    start_date = %s,
    end_date = %s,
    status = %s,
    include_delivery = %s,
    delivery_fee = %s,
    include_setup_service = %s,
    custom_total_price = %s,
    custom_price_note = %s,
    booking_note = %s,
    admin_note = %s
WHERE id = %s;
"""

SQL_GET_CUSTOMER_FOR_EDIT = """
SELECT id, full_name, email, phone, address, user_id, created_at
FROM customers
WHERE id = %s;
"""

SQL_UPDATE_CUSTOMER = """
UPDATE customers
SET
    full_name = %s,
    email = %s,
    phone = %s,
    address = %s
WHERE id = %s
RETURNING id;
"""
