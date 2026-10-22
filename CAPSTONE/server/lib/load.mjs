// Reads the warehouse (schema dw) and returns plain objects. No business rules live here; see analysis.mjs.
import { query, tableExists } from './db.mjs';
import { addDays } from './dates.mjs';

const BASELINE = { start: '2026-06-01', end: '2026-08-31' }; // pre-DSS reference period (manuscript 1.3)
export const BASELINE_PERIOD = BASELINE;

export const loadMeta = async () => {
  const [row] = await query(`select (select max(snapshot_date) from dw.fact_inventory_snapshot)::text as as_of,
                                    (select max(sale_date) from dw.fact_sales)::text as sales_as_of`);
  return { asOf: row.as_of, salesAsOf: row.sales_as_of };
};

export const loadIngredients = async () => {
  const rows = await query(`
    select i.ingredient_id as id, i.ingredient_code as code, i.ingredient_name as name, i.category, i.storage_type,
           i.base_uom, i.shelf_life_days, i.standard_unit_cost as unit_cost, i.litres_per_base_unit as litres,
           t.supplier_id, t.pack_size_base as pack, t.min_order_packs as min_packs,
           s.supplier_name, s.lead_time_days as lead, s.delivery_interval_days as interval_days
    from dw.dim_ingredient i
    left join dw.supplier_item_terms t on t.ingredient_id = i.ingredient_id
    left join dw.dim_supplier s on s.supplier_id = t.supplier_id
    where i.is_perishable
    order by i.ingredient_id`);
  return rows.map((r) => ({
    id: r.id, code: r.code, name: r.name, category: r.category, storage: r.storage_type, uom: r.base_uom,
    shelfLife: r.shelf_life_days, unitCost: r.unit_cost, litres: r.litres,
    supplierId: r.supplier_id, supplierName: r.supplier_name, lead: r.lead ?? 1, intervalDays: r.interval_days,
    pack: r.pack, minPacks: r.min_packs,
  }));
};

export const loadStorage = () => query(`select storage_type, capacity_qty_l as capacity, shared_pool_l as pool from dw.dim_storage`);

export const loadSnapshot = async (asOf) => {
  const stock = await query(`select ingredient_id as id, closing_qty as closing, reorder_point as rop, on_order_qty as on_order
                             from dw.fact_inventory_snapshot where snapshot_date = $1`, [asOf]);
  const batches = await query(`select batch_id as id, ingredient_id, received_date::text as received, expiry_date::text as expiry,
                                      qty_on_hand as qty, unit_cost
                               from dw.fact_inventory_batch_snapshot where snapshot_date = $1`, [asOf]);
  const open = await query(`select t.ingredient_id, t.txn_date::text as ordered, t.quantity as qty, coalesce(s.lead_time_days, 1) as lead
                            from dw.fact_inventory_transaction t
                            left join dw.supplier_item_terms sit on sit.ingredient_id = t.ingredient_id
                            left join dw.dim_supplier s on s.supplier_id = sit.supplier_id
                            where t.txn_type = 'PURCHASE_ORDER' and t.txn_date > $1::date - 14`, [asOf]);
  return { stock, batches, openOrders: open };
};

export const loadOffPosBaseline = async (asOf) => {
  const rows = await query(`select ingredient_id, sum(qty_off_pos_use) / 28.0 as per_day
                            from dw.fact_inventory_snapshot where snapshot_date > $1::date - 28 and snapshot_date <= $1
                            group by 1`, [asOf]);
  return new Map(rows.map((r) => [r.ingredient_id, r.per_day]));
};

export const loadForecastRuns = () => query(`
  select run_id, created_at::text as created_at, model_name, train_end_date::text as train_end, horizon_days, wmape, mase, is_selected
  from dw.forecast_run order by created_at desc, run_id desc`);

// Ingredient-level daily forecast of one run: dish forecast x bill of materials, perishable scope only.
export const loadIngredientForecast = (runIds) => query(`
  select f.run_id, b.ingredient_id, f.target_date::text as d, sum(f.forecast_qty * b.qty_base) as q,
         sum(f.lower_qty * b.qty_base) as lo, sum(f.upper_qty * b.qty_base) as hi
  from dw.fact_demand_forecast f
  join dw.bridge_recipe_bom b on b.item_id = f.item_id
  join dw.dim_ingredient i on i.ingredient_id = b.ingredient_id and i.is_perishable
  where f.run_id = any($1::bigint[]) group by 1, 2, 3`, [runIds]);

