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
SQL_GET_CUSTOMER_BY_EMAIL = """
SELECT id, full_name, email, phone, address, postal_city, user_id, created_at
FROM customers
WHERE lower(email) = lower(%s)
LIMIT 1;
"""

SQL_CREATE_CUSTOMER = """
INSERT INTO customers (full_name, email, phone, address, postal_city, user_id)
VALUES (%s, %s, %s, %s, %s, %s)
RETURNING id;
"""

SQL_LIST_CUSTOMERS = """
SELECT id, full_name, email, phone, address, postal_city, created_at, user_id
FROM customers
ORDER BY created_at DESC;
"""

SQL_GET_CUSTOMER = """
SELECT id, full_name, email, phone, address, postal_city, user_id, created_at
FROM customers
WHERE id = %s;
"""

SQL_GET_CUSTOMER_BY_FULL_NAME = """
SELECT id, full_name, email, phone, address, postal_city, user_id, created_at
FROM customers
WHERE lower(full_name) = lower(%s)
ORDER BY id
LIMIT 1;
"""

SQL_GET_CUSTOMER_BY_USER_ID = """
SELECT id, full_name, email, phone, address, postal_city, created_at, user_id
FROM customers
WHERE user_id = %s;
"""

SQL_EXPIRE_STALE_PENDING_BOOKINGS = """
UPDATE bookings
SET status = 'cancelled'
WHERE status = 'pending'
  AND created_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day');
"""

SQL_ACTIVE_PENDING_BOOKING_COUNT = """
SELECT COUNT(*) AS pending_count
FROM bookings
WHERE customer_id = %s
  AND status = 'pending'
  AND created_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day');
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
WITH request_window AS (
  SELECT
    base.requested_start,
    base.requested_end,
    (base.requested_end - base.requested_start + 1) AS rental_days
  FROM (
    SELECT
      %s::date AS requested_start,
      %s::date AS requested_end
  ) base
),
item_overlap AS (
  SELECT
    i.id,
    i.category_id,
    COUNT(b.id) AS overlap_count,
    COUNT(*) FILTER (
      WHERE b.id IS NOT NULL
        AND b.end_date <> rw.requested_start
    ) AS blocking_overlap_count
  FROM items i
  CROSS JOIN request_window rw
  LEFT JOIN booking_items bi
    ON bi.item_id = i.id
  LEFT JOIN bookings b
    ON b.id = bi.booking_id
   AND b.status <> 'cancelled'
   AND rw.requested_start <= b.end_date
   AND rw.requested_end >= b.start_date
  WHERE i.is_active = TRUE
  GROUP BY i.id, i.category_id
),
availability AS (
  SELECT
    category_id,
    COUNT(*) FILTER (WHERE overlap_count = 0) AS available_items,
    COUNT(*) FILTER (
      WHERE overlap_count > 0
        AND blocking_overlap_count = 0
    ) AS same_day_turnaround_items
  FROM item_overlap
  GROUP BY category_id
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
  CROSS JOIN request_window rw
  WHERE rw.rental_days BETWEEN rp.min_days AND rp.max_days
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

  COALESCE(a.available_items, 0) AS available_items,
  COALESCE(a.same_day_turnaround_items, 0) AS same_day_turnaround_items,
  COALESCE(a.available_items, 0) + COALESCE(a.same_day_turnaround_items, 0) AS admin_available_items
FROM categories c
LEFT JOIN availability a ON a.category_id = c.id
LEFT JOIN tent_categories tc ON tc.category_id = c.id
LEFT JOIN furnishing_categories fc ON fc.category_id = c.id
LEFT JOIN matching_period mp
  ON mp.category_id = c.id
 AND mp.rn = 1
ORDER BY
  (COALESCE(a.available_items, 0) = 0),
  (mp.rental_period_id IS NULL),
  (tc.category_id IS NOT NULL) DESC,
  c.display_name;
"""

SQL_FIND_CATEGORY_RENTAL_PRICING = """
SELECT
  rp.id AS rental_period_id,
  rp.label AS period_label,
  crpp.price AS period_price
FROM category_rental_period_prices crpp
JOIN rental_periods rp ON rp.id = crpp.rental_period_id
WHERE crpp.category_id = %s
  AND %s BETWEEN rp.min_days AND rp.max_days
ORDER BY crpp.sort_order, rp.min_days, rp.max_days, rp.id
LIMIT 1;
"""

SQL_CREATE_BOOKING_WITH_ALLOCATIONS = """
SELECT create_booking_with_allocations(
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
SQL_CREATE_ITEM = """
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
  delivery_address,
  delivery_distance_km,
  include_setup_service,
  custom_total_price,
  custom_price_note,
  booking_note,
  admin_note
)
VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id;
"""

SQL_BOOKING_DETAIL = """
SELECT
  b.id,
  b.customer_id,
  c.full_name,
  c.email,
  c.phone,
  c.address,
  c.postal_city,
  b.start_date,
  b.end_date,
  b.status,
  b.include_delivery,
  b.delivery_fee,
  b.delivery_address,
  b.delivery_distance_km,
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
  c.address,
  c.postal_city,
  b.start_date,
  b.end_date,
  b.status,
  b.include_delivery,
  b.delivery_fee,
  b.delivery_address,
  b.delivery_distance_km,
  b.include_setup_service,
  b.custom_total_price,
  b.custom_price_note,
  b.booking_note,
  NULL::TEXT AS admin_note,
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

