ALTER TABLE delivery_pricing_settings
ADD COLUMN IF NOT EXISTS customer_furnishing_without_tent_surcharge_enabled BOOLEAN NOT NULL DEFAULT TRUE;