export const loadItemForecast = (runIds, fromDate, toDate) => query(`
  select f.item_id, f.target_date::text as d, f.forecast_qty as q
  from dw.fact_demand_forecast f where f.run_id = any($1::bigint[]) and f.target_date between $2 and $3`, [runIds, fromDate, toDate]);

export const loadItemPrices = async (asOf) => {
  const rows = await query(`select s.item_id, sum(s.net_sales) / nullif(sum(s.quantity_sold), 0) as price, sum(s.net_sales) as revenue
                            from dw.fact_sales s where s.is_revenue and s.sale_date > $1::date - 28 and s.sale_date <= $1 group by 1`, [asOf]);
  const list = await query(`select item_id, list_price from dw.dim_menu_item`);
  return { recent: new Map(rows.map((r) => [r.item_id, r])), list: new Map(list.map((r) => [r.item_id, r.list_price])) };
};

// Recipe-derived usage (paying sales x BOM) and the simulated off-POS use per ingredient and day.
export const loadActualUsage = (fromDate, toDate) => query(`
  select s.sale_date::text as d, b.ingredient_id, sum(s.quantity_sold * b.qty_base) as q
  from dw.fact_sales s
  join dw.bridge_recipe_bom b on b.item_id = s.item_id
  join dw.dim_ingredient i on i.ingredient_id = b.ingredient_id and i.is_perishable
  where s.is_revenue and s.sale_date between $1 and $2 group by 1, 2`, [fromDate, toDate]);

export const loadOffPosActual = (fromDate, toDate) => query(`
  select snapshot_date::text as d, ingredient_id, qty_off_pos_use as q
  from dw.fact_inventory_snapshot where snapshot_date between $1 and $2`, [fromDate, toDate]);

export const loadHolidays = (fromDate, toDate) => query(`
  select date::text as d from dw.dim_date where is_holiday and date between $1 and $2 order by 1`, [fromDate, toDate]);

export const loadBom = () => query(`
  select b.item_id, b.ingredient_id, b.qty_base
  from dw.bridge_recipe_bom b join dw.dim_ingredient i on i.ingredient_id = b.ingredient_id and i.is_perishable`);

export const loadTotalRecentRevenue = async (asOf) => {
  const [row] = await query(`select sum(net_sales) as revenue from dw.fact_sales where is_revenue and sale_date > $1::date - 28 and sale_date <= $1`, [asOf]);
  return row?.revenue ?? 0;
};

export const loadDishesByIngredient = (asOf) => query(`
  select b.ingredient_id, m.item_name as dish, sum(s.quantity_sold) as units
  from dw.bridge_recipe_bom b
  join dw.dim_menu_item m on m.item_id = b.item_id and m.is_active and not m.is_complimentary
  left join dw.fact_sales s on s.item_id = b.item_id and s.is_revenue and s.sale_date > $1::date - 28 and s.sale_date <= $1
  group by 1, 2 order by 1, 3 desc nulls last`, [asOf]);

// Evaluation runs: forecasts of the held-out window per ingredient and day, for the scored models.
export const loadEvaluationForecast = (runIds) => query(`
  select f.run_id, b.ingredient_id, f.target_date::text as d, sum(f.forecast_qty * b.qty_base) as q
  from dw.fact_demand_forecast f
  join dw.bridge_recipe_bom b on b.item_id = f.item_id
  join dw.dim_ingredient i on i.ingredient_id = b.ingredient_id and i.is_perishable
  where f.run_id = any($1::bigint[]) group by 1, 2, 3`, [runIds]);

