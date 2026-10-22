"""v12 step 2 (user decision 2026-10-12): drop fact_recommendation_outcome, dim_supplier.supplier_type, fact_waste.waste_reason."""
import re
def load(p): return open(p,encoding='utf-8',newline='').read().replace('\r\n','\n')
def save(p,t): open(p,'w',encoding='utf-8',newline='').write(t.replace('\n','\r\n'))
def rep(t,a,b):
    assert a in t,a[:90]; return t.replace(a,b,1)
def cut(t,a,b,keep_b=True):
    i=t.index(a); j=t.index(b,i); return t[:i]+t[j:]

p='supabase_final/01_schema.sql'; t=load(p)
t=rep(t,"    supplier_type          text not null,\n","")
t=rep(t,"    waste_reason     text not null check (waste_reason in ('expiry', 'overstock', 'Expired during closure')),\n","")
t=cut(t,"create table if not exists dw.fact_recommendation_outcome (","-- =====================================================================\n-- VIEWS")
t=rep(t,"select case when waste_reason = 'Expired during closure' then 'expired during closure'","select case when waste_date > expiry_date + 1 then 'expired during closure'   -- binned after the day following expiry_date = the restaurant was shut")
t=cut(t,"comment on column dw.fact_waste.waste_reason is","comment on column dw.fact_inventory_transaction.quantity is")
t=cut(t,"comment on column dw.dim_supplier.supplier_type is","comment on column dw.dim_ingredient.is_perishable is")
t=rep(t,"-- v12 (2026-10-12): 15 columns removed","-- v12 (2026-10-12): 15 columns plus dim_supplier.supplier_type, fact_waste.waste_reason and table fact_recommendation_outcome removed")
save(p,t)

p='supabase_final/02_load_staging.psql'; t=load(p)
t=rep(t,"-- -> dw.dim_supplier (supplier_type has no source column: derived in 03_transform)","-- -> dw.dim_supplier (column for column)")
t=rep(t,"    waste_reason    text,\n","    waste_reason    text,                -- CSV column; not loaded to dw (a simulation-rule label)\n")
save(p,t)

p='supabase_final/03_transform.sql'; t=load(p)
t=rep(t,"truncate dw.fact_recommendation_outcome, dw.fact_replenishment_plan,","truncate dw.fact_replenishment_plan,")
t=rep(t,"-- supplier_type: no source column; the label is derived from each supplier's delivery_terms_basis (SYNTHETIC terms).\n","")
i=t.index("insert into dw.dim_supplier"); j=t.index("from stg.suppliers;",i)
t=t[:i]+"""insert into dw.dim_supplier (supplier_id, supplier_name, lead_time_days,
                             lead_time_sd_days, delivery_interval_days)
select supplier_id, trim(supplier_name),
       greatest(lead_time_days, 1), lead_time_sd_days, delivery_interval_days
"""+t[j:]
t=rep(t,"waste_reason, unit_cost, waste_value_php, received_date, expiry_date)\nselect waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,\n       waste_reason, unit_cost,","unit_cost, waste_value_php, received_date, expiry_date)\nselect waste_id, waste_date, ingredient_id, supplier_id, batch_id, waste_qty,\n       unit_cost,")
save(p,t)

p='validation/post_load_validation.sql'; t=load(p)
t=rep(t,"+(select count(*) from dw.fact_replenishment_plan)+(select count(*) from dw.fact_recommendation_outcome)),null","+(select count(*) from dw.fact_replenishment_plan)),null")
t=cut(t,"  union all select 'WST06'","  union all select 'WST08'")
t=t[:t.index("  union all select 'WST08'")]+"""  union all select 'WST06','waste','waste_date later than the day after expiry_date (expired during a closure, binned on reopening; info)',
     (select count(*) from dw.fact_waste where waste_date>expiry_date+1),null
"""+t[t.index("  union all select 'WST08'"):]
i=t.index("  union all select 'WST09'"); j=t.index("\n",i)+1; t=t[:i]+t[j:]
save(p,t)

p='erd/build_erd.py'; t=open(p,encoding='utf-8',newline='').read(); nl='\r\n' if '\r\n' in t else '\n'; t=t.replace('\r\n','\n')
t=rep(t,"('supplier_name', 'text', ''), ('supplier_type', 'text', ''),","('supplier_name', 'text', ''),")
t=rep(t,"    ('waste_reason', 'text', ''), ('unit_cost', 'numeric', ''),","    ('unit_cost', 'numeric', ''),")
t=cut(t," 'fact_recommendation_outcome': ('presc'","}\n\n# ---- layout")
t=rep(t,"['fact_replenishment_plan', 'fact_recommendation_outcome']","['fact_replenishment_plan']")
t=cut(t," ('fact_recommendation_outcome', 'opt_run_id', 'R'","]\n\nfrom") if False else t
i=t.index(" ('fact_recommendation_outcome', 'opt_run_id', 'R'"); j=t.index("\n",i)+1; t=t[:i]+t[j:]
open(p,'w',encoding='utf-8',newline='').write(t.replace('\n',nl))
print('ok')
