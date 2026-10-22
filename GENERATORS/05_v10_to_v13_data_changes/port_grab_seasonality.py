"""Ports the GrabFood-seasonality rebuild (scratch package, old item ids) into datasets/ (v13, 2026-10-14).
Same mapping as v12/port_staples_rebuild.py (item 14 -> 13, ids above 14 down by 1, the two paid lines flagged revenue) plus waste_reason overstock -> over_ordering.
The real POS lines (>= 2025-12-01) must be identical to the current ones. Also writes v12/stock_rebuild/sales*_old_item_ids.csv and refreshes MANIFEST_final.csv rows / bytes / sha256.
Usage (package folder): py v13/port_grab_seasonality.py <scratch generated_v4 folder>"""
import sys, shutil, hashlib
import pandas as pd

R = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'; D = 'datasets/'
mp = lambda s: s.where(s < 14, s - 1).where(s != 14, 13)
for f in ('inventory', 'inventory_batches', 'stockout_events', 'storage_capacity'):
    shutil.copy2(R + f + '.csv', D + f + '.csv')
w = pd.read_csv(R + 'waste.csv'); w['waste_reason'] = w.waste_reason.replace({'overstock': 'over_ordering'}); assert set(w.waste_reason) <= {'over_ordering', 'expiry'}
w.to_csv(D + 'waste.csv', index=False, lineterminator='\n')
s = pd.read_csv(R + 'sales.csv'); cur = pd.read_csv(D + 'sales.csv'); shutil.copy2(R + 'sales.csv', 'v12/stock_rebuild/sales_old_item_ids.csv'); shutil.copy2(R + 'sales_dropped.csv', 'v12/stock_rebuild/sales_dropped_old_item_ids.csv')
s['item_id'] = mp(s.item_id)
paid = ((s.sale_date == '2026-03-13') & (s.item_id == 7) & (s.net_sales > 0)) | ((s.sale_date == '2026-04-15') & (s.item_id == 120) & (s.net_sales > 0)); assert paid.sum() == 2, paid.sum()
s.loc[paid, 'is_revenue'] = True
k = ['sale_date', 'item_id', 'channel', 'quantity_sold', 'unit_price', 'gross_sales', 'discount', 'net_sales', 'is_revenue']
a = s[s.sale_date >= '2025-12-01'][k].sort_values(k).reset_index(drop=True); b = cur[cur.sale_date >= '2025-12-01'][k].sort_values(k).reset_index(drop=True); assert a.equals(b), 'real POS lines changed'
s.to_csv(D + 'sales.csv', index=False, lineterminator='\n')
d = pd.read_csv(R + 'sales_dropped.csv'); d['item_id'] = mp(d.item_id); d.to_csv(D + 'sales_dropped.csv', index=False, lineterminator='\n')
mf = pd.read_csv('MANIFEST_final.csv')
for i, r in mf.iterrows():
    p = D + r.path.split('/')[-1]
    if r.path.startswith('generated_v4/') and r.path.split('/')[-1] in ('sales.csv', 'sales_dropped.csv', 'inventory.csv', 'inventory_batches.csv', 'waste.csv', 'stockout_events.csv', 'storage_capacity.csv'):
        raw = open(p, 'rb').read(); mf.at[i, 'sha256'] = hashlib.sha256(raw).hexdigest(); mf.at[i, 'bytes'] = len(raw); mf.at[i, 'rows'] = float(len(pd.read_csv(p)))
mf.to_csv('MANIFEST_final.csv', index=False, lineterminator='\n')
print('sales', len(s), 'dropped', len(d), 'real POS lines identical;', 'manifest refreshed')
