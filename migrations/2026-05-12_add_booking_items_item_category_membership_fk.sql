BEGIN;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM booking_items bi
    LEFT JOIN item_category_memberships icm
      ON icm.item_id = bi.item_id
     AND icm.category_id = bi.category_id
    WHERE icm.item_id IS NULL
  ) THEN
    RAISE EXCEPTION
      'Cannot add booking_items item/category membership FK because some booking_items rows reference invalid item/category pairs';
  END IF;
END$$;

ALTER TABLE booking_items
  DROP CONSTRAINT IF EXISTS booking_items_item_category_membership_fkey;

ALTER TABLE booking_items
  ADD CONSTRAINT booking_items_item_category_membership_fkey
  FOREIGN KEY (item_id, category_id)
  REFERENCES item_category_memberships(item_id, category_id)
  ON DELETE RESTRICT;

COMMIT;
