-- Tent Rental Schema

DROP TABLE IF EXISTS booking_items;
DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS furnishings;
DROP TABLE IF EXISTS tents;
DROP TABLE IF EXISTS items;
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

-- CUSTOMERS (profiles; optional)
CREATE TABLE customers (
  id SERIAL PRIMARY KEY,
  full_name VARCHAR(200) NOT NULL,
  email VARCHAR(255) NOT NULL UNIQUE,
  phone VARCHAR(50),
  user_id INT UNIQUE REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ITEMS
CREATE TABLE items (
  id SERIAL PRIMARY KEY,
  sku VARCHAR(100) NOT NULL UNIQUE,
  display_name VARCHAR(200) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active',
  daily_rate NUMERIC(10,2) NOT NULL DEFAULT 0.00,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_item_status CHECK (status IN ('active','maintenance','retired')),
  CONSTRAINT chk_item_daily_rate CHECK (daily_rate >= 0)
);
CREATE INDEX idx_items_status ON items(status);

-- TENTS
CREATE TABLE tents (
  item_id INT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  capacity INT NOT NULL,
  season_rating INT NOT NULL,
  packed_weight_kg NUMERIC(5,2),
  floor_area_m2 NUMERIC(5,2),
  estimated_build_time_minutes INT NOT NULL DEFAULT 10,
  construction_cost NUMERIC(10,2) NOT NULL DEFAULT 0.00,
  deconstruction_cost NUMERIC(10,2) NOT NULL DEFAULT 0.00,

  CONSTRAINT chk_tents_capacity CHECK (capacity > 0),
  CONSTRAINT chk_tents_season CHECK (season_rating BETWEEN 1 AND 5),
  CONSTRAINT chk_tents_weight CHECK (packed_weight_kg IS NULL OR packed_weight_kg >= 0),
  CONSTRAINT chk_tents_area CHECK (floor_area_m2 IS NULL OR floor_area_m2 >= 0),
  CONSTRAINT chk_tents_build_time CHECK (estimated_build_time_minutes >= 0),
  CONSTRAINT chk_tents_construction_cost CHECK (construction_cost >= 0),
  CONSTRAINT chk_tents_deconstruction_cost CHECK (deconstruction_cost >= 0)
);

-- FURNISHINGS
CREATE TABLE furnishings (
  item_id INT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
  furnishing_kind VARCHAR(100) NOT NULL,
  weight_kg NUMERIC(5,2),
  notes TEXT,
  CONSTRAINT chk_furn_weight CHECK (weight_kg IS NULL OR weight_kg >= 0)
);

-- subtype enforcement (tents XOR furnishings)
CREATE OR REPLACE FUNCTION trg_prevent_two_subtypes()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'tents' THEN
    IF EXISTS (SELECT 1 FROM furnishings f WHERE f.item_id = NEW.item_id) THEN
      RAISE EXCEPTION 'Item % cannot be both tent and furnishing', NEW.item_id;
    END IF;
  ELSIF TG_TABLE_NAME = 'furnishings' THEN
    IF EXISTS (SELECT 1 FROM tents t WHERE t.item_id = NEW.item_id) THEN
      RAISE EXCEPTION 'Item % cannot be both tent and furnishing', NEW.item_id;
    END IF;
  END IF;
  RETURN NEW;
END$$;

DROP TRIGGER IF EXISTS before_tents_insert ON tents;
CREATE TRIGGER before_tents_insert
BEFORE INSERT OR UPDATE ON tents
FOR EACH ROW EXECUTE FUNCTION trg_prevent_two_subtypes();

DROP TRIGGER IF EXISTS before_furnishings_insert ON furnishings;
CREATE TRIGGER before_furnishings_insert
BEFORE INSERT OR UPDATE ON furnishings
FOR EACH ROW EXECUTE FUNCTION trg_prevent_two_subtypes();

CREATE OR REPLACE FUNCTION trg_item_must_have_exactly_one_subtype()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE v_count INT;
BEGIN
  SELECT
    (CASE WHEN EXISTS (SELECT 1 FROM tents t WHERE t.item_id = NEW.id) THEN 1 ELSE 0 END) +
    (CASE WHEN EXISTS (SELECT 1 FROM furnishings f WHERE f.item_id = NEW.id) THEN 1 ELSE 0 END)
  INTO v_count;

  IF v_count <> 1 THEN
    RAISE EXCEPTION 'Item % must have exactly one subtype row (tents XOR furnishings)', NEW.id;
  END IF;
  RETURN NULL;
END$$;

DROP TRIGGER IF EXISTS item_subtype_required ON items;
CREATE CONSTRAINT TRIGGER item_subtype_required
AFTER INSERT ON items
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION trg_item_must_have_exactly_one_subtype();

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

-- overlap prevention
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

-- stored functions:
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
DECLARE v_item_id INT;
BEGIN
  INSERT INTO items (sku, display_name, daily_rate)
  VALUES (p_sku, p_display_name, p_daily_rate)
  RETURNING id INTO v_item_id;

  INSERT INTO tents (
    item_id, capacity, season_rating, estimated_build_time_minutes,
    construction_cost, deconstruction_cost, packed_weight_kg, floor_area_m2
  )
  VALUES (
    v_item_id, p_capacity, p_season_rating, p_estimated_build_time_minutes,
    p_construction_cost, p_deconstruction_cost, p_packed_weight_kg, p_floor_area_m2
  );

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
DECLARE v_item_id INT;
BEGIN
  INSERT INTO items (sku, display_name, daily_rate)
  VALUES (p_sku, p_display_name, p_daily_rate)
  RETURNING id INTO v_item_id;

  INSERT INTO furnishings (item_id, furnishing_kind, weight_kg, notes)
  VALUES (v_item_id, p_furnishing_kind, p_weight_kg, p_notes);

  RETURN v_item_id;
END$$;