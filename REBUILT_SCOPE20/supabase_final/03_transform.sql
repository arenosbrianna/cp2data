begin;

do $$
begin
    if coalesce(current_setting('makisushi.allow_reset', true), 'off') <> 'on'
       and (exists (select 1 from dw.forecast_run) or exists (select 1 from dw.optimization_run)) then
        raise exception 'dw.forecast_run / dw.optimization_run already hold results; re-running 03_transform.sql would delete them. If that is intended: set makisushi.allow_reset = ''on''; and run it again.';
    end if;
end $$;

truncate dw.fact_replenishment_plan, dw.optimization_run, dw.fact_demand_forecast,
         dw.forecast_run, dw.fact_waste, dw.fact_inventory_transaction,
         dw.fact_inventory_batch_snapshot, dw.fact_inventory_snapshot, dw.fact_sales,
         dw.fact_stockout_event,
         dw.supplier_item_terms, dw.bridge_recipe_bom, dw.dim_menu_item,
         dw.dim_menu_category, dw.dim_ingredient,
         dw.dim_supplier, dw.dim_storage, dw.dim_date
         restart identity cascade;

-- ---------------------------------------------------------------- dim_date
insert into dw.dim_date (date, day_of_week, dow, iso_week, iso_year, week_start_date, month, quarter,
                         year, is_weekend, is_holiday, is_payday, is_ber_month,
                         is_open)
select e.date, e.day_of_week, e.dow, e.iso_week, e.iso_year, e.week_start_date, e.month, e.quarter,
       e.year, e.is_weekend, e.is_holiday, e.is_payday, e.is_ber_month,
       e.is_open
from stg.calendar_ext e;      -- history plus the forecast horizon to 2027-09-30 

-- ---------------------------------------------------------------- dim_storage
-- One row per storage type. capacity_qty = dedicated litres of the client's storage units (storage_locations.csv, units that count toward raw
-- ingredient capacity); shared_pool_l = the FR2 unit (chiller + freezer) that can serve chilled OR frozen stock.
-- Fridge 1 holds drinks and does not count toward ingredient capacity.
insert into dw.dim_storage (storage_type, capacity_qty_l, shared_pool_l)
select c.storage_type, c.capacity_dedicated_l, c.shared_pool_l
from stg.storage_capacity c;

-- ---------------------------------------------------------------- categories
-- Title-case, spelled exactly as menu_items.csv spells them (team decision 2026-10-10), so the item join below is an
-- exact match on the name Stardeals and Value Meals are ordinary menu categories and sell as normal food (v12: no PROMO group).
insert into dw.dim_menu_category (category_name, category_group) values
    ('All Time Favorites', 'FOOD'),   ('Baked Sushi', 'FOOD'),
    ('Baked Sushi Pie', 'FOOD'),      ('Don Buri (Beef)', 'FOOD'),
    ('Don Buri (Chicken)', 'FOOD'),   ('Don Buri (Pork)', 'FOOD'),
    ('Don Buri (Seafood)', 'FOOD'),   ('House Specialty', 'FOOD'),
    ('Maki Rolls', 'FOOD'),           ('Mix & Match', 'FOOD'),
    ('Platters', 'FOOD'),             ('Ramen Bowls', 'FOOD'),
    ('Salad', 'FOOD'),                ('Sashimi', 'FOOD'),
    ('Snack Meals', 'FOOD'),          ('Starters', 'FOOD'),
    ('Sushi Burrito', 'FOOD'),        ('Tempura Meals', 'FOOD'),
    ('Desserts', 'FOOD'),
    ('Drinks & Shakes', 'DRINK'),
    ('Other / Add-ons', 'ADD_ON'),
    ('Stardeals', 'FOOD'),           ('Value Meals', 'FOOD'),
    ('GrabFood', 'DELIVERY'),
    ('Management', 'COMP');

-- ---------------------------------------------------------------- dim_menu_item
-- item_name is the menu name. It is NOT unique: a dish sold as several listings shares it; dw.v_dish groups by it.
insert into dw.dim_menu_item (item_id, item_name, category_id, list_price,
                              pos_sku, is_complimentary,
                              is_active)
select m.item_id,
       m.item_name,
       c.category_id, m.list_price,
       nullif(m.pos_sku, 0), m.is_complimentary, m.is_active
from stg.menu_items m
join dw.dim_menu_category c on c.category_name = m.category;

-- ---------------------------------------------------------------- dim_ingredient
insert into dw.dim_ingredient (ingredient_id, ingredient_code, ingredient_name, category, storage_type,
                               base_uom, shelf_life_days, is_perishable, standard_unit_cost, litres_per_base_unit)
select i.ingredient_id, i.ingredient_code, i.ingredient_name, i.category, i.storage_type,
       i.base_uom, i.shelf_life_days, i.is_perishable, i.standard_unit_cost, v.litres_per_base_unit
