"""v12: remove dw columns that are constant, always NULL, or an exact copy of a value held elsewhere. No column is added.
Run from the package folder:  py v12/apply_slim.py      (one-shot; asserts every anchor exists, so a second run stops)
Evidence for each drop: v12/COLUMN_AUDIT.md and v12/dup_checks.txt (0 mismatches on the loaded v11 data)."""
import re


def load(p):
    return open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


def save(p, t):
    open(p, 'w', encoding='utf-8', newline='').write(t.replace('\n', '\r\n'))


def rep(t, a, b):
    assert a in t, a[:100]
    return t.replace(a, b, 1)


# ===================================================================== 01_schema.sql
p = 'supabase_final/01_schema.sql'
t = load(p)

# bridge_recipe_bom: one recipe version, grams are usable grams -> no validity window, no yield factor
t = rep(t, """    item_id          int  not null references dw.dim_menu_item,
    ingredient_id    int  not null references dw.dim_ingredient,
    valid_from       date not null default date '2021-01-01',
    valid_to         date,
    qty_base         numeric not null check (qty_base > 0),
    yield_factor     numeric not null default 1.0 check (yield_factor > 0 and yield_factor <= 1),
    primary key (item_id, ingredient_id, valid_from),
    check (valid_to is null or valid_to > valid_from)
);""", """    item_id          int  not null references dw.dim_menu_item,
    ingredient_id    int  not null references dw.dim_ingredient,
    qty_base         numeric not null check (qty_base > 0),     -- usable base units per serving (client MENU2 grams)
    primary key (item_id, ingredient_id)
);""")

# supplier_item_terms: exactly one supplier per ingredient
t = rep(t, "    is_primary      boolean not null default true,\n", "")
t = rep(t, """create unique index if not exists ux_one_primary_supplier
    on dw.supplier_item_terms (ingredient_id) where is_primary;""",
        """create unique index if not exists ux_one_supplier_per_ingredient
    on dw.supplier_item_terms (ingredient_id);""")

# fact_sales: category and pos_sku are properties of the menu item
t = rep(t, "    pos_sku           bigint,\n    category          text not null,         -- canonical menu category name of the item (= dim_menu_category.category_name via item_id)\n", "")
t = rep(t, "-- group x channel is unique once", "-- group x channel is unique once")  # anchor check only

# fact_inventory_snapshot: stockout cost / unmet / flag live in fact_stockout_event; closing value = closing_qty x standard_unit_cost
t = rep(t, """    stockout_flag        boolean not null,                                    -- a row exists in fact_stockout_event (cured or lost sales)
    emergency_cost_php   numeric(14,2) not null check (emergency_cost_php >= 0),
    qty_unmet            numeric not null check (qty_unmet >= 0),             -- need that could not be met: sales lost (synthetic years)
    shortage_cost_php    numeric(14,2) not null,                              -- lost contribution margin + emergency premium
    closing_value        numeric(14,2) not null,
""", "")
t = rep(t, "    reorder_point        numeric not null check (reorder_point >= 0),\n    primary key (snapshot_date, ingredient_id),",
        "    reorder_point        numeric not null check (reorder_point >= 0),\n    primary key (snapshot_date, ingredient_id),")

# batch snapshot: days_to_expiry = expiry_date - snapshot_date
t = rep(t, "    unit_cost        numeric(12,4) not null,\n    days_to_expiry   int    not null,              -- 0 = last usable day\n", "    unit_cost        numeric(12,4) not null,\n")
t = rep(t, "    check (snapshot_date between received_date and expiry_date),\n    check (days_to_expiry = expiry_date - snapshot_date)\n", "    check (snapshot_date between received_date and expiry_date)\n")

# fact_waste: expired_on_date = expiry_date + 1, days_held = waste_date - received_date
t = rep(t, """    expired_on_date  date not null,                -- day the batch became unusable and left usable stock
    days_held        int not null check (days_held >= 0),
""", "")
t = rep(t, """    check (expired_on_date = expiry_date + 1),
    check (waste_date >= expired_on_date),         -- disposal may be later when it expired during a closure
    check (waste_date > expiry_date),
    check (days_held = waste_date - received_date),
""", """    check (waste_date > expiry_date),              -- the batch leaves stock the day after expiry_date; disposal may be later when it expired during a closure
""")

