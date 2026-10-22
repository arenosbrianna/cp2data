"""v14 perishable-scope version of v13/port_grab_seasonality.py: additionally sets dim_ingredient.is_perishable from v14/ingredient_scope_register.csv (values only).
Ports the rebuild (scratch package, old item ids) into datasets/ (v13, 2026-10-14).
Same mapping as v12/port_staples_rebuild.py (item 14 -> 13, ids above 14 down by 1, the two paid lines flagged revenue) plus waste_reason overstock -> over_ordering.
The real POS lines (>= 2025-12-01) must be identical to the current ones. Also writes v12/stock_rebuild/sales*_old_item_ids.csv and refreshes MANIFEST_final.csv rows / bytes / sha256.
Usage (package folder): py v13/port_grab_seasonality.py <scratch generated_v4 folder>"""
import sys, shutil, hashlib
import pandas as pd

R = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'; D = 'datasets/'
mp = lambda s: s.where(s < 14, s - 1).where(s != 14, 13)
ing = pd.read_csv(D + 'ingredients.csv'); reg = pd.read_csv('v14/ingredient_scope_register.csv').set_index('ingredient_code'); ing['is_perishable'] = ing.ingredient_code.map(reg.in_inventory_scope).astype(bool)
ing['is_perishable'] = ing.is_perishable.map({True: 'True', False: 'False'}); ing.to_csv(D + 'ingredients.csv', index=False, lineterminator=chr(10))
for f in ('inventory', 'inventory_batches', 'stockout_events', 'storage_capacity'):
    shutil.copy2(R + f + '.csv', D + f + '.csv')
# final audit (2026-10-16, P1-STK1): when another ingredient's shortage cut a dish, the need recorded for this ingredient was larger than what was actually consumed (3 events of 217):
# the realised need = consumed + unmet; shortfall = realised need - available (restores need - available = emergency + unmet)
_e = pd.read_csv(D + 'stockout_events.csv'); _v = pd.read_csv(D + 'inventory.csv', usecols=['snapshot_date', 'ingredient_id', 'qty_consumed']).set_index(['snapshot_date', 'ingredient_id']).qty_consumed
_gap = (_e.shortfall_qty - _e.emergency_qty - _e.unmet_qty) > 0.001
for _i in _e.index[_gap]:
    _c = float(_v.loc[(_e.at[_i, 'event_date'], _e.at[_i, 'ingredient_id'])]); assert abs(_c - (_e.at[_i, 'available_qty'] + _e.at[_i, 'emergency_qty'] + _e.at[_i, 'unmet_qty'])) < 1e-3
    _e.at[_i, 'need_qty'] = round(_c + _e.at[_i, 'unmet_qty'], 4); _e.at[_i, 'shortfall_qty'] = round(_e.at[_i, 'need_qty'] - _e.at[_i, 'available_qty'], 4)
# final audit (2026-10-16): a shortage must never earn money. A lost sale priced below today's standard cost (older prices) produced a negative lost margin; the recorded cost is floored at 0 (event and daily snapshot)
_neg = _e.shortage_cost_php < 0
_vi = pd.read_csv(D + 'inventory.csv'); _ix = _vi.set_index(['snapshot_date', 'ingredient_id']).index
for _i in _e.index[_neg]:
    _k = (_vi.snapshot_date == _e.at[_i, 'event_date']) & (_vi.ingredient_id == _e.at[_i, 'ingredient_id']); assert _k.sum() == 1 and abs(float(_vi.loc[_k, 'shortage_cost_php'].iloc[0]) - float(_e.at[_i, 'shortage_cost_php'])) < 1e-6; _vi.loc[_k, 'shortage_cost_php'] = 0.0
    _e.at[_i, 'shortage_cost_php'] = 0.0
_vi.to_csv(D + 'inventory.csv', index=False, lineterminator=chr(10)); print('negative shortage costs floored at 0:', int(_neg.sum()))
_e.to_csv(D + 'stockout_events.csv', index=False, lineterminator=chr(10)); print('stockout events with realised need set:', int(_gap.sum()))
w = pd.read_csv(R + 'waste.csv'); w['waste_reason'] = w.waste_reason.replace({'overstock': 'over_ordering'}); assert set(w.waste_reason) <= {'over_ordering', 'expiry', 'spoilage', 'shrinkage'}      # 2026-10-22: mid-shelf spoilage and shrinkage are waste reasons too
w.to_csv(D + 'waste.csv', index=False, lineterminator='\n')
s = pd.read_csv(R + 'sales.csv'); cur = pd.read_csv(D + 'sales.csv'); shutil.copy2(R + 'sales.csv', 'v12/stock_rebuild/sales_old_item_ids.csv'); shutil.copy2(R + 'sales_dropped.csv', 'v12/stock_rebuild/sales_dropped_old_item_ids.csv')
s['item_id'] = mp(s.item_id)
paid = ((s.sale_date == '2026-03-13') & (s.item_id == 7) & (s.net_sales > 0)) | ((s.sale_date == '2026-04-15') & (s.item_id == 120) & (s.net_sales > 0)); assert paid.sum() == 2, paid.sum()
s.loc[paid, 'is_revenue'] = True
k = ['sale_date', 'item_id', 'channel', 'quantity_sold', 'unit_price', 'gross_sales', 'discount', 'net_sales', 'is_revenue']
a = s[s.sale_date >= '2025-12-01'][k].sort_values(k).reset_index(drop=True); b = cur[cur.sale_date >= '2025-12-01'][k].sort_values(k).reset_index(drop=True); assert a.equals(b), 'real POS lines changed'
# audit ID-009 (2026-10-16): sale_id is a pure function of the line content: lines are ordered by the natural key below and numbered 1..n, so identical inputs always give identical ids
# (ids still shift when lines are added or removed, as for any contiguous surrogate key; the natural key itself is the stable identity)
s['_i'] = range(len(s)); s = s.sort_values(['sale_date', 'item_id', 'channel', 'is_revenue', 'unit_price', 'quantity_sold', 'gross_sales', 'discount', 'net_sales'], kind='stable').reset_index(drop=True)
old = pd.read_csv(R + 'sales.csv').iloc[s._i.to_numpy()].reset_index(drop=True); old['sale_id'] = range(1, len(old) + 1); old.to_csv('v12/stock_rebuild/sales_old_item_ids.csv', index=False, lineterminator=chr(10))   # same row order / ids for test 19
s = s.drop(columns='_i'); s['sale_id'] = range(1, len(s) + 1)
s.to_csv(D + 'sales.csv', index=False, lineterminator='\n')
d = pd.read_csv(R + 'sales_dropped.csv'); d['item_id'] = mp(d.item_id); d.to_csv(D + 'sales_dropped.csv', index=False, lineterminator='\n')
mf = pd.read_csv('MANIFEST_final.csv')
for i, r in mf.iterrows():
    p = D + r.path.split('/')[-1]
    if r.path.startswith('generated_v4/') and r.path.split('/')[-1] in ('ingredients.csv', 'sales.csv', 'sales_dropped.csv', 'inventory.csv', 'inventory_batches.csv', 'waste.csv', 'stockout_events.csv', 'storage_capacity.csv'):
        raw = open(p, 'rb').read(); mf.at[i, 'sha256'] = hashlib.sha256(raw).hexdigest(); mf.at[i, 'bytes'] = len(raw); mf.at[i, 'rows'] = float(len(pd.read_csv(p)))
mf.to_csv('MANIFEST_final.csv', index=False, lineterminator='\n')
print('sales', len(s), 'dropped', len(d), 'real POS lines identical;', 'manifest refreshed')
