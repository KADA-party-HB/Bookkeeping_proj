CREATE TABLE IF NOT EXISTS delivery_pricing_settings (
  singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton = TRUE),
  base_fee NUMERIC(10,2) NOT NULL DEFAULT 449.00,
  included_distance_km NUMERIC(10,2) NOT NULL DEFAULT 10.00,
  extra_fee_per_km NUMERIC(10,2) NOT NULL DEFAULT 5.00,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_delivery_pricing_base_fee CHECK (base_fee >= 0),
  CONSTRAINT chk_delivery_pricing_included_distance CHECK (included_distance_km >= 0),
  CONSTRAINT chk_delivery_pricing_extra_fee CHECK (extra_fee_per_km >= 0)
);

INSERT INTO delivery_pricing_settings (
  singleton,
  base_fee,
  included_distance_km,
  extra_fee_per_km
)
VALUES (TRUE, 449.00, 10.00, 5.00)
ON CONFLICT (singleton) DO NOTHING;
