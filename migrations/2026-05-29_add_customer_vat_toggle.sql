ALTER TABLE delivery_pricing_settings
ADD COLUMN IF NOT EXISTS customer_prices_include_vat BOOLEAN NOT NULL DEFAULT FALSE;