# fact_stockout_event: shortfall = need - available
t = rep(t, "    shortfall_qty      numeric not null,\n", "")

# views --------------------------------------------------------------------------------------------
t = rep(t, """       sum(s.quantity_sold * b.qty_base / b.yield_factor) as theoretical_qty
from dw.fact_sales s
join dw.bridge_recipe_bom b on b.item_id = s.item_id
                           and s.sale_date >= b.valid_from
                           and (b.valid_to is null or s.sale_date < b.valid_to)
group by""", """       sum(s.quantity_sold * b.qty_base) as theoretical_qty
from dw.fact_sales s
join dw.bridge_recipe_bom b on b.item_id = s.item_id
group by""")
t = rep(t, """       sum(b.qty_base / b.yield_factor * i.standard_unit_cost) as standard_cost_php,
       count(*) as ingredient_lines
from dw.bridge_recipe_bom b
join dw.dim_ingredient i using (ingredient_id)
where b.valid_to is null
group by""", """       sum(b.qty_base * i.standard_unit_cost) as standard_cost_php,
       count(*) as ingredient_lines
from dw.bridge_recipe_bom b
join dw.dim_ingredient i using (ingredient_id)
group by""")
t = rep(t, """left join (select expired_on_date, ingredient_id, sum(waste_qty) as wasted   -- stock leaves on the expiry day
           from dw.fact_waste group by 1, 2) w
       on w.expired_on_date = s.snapshot_date""", """left join (select expiry_date + 1 as expired_on_date, ingredient_id, sum(waste_qty) as wasted   -- stock leaves the day after the last usable day
           from dw.fact_waste group by 1, 2) w
       on w.expired_on_date = s.snapshot_date""")
t = rep(t, "       date_trunc('month', expired_on_date)::date as month,", "       date_trunc('month', expiry_date + 1)::date as month,")
t = rep(t, "select b.snapshot_date, b.days_to_expiry, i.ingredient_code,", "select b.snapshot_date, (b.expiry_date - b.snapshot_date) as days_to_expiry, i.ingredient_code,")
t = rep(t, "join dw.bridge_recipe_bom bom on bom.ingredient_id = b.ingredient_id and bom.valid_to is null\n", "join dw.bridge_recipe_bom bom on bom.ingredient_id = b.ingredient_id\n")
t = rep(t, "where b.days_to_expiry <= 2;", "where b.expiry_date - b.snapshot_date <= 2;")
# shortage penalty view
t = rep(t, """    select b.item_id, b.ingredient_id, b.qty_base / b.yield_factor as qty,
           sum(b.qty_base / b.yield_factor * i.standard_unit_cost) over (partition by b.item_id) as recipe_cost
    from dw.bridge_recipe_bom b join dw.dim_ingredient i using (ingredient_id) where b.valid_to is null""",
        """    select b.item_id, b.ingredient_id, b.qty_base as qty,
           sum(b.qty_base * i.standard_unit_cost) over (partition by b.item_id) as recipe_cost
    from dw.bridge_recipe_bom b join dw.dim_ingredient i using (ingredient_id)""")
t = rep(t, "join dw.supplier_item_terms t on t.ingredient_id = e.ingredient_id and t.is_primary group by t.supplier_id",
        "join dw.supplier_item_terms t on t.ingredient_id = e.ingredient_id group by t.supplier_id")
t = rep(t, "left join dw.supplier_item_terms t on t.ingredient_id = i.ingredient_id and t.is_primary left join rho r",
        "left join dw.supplier_item_terms t on t.ingredient_id = i.ingredient_id left join rho r")
# LP input view
t = rep(t, """           sum(f.forecast_qty * b.qty_base / b.yield_factor) as forecast_requirement
    from dw.fact_demand_forecast f
    join champion c            on c.run_id = f.run_id
    join dw.bridge_recipe_bom b on b.item_id = f.item_id
                               and f.target_date >= b.valid_from
                               and (b.valid_to is null or f.target_date < b.valid_to)
""", """           sum(f.forecast_qty * b.qty_base) as forecast_requirement
    from dw.fact_demand_forecast f
    join champion c            on c.run_id = f.run_id
    join dw.bridge_recipe_bom b on b.item_id = f.item_id
""")
t = rep(t, "       on sit.ingredient_id = q.ingredient_id and sit.is_primary\n", "       on sit.ingredient_id = q.ingredient_id\n")

