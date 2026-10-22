-- =====================================================================
-- Makisushi DSS - data marts for forecasting and optimization (schema mart)
-- ---------------------------------------------------------------------
-- Views only (no stored copies): they are always current, and a new mart is one more
-- "create or replace view" here, with no change to dw. Run after 01_schema.sql (the views read dw.*), at any time:
--     psql "<connection string>" -v ON_ERROR_STOP=1 -f supabase_final/04_marts.sql
-- Every view is security_invoker: it runs with the rights of whoever queries it, so it cannot open up dw.
-- Keep schema mart out of Settings > API > Exposed schemas unless row level security is set up on dw.
-- The forecast and optimizer source tables are empty until the Python engines write to them; the views then return no rows.
--
-- Forecast marts      mart.forecast_daily               the production forecast, by day and menu item
--                     mart.forecast_vs_actual           forecast against actual paying units, by day and item, with errors
--                     mart.forecast_vs_actual_weekly    the same by ISO week (Monday start, the optimiser's bucket)
--                     mart.forecast_model_scorecard     one row per forecast run: model, accuracy, rank
-- Optimization marts  mart.replenishment_plan           the recommended order per ingredient and week, with run settings
--                     mart.plan_vs_actual               recommended against ordered / received quantities
--                     mart.scenario_comparison          the optimisation scenarios side by side (cost, waste, shortage)
--                     mart.shortage_waste_summary       waste and stockouts per ingredient and month (history)
-- =====================================================================
create schema if not exists mart;

-- ------------------------------------------------------------- forecast
-- The production forecast = the latest run flagged is_selected (the champion), the same rule dw.v_lp_ingredient_week_input uses.
create or replace view mart.forecast_daily with (security_invoker = true) as
with champion as (
    select run_id from dw.forecast_run where is_selected order by created_at desc limit 1
)
select r.run_id, r.model_name, r.train_end_date,
       f.target_date, d.day_of_week, d.week_start_date, d.is_weekend, d.is_holiday, d.is_payday, d.is_open,
       f.item_id, m.item_name, c.category_name, c.category_group,
       f.forecast_qty, f.lower_qty, f.upper_qty
from dw.fact_demand_forecast f
join champion ch              on ch.run_id = f.run_id
join dw.forecast_run r        on r.run_id = f.run_id
join dw.dim_menu_item m       on m.item_id = f.item_id
join dw.dim_menu_category c   on c.category_id = m.category_id
join dw.dim_date d            on d.date = f.target_date;

-- Forecast against what was sold. Actual = paying units (is_revenue) per item and day; a day after the last sale date is not observed yet, so its actual and errors are null.
create or replace view mart.forecast_vs_actual with (security_invoker = true) as
with champion as (
    select run_id from dw.forecast_run where is_selected order by created_at desc limit 1
),
last_obs as (select max(sale_date) as last_day from dw.fact_sales),
act as (
    select sale_date, item_id, sum(quantity_sold) as actual_qty
    from dw.fact_sales where is_revenue group by 1, 2
)
select f.run_id, f.target_date, d.week_start_date, f.item_id, m.item_name, c.category_name,
       f.forecast_qty, f.lower_qty, f.upper_qty,
       (f.target_date <= lo.last_day)                                                   as is_observed,
       case when f.target_date <= lo.last_day then coalesce(a.actual_qty, 0) end        as actual_qty,
       case when f.target_date <= lo.last_day then f.forecast_qty - coalesce(a.actual_qty, 0) end      as error_qty,
       case when f.target_date <= lo.last_day then abs(f.forecast_qty - coalesce(a.actual_qty, 0)) end as abs_error_qty,
       case when f.target_date <= lo.last_day and a.actual_qty > 0
            then (f.forecast_qty - a.actual_qty) / a.actual_qty end                     as pct_error,
       case when f.target_date <= lo.last_day and f.lower_qty is not null and f.upper_qty is not null
            then coalesce(a.actual_qty, 0) between f.lower_qty and f.upper_qty end      as within_interval
from dw.fact_demand_forecast f
join champion ch            on ch.run_id = f.run_id
cross join last_obs lo
join dw.dim_menu_item m     on m.item_id = f.item_id
join dw.dim_menu_category c on c.category_id = m.category_id
join dw.dim_date d          on d.date = f.target_date
left join act a             on a.sale_date = f.target_date and a.item_id = f.item_id;

-- Weekly roll-up. A week counts as observed only when its Sunday is on or before the last sale date.
create or replace view mart.forecast_vs_actual_weekly with (security_invoker = true) as
with last_obs as (select max(sale_date) as last_day from dw.fact_sales)
select v.run_id, v.week_start_date, v.item_id, v.item_name, v.category_name,
       sum(v.forecast_qty)                                          as forecast_qty,
       (v.week_start_date + 6 <= max(lo.last_day))                  as is_observed,
       case when v.week_start_date + 6 <= max(lo.last_day) then sum(v.actual_qty) end                             as actual_qty,
       case when v.week_start_date + 6 <= max(lo.last_day) then sum(v.forecast_qty) - sum(v.actual_qty) end       as error_qty,
       case when v.week_start_date + 6 <= max(lo.last_day) then abs(sum(v.forecast_qty) - sum(v.actual_qty)) end  as abs_error_qty,
       count(*)                                                     as days_in_week
from mart.forecast_vs_actual v
cross join last_obs lo
group by v.run_id, v.week_start_date, v.item_id, v.item_name, v.category_name;

-- One row per forecast run (all runs, not only the champion): model, accuracy and size.
create or replace view mart.forecast_model_scorecard with (security_invoker = true) as
select r.run_id, r.model_name, r.created_at, r.train_end_date, r.horizon_days, r.wmape, r.mase, r.is_selected,
       rank() over (order by r.wmape nulls last)                                   as wmape_rank,
       (select count(*)                from dw.fact_demand_forecast f where f.run_id = r.run_id) as forecast_rows,
       (select count(distinct f.item_id) from dw.fact_demand_forecast f where f.run_id = r.run_id) as items_forecast
from dw.forecast_run r;

-- ------------------------------------------------------------- optimization
-- The recommended order per ingredient and planning week, with the settings of the run that produced it.
create or replace view mart.replenishment_plan with (security_invoker = true) as
select p.opt_run_id, o.scenario, o.forecast_run_id, o.created_at as run_created_at, o.plan_week_start, o.horizon_weeks,
       o.budget_php, o.waste_penalty, o.shortage_penalty, o.solver_status,
       p.week_start, p.ingredient_id, i.ingredient_code, i.ingredient_name, i.category, i.storage_type,
       p.supplier_id, s.supplier_name,
       p.forecast_requirement, p.opening_position, p.recommended_order_qty, p.recommended_packs,
       p.expected_cost_php, p.expected_waste_qty, p.expected_shortage_qty, p.binding_constraint
from dw.fact_replenishment_plan p
join dw.optimization_run o   on o.opt_run_id = p.opt_run_id
join dw.dim_ingredient i     on i.ingredient_id = p.ingredient_id
left join dw.dim_supplier s  on s.supplier_id = p.supplier_id;

-- Was the plan followed? Builds on dw.v_plan_vs_actual (ordered in the plan week, received in that week and the next; 25 % tolerance is a reporting choice).
create or replace view mart.plan_vs_actual with (security_invoker = true) as
select v.opt_run_id, o.scenario, v.week_start, v.ingredient_id, i.ingredient_code, i.ingredient_name,
       v.recommended_order_qty, v.ordered_qty, v.received_qty, v.order_gap_qty, v.order_ratio, v.followed_within_25pct
from dw.v_plan_vs_actual v
join dw.optimization_run o on o.opt_run_id = v.opt_run_id
join dw.dim_ingredient i   on i.ingredient_id = v.ingredient_id;

-- The scenarios (balanced, min_spoilage, min_cost, max_availability) side by side: one row per optimisation run.
create or replace view mart.scenario_comparison with (security_invoker = true) as
select o.opt_run_id, o.scenario, o.forecast_run_id, o.plan_week_start, o.horizon_weeks, o.budget_php,
       o.waste_penalty, o.shortage_penalty, o.solver_status, o.objective_value,
       count(distinct p.ingredient_id)              as ingredients_planned,
       coalesce(sum(p.recommended_order_qty), 0)    as total_order_qty,
       coalesce(sum(p.expected_cost_php), 0)        as total_expected_cost_php,
       coalesce(sum(p.expected_waste_qty), 0)       as total_expected_waste_qty,
       coalesce(sum(p.expected_shortage_qty), 0)    as total_expected_shortage_qty,
       round(100 * coalesce(sum(p.expected_cost_php), 0) / nullif(o.budget_php * o.horizon_weeks, 0), 1) as budget_used_pct
from dw.optimization_run o
left join dw.fact_replenishment_plan p on p.opt_run_id = o.opt_run_id
group by o.opt_run_id;

-- History of what went wrong per ingredient and month: waste (batches that expired) and stockouts (emergency purchases and lost sales).
create or replace view mart.shortage_waste_summary with (security_invoker = true) as
with w as (
    select date_trunc('month', waste_date)::date as month, ingredient_id,
           count(*) as waste_batches, sum(waste_qty) as waste_qty, sum(waste_value_php) as waste_value_php
    from dw.fact_waste group by 1, 2
), s as (
    select date_trunc('month', event_date)::date as month, ingredient_id,
           count(*) as stockout_events, count(*) filter (where outcome = 'LOST_SALES') as lost_sales_events,
           sum(unmet_qty) as unmet_qty, sum(emergency_cost_php) as emergency_cost_php, sum(shortage_cost_php) as shortage_cost_php
    from dw.fact_stockout_event group by 1, 2
)
select coalesce(w.month, s.month) as month, coalesce(w.ingredient_id, s.ingredient_id) as ingredient_id,
       i.ingredient_code, i.ingredient_name, i.category,
       coalesce(w.waste_batches, 0) as waste_batches, coalesce(w.waste_qty, 0) as waste_qty, coalesce(w.waste_value_php, 0) as waste_value_php,
       coalesce(s.stockout_events, 0) as stockout_events, coalesce(s.lost_sales_events, 0) as lost_sales_events,
       coalesce(s.unmet_qty, 0) as unmet_qty, coalesce(s.emergency_cost_php, 0) as emergency_cost_php, coalesce(s.shortage_cost_php, 0) as shortage_cost_php
from w
full join s on s.month = w.month and s.ingredient_id = w.ingredient_id
join dw.dim_ingredient i on i.ingredient_id = coalesce(w.ingredient_id, s.ingredient_id);
