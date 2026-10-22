-- =====================================================================
-- Makisushi DSS - landing + staging layers (Supabase / PostgreSQL 15+)
-- ---------------------------------------------------------------------
-- GENERATED from UPDATED FILES/supabase_final/02_load_staging.psql and UPDATED FILES/datasets/*.csv (header check passed).
-- Not applied to any database yet: review first.
--
--   landing.*  the raw drop-off. Every CSV column is text, so an upload (dashboard import or \copy) never fails on a type.
--              _loaded_at / _source_file record when and from which upload a row arrived.
--   stg.*      the same tables, typed exactly as 02_load_staging.psql types them (03_transform.sql reads these).
--   stg.promote_from_landing()  casts landing -> stg in one transaction (empty string -> NULL), then fills the derived
--              columns 02_load_staging.psql fills (inventory.supplier_id; waste supplier / cost / dates).
--
-- Order:  00_landing_and_staging.sql  ->  01_schema.sql  ->  upload the 14 CSVs into landing.*  ->
--         select stg.promote_from_landing();  ->  03_transform.sql  ->  04_marts.sql
-- Do not run 02_load_staging.psql after this file: it drops and recreates stg.* from the CSVs directly (the psql-only route).
-- landing, stg and mart are not exposed through the Supabase API; keep them out of Settings > API > Exposed schemas.
-- =====================================================================
create schema if not exists landing;
create schema if not exists stg;
create schema if not exists mart;

create table if not exists landing.calendar_ext (
    date text,
    day_of_week text,
    dow text,
    iso_week text,
    iso_year text,
    week_start_date text,
    month text,
    quarter text,
    year text,
    is_weekend text,
    is_holiday text,
    is_payday text,
    is_ber_month text,
    is_open text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.storage_capacity (
    storage_type text,
    capacity_dedicated_l text,
    shared_pool_l text,
    locations text,
    capacity_total_if_pool_taken_l text,
    rule text,
    provenance text,
    baseline_stock_p95_l text,
    baseline_stock_max_l text,
    baseline_days_above_dedicated text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.ingredient_volume (
    ingredient_id text,
    ingredient_code text,
    storage_type text,
    base_uom text,
    litres_per_base_unit text,
    provenance text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.menu_items (
    item_id text,
    item_name text,
    category text,
    list_price text,
    pos_sku text,
    is_complimentary text,
    is_active text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.ingredients (
    ingredient_id text,
    ingredient_code text,
    ingredient_name text,
    category text,
    storage_type text,
    base_uom text,
    shelf_life_days text,
    is_perishable text,
    standard_unit_cost text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.suppliers (
    supplier_id text,
    supplier_name text,
    lead_time_days text,
    lead_time_sd_days text,
    delivery_interval_days text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.supplier_item_terms (
    supplier_id text,
    ingredient_id text,
    order_unit text,
    pack_size text,
    pack_unit text,
    pack_size_base text,
    min_order_packs text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.recipes (
    item_id text,
    ingredient_id text,
    qty_base text,
    uom text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.sales (
    sale_id text,
    sale_date text,
    item_id text,
    channel text,
    quantity_sold text,
    unit_price text,
    gross_sales text,
    discount text,
    net_sales text,
    is_revenue text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.sales_dropped (
    sale_date text,
    item_id text,
    quantity_sold text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.inventory (
    snapshot_date text,
    ingredient_id text,
    opening_qty text,
    qty_received text,
    qty_emergency text,
    qty_consumed text,
    qty_off_pos_use text,
    closing_qty text,
    reorder_point text,
    order_qty text,
    on_order_qty text,
    stockout_flag text,
    emergency_cost_php text,
    qty_unmet text,
    shortage_cost_php text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.inventory_batches (
    snapshot_date text,
    batch_id text,
    ingredient_id text,
    supplier_id text,
    received_date text,
    expiry_date text,
    qty_on_hand text,
    unit_cost text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.waste (
    waste_id text,
    waste_date text,
    ingredient_id text,
    batch_id text,
    waste_qty text,
    waste_reason text,
    waste_value_php text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

create table if not exists landing.stockout_events (
    event_date text,
    ingredient_id text,
    need_qty text,
    available_qty text,
    shortfall_qty text,
    outcome text,
    emergency_qty text,
    emergency_cost_php text,
    unmet_qty text,
    shortage_cost_php text,
    _loaded_at timestamptz not null default now(),
    _source_file text
);

-- ---------------------------------------------------------------- typed staging
create table if not exists stg.calendar_ext (
    date date,
    day_of_week text,
    dow smallint,
    iso_week smallint,
    iso_year smallint,
    week_start_date date,
    month smallint,
    quarter smallint,
    year smallint,
    is_weekend boolean,
    is_holiday boolean,
    is_payday boolean,
    is_ber_month boolean,
    is_open boolean
);

create table if not exists stg.storage_capacity (
    storage_type text,
    capacity_dedicated_l numeric,
    shared_pool_l numeric,
    locations text,
    capacity_total_if_pool_taken_l numeric,
    rule text,
    provenance text,
    baseline_stock_p95_l numeric,
    baseline_stock_max_l numeric,
    baseline_days_above_dedicated int
);

create table if not exists stg.ingredient_volume (
    ingredient_id int,
    ingredient_code text,
    storage_type text,
    base_uom text,
    litres_per_base_unit numeric,
    provenance text
);

create table if not exists stg.menu_items (
    item_id int,
    item_name text,
    category text,
    list_price numeric(10,2),
    pos_sku bigint,
    is_complimentary boolean,
    is_active boolean
);

create table if not exists stg.ingredients (
    ingredient_id int,
    ingredient_code text,
    ingredient_name text,
    category text,
    storage_type text,
    base_uom text,
    shelf_life_days int,
    is_perishable boolean,
    standard_unit_cost numeric(12,4)
);

create table if not exists stg.suppliers (
    supplier_id int,
    supplier_name text,
    lead_time_days numeric,
    lead_time_sd_days numeric,
    delivery_interval_days int
);

create table if not exists stg.supplier_item_terms (
    supplier_id int,
    ingredient_id int,
    order_unit text,
    pack_size numeric,
    pack_unit text,
    pack_size_base numeric,
    min_order_packs int
);

create table if not exists stg.recipes (
    item_id int,
    ingredient_id int,
    qty_base numeric,
    uom text
);

create table if not exists stg.sales (
    sale_id bigint,
    sale_date date,
    item_id int,
    channel text,
    quantity_sold int,
    unit_price numeric(10,2),
    gross_sales numeric(12,2),
    discount numeric(12,2),
    net_sales numeric(12,2),
    is_revenue boolean
);

create table if not exists stg.sales_dropped (
    sale_date date,
    item_id int,
    quantity_sold int
);

create table if not exists stg.inventory (
    snapshot_date date,
    ingredient_id int,
    opening_qty numeric,
    qty_received numeric,
    qty_emergency numeric,
    qty_consumed numeric,
    qty_off_pos_use numeric,
    closing_qty numeric,
    reorder_point numeric,
    order_qty numeric,
    on_order_qty numeric,
    stockout_flag boolean,
    emergency_cost_php numeric(14,2),
    qty_unmet numeric,
    shortage_cost_php numeric(14,2),
    supplier_id int
);

create table if not exists stg.inventory_batches (
    snapshot_date date,
    batch_id bigint,
    ingredient_id int,
    supplier_id int,
    received_date date,
    expiry_date date,
    qty_on_hand numeric,
    unit_cost numeric(12,4)
);

create table if not exists stg.waste (
    waste_id bigint,
    waste_date date,
    ingredient_id int,
    batch_id bigint,
    waste_qty numeric,
    waste_reason text,
    waste_value_php numeric(14,2),
    supplier_id int,
    unit_cost numeric(12,4),
    received_date date,
    expiry_date date,
    expired_on_date date
);

create table if not exists stg.stockout_events (
    event_date date,
    ingredient_id int,
    need_qty numeric,
    available_qty numeric,
    shortfall_qty numeric,
    outcome text,
    emergency_qty numeric,
    emergency_cost_php numeric(14,2),
    unmet_qty numeric,
    shortage_cost_php numeric(14,2)
);

-- ---------------------------------------------------------------- landing -> staging
create or replace function stg.promote_from_landing() returns text
language plpgsql as $fn$
declare n bigint; msg text := '';
begin
    truncate stg.calendar_ext, stg.storage_capacity, stg.ingredient_volume, stg.menu_items, stg.ingredients, stg.suppliers, stg.supplier_item_terms, stg.recipes, stg.sales, stg.sales_dropped, stg.inventory, stg.inventory_batches, stg.waste, stg.stockout_events;

    insert into stg.calendar_ext (date, day_of_week, dow, iso_week, iso_year, week_start_date, month, quarter, year, is_weekend, is_holiday, is_payday, is_ber_month, is_open)
    select nullif(btrim(date), '')::date, nullif(btrim(day_of_week), ''), nullif(btrim(dow), '')::smallint, nullif(btrim(iso_week), '')::smallint, nullif(btrim(iso_year), '')::smallint, nullif(btrim(week_start_date), '')::date, nullif(btrim(month), '')::smallint, nullif(btrim(quarter), '')::smallint, nullif(btrim(year), '')::smallint, nullif(btrim(is_weekend), '')::boolean, nullif(btrim(is_holiday), '')::boolean, nullif(btrim(is_payday), '')::boolean, nullif(btrim(is_ber_month), '')::boolean, nullif(btrim(is_open), '')::boolean
    from landing.calendar_ext;
    get diagnostics n = row_count; msg := msg || 'calendar_ext=' || n || ' ';

    insert into stg.storage_capacity (storage_type, capacity_dedicated_l, shared_pool_l, locations, capacity_total_if_pool_taken_l, rule, provenance, baseline_stock_p95_l, baseline_stock_max_l, baseline_days_above_dedicated)
    select nullif(btrim(storage_type), ''), nullif(btrim(capacity_dedicated_l), '')::numeric, nullif(btrim(shared_pool_l), '')::numeric, nullif(btrim(locations), ''), nullif(btrim(capacity_total_if_pool_taken_l), '')::numeric, nullif(btrim(rule), ''), nullif(btrim(provenance), ''), nullif(btrim(baseline_stock_p95_l), '')::numeric, nullif(btrim(baseline_stock_max_l), '')::numeric, nullif(btrim(baseline_days_above_dedicated), '')::int
    from landing.storage_capacity;
    get diagnostics n = row_count; msg := msg || 'storage_capacity=' || n || ' ';

    insert into stg.ingredient_volume (ingredient_id, ingredient_code, storage_type, base_uom, litres_per_base_unit, provenance)
    select nullif(btrim(ingredient_id), '')::int, nullif(btrim(ingredient_code), ''), nullif(btrim(storage_type), ''), nullif(btrim(base_uom), ''), nullif(btrim(litres_per_base_unit), '')::numeric, nullif(btrim(provenance), '')
    from landing.ingredient_volume;
    get diagnostics n = row_count; msg := msg || 'ingredient_volume=' || n || ' ';

    insert into stg.menu_items (item_id, item_name, category, list_price, pos_sku, is_complimentary, is_active)
    select nullif(btrim(item_id), '')::int, nullif(btrim(item_name), ''), nullif(btrim(category), ''), nullif(btrim(list_price), '')::numeric(10,2), nullif(btrim(pos_sku), '')::bigint, nullif(btrim(is_complimentary), '')::boolean, nullif(btrim(is_active), '')::boolean
    from landing.menu_items;
    get diagnostics n = row_count; msg := msg || 'menu_items=' || n || ' ';

    insert into stg.ingredients (ingredient_id, ingredient_code, ingredient_name, category, storage_type, base_uom, shelf_life_days, is_perishable, standard_unit_cost)
    select nullif(btrim(ingredient_id), '')::int, nullif(btrim(ingredient_code), ''), nullif(btrim(ingredient_name), ''), nullif(btrim(category), ''), nullif(btrim(storage_type), ''), nullif(btrim(base_uom), ''), nullif(btrim(shelf_life_days), '')::int, nullif(btrim(is_perishable), '')::boolean, nullif(btrim(standard_unit_cost), '')::numeric(12,4)
    from landing.ingredients;
    get diagnostics n = row_count; msg := msg || 'ingredients=' || n || ' ';

    insert into stg.suppliers (supplier_id, supplier_name, lead_time_days, lead_time_sd_days, delivery_interval_days)
    select nullif(btrim(supplier_id), '')::int, nullif(btrim(supplier_name), ''), nullif(btrim(lead_time_days), '')::numeric, nullif(btrim(lead_time_sd_days), '')::numeric, nullif(btrim(delivery_interval_days), '')::int
    from landing.suppliers;
    get diagnostics n = row_count; msg := msg || 'suppliers=' || n || ' ';

    insert into stg.supplier_item_terms (supplier_id, ingredient_id, order_unit, pack_size, pack_unit, pack_size_base, min_order_packs)
    select nullif(btrim(supplier_id), '')::int, nullif(btrim(ingredient_id), '')::int, nullif(btrim(order_unit), ''), nullif(btrim(pack_size), '')::numeric, nullif(btrim(pack_unit), ''), nullif(btrim(pack_size_base), '')::numeric, nullif(btrim(min_order_packs), '')::int
    from landing.supplier_item_terms;
    get diagnostics n = row_count; msg := msg || 'supplier_item_terms=' || n || ' ';

    insert into stg.recipes (item_id, ingredient_id, qty_base, uom)
    select nullif(btrim(item_id), '')::int, nullif(btrim(ingredient_id), '')::int, nullif(btrim(qty_base), '')::numeric, nullif(btrim(uom), '')
    from landing.recipes;
    get diagnostics n = row_count; msg := msg || 'recipes=' || n || ' ';

    insert into stg.sales (sale_id, sale_date, item_id, channel, quantity_sold, unit_price, gross_sales, discount, net_sales, is_revenue)
    select nullif(btrim(sale_id), '')::bigint, nullif(btrim(sale_date), '')::date, nullif(btrim(item_id), '')::int, nullif(btrim(channel), ''), nullif(btrim(quantity_sold), '')::int, nullif(btrim(unit_price), '')::numeric(10,2), nullif(btrim(gross_sales), '')::numeric(12,2), nullif(btrim(discount), '')::numeric(12,2), nullif(btrim(net_sales), '')::numeric(12,2), nullif(btrim(is_revenue), '')::boolean
    from landing.sales;
    get diagnostics n = row_count; msg := msg || 'sales=' || n || ' ';

    insert into stg.sales_dropped (sale_date, item_id, quantity_sold)
    select nullif(btrim(sale_date), '')::date, nullif(btrim(item_id), '')::int, nullif(btrim(quantity_sold), '')::int
    from landing.sales_dropped;
    get diagnostics n = row_count; msg := msg || 'sales_dropped=' || n || ' ';

    insert into stg.inventory (snapshot_date, ingredient_id, opening_qty, qty_received, qty_emergency, qty_consumed, qty_off_pos_use, closing_qty, reorder_point, order_qty, on_order_qty, stockout_flag, emergency_cost_php, qty_unmet, shortage_cost_php)
    select nullif(btrim(snapshot_date), '')::date, nullif(btrim(ingredient_id), '')::int, nullif(btrim(opening_qty), '')::numeric, nullif(btrim(qty_received), '')::numeric, nullif(btrim(qty_emergency), '')::numeric, nullif(btrim(qty_consumed), '')::numeric, nullif(btrim(qty_off_pos_use), '')::numeric, nullif(btrim(closing_qty), '')::numeric, nullif(btrim(reorder_point), '')::numeric, nullif(btrim(order_qty), '')::numeric, nullif(btrim(on_order_qty), '')::numeric, nullif(btrim(stockout_flag), '')::boolean, nullif(btrim(emergency_cost_php), '')::numeric(14,2), nullif(btrim(qty_unmet), '')::numeric, nullif(btrim(shortage_cost_php), '')::numeric(14,2)
    from landing.inventory;
    get diagnostics n = row_count; msg := msg || 'inventory=' || n || ' ';

    insert into stg.inventory_batches (snapshot_date, batch_id, ingredient_id, supplier_id, received_date, expiry_date, qty_on_hand, unit_cost)
    select nullif(btrim(snapshot_date), '')::date, nullif(btrim(batch_id), '')::bigint, nullif(btrim(ingredient_id), '')::int, nullif(btrim(supplier_id), '')::int, nullif(btrim(received_date), '')::date, nullif(btrim(expiry_date), '')::date, nullif(btrim(qty_on_hand), '')::numeric, nullif(btrim(unit_cost), '')::numeric(12,4)
    from landing.inventory_batches;
    get diagnostics n = row_count; msg := msg || 'inventory_batches=' || n || ' ';

    insert into stg.waste (waste_id, waste_date, ingredient_id, batch_id, waste_qty, waste_reason, waste_value_php)
    select nullif(btrim(waste_id), '')::bigint, nullif(btrim(waste_date), '')::date, nullif(btrim(ingredient_id), '')::int, nullif(btrim(batch_id), '')::bigint, nullif(btrim(waste_qty), '')::numeric, nullif(btrim(waste_reason), ''), nullif(btrim(waste_value_php), '')::numeric(14,2)
    from landing.waste;
    get diagnostics n = row_count; msg := msg || 'waste=' || n || ' ';

    insert into stg.stockout_events (event_date, ingredient_id, need_qty, available_qty, shortfall_qty, outcome, emergency_qty, emergency_cost_php, unmet_qty, shortage_cost_php)
    select nullif(btrim(event_date), '')::date, nullif(btrim(ingredient_id), '')::int, nullif(btrim(need_qty), '')::numeric, nullif(btrim(available_qty), '')::numeric, nullif(btrim(shortfall_qty), '')::numeric, nullif(btrim(outcome), ''), nullif(btrim(emergency_qty), '')::numeric, nullif(btrim(emergency_cost_php), '')::numeric(14,2), nullif(btrim(unmet_qty), '')::numeric, nullif(btrim(shortage_cost_php), '')::numeric(14,2)
    from landing.stockout_events;
    get diagnostics n = row_count; msg := msg || 'stockout_events=' || n || ' ';

    -- derived columns (same rules as 02_load_staging.psql)
    update stg.inventory i set supplier_id = t.supplier_id
      from stg.supplier_item_terms t where t.ingredient_id = i.ingredient_id;
    update stg.waste w set supplier_id = b.supplier_id, unit_cost = b.unit_cost,
                           received_date = b.received_date, expiry_date = b.expiry_date
      from (select distinct batch_id, supplier_id, unit_cost, received_date, expiry_date from stg.inventory_batches) b
     where b.batch_id = w.batch_id;
    update stg.waste set expired_on_date = case when waste_reason in ('spoilage', 'shrinkage') then waste_date else expiry_date + 1 end;      -- the ledger day: expired stock leaves the day after the last usable day, a loss inside the shelf life on its own day

    return 'staged: ' || msg;
end
$fn$;
