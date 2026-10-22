"""v12 step 8 (user decision 2026-10-13): bring dw.fact_waste.waste_reason back, now with two informative values:
  overstock = the batch was larger than the ingredient's normal demand over its whole shelf life (quantity at receipt > shelf_life_days x trailing 90-day mean use)
  expiry    = normal demand would have used the batch up within its shelf life, but part of it was left when it expired
(the old third value 'Expired during closure' is gone: the closure split is derived from the dates in dw.v_waste_by_context)."""


def load(p):
    return open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


def save(p, t):
    open(p, 'w', encoding='utf-8', newline='').write(t.replace('\n', '\r\n'))


def rep(t, a, b):
    assert a in t, a[:90]
    return t.replace(a, b, 1)


p = 'supabase_final/01_schema.sql'; t = load(p)
t = rep(t, "    waste_qty        numeric not null check (waste_qty > 0),\n    unit_cost        numeric(12,4) not null,\n    waste_value_php",
        "    waste_qty        numeric not null check (waste_qty > 0),\n    waste_reason     text not null check (waste_reason in ('overstock', 'expiry')),\n    unit_cost        numeric(12,4) not null,\n    waste_value_php")
t = rep(t, "-- v12 step 5:", "-- v12 step 8: waste_reason is back (fact_waste), values 'overstock' / 'expiry' only (rule in the column comment).\n--\n-- v12 step 5:")
t = t.replace("-- v12 step 8: dim waste_reason", "-- v12 step 8: waste_reason")
t = t.rstrip('\n') + """
comment on column dw.fact_waste.waste_reason is
    'Derived by the simulation, not recorded. overstock = the batch was larger than the ingredient''s normal demand over its whole shelf life (quantity at receipt > shelf_life_days x trailing 90-day mean use: bought or packed too much); expiry = normal demand would have used the batch up within its shelf life, but part was left when it expired. Every waste row is an expired batch; the closure split is in dw.v_waste_by_context.';
"""
save(p, t)
p = 'supabase_final/02_load_staging.psql'; t = load(p)
t = rep(t, "    waste_reason    text,                -- CSV column; not loaded to dw (a simulation-rule label)\n", "    waste_reason    text,                -- overstock / expiry (simulation rule, see the column comment in 01_schema.sql)\n")
save(p, t)
p = 'supabase_final/03_transform.sql'; t = load(p)
t = rep(t, "insert into dw.fact_waste (waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,\n                           unit_cost, waste_value_php, received_date, expiry_date)\nselect waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,\n       unit_cost,",
        "insert into dw.fact_waste (waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,\n                           waste_reason, unit_cost, waste_value_php, received_date, expiry_date)\nselect waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,\n       waste_reason, unit_cost,")
save(p, t)
p = 'validation/post_load_validation.sql'; t = load(p)
a = "  union all select 'WST08'"
assert a in t
t = t.replace(a, "  union all select 'WST11','waste','waste rows per reason: overstock (batch larger than normal demand over its shelf life; info)',(select count(*) from dw.fact_waste where waste_reason='overstock'),null\n"
                 "  union all select 'WST12','waste','waste rows per reason: expiry (info)',(select count(*) from dw.fact_waste where waste_reason='expiry'),null\n" + a, 1)
save(p, t)
p = 'erd/build_erd.py'; t = open(p, encoding='utf-8', newline='').read(); nl = '\r\n' if '\r\n' in t else '\n'; t = t.replace('\r\n', '\n')
t = rep(t, "('waste_qty', 'numeric', ''),\n    ('unit_cost', 'numeric', ''), ('waste_value_php'", "('waste_qty', 'numeric', ''),\n    ('waste_reason', 'text', ''), ('unit_cost', 'numeric', ''), ('waste_value_php'") if "('waste_qty', 'numeric', ''),\n    ('unit_cost'" in t else t
open(p, 'w', encoding='utf-8', newline='').write(t.replace('\n', nl))
print('waste_reason in ERD source:', "('waste_reason'" in t)
