BEGIN;

CREATE TABLE IF NOT EXISTS item_category_memberships (
  item_id INT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  category_id INT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (item_id, category_id)
);

CREATE INDEX IF NOT EXISTS idx_item_category_memberships_category
  ON item_category_memberships(category_id);

DROP TRIGGER IF EXISTS validate_item_primary_category_change ON items;
DROP FUNCTION IF EXISTS trg_validate_item_primary_category_change();

DROP TRIGGER IF EXISTS validate_item_category_membership ON item_category_memberships;

CREATE OR REPLACE FUNCTION trg_validate_item_category_membership()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_target_is_tent BOOLEAN;
  v_target_is_furnishing BOOLEAN;
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM items i
    WHERE i.id = NEW.item_id
  ) THEN
    RAISE EXCEPTION 'Item % does not exist', NEW.item_id;
  END IF;

  SELECT
    EXISTS (SELECT 1 FROM tent_categories WHERE category_id = NEW.category_id),
    EXISTS (SELECT 1 FROM furnishing_categories WHERE category_id = NEW.category_id)
  INTO
    v_target_is_tent,
    v_target_is_furnishing;

  IF EXISTS (
    SELECT 1
    FROM item_category_memberships icm
    WHERE icm.item_id = NEW.item_id
      AND (TG_OP <> 'UPDATE' OR icm.category_id <> OLD.category_id)
      AND NOT EXISTS (
        SELECT 1
        FROM tent_categories tc
        WHERE tc.category_id = icm.category_id
          AND v_target_is_tent
      )
      AND NOT EXISTS (
        SELECT 1
        FROM furnishing_categories fc
        WHERE fc.category_id = icm.category_id
          AND v_target_is_furnishing
      )
  ) THEN
    RAISE EXCEPTION
      'Item % can only be linked to categories of the same type',
      NEW.item_id;
  END IF;

  RETURN NEW;
END$$;

CREATE TRIGGER validate_item_category_membership
BEFORE INSERT OR UPDATE ON item_category_memberships
FOR EACH ROW EXECUTE FUNCTION trg_validate_item_category_membership();

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'items'
      AND column_name = 'category_id'
  ) THEN
    INSERT INTO item_category_memberships (item_id, category_id)
    SELECT i.id, i.category_id
    FROM items i
    WHERE i.category_id IS NOT NULL
    ON CONFLICT (item_id, category_id) DO NOTHING;
  END IF;
END$$;

ALTER TABLE booking_items
  ADD COLUMN IF NOT EXISTS category_id INT;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'items'
      AND column_name = 'category_id'
  ) THEN
    UPDATE booking_items bi
    SET category_id = i.category_id
    FROM items i
    WHERE i.id = bi.item_id
      AND bi.category_id IS NULL;
  END IF;
END$$;

ALTER TABLE booking_items
  ALTER COLUMN category_id SET NOT NULL;

ALTER TABLE booking_items
  DROP CONSTRAINT IF EXISTS booking_items_category_id_fkey;

ALTER TABLE booking_items
  ADD CONSTRAINT booking_items_category_id_fkey
  FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_booking_items_category
  ON booking_items(category_id);

DROP TRIGGER IF EXISTS item_membership_required_on_items ON items;
DROP TRIGGER IF EXISTS item_membership_required_on_memberships ON item_category_memberships;
DROP FUNCTION IF EXISTS trg_item_must_have_membership();

CREATE OR REPLACE FUNCTION trg_item_must_have_membership()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'items' THEN
    IF NOT EXISTS (
      SELECT 1
      FROM item_category_memberships icm
      WHERE icm.item_id = NEW.id
    ) THEN
      RAISE EXCEPTION 'Item % must belong to at least one category', NEW.id;
    END IF;
    RETURN NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM item_category_memberships icm
    WHERE icm.item_id = OLD.item_id
  ) THEN
    RAISE EXCEPTION 'Item % must belong to at least one category', OLD.item_id;
  END IF;

  RETURN NULL;
END$$;

CREATE CONSTRAINT TRIGGER item_membership_required_on_items
AFTER INSERT ON items
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION trg_item_must_have_membership();

CREATE CONSTRAINT TRIGGER item_membership_required_on_memberships
AFTER DELETE OR UPDATE ON item_category_memberships
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION trg_item_must_have_membership();

DROP INDEX IF EXISTS idx_items_category;

ALTER TABLE items
  DROP COLUMN IF EXISTS category_id;

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

  INSERT INTO items (sku, is_active)
  VALUES (p_sku, TRUE)
  ON CONFLICT (sku)
  DO UPDATE SET
    is_active = TRUE
  RETURNING id INTO v_item_id;

  INSERT INTO item_category_memberships (item_id, category_id)
  VALUES (v_item_id, v_category_id)
  ON CONFLICT (item_id, category_id) DO NOTHING;

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

  INSERT INTO items (sku, is_active)
  VALUES (p_sku, TRUE)
  ON CONFLICT (sku)
  DO UPDATE SET
    is_active = TRUE
  RETURNING id INTO v_item_id;

  INSERT INTO item_category_memberships (item_id, category_id)
  VALUES (v_item_id, v_category_id)
  ON CONFLICT (item_id, category_id) DO NOTHING;

  RETURN v_item_id;
END$$;

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
      JOIN item_category_memberships icm
        ON icm.item_id = i.id
       AND icm.category_id = v_cat
      WHERE i.is_active = TRUE
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
        category_id,
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
        v_cat,
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
  IF NOT EXISTS (SELECT 1 FROM categories c WHERE c.id = p_category_id) THEN
    RAISE EXCEPTION 'Category % does not exist', p_category_id;
  END IF;

  INSERT INTO items (sku, is_active)
  VALUES (p_sku, p_is_active)
  RETURNING id INTO v_item_id;

  INSERT INTO item_category_memberships (item_id, category_id)
  VALUES (v_item_id, p_category_id);

  RETURN v_item_id;
END$$;

COMMIT;
