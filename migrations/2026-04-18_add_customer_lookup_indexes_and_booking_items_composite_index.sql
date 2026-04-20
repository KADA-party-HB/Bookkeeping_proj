BEGIN;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM customers
    WHERE email IS NOT NULL
    GROUP BY lower(email)
    HAVING COUNT(*) > 1
  ) THEN
    RAISE EXCEPTION
      'Cannot create customers_email_lower_uniq because duplicate customer emails exist ignoring case.';
  END IF;
END$$;

ALTER TABLE customers
  DROP CONSTRAINT IF EXISTS customers_email_key;

DROP INDEX IF EXISTS customers_email_lower_uniq;
CREATE UNIQUE INDEX customers_email_lower_uniq
  ON customers ((lower(email)))
  WHERE email IS NOT NULL;

DROP INDEX IF EXISTS customers_full_name_lower_idx;
CREATE INDEX customers_full_name_lower_idx
  ON customers ((lower(full_name)));

DROP INDEX IF EXISTS idx_booking_items_item_id;
DROP INDEX IF EXISTS idx_booking_items_item_booking;
CREATE INDEX idx_booking_items_item_booking
  ON booking_items(item_id, booking_id);

COMMIT;