# column comments that named dropped columns
i = t.index("comment on column dw.fact_inventory_snapshot.stockout_flag is"); j = t.index("comment on column dw.fact_sales.is_revenue is")
t = t[:i] + t[j:]
t = rep(t, "comment on column dw.fact_waste.waste_reason is", "comment on column dw.fact_waste.waste_reason is")
# header note
t = rep(t, "-- v5 (2026-10-10):", "-- v12 (2026-10-12): 15 columns removed (constant, always NULL, or an exact copy of a value held elsewhere); see v12/COLUMN_AUDIT.md.\n--\n-- v5 (2026-10-10):")
# stale wording that named dropped columns
t = t.replace("fact_sales.pos_sku replaced", "fact_sales.pos_sku replaced")
save(p, t)
left = [l for l in t.split('\n') if re.search(r'valid_from|valid_to|yield_factor|is_primary|closing_value|stockout_flag|qty_unmet|days_to_expiry\b(?!.*as days)|expired_on_date|days_held|shortfall_qty', l) and not l.strip().startswith('--')]
print('01 leftovers:', *left, sep='\n  ')

# ===================================================================== 02_load_staging.psql
p = 'supabase_final/02_load_staging.psql'
t = load(p)
t = rep(t, """alter table stg.sales add column category text, add column pos_sku bigint;                         -- the menu's label and SKU win
update stg.sales s set category = m.category, pos_sku = m.pos_sku from stg.menu_items m where m.item_id = s.item_id;

""", "")
t = rep(t, """alter table stg.inventory_batches add column days_to_expiry int;                                   -- 0 = last usable day
update stg.inventory_batches set days_to_expiry = expiry_date - snapshot_date;

""", "")
t = rep(t, """alter table stg.waste add column supplier_id int, add column unit_cost numeric(12,4), add column received_date date,
                      add column expiry_date date, add column expired_on_date date, add column days_held int;""",
        """alter table stg.waste add column supplier_id int, add column unit_cost numeric(12,4), add column received_date date,
                      add column expiry_date date, add column expired_on_date date;""")
t = rep(t, "update stg.waste set expired_on_date = expiry_date + 1, days_held = waste_date - received_date;   -- usable through expiry_date; binned the next day",
        "update stg.waste set expired_on_date = expiry_date + 1;   -- usable through expiry_date; binned the next day (assertion input: the ledger day the waste leaves stock)")
t = rep(t, "-- -> dw.fact_sales (every validated line; duplicates and closure-day lines were removed upstream into cleaned/).\n--    is_revenue = false marks staff / complimentary lines. category and pos_sku are filled below from stg.menu_items.",
        "-- -> dw.fact_sales (every validated line; duplicates and closure-day lines were removed upstream into cleaned/).\n--    is_revenue = false marks staff / complimentary lines. Category and SKU are the menu item's (dw.dim_menu_item), not repeated on the fact.")
t = rep(t, "-- -> dw.fact_inventory_batch_snapshot. days_to_expiry is filled below.", "-- -> dw.fact_inventory_batch_snapshot (days to expiry = expiry_date - snapshot_date, not stored).")
# stg.inventory columns that no longer have a dw home (stockout_flag, qty_unmet, shortage_cost_php) stay: they are the CSV's columns and feed the v5 assertions
save(p, t)

# ===================================================================== 03_transform.sql
p = 'supabase_final/03_transform.sql'
t = load(p)
t = rep(t, """insert into dw.supplier_item_terms (supplier_id, ingredient_id, is_primary, order_unit,
                                    pack_size, pack_unit, pack_size_base, min_order_packs)
select supplier_id, ingredient_id, true, order_unit, pack_size, pack_unit,
       pack_size_base, min_order_packs""", """insert into dw.supplier_item_terms (supplier_id, ingredient_id, order_unit,
                                    pack_size, pack_unit, pack_size_base, min_order_packs)
select supplier_id, ingredient_id, order_unit, pack_size, pack_unit,
       pack_size_base, min_order_packs""")
