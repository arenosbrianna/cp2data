"""v12 step 4 (user decision 2026-10-12): drop dim_date.forecast_split. 'Observed' days = date <= the last inventory snapshot date; the train/test cut-off belongs to forecast_run.train_end_date."""
import pandas as pd
def load(p): return open(p,encoding='utf-8',newline='').read().replace('\r\n','\n')
def save(p,t,crlf=True): open(p,'w',encoding='utf-8',newline='').write(t.replace('\n','\r\n') if crlf else t)
def rep(t,a,b):
    assert a in t,a[:80]; return t.replace(a,b,1)
OBS="(select max(snapshot_date) from dw.fact_inventory_snapshot)"
c=pd.read_csv('generated_v4/calendar_ext.csv',dtype=str,keep_default_na=False); c=c.drop(columns=['forecast_split']); c.to_csv('generated_v4/calendar_ext.csv',index=False,lineterminator='\n')
p='supabase_final/01_schema.sql'; t=load(p)
t=rep(t,"    forecast_split  text not null check (forecast_split in ('train', 'test', 'forecast')),   -- 'forecast' = after the data ends, up to the 2027-09-30 horizon\n","")
t=rep(t,"planned, not observed, when forecast_split = 'forecast'","planned, not observed, after the last data day (2026-09-08; the calendar runs to the 2027-09-30 forecast horizon)")
t=rep(t,"-- v5 (2026-10-10):","-- v12 step 4: dim_date.forecast_split removed; observed days are date <= the last fact_inventory_snapshot date, the train/test cut-off is forecast_run.train_end_date.\n--\n-- v5 (2026-10-10):")
save(p,t)
p='supabase_final/02_load_staging.psql'; t=load(p)
t=rep(t,"-- -> dw.dim_date (column for column; the week column is iso_week; forecast_split is train / test, 'forecast' beyond the data)","-- -> dw.dim_date (column for column; the week column is iso_week; the calendar runs to the 2027-09-30 forecast horizon)")
t=rep(t,"    is_open         boolean,\n    forecast_split  text\n","    is_open         boolean\n")
save(p,t)
p='supabase_final/03_transform.sql'; t=load(p)
t=rep(t,"is_ber_month, forecast_split,\n                         is_open)","is_ber_month,\n                         is_open)")
t=rep(t,"e.is_ber_month, coalesce(e.forecast_split, 'forecast'),\n       e.is_open","e.is_ber_month,\n       e.is_open")
t=rep(t,"(forecast_split from calendar_ext.csv)","")
t=rep(t,"where d.forecast_split <> 'forecast' and d.is_open and not exists","where d.date <= "+OBS+" and d.is_open and not exists")
save(p,t)
p='validation/post_load_validation.sql'; t=load(p)
i=t.index("  union all select 'DAT08'"); j=t.index("\n",t.index("\n",t.index("  union all select 'DAT09'"))); 
# remove DAT08 (2 lines) and DAT09 (1 line)
i9=t.index("  union all select 'DAT09'"); j9=t.index("\n",i9)+1
t=t[:i]+t[j9:]
t=t.replace("where forecast_split <> 'forecast'","where date <= "+OBS).replace("d.forecast_split <> 'forecast'","d.date <= "+OBS)
i=t.index("  union all select 'CLS03'"); j=t.index("\n",t.index("\n",i)+1)+1; t=t[:i]+t[j:]
save(p,t)
import re
print('validation leftovers:',[l[:100] for l in t.split('\n') if 'forecast_split' in l])
p='erd/build_erd.py'; t=open(p,encoding='utf-8',newline='').read(); nl='\r\n' if '\r\n' in t else '\n'; t=t.replace('\r\n','\n')
t=rep(t,"    ('forecast_split', 'text', ''), ('is_open', 'boolean', '')]),","    ('is_open', 'boolean', '')]),")
open(p,'w',encoding='utf-8',newline='').write(t.replace('\n',nl))
p='build_stg_extract.py'; t=open(p,encoding='utf-8',newline='').read()
print([l for l in t.split('\n') if 'forecast_split' in l])
