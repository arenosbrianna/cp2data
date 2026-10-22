-- =====================================================================
-- Makisushi DSS - Fact Constellation Schema (Supabase / PostgreSQL 15+)
-- ---------------------------------------------------------------------
-- The dw tables below are exactly the project ERD, erd/makisushi_erd.png
-- (drawn by erd/build_erd.py): same tables, same columns, same order, same keys.
-- The staging tables (stg.*) are created and loaded by 02_load_staging.psql from
-- datasets/ (trimmed from generated_v4_pre_stg_trim/ by build_stg_extract.py), and
-- 03_transform.sql loads stg -> dw.
-- Changes from supabase_v3 (team decisions 2026-10-08): dim_supplier.service_area and
-- dim_date.is_open and dim_supplier.fill_rate removed; fact_sales.pos_category_raw replaced by category_group and fact_sales.is_complimentary by is_revenue; waste_reason 'EXPIRED_DURING_CLOSURE' renamed 'Expired during closure'.
--
-- v12 (2026-10-12): 15 columns plus dim_supplier.supplier_type, fact_waste.waste_reason and table fact_recommendation_outcome removed (constant, always NULL, or an exact copy of a value held elsewhere); see v12/COLUMN_AUDIT.md.
--
-- v12 step 4: dim_date.forecast_split removed; observed days are date <= the last fact_inventory_snapshot date, the train/test cut-off is forecast_run.train_end_date.
--
-- v12 step 8: waste_reason is back (fact_waste), values 'overstock' / 'expiry' only (rule in the column comment). v13: 'overstock' renamed 'over_ordering' (same rule, manuscript wording).
--
-- v12 step 5: dim_supplier.lead_time_sd_days, supplier_item_terms.order_unit / pack_size / pack_unit and fact_stockout_event.emergency_qty removed.
--
-- v5 (2026-10-10): ERD, this schema, 02_load_staging.psql and 03_transform.sql were brought in line (dish dimension, open-day calendar,
-- storage capacity, stockout events, kitchen variance; dim_dish and the lost-sales / off-POS facts were dropped and dw.v_dish replaces the dish table).
-- Run order (from the package folder): 01_schema.sql, 02_load_staging.psql, 03_transform.sql, then validation/post_load_validation.sql
-- The ERD (erd/makisushi_erd.png) and this file describe the same tables and columns (checked by v5/erd_vs_schema.py).
-- Expiry convention: the receipt date is usable day 1; expiry_date is the last
-- usable day = received_date + shelf_life_days - 1; nothing is used after it.
-- =====================================================================

create schema if not exists dw;

-- =====================================================================
-- CONFORMED DIMENSIONS
-- =====================================================================

create table if not exists dw.dim_date (
    date            date primary key,
    day_of_week     text not null,
    dow             smallint not null check (dow between 0 and 6),   -- 0 = Monday
    iso_week        smallint not null check (iso_week between 1 and 53),
    iso_year        smallint not null,             -- the year iso_week belongs to
    week_start_date date not null,                 -- Monday; LP planning bucket
    month           smallint not null check (month between 1 and 12),
    quarter         smallint not null check (quarter between 1 and 4),
    year            smallint not null,
    is_weekend      boolean not null,
    is_holiday      boolean not null,
    is_payday       boolean not null,
    is_ber_month    boolean not null,
    is_open         boolean not null,      -- false = closure (public holiday with no sale line); planned, not observed, after the last data day (2026-09-08; the calendar runs to the 2027-09-30 forecast horizon)
    check (week_start_date = date - dow),
    check (is_weekend = (dow >= 5))
);

create table if not exists dw.dim_storage (
    storage_type      text primary key check (storage_type in ('ambient', 'chilled', 'frozen')),
    capacity_qty_l    numeric not null,            -- LP storage constraint: dedicated litres (client storage_locations); the shared FR2 unit is in shared_pool_l
    shared_pool_l     numeric not null default 0   -- FR2 (chiller + freezer in one unit) can serve chilled OR frozen stock: share(chilled) + share(frozen) <= pool
);

create table if not exists dw.dim_menu_category (
    category_id     smallint generated always as identity primary key,
    category_name   text not null unique,
    category_group  text not null check (category_group in
                        ('FOOD', 'DRINK', 'ADD_ON', 'DELIVERY', 'COMP'))
);

create table if not exists dw.dim_menu_item (
    item_id               int primary key,
    item_name             text not null,           -- the menu name. Not unique: a dish sold as several listings (channel, staff, price) shares it; dw.v_dish groups by it
    category_id           smallint not null references dw.dim_menu_category,
    list_price            numeric(10,2) not null check (list_price >= 0),
    pos_sku               bigint,                  -- NOT unique in source
    is_complimentary      boolean not null,
    is_active             boolean not null          -- True for every item in the source
);