from stg.ingredients i join stg.ingredient_volume v using (ingredient_id);

-- lead_time_days: datasets gives HI-TOP 0 (walk-in; an evening run is on the shelf the
-- next morning). The ledger receives every HI-TOP order the next day, which is
-- 1 day in this schema's order -> receipt convention (B5), so 0 loads as 1.
insert into dw.dim_supplier (supplier_id, supplier_name, lead_time_days,
                             delivery_interval_days)
select supplier_id, trim(supplier_name),
       greatest(lead_time_days, 1), delivery_interval_days
from stg.suppliers;

-- ---------------------------------------------------------------- bridges
-- Recipe grams are usable grams (stock is held in usable units): no yield factor
insert into dw.bridge_recipe_bom (item_id, ingredient_id, qty_base)
select item_id, ingredient_id, qty_base
from stg.recipes;

insert into dw.supplier_item_terms (supplier_id, ingredient_id, pack_size_base, min_order_packs)
select supplier_id, ingredient_id, pack_size_base, min_order_packs
from stg.supplier_item_terms;

-- ---------------------------------------------------------------- fact_sales
-- Category and POS SKU are properties of the menu item (dw.dim_menu_item); the fact carries item_id only.
insert into dw.fact_sales (sale_id, sale_date, item_id, channel,
                           quantity_sold, unit_price, gross_sales, discount, net_sales,
                           is_revenue)
select s.sale_id, s.sale_date, s.item_id, s.channel,
       s.quantity_sold, s.unit_price, s.gross_sales, s.discount, s.net_sales,
       s.is_revenue
from stg.sales s
order by s.sale_id;

-- ---------------------------------------------------------------- inventory snapshots
-- Stockout cost, unmet quantity and the stockout flag are not repeated here: dw.fact_stockout_event holds them (one row per short ingredient-day).
-- Inventory value = closing_qty x dim_ingredient.standard_unit_cost (not stored).
insert into dw.fact_inventory_snapshot (snapshot_date, ingredient_id, supplier_id, opening_qty, qty_received, qty_emergency, qty_consumed,
                                        qty_off_pos_use, qty_wasted, closing_qty, order_qty, on_order_qty, reorder_point)
select v.snapshot_date, v.ingredient_id, v.supplier_id, v.opening_qty, v.qty_received, v.qty_emergency, v.qty_consumed,
       v.qty_off_pos_use,
       coalesce(w.wasted, 0),                       -- waste leaves stock the day after the last usable day (expiry_date + 1), as v_inventory_ledger_check
       v.closing_qty, v.order_qty, v.on_order_qty, v.reorder_point
from stg.inventory v
left join (select expired_on_date, ingredient_id, sum(waste_qty) as wasted from stg.waste group by 1, 2) w
       on w.expired_on_date = v.snapshot_date and w.ingredient_id = v.ingredient_id;

insert into dw.fact_inventory_batch_snapshot (snapshot_date, batch_id, ingredient_id, supplier_id,
                                              received_date, expiry_date, qty_on_hand, unit_cost)
select snapshot_date, batch_id, ingredient_id, supplier_id, received_date,
       expiry_date, qty_on_hand, unit_cost
from stg.inventory_batches;

-- ---------------------------------------------------------------- inventory transactions
insert into dw.fact_inventory_transaction
       (txn_date, ingredient_id, supplier_id, txn_type, quantity, unit_cost)
select v.snapshot_date, v.ingredient_id, x.supplier_id, x.txn_type, x.qty, x.unit_cost
from stg.inventory v
join dw.dim_ingredient i using (ingredient_id)
cross join lateral (values
    ('PURCHASE_ORDER',     v.order_qty,     v.supplier_id, i.standard_unit_cost),
    ('RECEIPT',            v.qty_received,  v.supplier_id, i.standard_unit_cost),
    ('EMERGENCY_PURCHASE', v.qty_emergency, null::int,
        coalesce(nullif(round(v.emergency_cost_php / nullif(v.qty_emergency, 0), 4), 0), i.standard_unit_cost)),   -- a few-milligram buy rounds to 0.00 php: use the standard cost
    ('CONSUMPTION',        v.qty_consumed,  null::int,     i.standard_unit_cost)
) x(txn_type, qty, supplier_id, unit_cost)
where x.qty > 0
order by v.snapshot_date, v.ingredient_id,           -- fixed order: txn_id (identity) is the same on every run
         case x.txn_type when 'PURCHASE_ORDER' then 1 when 'RECEIPT' then 2 when 'EMERGENCY_PURCHASE' then 3 else 4 end;

-- ---------------------------------------------------------------- fact_waste
insert into dw.fact_waste (waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,
                           waste_reason, unit_cost, waste_value_php, received_date, expiry_date)
select waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,
       waste_reason, unit_cost, waste_value_php, received_date, expiry_date
from stg.waste;

-- ---------------------------------------------------------------- stockouts and off-POS events
insert into dw.fact_stockout_event (event_date, ingredient_id, need_qty, available_qty, outcome,
                                     emergency_cost_php, unmet_qty, shortage_cost_php)
select event_date, ingredient_id, need_qty, available_qty, outcome,
       emergency_cost_php, unmet_qty, shortage_cost_php
from stg.stockout_events;

-- ---------------------------------------------------------------- 
do $$
declare n_stg int; n_dw int; worst numeric;
begin
    select count(*) into n_stg from stg.menu_items;
    select count(*) into n_dw  from dw.dim_menu_item;
    if n_stg <> n_dw then
        raise exception 'dim_menu_item: % of % rows loaded - unmapped category label', n_dw, n_stg;
    end if;

    select count(*) into n_stg from stg.inventory;
    select count(*) into n_dw  from dw.fact_inventory_snapshot;
    if n_stg <> n_dw then
        raise exception 'fact_inventory_snapshot: % of % rows loaded', n_dw, n_stg;
    end if;

    -- every staged sale line lands in the fact exactly once, money intact
    select count(*) into n_stg from stg.sales;
    select count(*) into n_dw  from dw.fact_sales;
    if n_stg <> n_dw then
        raise exception 'fact_sales: % of % sale lines loaded', n_dw, n_stg;
    end if;
    if (select sum(net_sales) from stg.sales) <> (select sum(net_sales) from dw.fact_sales) then
        raise exception 'fact_sales: net sales do not equal the staged total';
    end if;

    select count(*) into n_dw from stg.recipes r join stg.ingredients i using (ingredient_id)
    where r.uom <> i.base_uom;
    if n_dw > 0 then
        raise exception 'recipes: % lines state a unit different from the ingredient master', n_dw;
    end if;

    select count(*) into n_dw from stg.inventory v
    left join dw.supplier_item_terms t
           on t.ingredient_id = v.ingredient_id and t.supplier_id = v.supplier_id
    where t.ingredient_id is null;
    if n_dw > 0 then
        raise exception 'inventory: % rows name a supplier other than the ingredient''s primary supplier', n_dw;
    end if;

    -- scope: only perishable raw materials may have stock, batches, waste, shortage events or transactions (20 ingredients since 2026-10-19; the flag comes from datasets/ingredients.csv, not from this file)
    select count(*) into n_dw from (select ingredient_id from stg.inventory union all select ingredient_id from stg.inventory_batches union all select ingredient_id from stg.waste
                                    union all select ingredient_id from stg.stockout_events) x
    join stg.ingredients i using (ingredient_id) where not i.is_perishable;
    if n_dw > 0 then
        raise exception 'inventory scope: % inventory, batch, waste or shortage rows belong to ingredients outside the perishable scope', n_dw;
    end if;

    select max(abs(imbalance)) into worst from dw.v_inventory_ledger_check;
    if worst > 0.01 then
        raise exception 'inventory ledger does not reconcile: max imbalance %', worst;
    end if;

    select max(abs(difference)) into worst from dw.v_batch_snapshot_check;
    if worst > 0.01 then
        raise exception 'batch stock does not add up to closing stock: max difference %', worst;
    end if;

    -- consumption = recorded sales x recipes
    --             + lines rejected before the load (stg.sales_dropped: stock was used, line not loaded)
    --             + use outside the POS (staff meals, tuna bulk prep: stg.inventory.qty_off_pos_use)
    -- The remainder is bounded per ingredient: 0 to 10 % of recipe use (measured 2.0 - 6.4 %, 3.0 % overall).
    select count(*) into n_dw
    from (select v.ingredient_id,
                 sum(v.variance_qty - coalesce(u.unrecorded_qty, 0) - coalesce(o.qty_off_pos_use, 0)) as implied_variance,
                 sum(v.theoretical_qty) as theo
          from dw.v_consumption_variance v
          left join (select a.sale_date, b.ingredient_id,
                            sum(a.quantity_sold * b.qty_base) as unrecorded_qty
                     from (select sale_date, item_id, quantity_sold from stg.sales_dropped) a
                     join dw.bridge_recipe_bom b on b.item_id = a.item_id
                     group by 1, 2) u
                 on u.sale_date = v.usage_date and u.ingredient_id = v.ingredient_id
          left join stg.inventory o
                 on o.snapshot_date = v.usage_date and o.ingredient_id = v.ingredient_id
          group by v.ingredient_id) r
    where r.theo > 0 and (r.implied_variance < -0.001 * r.theo or r.implied_variance > 0.10 * r.theo);
    if n_dw > 0 then
        raise exception 'consumption: % ingredients have unexplained use outside 0 - 10 percent of sales x recipes', n_dw;
    end if;

    -- B4: nothing is used after its last usable day
    select max(abs(used_after_expiry)) into worst from dw.v_expired_batch_use_check;
    if worst > 0.01 then
        raise exception 'a batch was used after its expiry date: max % used', worst;
    end if;

    -- B4: the receipt date is usable day 1. 2026-10-22: the shelf life of a batch varies by one day around the nominal one (freshness at delivery), so the last usable day is
    -- received_date + shelf_life_days - 1, give or take one day, and never before the receipt date.
    select count(*) into n_dw
    from (select distinct batch_id, ingredient_id, received_date, expiry_date
          from dw.fact_inventory_batch_snapshot) b
    join dw.dim_ingredient i using (ingredient_id)
    where abs(b.expiry_date - (b.received_date + (i.shelf_life_days - 1))) > 1 or b.expiry_date < b.received_date;
    if n_dw > 0 then
        raise exception '% batches do not expire within one day of received_date + shelf_life_days - 1', n_dw;
    end if;

    -- B5: no supplier delivers on the day the order is placed
    select count(*) into n_dw from dw.dim_supplier where lead_time_days < 1;
    if n_dw > 0 then
        raise exception '% suppliers have a lead time below 1 day', n_dw;
    end if;

    raise notice 'load OK - ledger, batch stock, expiry rule and sales-to-consumption all reconcile';
