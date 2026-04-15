BEGIN;

ALTER TABLE bookings
  ADD COLUMN IF NOT EXISTS address TEXT,
  ADD COLUMN IF NOT EXISTS postal_city TEXT;

CREATE OR REPLACE FUNCTION create_booking_with_allocations(
  p_customer_id INT,
  p_start DATE,
  p_end DATE,
  p_category_ids INT[],
  p_qtys INT[],
  p_include_delivery BOOLEAN DEFAULT FALSE,
  p_delivery_fee NUMERIC(10,2) DEFAULT NULL,
  p_address TEXT DEFAULT NULL,
  p_postal_city TEXT DEFAULT NULL,
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
    address,
    postal_city,
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
    p_address,
    p_postal_city,
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
    ), ins AS (
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

COMMIT;