create table if not exists dw.dim_ingredient (
    ingredient_id       int primary key,
    ingredient_code     text not null unique,
    ingredient_name     text not null,
    category            text not null,
    storage_type        text not null references dw.dim_storage,
    base_uom            text not null check (base_uom in ('g', 'ml', 'pc', 'serving')),
    shelf_life_days     int not null check (shelf_life_days > 0),   -- usable days, receipt day = day 1
    is_perishable       boolean not null,   -- v14 (scope narrowed 2026-10-19 to 20 ingredients): TRUE = perishable raw material, in the inventory-management scope (stock, purchasing, expiry, stockouts, optimiser); FALSE = shelf-stable, kept for recipe costing only
    standard_unit_cost  numeric(12,4) not null check (standard_unit_cost >= 0),
    litres_per_base_unit numeric not null check (litres_per_base_unit > 0),  
    -- fresh short-life stock (5 days or less) is always perishable; scope 2026-10-19: 20 perishable raw materials (raw / frozen proteins and seafood, tofu, tamago and the fresh items that spoil within days),
    -- classification by physical form, storage and quality risk, see v14/ingredient_scope_register.csv. The old rule (7 days or less, or any dairy) is gone: bell pepper and cheese are no longer inventory-managed.
    check (is_perishable or shelf_life_days > 5)
);

