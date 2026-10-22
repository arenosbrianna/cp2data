"""v10: regulated policy (shortage weight 3, late-delivery buffer, no trip cost). Regenerates the stock-side tables and the synthetic sales with the optimiser (v6/opt_policy.py) as the ordering policy, now with the corrected
expected shortage cost (v8/penalty_v8.py: recovery-adjusted, recipe-based, policy-independent). Shortage weight chosen by the same service-parity rule as v7
(see v8/V8_REPORT.md). The V7 outputs are kept in generated_v4_pre_v8/.
Writes generated_v4/{inventory, inventory_batches, waste, stockout_events, sales, storage_capacity}.csv (same columns as before; none added).
Backup of the previous files: generated_v4_pre_v7/.   Real POS lines (2025-12-01 ..), sales_dropped, calendar, dimensions are not touched."""
import shutil, sys, json
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / 'v6')); sys.path.insert(0, str(HERE.parent / 'v7')); sys.path.insert(0, str(HERE.parent / 'v10')); sys.path.insert(0, str(HERE.parent / 'v8'))
from full_sim10 import World, FullSim, Env, load, SEAM, SEED
from opt_policy import OptPolicy
from s3_shortage_penalty import penalty_table
from penalty_v8 import shortage_costs
from penalty_v10 import planner_cost
BUNDLE_MULT = 155.0 / 120.0
CFG = {'inc': {'PCH': 100.0}, 'bundle_price_mult': BUNDLE_MULT, 'yield': {'PCH': (0.70, 0.06)}}

import os
CU_MULT = float(os.environ.get('CU_MULT', '3.0'))
PKG = HERE.parent; G = PKG / 'generated_v4'; BK = PKG / 'generated_v4_pre_v7'
P_DISCOUNT, DISC_BETA = 0.255, (1.6, 18.0)
BK8 = PKG / 'generated_v4_pre_v10'
if not BK8.exists():                 # keep the v9 package outputs (the comparison baseline) before the first v10 write
    BK8.mkdir()
    for f in ('inventory.csv', 'inventory_batches.csv', 'waste.csv', 'stockout_events.csv', 'sales.csv', 'storage_capacity.csv', 'MANIFEST.csv'):
        shutil.copy2(G / f, BK8 / f)
if not BK.exists():
    BK.mkdir()
    for f in ('inventory.csv', 'inventory_batches.csv', 'waste.csv', 'stockout_events.csv', 'sales.csv', 'storage_capacity.csv', 'MANIFEST.csv'):
        shutil.copy2(G / f, BK / f)

d = load()
# every 'before' input comes from the backup, so the build is repeatable (never reads its own output)
import pandas as pd
d['inv'] = pd.read_csv(BK / 'inventory.csv', parse_dates=['snapshot_date']); d['bat'] = pd.read_csv(BK / 'inventory_batches.csv', parse_dates=['snapshot_date', 'received_date', 'expiry_date'])
d['waste'] = pd.read_csv(BK / 'waste.csv', parse_dates=['waste_date']); d['so'] = pd.read_csv(BK / 'stockout_events.csv', parse_dates=['event_date'])
d['sales'] = pd.read_csv(BK / 'sales.csv', parse_dates=['sale_date'])
W = World(d)
pen = planner_cost(d, bundle_mult=BUNDLE_MULT).planner_cu.to_numpy(); env = Env(d, pen=pen)
sim = FullSim(env, OptPolicy(cu_mult=CU_MULT, guard_shelf_stable=True, lead_z=1.0), W, seed=SEED, cfg=CFG)
inv, bat, wst, ev = sim.tables()
DIAG = HERE / 'diagnostics'; DIAG.mkdir(exist_ok=True)
pd.DataFrame(sim.deliveries).to_csv(DIAG / 'pch_deliveries_seed20261010.csv', index=False)

# ---------------------------------------------------------------- sales: apply the change in served units on synthetic days
sales = pd.read_csv(BK / 'sales.csv', parse_dates=['sale_date'])
menu = d['menu'].set_index('item_id')
real = sales[sales.sale_date >= SEAM].copy(); syn = sales[sales.sale_date < SEAM].copy()
di = {x: k for k, x in enumerate(W.days)}
rng = np.random.default_rng(SEED + 7)
syn['t'] = syn.sale_date.map(di); syn['i'] = syn.item_id.map(W.iidx)
Dr = np.zeros_like(W.served_old)                      # rejected lines (sales_dropped): they consume stock but are not sales lines
for r_ in d['dropped'].itertuples():
    Dr[di[pd.Timestamp(r_.sale_date)], W.iidx[int(r_.item_id)]] += r_.quantity_sold