end $$;

-- ---------------------------------------------------------------- (stockouts, calendar, storage)
do $$
declare n_a bigint; n_b bigint;
begin
    select count(*) into n_a from dw.fact_stockout_event; select count(*) into n_b from stg.stockout_events;
    if n_a <> n_b then raise exception 'fact_stockout_event: % of % rows', n_a, n_b; end if;
    -- the staged inventory file's stockout columns (not loaded to the snapshot) agree with the events that are loaded:
    -- unmet quantity only where a LOST_SALES event says so; stockout_flag = a stockout event exists; cost, unmet and emergency quantity match
    select count(*) into n_a from stg.inventory f
      where f.qty_unmet > 0 and not exists (select 1 from dw.fact_stockout_event e where e.event_date = f.snapshot_date and e.ingredient_id = f.ingredient_id and e.outcome = 'LOST_SALES');
    if n_a > 0 then raise exception '% ingredient-days have unmet quantity without a LOST_SALES event', n_a; end if;
    select count(*) into n_a from stg.inventory s left join stg.stockout_events e on e.event_date = s.snapshot_date and e.ingredient_id = s.ingredient_id
      where s.stockout_flag <> (e.event_date is not null)
         or s.emergency_cost_php <> coalesce(e.emergency_cost_php, 0) or s.qty_unmet <> coalesce(e.unmet_qty, 0)
         or s.shortage_cost_php <> coalesce(e.shortage_cost_php, 0) or s.qty_emergency <> coalesce(e.emergency_qty, 0);
    if n_a > 0 then raise exception 'stg.inventory stockout columns disagree with fact_stockout_event on % rows', n_a; end if;
    -- pack checks on the staged client pack description (moved here from validation SUP04 / SUP06 when pack_size and pack_unit left dw)
    select count(*) into n_a from stg.supplier_item_terms t join dw.dim_ingredient i using (ingredient_id) where t.pack_unit = i.base_uom and t.pack_size_base > t.pack_size + 0.0001;
    if n_a > 0 then raise exception '% packs yield more usable base units than the pack holds', n_a; end if;
    select count(*) into n_a from stg.supplier_item_terms t where t.pack_unit in ('kg', 'l', 'L') and (t.pack_size_base <= 0 or t.pack_size_base > 1200 * t.pack_size + 0.0001 or (t.pack_unit = 'kg' and t.pack_size_base > 1000 * t.pack_size + 0.0001));
    if n_a > 0 then raise exception '% kg / L packs have an impossible base-unit size', n_a; end if;
    select count(*) into n_a from dw.dim_date d where d.date <= (select max(snapshot_date) from dw.fact_inventory_snapshot) and d.is_open and not exists (select 1 from dw.fact_sales s where s.sale_date = d.date);
    if n_a <> 2 then raise exception '% open observed days have no sale line', n_a; end if;
    select count(*) into n_a from dw.dim_date d where not d.is_open and exists (select 1 from dw.fact_sales s where s.sale_date = d.date);
    if n_a > 0 then raise exception '% closed days carry sales', n_a; end if;
    if exists (select 1 from dw.dim_storage where capacity_qty_l <= 0) then raise exception 'dim_storage capacity missing'; end if;
    raise notice 'v5 checks OK - stockouts, calendar and storage';
end $$;

commit;