-- supplies and on what terms (lead time, interval) is a modelling assumption. Only suppliers that sell an
-- ingredient in the master are loaded (7 of the sheet's 9).
create table if not exists dw.dim_supplier (
    supplier_id            int primary key,
    supplier_name          text not null unique,
    lead_time_days         numeric not null check (lead_time_days >= 1),   -- order -> receipt, calendar days (B5)
    delivery_interval_days int not null check (delivery_interval_days > 0)
);

-- =====================================================================
-- BRIDGES
-- =====================================================================

create table if not exists dw.bridge_recipe_bom (
    item_id          int  not null references dw.dim_menu_item,
    ingredient_id    int  not null references dw.dim_ingredient,
    qty_base         numeric not null check (qty_base > 0),     -- usable base units per serving (client MENU2 grams)
    primary key (item_id, ingredient_id)
);

create table if not exists dw.supplier_item_terms (
    supplier_id     int not null references dw.dim_supplier,
    ingredient_id   int not null references dw.dim_ingredient,
    pack_size_base  numeric not null check (pack_size_base > 0),   -- usable base units per pack (client pack, yield loss already inside)
    min_order_packs int not null check (min_order_packs >= 1),
    primary key (supplier_id, ingredient_id)
);
create unique index if not exists ux_one_supplier_per_ingredient
    on dw.supplier_item_terms (ingredient_id);

-- =====================================================================
-- FACTS
-- =====================================================================

-- Sales: transactional. Grain = one POS sale line (sale_id), every validated line: paying sales and
-- staff / complimentary lines (is_revenue = false). Its natural key sale date x item x POS SKU x category
-- group x channel is unique once double-logged copies are excluded; channel describes the line, it does not
-- identify it.
create table if not exists dw.fact_sales (
    sale_id           bigint primary key,
    sale_date         date not null references dw.dim_date,
    item_id           int not null references dw.dim_menu_item,
    channel           text not null check (channel in ('Dine-In', 'GrabFood')),
    quantity_sold     int not null check (quantity_sold > 0),
    unit_price        numeric(10,2) not null check (unit_price >= 0),
    gross_sales       numeric(12,2) not null check (gross_sales >= 0),
    discount          numeric(12,2) not null check (discount >= 0),
    net_sales         numeric(12,2) not null check (net_sales >= 0),
    is_revenue        boolean not null,      -- false = staff meal / complimentary line: consumes stock, earns nothing
    check (abs(net_sales - (gross_sales - discount)) <= 0.02),
    check (discount <= gross_sales)
);
create index if not exists ix_fact_sales_date_item on dw.fact_sales (sale_date, item_id);
create index if not exists ix_fact_sales_item_date on dw.fact_sales (item_id, sale_date);

-- Inventory PERIODIC SNAPSHOT, ingredient level. Grain = ingredient x day (end of day).
-- Flow identity: opening + received + emergency - consumed - wasted = closing.  qty_consumed already INCLUDES qty_off_pos_use and the
-- kitchen variance (prep waste / yield / portioning), which is not stored: it is qty_consumed - qty_off_pos_use - recipe use (dw.v_consumption_variance).
create table if not exists dw.fact_inventory_snapshot (
    snapshot_date        date not null references dw.dim_date,
    ingredient_id        int  not null references dw.dim_ingredient,
    supplier_id          int  not null references dw.dim_supplier,
    opening_qty          numeric not null check (opening_qty >= 0),
    qty_received         numeric not null check (qty_received >= 0),
    qty_emergency        numeric not null check (qty_emergency >= 0),
    qty_consumed         numeric not null check (qty_consumed >= 0),
    qty_off_pos_use      numeric not null check (qty_off_pos_use >= 0),       -- staff meals, bulk prep (inside qty_consumed)
    qty_wasted           numeric not null check (qty_wasted >= 0),            -- expired batches binned this day
    closing_qty          numeric not null check (closing_qty >= 0),
    order_qty            numeric not null check (order_qty >= 0),
    on_order_qty         numeric not null check (on_order_qty >= 0),
    reorder_point        numeric not null check (reorder_point >= 0),
    primary key (snapshot_date, ingredient_id),
    check (abs(opening_qty + qty_received + qty_emergency - qty_consumed - qty_wasted - closing_qty) <= 0.01)
);

-- Inventory PERIODIC SNAPSHOT, batch level. Grain = batch x day (end of day, qty > 0).
create table if not exists dw.fact_inventory_batch_snapshot (
    snapshot_date    date   not null references dw.dim_date,
    batch_id         bigint not null,
    ingredient_id    int    not null references dw.dim_ingredient,
    supplier_id      int    not null references dw.dim_supplier,
    received_date    date   not null,
    expiry_date      date   not null,              -- last usable day
    qty_on_hand      numeric not null check (qty_on_hand > 0),
    unit_cost        numeric(12,4) not null,
    primary key (snapshot_date, batch_id),
    check (expiry_date >= received_date),
    check (snapshot_date between received_date and expiry_date)
);
create index if not exists ix_batch_snap_ing on dw.fact_inventory_batch_snapshot (ingredient_id, snapshot_date);

-- Inventory TRANSACTIONS. Grain = one movement type of one ingredient on one day.
create table if not exists dw.fact_inventory_transaction (
    txn_id           bigint generated always as identity primary key,
    txn_date         date not null references dw.dim_date,
    ingredient_id    int not null references dw.dim_ingredient,
    supplier_id      int references dw.dim_supplier,
    txn_type         text not null check (txn_type in
                        ('PURCHASE_ORDER', 'RECEIPT', 'EMERGENCY_PURCHASE', 'CONSUMPTION')),
    quantity         numeric not null check (quantity > 0),
    stock_effect     numeric generated always as (
                        case txn_type when 'RECEIPT' then quantity
                                      when 'EMERGENCY_PURCHASE' then quantity
                                      when 'CONSUMPTION' then -quantity
                                      else 0 end) stored,
    unit_cost        numeric(12,4) not null,
    extended_cost    numeric(14,2) generated always as (round(quantity * unit_cost, 2)) stored,
    unique (txn_date, ingredient_id, txn_type)
);
create index if not exists ix_inv_txn_ing_date on dw.fact_inventory_transaction (ingredient_id, txn_date);

-- Waste: transactional, batch grain (one expired batch, binned whole).
create table if not exists dw.fact_waste (
    waste_id         bigint primary key,
    waste_date       date not null references dw.dim_date,
    ingredient_id    int not null references dw.dim_ingredient,
    supplier_id      int not null references dw.dim_supplier,
    batch_id         bigint not null,              -- no longer unique (2026-10-22): a batch can lose part of its stock inside the shelf life ('spoilage', 'shrinkage') and the rest at expiry
    waste_qty        numeric not null check (waste_qty > 0),
    waste_reason     text not null check (waste_reason in ('over_ordering', 'expiry', 'spoilage', 'shrinkage')),
    unit_cost        numeric(12,4) not null,
    waste_value_php  numeric(14,2) not null,
    received_date    date not null,
    expiry_date      date not null,                -- last usable day (shelf life; closures do not extend it)
    check (expiry_date >= received_date),
    check (case when waste_reason in ('spoilage', 'shrinkage') then waste_date between received_date and expiry_date   -- a loss inside the shelf life
               else waste_date > expiry_date end),                                                                   -- an expired batch leaves stock the day after expiry_date; disposal may be later when it expired during a closure
    check (abs(waste_value_php - round(waste_qty * unit_cost, 2)) <= 0.01)
);
create index if not exists ix_fact_waste_batch on dw.fact_waste (batch_id);
create index if not exists ix_fact_waste_ing_date on dw.fact_waste (ingredient_id, waste_date);
create index if not exists ix_fact_waste_date on dw.fact_waste (waste_date);

-- Stockouts made explicit (v5). One row per ingredient-day on which usable stock was short.
--   EMERGENCY_PURCHASE: the gap was bought the same day (emergency_cost_php includes the premium).
--   LOST_SALES: the gap could not be bought; the dishes that need it were not served and are absent from fact_sales.
-- Real-POS days are always EMERGENCY_PURCHASE (their sales are client data). shortage_cost_php = lost contribution margin + premium.
create table if not exists dw.fact_stockout_event (
    event_date         date not null references dw.dim_date,
    ingredient_id      int  not null references dw.dim_ingredient,
    need_qty           numeric not null,
    available_qty      numeric not null,
    outcome            text not null check (outcome in ('EMERGENCY_PURCHASE', 'LOST_SALES')),
    emergency_cost_php numeric(14,2) not null,
    unmet_qty          numeric not null,
    shortage_cost_php  numeric(14,2) not null,
    primary key (event_date, ingredient_id)
);

create table if not exists dw.forecast_run (
    run_id             bigint generated always as identity primary key,
    created_at         timestamptz not null default now(),
    model_name         text not null check (model_name in ('SES', 'SARIMA', 'HOLT_WINTERS', 'NAIVE', 'ML_REGRESSION', 'HOLT_LINEAR')),   -- v15: ML_REGRESSION and HOLT_LINEAR added (team decisions 2026-10-19; no column added)
    train_end_date     date not null references dw.dim_date,
    horizon_days       int not null check (horizon_days > 0),
    wmape              numeric,
    mase               numeric,
    is_selected        boolean not null default false
);

create table if not exists dw.fact_demand_forecast (
    run_id           bigint not null references dw.forecast_run on delete cascade,
    item_id          int    not null references dw.dim_menu_item,
    target_date      date   not null,
    forecast_qty     numeric not null check (forecast_qty >= 0),
    lower_qty        numeric,
    upper_qty        numeric,
    primary key (run_id, item_id, target_date)
);

create table if not exists dw.optimization_run (
    opt_run_id         bigint generated always as identity primary key,
    forecast_run_id    bigint not null references dw.forecast_run,
    created_at         timestamptz not null default now(),
    plan_week_start    date not null,
    horizon_weeks      int not null check (horizon_weeks > 0),
    scenario           text not null default 'balanced' check (scenario in
                           ('balanced', 'min_spoilage', 'min_cost', 'max_availability')),
    budget_php         numeric not null check (budget_php > 0),
    waste_penalty      numeric not null default 1.0,
    shortage_penalty   numeric not null default 1.25,
    solver_status      text,
    objective_value    numeric
);

create table if not exists dw.fact_replenishment_plan (
    opt_run_id              bigint not null references dw.optimization_run on delete cascade,
    ingredient_id           int    not null references dw.dim_ingredient,
    week_start              date   not null,
    supplier_id             int    references dw.dim_supplier,
    forecast_requirement    numeric not null,
    opening_position        numeric not null,
    recommended_order_qty   numeric not null check (recommended_order_qty >= 0),
    recommended_packs       int,
    expected_cost_php       numeric(14,2),
    expected_waste_qty      numeric,
    expected_shortage_qty   numeric,
    binding_constraint      text,
    primary key (opt_run_id, ingredient_id, week_start)
);

-- =====================================================================
-- VIEWS
-- =====================================================================

-- fact_sales -> bridge -> ingredient: theoretical usage from recorded sales, for the ingredients in the inventory scope only (dim_ingredient.is_perishable).
-- Full recipe costing for all ingredients is dw.v_menu_item_standard_cost, which does not filter.
create or replace view dw.v_theoretical_consumption as
select s.sale_date, b.ingredient_id,
       sum(s.quantity_sold * b.qty_base) as theoretical_qty
from dw.fact_sales s
join dw.bridge_recipe_bom b on b.item_id = s.item_id
join dw.dim_ingredient i on i.ingredient_id = b.ingredient_id and i.is_perishable
group by s.sale_date, b.ingredient_id;

-- Actual (inventory CONSUMPTION) vs theoretical usage from recorded sales.
-- The variance is dropped POS lines, off-POS use and kitchen variance; 03_transform.sql
-- bounds the implied kitchen variance (variance - dropped lines - off-POS use) per ingredient.
create or replace view dw.v_consumption_variance as
select coalesce(t.sale_date, c.txn_date)                          as usage_date,
       coalesce(t.ingredient_id, c.ingredient_id)                 as ingredient_id,
       coalesce(t.theoretical_qty, 0)                             as theoretical_qty,
       coalesce(c.quantity, 0)                                    as actual_qty,
       coalesce(c.quantity, 0) - coalesce(t.theoretical_qty, 0)   as variance_qty
from dw.v_theoretical_consumption t
full join (select txn_date, ingredient_id, quantity
           from dw.fact_inventory_transaction where txn_type = 'CONSUMPTION') c
       on c.txn_date = t.sale_date and c.ingredient_id = t.ingredient_id;

-- Full recipe cost: EVERY recipe ingredient, perishable or not (v14: the inventory scope does not change recipe costing).
create or replace view dw.v_menu_item_standard_cost as
select b.item_id,
       sum(b.qty_base * i.standard_unit_cost) as standard_cost_php,
       count(*) as ingredient_lines
from dw.bridge_recipe_bom b
join dw.dim_ingredient i using (ingredient_id)
group by b.item_id;

create or replace view dw.v_inventory_ledger_check as
select s.snapshot_date, s.ingredient_id, s.opening_qty,
       coalesce(t.received, 0)  as received,  coalesce(t.emergency, 0) as emergency,
       coalesce(t.consumed, 0)  as consumed,  coalesce(w.wasted, 0)    as wasted,
       s.closing_qty,
       s.opening_qty + coalesce(t.received, 0) + coalesce(t.emergency, 0)
         - coalesce(t.consumed, 0) - coalesce(w.wasted, 0) - s.closing_qty as imbalance
from dw.fact_inventory_snapshot s
left join (select txn_date, ingredient_id,
                  sum(quantity) filter (where txn_type = 'RECEIPT')            as received,
                  sum(quantity) filter (where txn_type = 'EMERGENCY_PURCHASE') as emergency,
                  sum(quantity) filter (where txn_type = 'CONSUMPTION')        as consumed
           from dw.fact_inventory_transaction group by 1, 2) t
       on t.txn_date = s.snapshot_date and t.ingredient_id = s.ingredient_id
left join (select case when waste_reason in ('spoilage', 'shrinkage') then waste_date else expiry_date + 1 end as expired_on_date,   -- expired stock leaves the day after the last usable day; a loss inside the shelf life leaves on its own day
                  ingredient_id, sum(waste_qty) as wasted
           from dw.fact_waste group by 1, 2) w
       on w.expired_on_date = s.snapshot_date and w.ingredient_id = s.ingredient_id;

-- Waste split by context: expiry while the restaurant was closed (unavoidable by
-- operations) vs waste during normal operations.
create or replace view dw.v_waste_by_context as
select case when waste_reason in ('spoilage', 'shrinkage') then 'lost inside the shelf life'
            when waste_date > expiry_date + 1 then 'expired during closure'   -- binned after the day following expiry_date = the restaurant was shut
            else 'operational' end              as waste_context,
       date_trunc('month', case when waste_reason in ('spoilage', 'shrinkage') then waste_date else expiry_date + 1 end)::date as month,
       ingredient_id,
       count(*)                                  as events,
       sum(waste_qty)                            as waste_qty,
       sum(waste_value_php)                      as waste_value_php
from dw.fact_waste
group by 1, 2, 3;

create or replace view dw.v_batch_snapshot_check as
select s.snapshot_date, s.ingredient_id, s.closing_qty,
       coalesce(b.batch_qty, 0) as batch_qty,
       s.closing_qty - coalesce(b.batch_qty, 0) as difference
from dw.fact_inventory_snapshot s
left join (select snapshot_date, ingredient_id, sum(qty_on_hand) as batch_qty
           from dw.fact_inventory_batch_snapshot group by 1, 2) b
       using (snapshot_date, ingredient_id);

-- B4: a batch on hand at the end of its last usable day must be binned whole
-- the next morning (nothing is consumed after expiry_date).
create or replace view dw.v_expired_batch_use_check as
select s.batch_id, s.ingredient_id, s.expiry_date, s.qty_on_hand as qty_on_last_usable_day,
       w.waste_qty,
       s.qty_on_hand - coalesce(w.waste_qty, 0) as used_after_expiry
from dw.fact_inventory_batch_snapshot s
left join dw.fact_waste w on w.batch_id = s.batch_id and w.waste_reason in ('over_ordering', 'expiry')      -- the expiry-day waste row; earlier partial losses are already out of qty_on_hand
where s.snapshot_date = s.expiry_date
  and s.snapshot_date < (select max(snapshot_date) from dw.fact_inventory_batch_snapshot);

create or replace view dw.v_near_expiry_promotion as
with latest as (select max(snapshot_date) as d from dw.fact_inventory_batch_snapshot)
select b.snapshot_date, (b.expiry_date - b.snapshot_date) as days_to_expiry, i.ingredient_code, i.ingredient_name,
       b.batch_id, b.qty_on_hand, i.base_uom,
       round(b.qty_on_hand * b.unit_cost, 2) as value_at_risk_php,   -- repeats per dish: do not sum
       m.item_id, m.item_name, bom.qty_base as qty_per_dish,
       floor(b.qty_on_hand / bom.qty_base) as dishes_to_clear_batch
from dw.fact_inventory_batch_snapshot b
join latest l on b.snapshot_date = l.d
join dw.dim_ingredient i using (ingredient_id)
join dw.bridge_recipe_bom bom on bom.ingredient_id = b.ingredient_id
join dw.dim_menu_item m on m.item_id = bom.item_id and m.is_active and not m.is_complimentary
where b.expiry_date - b.snapshot_date <= 2;

-- Expected shortage cost for the optimiser, PHP per unmet BASE UNIT (v8; source rows are never edited). The optimiser's shortage variable is a
-- projected shortfall in base units; part of every shortfall is cured by a same-day purchase, so
--     cost = (1 - rho_supplier) x lam_ingredient + rho_supplier x pi_ingredient
--   lam = lost contribution per base unit = sum over dishes (max(0, mean net price - recipe cost) x units sold) / sum (recipe base units x units sold)
--         (PHP per serving / base units per serving; a serving lacking any recipe ingredient cannot be sold; negative margins floored at 0)
--   rho = share of the supplier's shortage events that were cured by a same-day purchase;  pi = emergency premium paid per unit (measured, 0 if none)
--   v15 (option A, 2026-10-19): a supplier with fewer than 5 stockout events (or none) uses the all-supplier rho instead of its own, so one event cannot set a penalty to 0 (MY OWN had a single, cured, event)
-- An ingredient in no sold recipe takes the pooled median of lam / unit cost x its unit cost. Replaces the V6/V7 rule, which used the lost-sales
-- cost of the old ordering policy as if every shortfall were lost.
create or replace view dw.v_ingredient_shortage_penalty as
with price as (
    select item_id, sum(net_sales) / sum(quantity_sold) as price, sum(quantity_sold) as units
    from dw.fact_sales where is_revenue and quantity_sold > 0 group by item_id
), recipe as (
    select b.item_id, b.ingredient_id, b.qty_base as qty,
           sum(b.qty_base * i.standard_unit_cost) over (partition by b.item_id) as recipe_cost
    from dw.bridge_recipe_bom b join dw.dim_ingredient i using (ingredient_id)
), lam as (
    select r.ingredient_id, sum(greatest(p.price - r.recipe_cost, 0) * p.units) / nullif(sum(r.qty * p.units), 0) as lam
    from recipe r join price p using (item_id) group by r.ingredient_id
), rho_supplier as (
    select t.supplier_id, count(*) as n_events, avg((e.outcome = 'EMERGENCY_PURCHASE')::int) as rho
    from dw.fact_stockout_event e join dw.supplier_item_terms t on t.ingredient_id = e.ingredient_id group by t.supplier_id
), rho_pool as (
    select avg((outcome = 'EMERGENCY_PURCHASE')::int) as rho from dw.fact_stockout_event
), rho as (                                   -- v15 (team decision 2026-10-19, option A): a supplier with fewer than 5 recorded stockout events (or none) takes the all-supplier same-day-fix rate
    select s.supplier_id, case when r.n_events >= 5 then r.rho else p.rho end as rho
    from dw.dim_supplier s left join rho_supplier r on r.supplier_id = s.supplier_id cross join rho_pool p
), prem as (
    select e.ingredient_id, (sum(e.emergency_cost_php) - sum(s.qty_emergency * i.standard_unit_cost)) / nullif(sum(s.qty_emergency), 0) as pi   -- emergency quantity = the snapshot's qty_emergency that day
    from dw.fact_stockout_event e join dw.dim_ingredient i using (ingredient_id)
    join dw.fact_inventory_snapshot s on s.snapshot_date = e.event_date and s.ingredient_id = e.ingredient_id
    where e.outcome = 'EMERGENCY_PURCHASE' group by e.ingredient_id
), m as (
    select i.ingredient_id, i.ingredient_code, i.standard_unit_cost, l.lam, greatest(coalesce(p.pi, 0), 0) as pi, r.rho as rho
    from dw.dim_ingredient i left join lam l using (ingredient_id) left join prem p using (ingredient_id)   -- v14: lam uses the full recipe cost; rows only for the inventory scope
    left join dw.supplier_item_terms t on t.ingredient_id = i.ingredient_id left join rho r on r.supplier_id = t.supplier_id
    where i.is_perishable
), pool as (
    select percentile_cont(0.5) within group (order by lam / standard_unit_cost) as multiple from m where lam is not null
)
select m.ingredient_id, m.ingredient_code,
       (1 - m.rho) * coalesce(m.lam, pool.multiple * m.standard_unit_cost) + m.rho * m.pi as penalty_php_per_base_unit
from m cross join pool;

-- Optimiser input: one row per ingredient x planning week. forecast_requirement is forecast x BOM only (paying dishes); ground beef and tuna are mostly
-- used outside the BOM, so total_requirement adds the trailing-28-day off-POS baseline per week. 2026-10-22 (user): it also adds the trailing-28-day
-- recipe use of the staff / management / complimentary sale lines (is_revenue = false), which the paying-dish forecast does not contain (3.2 % of tracked demand,
-- up to 10 % for chicken thigh); staff_weekly_baseline is the last column so that an existing view can still be replaced.
create or replace view dw.v_lp_ingredient_week_input as
with champion as (                       -- the production forecast the optimiser plans on: normally the is_selected run (the champion). A SESSION may plan on another model's production run by
                                         -- setting makisushi.forecast_run_ids = '<run_id>[,<run_id>]' (engines/optimize_engine.py, --forecast-model); nothing is changed in the data.
    select run_id from dw.forecast_run
    where case when coalesce(current_setting('makisushi.forecast_run_ids', true), '') <> ''
               then run_id = any (string_to_array(current_setting('makisushi.forecast_run_ids', true), ',')::int[])
               else is_selected end
),
req as (                                 -- every in-scope (perishable) ingredient x every forecast week: an ingredient no forecast dish uses (ground beef: used mostly off the POS) still gets a row, with forecast_requirement 0 and the off-POS / staff baselines below
    select i0.ingredient_id, wk.week_start, coalesce(r.forecast_requirement, 0) as forecast_requirement, wk.forecast_days
    from (select date_trunc('week', f.target_date)::date as week_start,
                 count(distinct f.target_date) as forecast_days            -- days of this week the forecast covers (the first planning week starts after the last observed day)
          from dw.fact_demand_forecast f join champion c on c.run_id = f.run_id group by 1) wk
    cross join dw.dim_ingredient i0
    left join (select b.ingredient_id, date_trunc('week', f.target_date)::date as week_start, sum(f.forecast_qty * b.qty_base) as forecast_requirement
               from dw.fact_demand_forecast f
               join champion c            on c.run_id = f.run_id
               join dw.bridge_recipe_bom b on b.item_id = f.item_id
               group by 1, 2) r on r.ingredient_id = i0.ingredient_id and r.week_start = wk.week_start
    where i0.is_perishable                                                -- v14: optimiser input = inventory scope only
),
latest as (
    select distinct on (ingredient_id) ingredient_id, closing_qty, on_order_qty
    from dw.fact_inventory_snapshot
    order by ingredient_id, snapshot_date desc
),
off as (
    select ingredient_id, sum(qty_off_pos_use) / 28.0 * 7 as off_pos_weekly_baseline
    from dw.fact_inventory_snapshot
    where snapshot_date > (select max(snapshot_date) from dw.fact_inventory_snapshot) - 28
    group by ingredient_id
),
staff as (                               -- staff / management / complimentary lines: they use stock but are not customer demand, so the forecast (paying units only) leaves them out
    select b.ingredient_id, sum(s.quantity_sold * b.qty_base) / 28.0 * 7 as staff_weekly_baseline
    from dw.fact_sales s
    join dw.bridge_recipe_bom b on b.item_id = s.item_id
    where not s.is_revenue
      and s.sale_date > (select max(snapshot_date) from dw.fact_inventory_snapshot) - 28
    group by b.ingredient_id
)
select q.ingredient_id, i.ingredient_code, q.week_start, q.forecast_requirement,
       l.closing_qty  as on_hand_qty,
       l.on_order_qty,
       i.standard_unit_cost as unit_cost,
       sit.pack_size_base, sit.min_order_packs,
       sit.min_order_packs * sit.pack_size_base as moq_base,
       sup.lead_time_days, sup.delivery_interval_days,
       i.shelf_life_days, i.is_perishable, i.storage_type,
       st.capacity_qty_l as storage_capacity, sit.supplier_id,
       coalesce(o.off_pos_weekly_baseline, 0)                         as off_pos_weekly_baseline,
       q.forecast_requirement + (coalesce(o.off_pos_weekly_baseline, 0) + coalesce(sf.staff_weekly_baseline, 0)) * least(q.forecast_days, 7) / 7.0 as total_requirement,   -- off-POS and staff baselines pro rata for a partial first week
       i.litres_per_base_unit, st.shared_pool_l,
       pen.penalty_php_per_base_unit as shortage_penalty_php_per_unit,
       coalesce(sf.staff_weekly_baseline, 0)                          as staff_weekly_baseline
from req q
join dw.dim_ingredient i using (ingredient_id)
left join latest l using (ingredient_id)
left join off o using (ingredient_id)
left join staff sf on sf.ingredient_id = q.ingredient_id
left join dw.supplier_item_terms sit
       on sit.ingredient_id = q.ingredient_id
left join dw.dim_supplier sup on sup.supplier_id = sit.supplier_id
left join dw.dim_storage  st  on st.storage_type = i.storage_type
left join dw.v_ingredient_shortage_penalty pen on pen.ingredient_id = q.ingredient_id;

-- Storage: litres of the latest closing stock per storage type next to the dedicated capacity and the FR2 shared pool.
create or replace view dw.v_lp_storage_input as
select st.storage_type, st.capacity_qty_l as capacity_dedicated_l, st.shared_pool_l,
       (select sum(s.closing_qty * i.litres_per_base_unit)
          from dw.fact_inventory_snapshot s join dw.dim_ingredient i using (ingredient_id)
         where i.storage_type = st.storage_type
           and s.snapshot_date = (select max(snapshot_date) from dw.fact_inventory_snapshot)) as current_stock_l
from dw.dim_storage st;

-- What stockouts cost per month (emergency premium + lost contribution margin).
-- Recommendation tracking (manuscript 3.3, prescriptive analysis: "monitor whether prescribed actions were implemented"):
-- was each planned order followed? One row per plan row (ingredient x week); empty until the optimiser writes fact_replenishment_plan.
-- ordered_qty = purchase orders placed in the plan week (weeks start on Monday, as in v_lp_ingredient_week_input); received_qty = receipts in the plan week and the next week (lead time).
-- followed_within_25pct is a reporting tolerance, not a business rule. Same-day purchases are not part of a plan and are not counted. Quantities are in base units.
create or replace view dw.v_plan_vs_actual as
select p.opt_run_id, p.ingredient_id, p.week_start,
       p.recommended_order_qty,
       coalesce(o.ordered_qty, 0)  as ordered_qty,
       coalesce(r.received_qty, 0) as received_qty,
       coalesce(o.ordered_qty, 0) - p.recommended_order_qty as order_gap_qty,
       case when p.recommended_order_qty > 0 then coalesce(o.ordered_qty, 0) / p.recommended_order_qty end as order_ratio,
       abs(coalesce(o.ordered_qty, 0) - p.recommended_order_qty) <= 0.25 * p.recommended_order_qty as followed_within_25pct
from dw.fact_replenishment_plan p
left join lateral (select sum(t.quantity) as ordered_qty
                   from dw.fact_inventory_transaction t
                   where t.ingredient_id = p.ingredient_id and t.txn_type = 'PURCHASE_ORDER'
                     and t.txn_date >= p.week_start and t.txn_date < p.week_start + 7) o on true
left join lateral (select sum(t.quantity) as received_qty
                   from dw.fact_inventory_transaction t
                   where t.ingredient_id = p.ingredient_id and t.txn_type = 'RECEIPT'
                     and t.txn_date >= p.week_start and t.txn_date < p.week_start + 14) r on true;

create or replace view dw.v_shortage_cost_month as
select date_trunc('month', event_date)::date as month, count(*) as events,
       count(*) filter (where outcome = 'LOST_SALES') as lost_sales_count,
       sum(emergency_cost_php) as emergency_cost_php, sum(shortage_cost_php) as shortage_cost_php
from dw.fact_stockout_event group by 1;

-- Dish-level forecasting input: paying units per dish and day. Build the item-free grid from dim_date.is_open: a closed day or a
-- documented missing day is not zero demand.
-- Dish = the sellable product. A dish sold as several listings (GrabFood, staff, a second price) shares one menu name, so
-- dw.v_dish groups dim_menu_item by item_name. Forecast at this grain.
create or replace view dw.v_dish as
select m.item_name as dish_name, count(*) as n_items, min(m.item_id) as representative_item_id
from dw.dim_menu_item m
group by m.item_name;

create or replace view dw.v_dish_daily_sales as
select s.sale_date, m.item_name as dish_name, sum(s.quantity_sold) as units, sum(s.net_sales) as net_sales
from dw.fact_sales s join dw.dim_menu_item m using (item_id)
where s.is_revenue group by 1, 2;

create or replace view dw.v_dish_weekly_sales as
select d.week_start_date as week_start, v.dish_name, sum(v.units) as units, sum(v.net_sales) as net_sales,
       count(distinct v.sale_date) as selling_days
from dw.v_dish_daily_sales v join dw.dim_date d on d.date = v.sale_date
group by 1, 2;