SQL_BOOKING_ITEMS_FOR_BOOKINGS = """
SELECT
  bi.booking_id,
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
WHERE bi.booking_id = ANY(%s)
ORDER BY bi.booking_id, c.display_name, i.sku;
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
  b.id,
  b.start_date,
  b.end_date,
  b.status,
  b.include_delivery,
  b.delivery_fee,
  c.address,
  c.postal_city,
  b.delivery_address,
  b.delivery_distance_km,
  b.include_setup_service,
  b.custom_total_price,
  b.custom_price_note,
  b.booking_note,
  NULL::TEXT AS admin_note,
  b.created_at
FROM bookings b
JOIN customers c ON c.id = b.customer_id
WHERE b.customer_id = %s
ORDER BY b.created_at DESC;
"""

SQL_LIST_ALL_BOOKINGS = """
WITH booking_rollup AS (
  SELECT
    bi.booking_id,
    BOOL_OR(tc.category_id IS NOT NULL) AS has_tent,
    COUNT(DISTINCT c.id) FILTER (WHERE tc.category_id IS NOT NULL) AS tent_category_count,
    MIN(c.display_name) FILTER (WHERE tc.category_id IS NOT NULL) AS single_tent_name,
    COALESCE(SUM(COALESCE(bi.custom_total_price, bi.quoted_period_price)), 0) AS rental_sum,
    COALESCE(SUM(COALESCE(bi.setup_service_fee, 0)), 0) AS setup_sum
  FROM booking_items bi
  JOIN items i ON i.id = bi.item_id
  JOIN categories c ON c.id = i.category_id
  LEFT JOIN tent_categories tc ON tc.category_id = c.id
  GROUP BY bi.booking_id
)
SELECT
  b.id,
  b.start_date,
  b.end_date,
  b.status,
  COALESCE(br.has_tent, FALSE) AS has_tent,
  CASE
    WHEN br.tent_category_count = 1 THEN br.single_tent_name
    WHEN br.tent_category_count >= 2 THEN '2+'
    ELSE NULL
  END AS tent_summary,
  CASE
    WHEN b.custom_total_price IS NOT NULL THEN b.custom_total_price
    ELSE
      COALESCE(br.rental_sum, 0)
      + CASE WHEN b.include_setup_service THEN COALESCE(br.setup_sum, 0) ELSE 0 END
      + CASE WHEN b.include_delivery THEN COALESCE(b.delivery_fee, 0) ELSE 0 END
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
  c.email,
  c.postal_city
FROM bookings b
JOIN customers c ON c.id = b.customer_id
LEFT JOIN booking_rollup br ON br.booking_id = b.id
ORDER BY b.created_at DESC;
"""

SQL_CONFIRM_BOOKING = """
UPDATE bookings
SET status = 'confirmed'
WHERE id = %s
  AND status = 'pending';
"""

SQL_CANCEL_BOOKING = """
UPDATE bookings
SET status = 'cancelled'
WHERE id = %s
  AND status <> 'cancelled';
"""

SQL_DELETE_BOOKING = """
DELETE FROM bookings
WHERE id = %s
  AND status = 'cancelled';
"""

SQL_BOOKING_ALLOCATION_CANDIDATES = """
WITH request_window AS (
  SELECT
    %s::int AS current_booking_id,
    %s::date AS requested_start,
    %s::date AS requested_end
)
SELECT
  i.id AS item_id,
  i.sku,
  COALESCE(ov.has_overlap, FALSE) AS is_turnaround
FROM items i
CROSS JOIN request_window rw
LEFT JOIN LATERAL (
  SELECT
    COUNT(*) > 0 AS has_overlap,
    COALESCE(BOOL_OR(b.end_date <> rw.requested_start), FALSE) AS has_blocking_overlap
  FROM booking_items bi
  JOIN bookings b ON b.id = bi.booking_id
  WHERE bi.item_id = i.id
    AND (rw.current_booking_id IS NULL OR bi.booking_id <> rw.current_booking_id)
    AND b.status <> 'cancelled'
    AND rw.requested_start <= b.end_date
    AND rw.requested_end >= b.start_date
) ov ON TRUE
WHERE i.category_id = %s
  AND (
    i.is_active = TRUE
    OR EXISTS (
      SELECT 1
      FROM booking_items current_bi
      WHERE current_bi.booking_id = rw.current_booking_id
        AND current_bi.item_id = i.id
    )
  )
  AND COALESCE(ov.has_blocking_overlap, FALSE) = FALSE
ORDER BY COALESCE(ov.has_overlap, FALSE), i.id
FOR UPDATE OF i SKIP LOCKED;
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

SQL_DELETE_BOOKING_ITEMS_FOR_BOOKING = """
DELETE FROM booking_items
WHERE booking_id = %s;
"""

SQL_INSERT_BOOKING_ITEM = """
INSERT INTO booking_items (
  booking_id,
  item_id,
  rental_period_id,
  quoted_period_label,
  quoted_period_price,
  setup_service_fee,
  custom_total_price,
  custom_price_note,
  line_note
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
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
SELECT id, full_name, email, phone, address, postal_city, user_id, created_at
FROM customers
WHERE id = %s;
"""

SQL_UPDATE_CUSTOMER = """
UPDATE customers
SET
    full_name = %s,
    email = %s,
    phone = %s,
    address = %s,
    postal_city = %s
WHERE id = %s
RETURNING id;
"""