t = rep(t, "-- One supplier per ingredient in generated_v4, so every row is the primary supplier.", "-- One supplier per ingredient in generated_v4 (unique index ux_one_supplier_per_ingredient).")
t = rep(t, """-- Recipe grams are usable grams (stock is held in usable units), so yield_factor keeps
-- its default 1.0; valid_from keeps its default and valid_to is null (one recipe version).""",
        """-- Recipe grams are usable grams (stock is held in usable units): no yield factor; one recipe version for the whole history.""")
t = rep(t, """-- category: the canonical dim_menu_category.category_name of the item. The staged label is the menu's raw label, which
-- spelled the same category two ways in the raw export; menu_items.csv now carries one spelling per category.
insert into dw.fact_sales (sale_id, sale_date, item_id, channel, pos_sku, category,
                           quantity_sold, unit_price, gross_sales, discount, net_sales,
                           is_revenue)
select s.sale_id, s.sale_date, s.item_id, s.channel, nullif(s.pos_sku, 0), c.category_name,
       s.quantity_sold, s.unit_price, s.gross_sales, s.discount, s.net_sales,
       s.is_revenue
from stg.sales s
join dw.dim_menu_item     m on m.item_id = s.item_id
join dw.dim_menu_category c on c.category_id = m.category_id
order by s.sale_id;""", """-- Category and POS SKU are properties of the menu item (dw.dim_menu_item); the fact carries item_id only.
insert into dw.fact_sales (sale_id, sale_date, item_id, channel,
                           quantity_sold, unit_price, gross_sales, discount, net_sales,
                           is_revenue)
select s.sale_id, s.sale_date, s.item_id, s.channel,
       s.quantity_sold, s.unit_price, s.gross_sales, s.discount, s.net_sales,
       s.is_revenue
from stg.sales s
order by s.sale_id;""")
t = rep(t, """insert into dw.fact_inventory_snapshot (snapshot_date, ingredient_id, supplier_id, opening_qty, qty_received, qty_emergency, qty_consumed,
                                        qty_off_pos_use, qty_wasted, closing_qty, order_qty, on_order_qty, reorder_point,
                                        stockout_flag, emergency_cost_php, qty_unmet, shortage_cost_php, closing_value)
select v.snapshot_date, v.ingredient_id, v.supplier_id, v.opening_qty, v.qty_received, v.qty_emergency, v.qty_consumed,
       v.qty_off_pos_use,
       coalesce(w.wasted, 0),                       -- waste leaves stock on the day the batch expired (expired_on_date), as v_inventory_ledger_check
       v.closing_qty, v.order_qty, v.on_order_qty, v.reorder_point,
       v.stockout_flag, v.emergency_cost_php, v.qty_unmet, v.shortage_cost_php,
       round(v.closing_qty * i.standard_unit_cost, 2)
from stg.inventory v
join dw.dim_ingredient i using (ingredient_id)
left join""", """-- Stockout cost, unmet quantity and the stockout flag are not repeated here: dw.fact_stockout_event holds them (one row per short ingredient-day).
-- Inventory value = closing_qty x dim_ingredient.standard_unit_cost (not stored).
insert into dw.fact_inventory_snapshot (snapshot_date, ingredient_id, supplier_id, opening_qty, qty_received, qty_emergency, qty_consumed,
                                        qty_off_pos_use, qty_wasted, closing_qty, order_qty, on_order_qty, reorder_point)
select v.snapshot_date, v.ingredient_id, v.supplier_id, v.opening_qty, v.qty_received, v.qty_emergency, v.qty_consumed,
       v.qty_off_pos_use,
       coalesce(w.wasted, 0),                       -- waste leaves stock the day after the last usable day (expiry_date + 1), as v_inventory_ledger_check
       v.closing_qty, v.order_qty, v.on_order_qty, v.reorder_point
from stg.inventory v
left join""")
t = rep(t, """                                              received_date, expiry_date, qty_on_hand, unit_cost, days_to_expiry)
select snapshot_date, batch_id, ingredient_id, supplier_id, received_date,
       expiry_date, qty_on_hand, unit_cost, days_to_expiry
from stg.inventory_batches;""", """                                              received_date, expiry_date, qty_on_hand, unit_cost)
select snapshot_date, batch_id, ingredient_id, supplier_id, received_date,
       expiry_date, qty_on_hand, unit_cost
from stg.inventory_batches;""")
t = rep(t, """insert into dw.fact_waste (waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,
                           waste_reason, unit_cost, waste_value_php, received_date, expiry_date,
                           expired_on_date, days_held)
select waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,
       waste_reason, unit_cost, waste_value_php, received_date, expiry_date, expired_on_date, days_held
from stg.waste;""", """insert into dw.fact_waste (waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,
                           waste_reason, unit_cost, waste_value_php, received_date, expiry_date)
select waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,
       waste_reason, unit_cost, waste_value_php, received_date, expiry_date
from stg.waste;""")
t = rep(t, "insert into dw.fact_stockout_event select * from stg.stockout_events;",
        """insert into dw.fact_stockout_event (event_date, ingredient_id, need_qty, available_qty, outcome, emergency_qty,
                                     emergency_cost_php, unmet_qty, shortage_cost_php)
select event_date, ingredient_id, need_qty, available_qty, outcome, emergency_qty,
       emergency_cost_php, unmet_qty, shortage_cost_php
from stg.stockout_events;""")
# assertions
t = rep(t, """    -- the staged category label of every sale line is the name of its item's category
    select count(*) into n_dw
    from stg.sales s join dw.dim_menu_item m using (item_id)
    join dw.dim_menu_category c on c.category_id = m.category_id
    where s.category is distinct from c.category_name;
    if n_dw > 0 then
        raise exception 'fact_sales: % lines carry a category label that is not their item''s category', n_dw;
    end if;

""", "")
t = rep(t, "sum(a.quantity_sold * b.qty_base / b.yield_factor) as unrecorded_qty", "sum(a.quantity_sold * b.qty_base) as unrecorded_qty")
t = rep(t, "on t.ingredient_id = v.ingredient_id and t.supplier_id = v.supplier_id and t.is_primary\n", "on t.ingredient_id = v.ingredient_id and t.supplier_id = v.supplier_id\n")
t = rep(t, """    -- unmet quantity only where a LOST_SALES event says so
    select count(*) into n_a from dw.fact_inventory_snapshot f
      where f.qty_unmet > 0 and not exists (select 1 from dw.fact_stockout_event e where e.event_date = f.snapshot_date and e.ingredient_id = f.ingredient_id and e.outcome = 'LOST_SALES');
    if n_a > 0 then raise exception '% ingredient-days have unmet quantity without a LOST_SALES event', n_a; end if;
    -- stockout_flag = a stockout event exists
    select count(*) into n_a from dw.fact_inventory_snapshot s left join dw.fact_stockout_event e on e.event_date = s.snapshot_date and e.ingredient_id = s.ingredient_id
      where s.stockout_flag <> (e.event_date is not null);
    if n_a > 0 then raise exception 'stockout_flag disagrees with fact_stockout_event on % rows', n_a; end if;
""", """    -- the staged inventory file's stockout columns (not loaded to the snapshot) agree with the events that are loaded:
    -- unmet quantity only where a LOST_SALES event says so; stockout_flag = a stockout event exists; cost, unmet and emergency quantity match
    select count(*) into n_a from stg.inventory f
      where f.qty_unmet > 0 and not exists (select 1 from dw.fact_stockout_event e where e.event_date = f.snapshot_date and e.ingredient_id = f.ingredient_id and e.outcome = 'LOST_SALES');
    if n_a > 0 then raise exception '% ingredient-days have unmet quantity without a LOST_SALES event', n_a; end if;
    select count(*) into n_a from stg.inventory s left join dw.fact_stockout_event e on e.event_date = s.snapshot_date and e.ingredient_id = s.ingredient_id
      where s.stockout_flag <> (e.event_date is not null)
         or s.emergency_cost_php <> coalesce(e.emergency_cost_php, 0) or s.qty_unmet <> coalesce(e.unmet_qty, 0)
         or s.shortage_cost_php <> coalesce(e.shortage_cost_php, 0) or s.qty_emergency <> coalesce(e.emergency_qty, 0);
    if n_a > 0 then raise exception 'stg.inventory stockout columns disagree with fact_stockout_event on % rows', n_a; end if;
""")
save(p, t)

