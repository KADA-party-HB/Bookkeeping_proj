ALTER TABLE bookings
  ADD COLUMN IF NOT EXISTS customer_prices_include_vat BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS no_tent_furnishing_surcharge_applied BOOLEAN NOT NULL DEFAULT FALSE;
