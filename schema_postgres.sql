-- Tent Rental Schema

DROP TABLE IF EXISTS booking_items;
DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS category_rental_period_prices;
DROP TABLE IF EXISTS rental_periods;
DROP TABLE IF EXISTS furnishing_categories;
DROP TABLE IF EXISTS tent_categories;
DROP TABLE IF EXISTS items;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS users;

-- USERS
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'customer',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_user_role CHECK (role IN ('customer','admin'))
);

-- CUSTOMERS (profiles; optional link to user)
CREATE TABLE customers (
  id SERIAL PRIMARY KEY,
  full_name VARCHAR(200) NOT NULL,
  email VARCHAR(255),
  phone VARCHAR(50),
  address TEXT,
  postal_city TEXT,
  user_id INT UNIQUE REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX customers_email_lower_uniq
  ON customers ((lower(email)))
  WHERE email IS NOT NULL;

CREATE INDEX customers_full_name_lower_idx
  ON customers ((lower(full_name)));

-- CATEGORIES (product/model)
-- Pricing removed from here. Pricing now depends on category + rental period.
CREATE TABLE categories (
  id SERIAL PRIMARY KEY,
  display_name VARCHAR(200) NOT NULL UNIQUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- RENTAL PERIODS (reusable)
-- Examples:
--   1 dag
--   2-3 dagar
--   4-7 dagar
--   3 dagar
--   4-5 dagar
--   6-7 dagar
CREATE TABLE rental_periods (
  id SERIAL PRIMARY KEY,
  label VARCHAR(100) NOT NULL UNIQUE,
  min_days INT NOT NULL,
  max_days INT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_rental_period_days CHECK (min_days > 0 AND max_days >= min_days),
  CONSTRAINT uq_rental_period_range UNIQUE (min_days, max_days)
);

-- CATEGORY <-> RENTAL PERIOD pricing
-- This is where the actual price lives.
CREATE TABLE category_rental_period_prices (
  category_id INT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  rental_period_id INT NOT NULL REFERENCES rental_periods(id) ON DELETE RESTRICT,
  price NUMERIC(10,2) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (category_id, rental_period_id),
  CONSTRAINT chk_category_period_price CHECK (price >= 0),
  CONSTRAINT chk_category_period_sort_order CHECK (sort_order >= 0)
);

CREATE INDEX idx_category_rental_period_prices_category
  ON category_rental_period_prices(category_id);

CREATE INDEX idx_category_rental_period_prices_period
  ON category_rental_period_prices(rental_period_id);

-- Prevent overlapping period ranges within the same category pricing setup
CREATE OR REPLACE FUNCTION trg_prevent_overlapping_category_periods()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_new_min INT;
  v_new_max INT;
BEGIN
  SELECT rp.min_days, rp.max_days
    INTO v_new_min, v_new_max
  FROM rental_periods rp
  WHERE rp.id = NEW.rental_period_id;

  IF EXISTS (
    SELECT 1
    FROM category_rental_period_prices crpp
    JOIN rental_periods rp_existing
      ON rp_existing.id = crpp.rental_period_id
    WHERE crpp.category_id = NEW.category_id
      AND crpp.rental_period_id <> NEW.rental_period_id
      AND v_new_min <= rp_existing.max_days
      AND v_new_max >= rp_existing.min_days
  ) THEN
    RAISE EXCEPTION 'Category % cannot have overlapping rental periods', NEW.category_id;
  END IF;

  RETURN NEW;
END$$;

DROP TRIGGER IF EXISTS prevent_overlapping_category_periods
ON category_rental_period_prices;

CREATE TRIGGER prevent_overlapping_category_periods
BEFORE INSERT OR UPDATE ON category_rental_period_prices
FOR EACH ROW EXECUTE FUNCTION trg_prevent_overlapping_category_periods();

-- ITEMS (physical items)
CREATE TABLE items (
  id SERIAL PRIMARY KEY,
  category_id INT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  sku VARCHAR(100) NOT NULL UNIQUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_items_active ON items(is_active);
CREATE INDEX idx_items_category ON items(category_id);

-- TENT_CATEGORIES (derived subtype of category)
-- setup_service_fee = construction + deconstruction together
CREATE TABLE tent_categories (
  category_id INT PRIMARY KEY REFERENCES categories(id) ON DELETE CASCADE,
  capacity INT NOT NULL,
  season_rating INT NOT NULL,
  packed_weight_kg NUMERIC(5,2),
  floor_area_m2 NUMERIC(5,2),

  estimated_build_time_minutes INT NOT NULL DEFAULT 10,
  setup_service_fee NUMERIC(10,2) NOT NULL DEFAULT 0.00,

  CONSTRAINT chk_tentcap_capacity CHECK (capacity > 0),
  CONSTRAINT chk_tentcap_season CHECK (season_rating BETWEEN 1 AND 5),
  CONSTRAINT chk_tentcap_weight CHECK (packed_weight_kg IS NULL OR packed_weight_kg >= 0),
  CONSTRAINT chk_tentcap_area CHECK (floor_area_m2 IS NULL OR floor_area_m2 >= 0),
  CONSTRAINT chk_tentcap_build_time CHECK (estimated_build_time_minutes >= 0),
  CONSTRAINT chk_tentcap_setup_fee CHECK (setup_service_fee >= 0)
);

-- FURNISHING_CATEGORIES (derived subtype of category)
CREATE TABLE furnishing_categories (
  category_id INT PRIMARY KEY REFERENCES categories(id) ON DELETE CASCADE,
  furnishing_kind VARCHAR(100) NOT NULL,
  weight_kg NUMERIC(5,2),
  notes TEXT,
  CONSTRAINT chk_furncat_weight CHECK (weight_kg IS NULL OR weight_kg >= 0)
);

-- subtype enforcement (tent_categories XOR furnishing_categories)

CREATE OR REPLACE FUNCTION trg_prevent_two_category_subtypes()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'tent_categories' THEN
    IF EXISTS (SELECT 1 FROM furnishing_categories f WHERE f.category_id = NEW.category_id) THEN
      RAISE EXCEPTION 'Category % cannot be both tent and furnishing', NEW.category_id;
    END IF;
  ELSIF TG_TABLE_NAME = 'furnishing_categories' THEN
    IF EXISTS (SELECT 1 FROM tent_categories t WHERE t.category_id = NEW.category_id) THEN
      RAISE EXCEPTION 'Category % cannot be both tent and furnishing', NEW.category_id;
    END IF;
  END IF;
  RETURN NEW;
END$$;

DROP TRIGGER IF EXISTS before_tentcat_insert ON tent_categories;
CREATE TRIGGER before_tentcat_insert
BEFORE INSERT OR UPDATE ON tent_categories
FOR EACH ROW EXECUTE FUNCTION trg_prevent_two_category_subtypes();

DROP TRIGGER IF EXISTS before_furncat_insert ON furnishing_categories;
CREATE TRIGGER before_furncat_insert
BEFORE INSERT OR UPDATE ON furnishing_categories
FOR EACH ROW EXECUTE FUNCTION trg_prevent_two_category_subtypes();

-- deferred: ensure each category ends up with exactly ONE subtype row
CREATE OR REPLACE FUNCTION trg_category_must_have_exactly_one_subtype()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_count INT;
BEGIN
  SELECT
    (CASE WHEN EXISTS (SELECT 1 FROM tent_categories t WHERE t.category_id = NEW.id) THEN 1 ELSE 0 END) +
    (CASE WHEN EXISTS (SELECT 1 FROM furnishing_categories f WHERE f.category_id = NEW.id) THEN 1 ELSE 0 END)
  INTO v_count;

  IF v_count <> 1 THEN
    RAISE EXCEPTION 'Category % must have exactly one subtype row (tent_categories XOR furnishing_categories)', NEW.id;
  END IF;

  RETURN NULL;
END$$;

DROP TRIGGER IF EXISTS category_subtype_required ON categories;
CREATE CONSTRAINT TRIGGER category_subtype_required
AFTER INSERT ON categories
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION trg_category_must_have_exactly_one_subtype();

-- BOOKINGS
-- include_delivery = whether delivery is part of booking
-- include_setup_service = whether setup/teardown is included
-- delivery_fee is stored as snapshot for the booking
-- custom_total_price lets admin override the full booking total
CREATE TABLE bookings (
  id SERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',

  include_delivery BOOLEAN NOT NULL DEFAULT FALSE,
  include_setup_service BOOLEAN NOT NULL DEFAULT FALSE,
  delivery_fee NUMERIC(10,2),
  delivery_address TEXT,
  delivery_distance_km NUMERIC(10,2),
  custom_total_price NUMERIC(10,2),
  custom_price_note TEXT,
  booking_note TEXT,

  admin_note TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT chk_booking_dates CHECK (end_date >= start_date),
  CONSTRAINT chk_booking_status CHECK (status IN ('pending','confirmed','cancelled')),
  CONSTRAINT chk_delivery_fee CHECK (delivery_fee IS NULL OR delivery_fee >= 0),
  CONSTRAINT chk_delivery_distance CHECK (delivery_distance_km IS NULL OR delivery_distance_km >= 0),
  CONSTRAINT chk_booking_custom_total CHECK (custom_total_price IS NULL OR custom_total_price >= 0)
);

CREATE INDEX idx_bookings_customer_created ON bookings(customer_id, created_at);
CREATE INDEX idx_bookings_status ON bookings(status);
CREATE INDEX idx_bookings_dates ON bookings(start_date, end_date);

-- BOOKING_ITEMS (many-to-many booking <-> physical items)
-- Stores the chosen rental period and price snapshot
-- custom_total_price lets admin override the standard calculated price
CREATE TABLE booking_items (
  booking_id INT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  item_id INT NOT NULL REFERENCES items(id) ON DELETE RESTRICT,

  rental_period_id INT REFERENCES rental_periods(id) ON DELETE SET NULL,
  quoted_period_label VARCHAR(100),
  quoted_period_price NUMERIC(10,2),
  setup_service_fee NUMERIC(10,2),

  custom_total_price NUMERIC(10,2),
  custom_price_note TEXT,

  line_note VARCHAR(255),

  PRIMARY KEY (booking_id, item_id),

  CONSTRAINT chk_line_period_price CHECK (quoted_period_price IS NULL OR quoted_period_price >= 0),
  CONSTRAINT chk_line_setup_fee CHECK (setup_service_fee IS NULL OR setup_service_fee >= 0),
  CONSTRAINT chk_line_custom_total CHECK (custom_total_price IS NULL OR custom_total_price >= 0)
);

CREATE INDEX idx_booking_items_item_booking ON booking_items(item_id, booking_id);

-- overlap prevention (per physical item)
CREATE OR REPLACE FUNCTION trg_prevent_overlapping_item_booking()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_start DATE;
DECLARE v_end DATE;
BEGIN
  SELECT b.start_date, b.end_date INTO v_start, v_end
  FROM bookings b WHERE b.id = NEW.booking_id;

  IF EXISTS (
    SELECT 1
    FROM booking_items bi
    JOIN bookings b2 ON b2.id = bi.booking_id
    WHERE bi.item_id = NEW.item_id
      AND b2.status <> 'cancelled'
      AND bi.booking_id <> NEW.booking_id
      AND v_start < b2.end_date
      AND v_end > b2.start_date
  ) THEN
    RAISE EXCEPTION 'Item % is already booked for an overlapping period', NEW.item_id;
  END IF;

  RETURN NEW;
END$$;

DROP TRIGGER IF EXISTS prevent_overlap_on_booking_items ON booking_items;
CREATE TRIGGER prevent_overlap_on_booking_items
BEFORE INSERT OR UPDATE ON booking_items
FOR EACH ROW EXECUTE FUNCTION trg_prevent_overlapping_item_booking();

-- Utility: find the rental period + price for a category and duration
CREATE OR REPLACE FUNCTION get_category_rental_pricing(
  p_category_id INT,
  p_rental_days INT
)
RETURNS TABLE (
  rental_period_id INT,
  period_label VARCHAR(100),
  period_price NUMERIC(10,2)
)
LANGUAGE plpgsql
AS $$
BEGIN
  IF p_rental_days <= 0 THEN
    RAISE EXCEPTION 'Rental days must be > 0';
  END IF;

  RETURN QUERY
  SELECT
    rp.id,
    rp.label,
    crpp.price
  FROM category_rental_period_prices crpp
  JOIN rental_periods rp ON rp.id = crpp.rental_period_id
  WHERE crpp.category_id = p_category_id
    AND p_rental_days BETWEEN rp.min_days AND rp.max_days
  ORDER BY crpp.sort_order, rp.min_days, rp.max_days
  LIMIT 1;

  IF NOT FOUND THEN
    RAISE EXCEPTION
      'No rental pricing configured for category % and % rental days',
      p_category_id, p_rental_days;
  END IF;
END$$;

-- stored functions: create (category + subtype) and one physical item

CREATE OR REPLACE FUNCTION add_tent_item(
  p_sku VARCHAR,
  p_display_name VARCHAR,
  p_capacity INT,
  p_season_rating INT,
  p_estimated_build_time_minutes INT,
  p_setup_service_fee NUMERIC(10,2),
  p_packed_weight_kg NUMERIC(5,2) DEFAULT NULL,
  p_floor_area_m2 NUMERIC(5,2) DEFAULT NULL
)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE v_category_id INT;
DECLARE v_item_id INT;
BEGIN
  INSERT INTO categories (display_name)
  VALUES (p_display_name)
  ON CONFLICT (display_name)
  DO UPDATE SET display_name = EXCLUDED.display_name
  RETURNING id INTO v_category_id;

  INSERT INTO tent_categories (
    category_id, capacity, season_rating, estimated_build_time_minutes,
    setup_service_fee, packed_weight_kg, floor_area_m2
  )
  VALUES (
    v_category_id, p_capacity, p_season_rating, p_estimated_build_time_minutes,
    p_setup_service_fee, p_packed_weight_kg, p_floor_area_m2
  )
  ON CONFLICT (category_id)
  DO UPDATE SET
    capacity = EXCLUDED.capacity,
    season_rating = EXCLUDED.season_rating,
    estimated_build_time_minutes = EXCLUDED.estimated_build_time_minutes,
    setup_service_fee = EXCLUDED.setup_service_fee,
    packed_weight_kg = EXCLUDED.packed_weight_kg,
    floor_area_m2 = EXCLUDED.floor_area_m2;

  INSERT INTO items (category_id, sku, is_active)
  VALUES (v_category_id, p_sku, TRUE)
  ON CONFLICT (sku)
  DO UPDATE SET
    category_id = EXCLUDED.category_id,
    is_active = TRUE
  RETURNING id INTO v_item_id;

  RETURN v_item_id;
END$$;

CREATE OR REPLACE FUNCTION add_furnishing_item(
  p_sku VARCHAR,
  p_display_name VARCHAR,
  p_furnishing_kind VARCHAR,
  p_weight_kg NUMERIC(5,2) DEFAULT NULL,
  p_notes TEXT DEFAULT NULL
)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE v_category_id INT;
DECLARE v_item_id INT;
BEGIN
  INSERT INTO categories (display_name)
  VALUES (p_display_name)
  ON CONFLICT (display_name)
  DO UPDATE SET display_name = EXCLUDED.display_name
  RETURNING id INTO v_category_id;

  INSERT INTO furnishing_categories (category_id, furnishing_kind, weight_kg, notes)
  VALUES (v_category_id, p_furnishing_kind, p_weight_kg, p_notes)
  ON CONFLICT (category_id)
  DO UPDATE SET
    furnishing_kind = EXCLUDED.furnishing_kind,
    weight_kg = EXCLUDED.weight_kg,
    notes = EXCLUDED.notes;

  INSERT INTO items (category_id, sku, is_active)
  VALUES (v_category_id, p_sku, TRUE)
  ON CONFLICT (sku)
  DO UPDATE SET
    category_id = EXCLUDED.category_id,
    is_active = TRUE
  RETURNING id INTO v_item_id;

  RETURN v_item_id;
END$$;

-- Configure a category price for a rental period
CREATE OR REPLACE FUNCTION set_category_rental_period_price(
  p_category_id INT,
  p_rental_period_id INT,
  p_price NUMERIC(10,2),
  p_sort_order INT DEFAULT 0
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO category_rental_period_prices (
    category_id,
    rental_period_id,
    price,
    sort_order
  )
  VALUES (
    p_category_id,
    p_rental_period_id,
    p_price,
    p_sort_order
  )
  ON CONFLICT (category_id, rental_period_id)
  DO UPDATE SET
    price = EXCLUDED.price,
    sort_order = EXCLUDED.sort_order;
END$$;

-- Uses row locking: FOR UPDATE SKIP LOCKED
CREATE OR REPLACE FUNCTION create_booking_with_allocations(
  p_customer_id INT,
  p_start DATE,
  p_end DATE,
  p_category_ids INT[],
  p_qtys INT[],
  p_include_delivery BOOLEAN DEFAULT FALSE,
  p_delivery_fee NUMERIC(10,2) DEFAULT NULL,
  p_include_setup_service BOOLEAN DEFAULT FALSE,
  p_booking_custom_total_price NUMERIC(10,2) DEFAULT NULL,
  p_booking_custom_price_note TEXT DEFAULT NULL,
  p_booking_note TEXT DEFAULT NULL,
  p_delivery_address TEXT DEFAULT NULL,
  p_delivery_distance_km NUMERIC(10,2) DEFAULT NULL,
  p_custom_total_prices NUMERIC(10,2)[] DEFAULT NULL,
  p_custom_price_notes TEXT[] DEFAULT NULL
)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
  v_booking_id INT;
  v_i INT;
  v_cat INT;
  v_qty INT;
  v_picked_count INT;
  v_rental_days INT;
  v_rental_period_id INT;
  v_period_label VARCHAR(100);
  v_period_price NUMERIC(10,2);
  v_setup_service_fee NUMERIC(10,2);
  v_custom_total_price NUMERIC(10,2);
  v_custom_price_note TEXT;
BEGIN
  IF array_length(p_category_ids, 1) IS NULL
     OR array_length(p_qtys, 1) IS NULL
     OR array_length(p_category_ids, 1) <> array_length(p_qtys, 1) THEN
    RAISE EXCEPTION 'category_ids and qtys must have same length';
  END IF;

  IF p_custom_total_prices IS NOT NULL
     AND array_length(p_custom_total_prices, 1) <> array_length(p_category_ids, 1) THEN
    RAISE EXCEPTION 'custom_total_prices must have same length as category_ids';
  END IF;

  IF p_custom_price_notes IS NOT NULL
     AND array_length(p_custom_price_notes, 1) <> array_length(p_category_ids, 1) THEN
    RAISE EXCEPTION 'custom_price_notes must have same length as category_ids';
  END IF;

  IF p_end < p_start THEN
    RAISE EXCEPTION 'Invalid dates: end_date must be after start_date';
  END IF;

  v_rental_days := (p_end - p_start + 1);

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
    booking_note
  )
  VALUES (
    p_customer_id,
    p_start,
    p_end,
    'pending',
    p_include_delivery,
    CASE WHEN p_include_delivery THEN COALESCE(p_delivery_fee, 0) ELSE NULL END,
    CASE WHEN p_include_delivery THEN p_delivery_address ELSE NULL END,
    CASE WHEN p_include_delivery THEN p_delivery_distance_km ELSE NULL END,
    p_include_setup_service,
    p_booking_custom_total_price,
    p_booking_custom_price_note,
    p_booking_note
  )
  RETURNING id INTO v_booking_id;

  FOR v_i IN 1..array_length(p_category_ids, 1) LOOP
    v_cat := p_category_ids[v_i];
    v_qty := p_qtys[v_i];

    IF v_qty IS NULL OR v_qty <= 0 THEN
      RAISE EXCEPTION 'Invalid qty % for category %', v_qty, v_cat;
    END IF;

    v_rental_period_id := NULL;
    v_period_label := NULL;
    v_period_price := NULL;

    SELECT
      rp.id,
      rp.label,
      crpp.price
    INTO
      v_rental_period_id,
      v_period_label,
      v_period_price
    FROM category_rental_period_prices crpp
    JOIN rental_periods rp ON rp.id = crpp.rental_period_id
    WHERE crpp.category_id = v_cat
      AND v_rental_days BETWEEN rp.min_days AND rp.max_days
    ORDER BY crpp.sort_order, rp.min_days, rp.max_days, rp.id
    LIMIT 1;

    v_custom_total_price := NULL;
    v_custom_price_note := NULL;

    IF p_custom_total_prices IS NOT NULL THEN
      v_custom_total_price := p_custom_total_prices[v_i];
    END IF;

    IF p_custom_price_notes IS NOT NULL THEN
      v_custom_price_note := p_custom_price_notes[v_i];
    END IF;

    IF v_rental_period_id IS NULL
       AND v_custom_total_price IS NULL
       AND p_booking_custom_total_price IS NULL THEN
      RAISE EXCEPTION
        'No standard pricing configured for category % and % rental days. Custom price required.',
        v_cat, v_rental_days;
    END IF;

    IF p_include_setup_service THEN
      SELECT tc.setup_service_fee
        INTO v_setup_service_fee
      FROM tent_categories tc
      WHERE tc.category_id = v_cat;
    ELSE
      v_setup_service_fee := NULL;
    END IF;

    WITH picked AS (
      SELECT i.id
      FROM items i
      WHERE i.category_id = v_cat
        AND i.is_active = TRUE
        AND NOT EXISTS (
          SELECT 1
          FROM booking_items bi
          JOIN bookings b ON b.id = bi.booking_id
          WHERE bi.item_id = i.id
            AND b.status <> 'cancelled'
            AND p_start <= b.end_date
            AND p_end >= b.start_date
        )
      ORDER BY i.id
      FOR UPDATE SKIP LOCKED
      LIMIT v_qty
    ),
    ins AS (
      INSERT INTO booking_items (
        booking_id,
        item_id,
        rental_period_id,
        quoted_period_label,
        quoted_period_price,
        setup_service_fee,
        custom_total_price,
        custom_price_note
      )
      SELECT
        v_booking_id,
        p.id,
        v_rental_period_id,
        v_period_label,
        v_period_price,
        v_setup_service_fee,
        v_custom_total_price,
        v_custom_price_note
      FROM picked p
      RETURNING 1
    )
    SELECT COUNT(*) INTO v_picked_count FROM ins;

    IF v_picked_count <> v_qty THEN
      RAISE EXCEPTION
        'Not enough available items for category %: requested %, got %',
        v_cat, v_qty, v_picked_count;
    END IF;
  END LOOP;

  RETURN v_booking_id;
END$$;

-- Add a physical item to an existing category
CREATE OR REPLACE FUNCTION add_item_unit(
  p_category_id INT,
  p_sku VARCHAR,
  p_is_active BOOLEAN DEFAULT TRUE
)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE v_item_id INT;
BEGIN
  -- Ensure category exists
  IF NOT EXISTS (SELECT 1 FROM categories c WHERE c.id = p_category_id) THEN
    RAISE EXCEPTION 'Category % does not exist', p_category_id;
  END IF;

  INSERT INTO items (category_id, sku, is_active)
  VALUES (p_category_id, p_sku, p_is_active)
  RETURNING id INTO v_item_id;

  RETURN v_item_id;
END$$;
