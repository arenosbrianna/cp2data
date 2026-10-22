"""v12 step 5 (user decision 2026-10-12): drop dim_supplier.lead_time_sd_days, supplier_item_terms.order_unit / pack_size / pack_unit, fact_stockout_event.emergency_qty.
The staging tables keep these CSV columns (stg.*); the pack checks (old validation SUP04/SUP06) and the emergency-quantity cross-check now run on staging in 03_transform.sql."""


def load(p):
    return open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


def save(p, t):
    open(p, 'w', encoding='utf-8', newline='').write(t.replace('\n', '\r\n'))


def rep(t, a, b):
    assert a in t, a[:90]
    return t.replace(a, b, 1)


p = 'supabase_final/01_schema.sql'; t = load(p)
t = rep(t, "    lead_time_sd_days      numeric not null check (lead_time_sd_days >= 0),\n", "")
t = rep(t, "    order_unit      text not null,\n    pack_size       numeric not null check (pack_size > 0),\n    pack_unit       text not null,\n    pack_size_base  numeric not null check (pack_size_base > 0),",
        "    pack_size_base  numeric not null check (pack_size_base > 0),   -- usable base units per pack (client pack, yield loss already inside)")
t = rep(t, "    emergency_qty      numeric not null,\n", "")
t = rep(t, """    select e.ingredient_id, (sum(e.emergency_cost_php) - sum(e.emergency_qty * i.standard_unit_cost)) / nullif(sum(e.emergency_qty), 0) as pi
    from dw.fact_stockout_event e join dw.dim_ingredient i using (ingredient_id) where e.outcome = 'EMERGENCY_PURCHASE' group by e.ingredient_id""",
        """    select e.ingredient_id, (sum(e.emergency_cost_php) - sum(s.qty_emergency * i.standard_unit_cost)) / nullif(sum(s.qty_emergency), 0) as pi   -- emergency quantity = the snapshot's qty_emergency that day
    from dw.fact_stockout_event e join dw.dim_ingredient i using (ingredient_id)
    join dw.fact_inventory_snapshot s on s.snapshot_date = e.event_date and s.ingredient_id = e.ingredient_id
    where e.outcome = 'EMERGENCY_PURCHASE' group by e.ingredient_id""")
t = rep(t, "sup.lead_time_days, sup.lead_time_sd_days, sup.delivery_interval_days,", "sup.lead_time_days, sup.delivery_interval_days,")
t = rep(t, "-- v5 (2026-10-10):", "-- v12 step 5: dim_supplier.lead_time_sd_days, supplier_item_terms.order_unit / pack_size / pack_unit and fact_stockout_event.emergency_qty removed.\n--\n-- v5 (2026-10-10):")
save(p, t)

p = 'supabase_final/02_load_staging.psql'; t = load(p)
t = rep(t, "    lead_time_sd_days      numeric,\n", "    lead_time_sd_days      numeric,      -- CSV column; not loaded to dw (simulation parameter)\n")
t = rep(t, "    order_unit      text,\n    pack_size       numeric,\n    pack_unit       text,\n",
        "    order_unit      text,         -- order_unit, pack_size, pack_unit: client pack description; CSV columns kept for the pack checks in 03_transform.sql, not loaded to dw\n    pack_size       numeric,\n    pack_unit       text,\n")
save(p, t)

p = 'supabase_final/03_transform.sql'; t = load(p)
t = rep(t, "                             lead_time_sd_days, delivery_interval_days)", "                             delivery_interval_days)")
t = rep(t, "greatest(lead_time_days, 1), lead_time_sd_days, delivery_interval_days", "greatest(lead_time_days, 1), delivery_interval_days")
t = rep(t, "insert into dw.supplier_item_terms (supplier_id, ingredient_id, order_unit,\n                                    pack_size, pack_unit, pack_size_base, min_order_packs)\nselect supplier_id, ingredient_id, order_unit, pack_size, pack_unit,\n       pack_size_base, min_order_packs",
        "insert into dw.supplier_item_terms (supplier_id, ingredient_id, pack_size_base, min_order_packs)\nselect supplier_id, ingredient_id, pack_size_base, min_order_packs")
t = rep(t, "need_qty, available_qty, outcome, emergency_qty,\n                                     emergency_cost_php", "need_qty, available_qty, outcome,\n                                     emergency_cost_php")
t = rep(t, "select event_date, ingredient_id, need_qty, available_qty, outcome, emergency_qty,\n       emergency_cost_php", "select event_date, ingredient_id, need_qty, available_qty, outcome,\n       emergency_cost_php")
t = rep(t, "    select count(*) into n_a from stg.inventory s left join dw.fact_stockout_event e on e.event_date = s.snapshot_date and e.ingredient_id = s.ingredient_id\n",
        "    select count(*) into n_a from stg.inventory s left join stg.stockout_events e on e.event_date = s.snapshot_date and e.ingredient_id = s.ingredient_id\n")
t = rep(t, "    -- every observed open day has a sale line,",
        """    -- pack checks on the staged client pack description (moved here from validation SUP04 / SUP06 when pack_size and pack_unit left dw)
    select count(*) into n_a from stg.supplier_item_terms t join dw.dim_ingredient i using (ingredient_id) where t.pack_unit = i.base_uom and t.pack_size_base > t.pack_size + 0.0001;
    if n_a > 0 then raise exception '% packs yield more usable base units than the pack holds', n_a; end if;
    select count(*) into n_a from stg.supplier_item_terms t where t.pack_unit in ('kg', 'l', 'L') and (t.pack_size_base <= 0 or t.pack_size_base > 1200 * t.pack_size + 0.0001 or (t.pack_unit = 'kg' and t.pack_size_base > 1000 * t.pack_size + 0.0001));
    if n_a > 0 then raise exception '% kg / L packs have an impossible base-unit size', n_a; end if;
    -- every observed open day has a sale line,""")
save(p, t)

p = 'validation/post_load_validation.sql'; t = load(p)
i = t.index("  union all select 'SUP04'"); j = t.index("  union all select 'SUP07'")
save(p, t[:i] + t[j:])

p = 'erd/build_erd.py'; t = open(p, encoding='utf-8', newline='').read(); nl = '\r\n' if '\r\n' in t else '\n'; t = t.replace('\r\n', '\n')
t = rep(t, "    ('order_unit', 'text', ''), ('pack_size', 'numeric', ''), ('pack_unit', 'text', ''),\n    ('pack_size_base'", "    ('pack_size_base'")
t = rep(t, "('lead_time_days', 'numeric', ''), ('lead_time_sd_days', 'numeric', ''),", "('lead_time_days', 'numeric', ''),")
t = rep(t, "('emergency_qty', 'numeric', ''), ('emergency_cost_php'", "('emergency_cost_php'")
open(p, 'w', encoding='utf-8', newline='').write(t.replace('\n', nl))

p = 'v12/build_column_register.py'; t = open(p, encoding='utf-8').read()
t = t.replace("put('dim_supplier', 'lead_time_days lead_time_sd_days delivery_interval_days',", "put('dim_supplier', 'lead_time_days delivery_interval_days',")
t = t.replace("put('supplier_item_terms', 'order_unit pack_size pack_unit', 'A', 'client SUPPLY-UR pack description', 'pack as ordered')\n", "")
t = t.replace("'fact_stockout_event', 'event_date ingredient_id need_qty available_qty outcome emergency_qty emergency_cost_php", "'fact_stockout_event', 'event_date ingredient_id need_qty available_qty outcome emergency_cost_php")
open(p, 'w', encoding='utf-8').write(t)
print('ok')
