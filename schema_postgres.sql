-- Tent Rental Schema (Categories + Multiple Items, is_active boolean)

DROP TABLE IF EXISTS booking_items;
DROP TABLE IF EXISTS bookings;
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
  email VARCHAR(255) NOT NULL UNIQUE,
  phone VARCHAR(50),
  user_id INT UNIQUE REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CATEGORIES (product/model)
CREATE TABLE categories (
  id SERIAL PRIMARY KEY,
  display_name VARCHAR(200) NOT NULL UNIQUE,
  daily_rate NUMERIC(10,2) NOT NULL DEFAULT 0.00,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_category_daily_rate CHECK (daily_rate >= 0)
);

-- ITEMS (physical units)
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
CREATE TABLE tent_categories (
  category_id INT PRIMARY KEY REFERENCES categories(id) ON DELETE CASCADE,
  capacity INT NOT NULL,
  season_rating INT NOT NULL,
  packed_weight_kg NUMERIC(5,2),
  floor_area_m2 NUMERIC(5,2),

  estimated_build_time_minutes INT NOT NULL DEFAULT 10,
  construction_cost NUMERIC(10,2) NOT NULL DEFAULT 0.00,
  deconstruction_cost NUMERIC(10,2) NOT NULL DEFAULT 0.00,

  CONSTRAINT chk_tentcap_capacity CHECK (capacity > 0),
  CONSTRAINT chk_tentcap_season CHECK (season_rating BETWEEN 1 AND 5),
  CONSTRAINT chk_tentcap_weight CHECK (packed_weight_kg IS NULL OR packed_weight_kg >= 0),
  CONSTRAINT chk_tentcap_area CHECK (floor_area_m2 IS NULL OR floor_area_m2 >= 0),
  CONSTRAINT chk_tentcap_build_time CHECK (estimated_build_time_minutes >= 0),
  CONSTRAINT chk_tentcap_construction_cost CHECK (construction_cost >= 0),
  CONSTRAINT chk_tentcap_deconstruction_cost CHECK (deconstruction_cost >= 0)
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
CREATE TABLE bookings (
  id SERIAL PRIMARY KEY,
  customer_id INT NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_booking_dates CHECK (end_date > start_date),
  CONSTRAINT chk_booking_status CHECK (status IN ('pending','confirmed','cancelled'))
);

CREATE INDEX idx_bookings_customer_created ON bookings(customer_id, created_at);
CREATE INDEX idx_bookings_status ON bookings(status);
CREATE INDEX idx_bookings_dates ON bookings(start_date, end_date);

-- BOOKING_ITEMS (many-to-many)
CREATE TABLE booking_items (
  booking_id INT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
  item_id INT NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
  price_per_day NUMERIC(10,2),
  line_note VARCHAR(255),

  PRIMARY KEY (booking_id, item_id),
  CONSTRAINT chk_line_price CHECK (price_per_day IS NULL OR price_per_day >= 0)
);

CREATE INDEX idx_booking_items_item_id ON booking_items(item_id);

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

-- stored functions: create (category + subtype) and one physical unit (item)

CREATE OR REPLACE FUNCTION add_tent_item(
  p_sku VARCHAR,
  p_display_name VARCHAR,
  p_daily_rate NUMERIC(10,2),
  p_capacity INT,
  p_season_rating INT,
  p_estimated_build_time_minutes INT,
  p_construction_cost NUMERIC(10,2),
  p_deconstruction_cost NUMERIC(10,2),
  p_packed_weight_kg NUMERIC(5,2) DEFAULT NULL,
  p_floor_area_m2 NUMERIC(5,2) DEFAULT NULL
)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE v_category_id INT;
DECLARE v_item_id INT;
BEGIN
  INSERT INTO categories (display_name, daily_rate)
  VALUES (p_display_name, p_daily_rate)
  ON CONFLICT (display_name)
  DO UPDATE SET daily_rate = EXCLUDED.daily_rate
  RETURNING id INTO v_category_id;

  INSERT INTO tent_categories (
    category_id, capacity, season_rating, estimated_build_time_minutes,
    construction_cost, deconstruction_cost, packed_weight_kg, floor_area_m2
  )
  VALUES (
    v_category_id, p_capacity, p_season_rating, p_estimated_build_time_minutes,
    p_construction_cost, p_deconstruction_cost, p_packed_weight_kg, p_floor_area_m2
  )
  ON CONFLICT (category_id)
  DO UPDATE SET
    capacity = EXCLUDED.capacity,
    season_rating = EXCLUDED.season_rating,
    estimated_build_time_minutes = EXCLUDED.estimated_build_time_minutes,
    construction_cost = EXCLUDED.construction_cost,
    deconstruction_cost = EXCLUDED.deconstruction_cost,
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
  p_daily_rate NUMERIC(10,2),
  p_furnishing_kind VARCHAR,
  p_weight_kg NUMERIC(5,2) DEFAULT NULL,
  p_notes TEXT DEFAULT NULL
)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE v_category_id INT;
DECLARE v_item_id INT;
BEGIN
  INSERT INTO categories (display_name, daily_rate)
  VALUES (p_display_name, p_daily_rate)
  ON CONFLICT (display_name)
  DO UPDATE SET daily_rate = EXCLUDED.daily_rate
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

-- Uses row locking: FOR UPDATE SKIP LOCKED

CREATE OR REPLACE FUNCTION create_booking_with_allocations(
  p_customer_id INT,
  p_start DATE,
  p_end DATE,
  p_category_ids INT[],
  p_qtys INT[]
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
BEGIN
  IF array_length(p_category_ids, 1) IS NULL
     OR array_length(p_qtys, 1) IS NULL
     OR array_length(p_category_ids, 1) <> array_length(p_qtys, 1) THEN
    RAISE EXCEPTION 'category_ids and qtys must have same length';
  END IF;

  IF p_end <= p_start THEN
    RAISE EXCEPTION 'Invalid dates: end_date must be after start_date';
  END IF;

  -- Create booking header
  INSERT INTO bookings (customer_id, start_date, end_date, status)
  VALUES (p_customer_id, p_start, p_end, 'pending')
  RETURNING id INTO v_booking_id;

  -- Allocate items per category
  FOR v_i IN 1..array_length(p_category_ids, 1) LOOP
    v_cat := p_category_ids[v_i];
    v_qty := p_qtys[v_i];

    IF v_qty IS NULL OR v_qty <= 0 THEN
      RAISE EXCEPTION 'Invalid qty % for category %', v_qty, v_cat;
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
            AND p_start < b.end_date
            AND p_end > b.start_date
        )
      ORDER BY i.id
      FOR UPDATE SKIP LOCKED
      LIMIT v_qty
    ),
    ins AS (
      INSERT INTO booking_items (booking_id, item_id, price_per_day)
      SELECT v_booking_id, p.id, c.daily_rate
      FROM picked p
      JOIN items i ON i.id = p.id
      JOIN categories c ON c.id = i.category_id
      RETURNING 1
    )
    SELECT COUNT(*) INTO v_picked_count FROM ins;

    IF v_picked_count <> v_qty THEN
      RAISE EXCEPTION
        'Not enough available units for category %: requested %, got %',
        v_cat, v_qty, v_picked_count;
    END IF;
  END LOOP;

  RETURN v_booking_id;
END$$;

-- Add a physical unit to an existing category
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