-- Makisushi DSS redesign schema additions.
-- Apply after backing up the production database and validating foreign-key names.

ALTER TABLE dim_ingredient
  ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(10,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS storage_zone VARCHAR(20) NOT NULL DEFAULT 'chiller',
  ADD COLUMN IF NOT EXISTS reorder_level NUMERIC(10,2),
  ADD COLUMN IF NOT EXISTS is_perishable BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS dim_storage_zone (
  storage_zone VARCHAR(20) PRIMARY KEY,
  capacity_kg NUMERIC(10,2) NOT NULL
);

INSERT INTO dim_storage_zone (storage_zone, capacity_kg)
VALUES ('chiller', 150), ('freezer', 500), ('dry', 1000)
ON CONFLICT (storage_zone) DO NOTHING;

CREATE TABLE IF NOT EXISTS bridge_bom (
  item_id INT REFERENCES dim_menu_item(item_id),
  ingredient_id INT REFERENCES dim_ingredient(ingredient_id),
  qty_per_serving NUMERIC(10,4) NOT NULL,
  PRIMARY KEY (item_id, ingredient_id)
);

-- Sales remain at menu-item grain. Ingredient consumption is derived through bridge_bom.
ALTER TABLE fact_sales DROP COLUMN IF EXISTS ingredient_id;

CREATE TABLE IF NOT EXISTS fact_inventory_batch (
  batch_id BIGSERIAL PRIMARY KEY,
  ingredient_id INT REFERENCES dim_ingredient(ingredient_id),
  supplier_id INT REFERENCES dim_supplier(supplier_id),
  received_date DATE NOT NULL,
  expiry_date DATE NOT NULL,
  qty_received NUMERIC(10,2) NOT NULL,
  qty_remaining NUMERIC(10,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_forecast (
  run_id INT,
  date_id INT REFERENCES dim_date(date_id),
  ingredient_id INT REFERENCES dim_ingredient(ingredient_id),
  model VARCHAR(30) NOT NULL,
  yhat NUMERIC(10,3),
  lo80 NUMERIC(10,3),
  hi80 NUMERIC(10,3),
  lo95 NUMERIC(10,3),
  hi95 NUMERIC(10,3),
  is_selected BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (run_id, date_id, ingredient_id, model)
);

CREATE TABLE IF NOT EXISTS fact_model_score (
  run_id INT,
  ingredient_id INT,
  model VARCHAR(30),
  wmape NUMERIC(6,3),
  mase NUMERIC(6,3),
  rmse NUMERIC(10,3),
  holdout_start DATE,
  holdout_end DATE,
  PRIMARY KEY (run_id, ingredient_id, model)
);

CREATE TABLE IF NOT EXISTS fact_purchase_plan (
  run_id INT,
  scenario VARCHAR(20),
  ingredient_id INT,
  supplier_id INT,
  order_qty NUMERIC(10,2),
  delivery_date DATE,
  order_by TIMESTAMP,
  line_cost NUMERIC(12,2),
  ordered BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS fact_recommendation (
  rec_id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMP NOT NULL,
  type VARCHAR(20) NOT NULL,
  ingredient_id INT REFERENCES dim_ingredient(ingredient_id),
  recommended_qty NUMERIC(10,2),
  peso_impact NUMERIC(12,2),
  status VARCHAR(12) NOT NULL CHECK (status IN ('open', 'applied', 'modified', 'dismissed')),
  decided_by VARCHAR(60),
  decided_at TIMESTAMP,
  reason TEXT,
  outcome_text TEXT,
  outcome_waste_kg NUMERIC(10,2)
);

CREATE TABLE IF NOT EXISTS fact_stockout_event (
  date_id INT,
  ingredient_id INT REFERENCES dim_ingredient(ingredient_id),
  service_period VARCHAR(10),
  note TEXT
);

CREATE TABLE IF NOT EXISTS etl_run (
  run_id SERIAL PRIMARY KEY,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  source_file TEXT,
  status VARCHAR(12) NOT NULL,
  rows_loaded INT
);
