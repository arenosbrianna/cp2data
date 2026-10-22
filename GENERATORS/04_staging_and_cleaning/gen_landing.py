import re, csv, sys
from pathlib import Path
ROOT = Path(r"C:/Users/Brianna/Desktop/CAPSTONE2/OTHER_PROJECT_FILES/UPDATED FILES")
sql = (ROOT/'supabase_final/02_load_staging.psql').read_text(encoding='utf8')

def split_top(body):
    out, depth, cur = [], 0, ''
    for ch in body:
        if ch == '(': depth += 1
        if ch == ')': depth -= 1
        if ch == ',' and depth == 0: out.append(cur); cur = ''
        else: cur += ch
    if cur.strip(): out.append(cur)
    return out

tables = {}   # name -> [(col, type)]
for m in re.finditer(r'create table stg\.(\w+) \((.*?)\n\);', sql, re.S):
    name, body = m.groups()
    body = re.sub(r'--[^\n]*', '', body)
    cols = []
    for part in split_top(body):
        part = part.strip()
        if not part: continue
        c, t = part.split(None, 1)
        cols.append((c, t.strip()))
    tables[name] = cols

# the CSV header must equal the stg column list (that is what header match enforces)
for t, cols in tables.items():
    hdr = next(csv.reader(open(ROOT/f'datasets/{t}.csv', encoding='utf8')))
    assert [c for c, _ in cols] == hdr, t

derived = {  # columns 02_load_staging.psql adds after the load
    'inventory': [('supplier_id', 'int')],
    'waste': [('supplier_id', 'int'), ('unit_cost', 'numeric(12,4)'), ('received_date', 'date'),
              ('expiry_date', 'date'), ('expired_on_date', 'date')],
}

o = []
w = o.append
w("""-- =====================================================================
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

""")
for t, cols in tables.items():
    w(f"create table if not exists landing.{t} (\n")
    lines = [f"    {c} text" for c, _ in cols]
    lines += ["    _loaded_at timestamptz not null default now()", "    _source_file text"]
    w(",\n".join(lines) + "\n);\n\n")
w("-- ---------------------------------------------------------------- typed staging\n")
for t, cols in tables.items():
    allc = cols + derived.get(t, [])
    w(f"create table if not exists stg.{t} (\n" + ",\n".join(f"    {c} {ty}" for c, ty in allc) + "\n);\n\n")

w("-- ---------------------------------------------------------------- landing -> staging\n")
w("create or replace function stg.promote_from_landing() returns text\nlanguage plpgsql as $fn$\ndeclare n bigint; msg text := '';\nbegin\n")
w("    truncate " + ", ".join(f"stg.{t}" for t in tables) + ";\n\n")
for t, cols in tables.items():
    names = ", ".join(c for c, _ in cols)
    sel = ", ".join(f"nullif(btrim({c}), '')::{ty}" if not ty.startswith('text') else f"nullif(btrim({c}), '')" for c, ty in cols)
    w(f"    insert into stg.{t} ({names})\n    select {sel}\n    from landing.{t};\n")
    w(f"    get diagnostics n = row_count; msg := msg || '{t}=' || n || ' ';\n\n")
w("""    -- derived columns (same rules as 02_load_staging.psql)
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
""")
(ROOT/'supabase_final/00_landing_and_staging.sql').write_text("".join(o), encoding='utf8')
print(len(tables), 'tables;', sum(len(c) for c in tables.values()), 'columns')