sold_new = np.maximum(sim.Qs.astype(np.int64) - Dr, 0)
diff = sold_new - W.served_old; diff[W.real_t, :] = 0
cells = list(zip(*np.nonzero(diff)))
groups = {k: v.index.tolist() for k, v in syn.groupby(['t', 'i'])}
new_rows, drop_idx = [], []
for t, i in cells:
    delta = int(diff[t, i]); idx = groups.get((t, i), [])
    if delta > 0 and idx:
        j = next((x for x in idx if syn.at[x, 'channel'] == 'Dine-In'), idx[0]); q0 = syn.at[j, 'quantity_sold']; q1 = q0 + delta
        syn.at[j, 'discount'] = round(syn.at[j, 'discount'] / q0 * q1, 2); syn.at[j, 'quantity_sold'] = q1
        syn.at[j, 'gross_sales'] = round(q1 * syn.at[j, 'unit_price'], 2); syn.at[j, 'net_sales'] = round(syn.at[j, 'gross_sales'] - syn.at[j, 'discount'], 2)
    elif delta < 0 and idx:
        rem = -delta
        for j in sorted(idx, key=lambda x: (syn.at[x, 'channel'] != 'Dine-In', x)):
            if rem <= 0:
                break
            q0 = syn.at[j, 'quantity_sold']; take = min(q0, rem); q1 = q0 - take; rem -= take
            if q1 == 0:
                drop_idx.append(j); continue
            syn.at[j, 'discount'] = round(syn.at[j, 'discount'] / q0 * q1, 2); syn.at[j, 'quantity_sold'] = q1
            syn.at[j, 'gross_sales'] = round(q1 * syn.at[j, 'unit_price'], 2); syn.at[j, 'net_sales'] = round(syn.at[j, 'gross_sales'] - syn.at[j, 'discount'], 2)
        assert rem == 0, (t, i, rem)
    elif delta > 0 and not idx:
        it = int(W.items[i]); m = menu.loc[it]; price = round(float(W.Pm[t, i]), 2)
        ch = 'GrabFood' if m.category == 'GrabFood' else 'Dine-In'
        gross = round(delta * price, 2); disc = round(rng.beta(*DISC_BETA) * gross, 2) if rng.random() < P_DISCOUNT else 0.0
        paid = (not bool(m.is_complimentary)) and m.category != 'Management' and price > 0
        if not paid:
            disc = gross
        new_rows.append(dict(sale_id=0, sale_date=W.days[t], item_id=it, channel=ch, quantity_sold=delta, unit_price=price, gross_sales=gross, discount=disc, net_sales=round(gross - disc, 2), is_revenue=paid))
syn = syn.drop(index=drop_idx).drop(columns=['t', 'i'])
cols = ['sale_id', 'sale_date', 'item_id', 'channel', 'quantity_sold', 'unit_price', 'gross_sales', 'discount', 'net_sales', 'is_revenue']
out = pd.concat([syn[cols], pd.DataFrame(new_rows, columns=cols), real[cols]], ignore_index=True)
out['sale_date'] = pd.to_datetime(out.sale_date)
real_key = out.sale_date >= SEAM
out = out.sort_values(['sale_date', 'item_id', 'channel']).reset_index(drop=True)
# keep the order of the shipped file for real lines (sorted by id there); ids are renumbered 1..n in the sorted order
old_order = real.assign(_k=range(len(real)))[['sale_date', 'item_id', 'channel', 'sale_id']]
out['sale_id'] = np.arange(1, len(out) + 1)
out['sale_date'] = out.sale_date.dt.strftime('%Y-%m-%d')

# ---------------------------------------------------------------- batch ids: contiguous 1..n over the batches that appear in a table (order-preserving, as v5/renumber_ids.py)
bmap = {old: new for new, old in enumerate(sorted(set(bat.batch_id) | set(wst.batch_id)), start=1)}
bat['batch_id'] = bat.batch_id.map(bmap); wst['batch_id'] = wst.batch_id.map(bmap)

# ---------------------------------------------------------------- write
def w(df, name, datecols=()):
    df = df.copy()
    for c in datecols:
        df[c] = pd.to_datetime(df[c]).dt.strftime('%Y-%m-%d')
    df.to_csv(G / name, index=False, lineterminator='\n')

inv['stockout_flag'] = inv.stockout_flag.map({True: 'True', False: 'False'})
w(inv, 'inventory.csv', ['snapshot_date'])
w(bat, 'inventory_batches.csv', ['snapshot_date', 'received_date', 'expiry_date'])
w(wst, 'waste.csv', ['waste_date'])
w(ev, 'stockout_events.csv', ['event_date'])
out['is_revenue'] = out.is_revenue.map({True: 'True', False: 'False', 'True': 'True', 'False': 'False'})
out.to_csv(G / 'sales.csv', index=False, lineterminator='\n')

# storage_capacity.csv: derived baseline columns recomputed on the new stock (same columns)
cap = pd.read_csv(BK / 'storage_capacity.csv'); vol = d['vol'].set_index('ingredient_id').litres_per_base_unit; ing = d['ing'].set_index('ingredient_id')
inv2 = pd.read_csv(G / 'inventory.csv'); inv2['l'] = inv2.closing_qty * inv2.ingredient_id.map(vol); inv2['st'] = inv2.ingredient_id.map(ing.storage_type)
dly = inv2.groupby(['snapshot_date', 'st']).l.sum().unstack()
for k, r in cap.iterrows():
    s_ = dly[r.storage_type]
    cap.at[k, 'baseline_stock_p95_l'] = round(float(np.percentile(s_, 95)), 1); cap.at[k, 'baseline_stock_max_l'] = round(float(s_.max()), 1)
    cap.at[k, 'baseline_days_above_dedicated'] = int((s_ > r.capacity_dedicated_l).sum())
cap.to_csv(G / 'storage_capacity.csv', index=False, lineterminator='\n')
json.dump(dict(cu_mult=CU_MULT, seed=SEED, sales_rows_old=len(sales), sales_rows_new=len(out), cells_changed=len(cells), rows_added=len(new_rows), rows_dropped=len(drop_idx),
               units_old=int(sales.quantity_sold.sum()), units_new=int(out.quantity_sold.sum()), lost_units_new=int(W.Q.sum() - sim.Qs.sum())), open(HERE / 'build_info_v10.json', 'w'), indent=1)
print(open(HERE / 'build_info_v10.json').read())
