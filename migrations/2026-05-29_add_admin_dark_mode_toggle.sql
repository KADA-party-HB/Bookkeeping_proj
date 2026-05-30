ALTER TABLE delivery_pricing_settings
ADD COLUMN IF NOT EXISTS admin_dark_mode_enabled BOOLEAN NOT NULL DEFAULT FALSE;