export const loadDailyOps = (fromDate, toDate) => query(`
  with dates as (select date as d from dw.dim_date where date between $1 and $2),
  w as (select waste_date as d, sum(case when i.base_uom = 'g' then waste_qty / 1000.0 else 0 end) as kg, sum(waste_value_php) as v
        from dw.fact_waste fw join dw.dim_ingredient i using (ingredient_id) where waste_date between $1 and $2 group by 1),
  r as (select txn_date as d, sum(extended_cost) as v from dw.fact_inventory_transaction where txn_type = 'RECEIPT' and txn_date between $1 and $2 group by 1),
  c as (select txn_date as d, sum(extended_cost) as v from dw.fact_inventory_transaction where txn_type = 'CONSUMPTION' and txn_date between $1 and $2 group by 1),
  iv as (select snapshot_date as d, sum(closing_qty * i.standard_unit_cost) as v
         from dw.fact_inventory_snapshot s join dw.dim_ingredient i using (ingredient_id) where snapshot_date between $1 and $2 group by 1),
  so as (select event_date as d, count(*) as n from dw.fact_stockout_event where event_date between $1 and $2 group by 1)
  select dates.d::text as d, coalesce(w.kg, 0) as waste_kg, coalesce(w.v, 0) as waste_value, coalesce(r.v, 0) as received_value,
         coalesce(c.v, 0) as cogs, coalesce(iv.v, 0) as inv_value, coalesce(so.n, 0) as stockouts
  from dates left join w using (d) left join r using (d) left join c using (d) left join iv using (d) left join so using (d)
  order by dates.d`, [fromDate, toDate]);

export const loadDailySales = (fromDate, toDate) => query(`
  select sale_date::text as d, sum(net_sales) as revenue, sum(quantity_sold) as units, count(*) as lines
  from dw.fact_sales where is_revenue and sale_date between $1 and $2 group by 1 order by 1`, [fromDate, toDate]);

export const loadTopDishes = (day) => query(`
  select m.item_name as name, sum(s.quantity_sold) as qty, sum(s.net_sales) as revenue
  from dw.fact_sales s join dw.dim_menu_item m using (item_id)
  where s.sale_date = $1 and s.is_revenue group by 1 order by 3 desc limit 3`, [day]);

export const loadWasteByWeekday = (fromDate, toDate) => query(`
  select i.ingredient_id, i.ingredient_name as name, ((extract(isodow from w.waste_date))::int - 1) as dow, sum(w.waste_qty) / 1000.0 as kg
  from dw.fact_waste w join dw.dim_ingredient i using (ingredient_id)
  where i.base_uom = 'g' and w.waste_date between $1 and $2 group by 1, 2, 3`, [fromDate, toDate]);

export const loadPlans = async () => {
  const runs = await query(`
    select o.opt_run_id, o.forecast_run_id, o.created_at::text as created_at, o.plan_week_start::text as plan_week_start, o.horizon_weeks,
           o.scenario, o.budget_php, o.solver_status, o.objective_value
    from dw.optimization_run o order by o.created_at desc, o.opt_run_id desc`);
  return runs;
};

export const loadPlanRows = (optRunId) => query(`
  select ingredient_id, week_start::text as week_start, supplier_id, forecast_requirement as requirement, opening_position as opening,
         recommended_order_qty as qty, recommended_packs as packs, expected_cost_php as cost, expected_waste_qty as waste,
         expected_shortage_qty as shortage, binding_constraint as binding
  from dw.fact_replenishment_plan where opt_run_id = $1`, [optRunId]);

export const loadDecisionTables = async () => ({
  recommendations: await tableExists('dw.fact_recommendation'),
  planLines: await tableExists('dw.plan_line_status'),
  wasteLog: await tableExists('dw.manual_waste_log'),
});

export const loadRecommendations = () => query(`
  select r.rec_id, r.rec_key, r.created_at::text as created_at, r.type, r.title, r.ingredient_id, r.recommended_qty, r.peso_impact,
         r.status, r.decided_by, r.decided_at::text as decided_at, r.reason, r.outcome_text, r.outcome_waste_kg
  from dw.fact_recommendation r order by coalesce(r.decided_at, r.created_at) desc, r.rec_id desc`);

export const loadPlanLines = (optRunId) => query(`
  select ingredient_id, ordered, ordered_by, ordered_at::text as ordered_at
  from dw.plan_line_status where opt_run_id = $1`, [optRunId]);

export const dateWindow = (asOf, days) => ({ from: addDays(asOf, -days + 1), to: asOf });