# ===================================================================== validation
p = 'validation/post_load_validation.sql'
t = load(p)
t = rep(t, "s as (select * from dw.fact_sales),",
        "s as (select f.*, c.category_name as category, m.pos_sku   -- category and SKU are the menu item's (not stored on the fact)\n      from dw.fact_sales f join dw.dim_menu_item m using (item_id) join dw.dim_menu_category c using (category_id)),")
i = t.index("  union all select 'SAL06'"); j = t.index("  union all select 'SAL08'")
t = t[:i] + t[j:]
t = rep(t, "group by sale_date,item_id,channel,pos_sku,category,quantity_sold,", "group by sale_date,item_id,channel,quantity_sold,")
t = rep(t, "'qty_base <= 0 or yield_factor outside (0,1]',(select count(*) from dw.bridge_recipe_bom where qty_base<=0 or yield_factor<=0 or yield_factor>1),0",
        "'qty_base <= 0',(select count(*) from dw.bridge_recipe_bom where qty_base<=0),0")
i = t.index("  union all select 'BOM02'"); j = t.index("  union all select 'BOM03'")
t = t[:i] + t[j:]
i = t.index("  union all select 'BOM08'"); j = t.index("  union all select 'BOM09'")
t = t[:i] + t[j:]
i = t.index("  union all select 'INV04'"); j = t.index("  union all select 'INV06'")
t = t[:i] + t[j:]
t = rep(t, "t.supplier_id=b.supplier_id and t.is_primary where", "t.supplier_id=b.supplier_id where")
i = t.index("  union all select 'WST06'"); j = t.index("  union all select 'WST08'")
t = t[:i] + """  union all select 'WST06','waste','reason = Expired during closure but disposal is on the day after expiry_date (not later)',
     (select count(*) from dw.fact_waste where waste_reason='Expired during closure' and waste_date=expiry_date+1),0
  union all select 'WST07','waste','reason expiry/overstock but disposal later than the day after expiry_date',
     (select count(*) from dw.fact_waste where waste_reason<>'Expired during closure' and waste_date<>expiry_date+1),null
""" + t[j:]
t = rep(t, "s.snapshot_date=w.expired_on_date and s.ingredient_id=w.ingredient_id", "s.snapshot_date=w.expiry_date+1 and s.ingredient_id=w.ingredient_id")
t = rep(t, "where t.ingredient_id=i.ingredient_id and t.is_primary)),0", "where t.ingredient_id=i.ingredient_id)),0")
t = rep(t, "(select count(distinct item_id) from dw.bridge_recipe_bom where valid_to is null)", "(select count(distinct item_id) from dw.bridge_recipe_bom)")
i = t.index("  union all select 'BOM10'"); j = t.index("\n", t.index("having count(*)>1) q),null", i)) + 1
t = t[:i] + t[j:]
save(p, t)
left = [(n + 1, l.strip()[:120]) for n, l in enumerate(t.split('\n')) if re.search(r'valid_from|valid_to|yield_factor|is_primary|closing_value|stockout_flag|qty_unmet|expired_on_date|days_held|shortfall_qty', l)]
print('validation leftovers:', *left, sep='\n  ')

# ===================================================================== ERD source
p = 'erd/build_erd.py'
t = open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in t else '\n'
t = t.replace('\r\n', '\n')
open('v12/_erd_before.txt', 'w').write('\n'.join(l for l in t.split('\n') if re.search(r"valid_from|valid_to|yield_factor|is_primary|closing_value|stockout_flag|qty_unmet|days_to_expiry|expired_on_date|days_held|shortfall_qty|'category'|'pos_sku'|emergency_cost_php|shortage_cost_php", l)))
print('ERD lines to edit written to v12/_erd_before.txt')
open(p, 'w', encoding='utf-8', newline='').write(t.replace('\n', nl))
print('done')
