"""v11: regulated policy (shortage weight 2, 95 % par level, late-delivery buffer, no trip cost). Regenerates the stock-side tables and the synthetic sales with the optimiser (v6/opt_policy.py) as the ordering policy, now with the corrected
expected shortage cost (v8/penalty_v8.py: recovery-adjusted, recipe-based, policy-independent). Shortage weight chosen by the same service-parity rule as v7
(see v8/V8_REPORT.md). The V7 outputs are kept in generated_v4_pre_v8/.
Writes generated_v4/{inventory, inventory_batches, waste, stockout_events, sales, storage_capacity}.csv (same columns as before; none added).
Backup of the previous files: generated_v4_pre_v7/.   Real POS lines (2025-12-01 ..), sales_dropped, calendar, dimensions are not touched."""
import shutil, sys, json
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / 'v6')); sys.path.insert(0, str(HERE.parent / 'v7')); sys.path.insert(0, str(HERE.parent / 'v11')); sys.path.insert(0, str(HERE.parent / 'v8'))
from full_sim10 import World, FullSim, Env, load, SEAM, SEED
import os as _o; SEED = int(_o.environ.get('SEEDX', SEED))
from opt_policy import OptPolicy
from s3_shortage_penalty import penalty_table
from penalty_v8 import shortage_costs
from penalty_v10 import planner_cost
BUNDLE_MULT = 1.0                     # one HI-TOP price for pechay: the client's PHP 120 per gross kg (SUPPLY-UR row 69), pro-rata for bundles
CFG = {'inc': {'PCH': 100.0}, 'bundle_price_mult': BUNDLE_MULT, 'yield': {'PCH': (0.70, 0.06)}}

import os
CU_MULT = float(os.environ.get('CU_MULT', '2.0'))
PKG = HERE.parent; G = PKG / 'generated_v4'; BK = PKG / 'generated_v4_pre_v7'
P_DISCOUNT, DISC_BETA = 0.255, (1.6, 18.0)
BK8 = PKG / 'generated_v4_pre_v11'
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
if not (BK / 'sales_dropped.csv').exists():
    shutil.copy2(PKG / 'generated_v4_v11_first_build' / 'sales_dropped.csv', BK / 'sales_dropped.csv')
d['dropped'] = pd.read_csv(BK / 'sales_dropped.csv')          # the original rejected lines (never read from this build's own output)
W = World(d)
# v12 step 8 (assumption, to confirm with the client): HI-TOP is a walk-in supermarket (the client confirmed small bundles for pechay), so its fresh produce and short-life items are bought by the portion,
# not in the SUPPLY-UR pack: 100 g steps for gram items, one piece / serving for count items. supplier_item_terms keeps the client pack.
_ing = d['ing'].set_index('ingredient_code'); _t = d['terms'].set_index('ingredient_id'); _sup = d['sup'].set_index('supplier_id')
PORTIONS = {}
for _c, _r in _ing.iterrows():
    if _c == 'PCH':
        continue
    if _sup.loc[int(_t.loc[_r.ingredient_id, 'supplier_id']), 'supplier_name'] == 'HI-TOP' and _r.shelf_life_days <= 60:
        _pk = float(_t.loc[_r.ingredient_id, 'pack_size_base']); PORTIONS[_c] = min(_pk, 100.0) if _r.base_uom in ('g', 'ml') else 1.0
if os.environ.get('PORTIONS') == '0':
    PORTIONS = {}
# v14 waste regulation (team choice B, 2026-10-16; assumption to confirm with the client): items whose supplier pack outlasts their demand are bought in smaller portions from the same supplier (cheese 2 slices, Ebiko (EBK) 100 g, peeled deveined shrimp (PDT) 5 pieces; salmon and tuna stay whole fish: client practice, a PHP 5k purchase once or twice a month each); EXTRA_PORTIONS='' reproduces the pre-regulation build
for _kv in filter(None, os.environ.get('EXTRA_PORTIONS', 'CHE:2,EBK:100,PDT:5').split(',')):
    PORTIONS[_kv.split(':')[0]] = float(_kv.split(':')[1])
print('PORTIONS', PORTIONS)
pen = planner_cost(d, bundle_mult=BUNDLE_MULT).planner_cu.to_numpy(); env = Env(d, pen=pen, pack_alt=PORTIONS)
kb = int(np.flatnonzero(env.code == 'PCH')[0]); env.pack = env.pack.copy(); env.moq_packs = env.moq_packs.copy(); env.pack[kb] = 100.0; env.moq_packs[kb] = 1.0; env.moq = env.moq_packs * env.pack      # pechay is bought at HI-TOP in 100 g (usable-equivalent) bundles, planned and same-day
# v14 client practice (2026-10-16): whole salmon is bought as a PHP ~5k purchase once or twice a month (SAL_MOQ whole fish per order; 1 = earlier build)
_ks = int(np.flatnonzero(env.code == 'SAL')[0]); env.moq_packs[_ks] = float(os.environ.get('SAL_MOQ', '1')); env.moq = env.moq_packs * env.pack
# v12 staple rule (user decision 2026-10-13): every ingredient is kept on hand (floor of packs one delivery cycle ahead) except pechay (100 g bundles, own rule) and whole tuna (one PHP 5,000 fish);
# env STAPLES overrides: comma list of codes, or empty for none (reproduces the v11 build byte for byte)
_s = os.environ.get('STAPLES')
STAPLES = tuple(c for c in env.code if c not in ('PCH', 'TUN')) if _s is None else tuple(x for x in _s.split(',') if x)
sim = FullSim(env, OptPolicy(cu_mult=CU_MULT, guard_shelf_stable=True, lead_z=1.0, par_alpha=float(os.environ.get('PAR_ALPHA', '0.05')), staples=STAPLES), W, seed=SEED, cfg=CFG)
inv, bat, wst, ev = sim.tables()
print('POLICY STATS', {k: v for k, v in sim.policy.stats.items() if 'staple' in k or 'solves' in k})
DIAG = HERE / 'diagnostics'; DIAG.mkdir(exist_ok=True)
pd.DataFrame(sim.deliveries).to_csv(DIAG / 'pch_deliveries_seed20261010.csv', index=False)

# ---------------------------------------------------------------- sales: apply the change in served units on synthetic days
sales = pd.read_csv(BK / 'sales.csv', parse_dates=['sale_date'])
menu = d['menu'].set_index('item_id')
real = sales[sales.sale_date >= SEAM].copy(); syn = sales[sales.sale_date < SEAM].copy()
di = {x: k for k, x in enumerate(W.days)}
rng = np.random.default_rng(SEED + 7)
GF_ITEMS = set(menu.index[menu.category == 'GrabFood'])
MARKUP_ITEMS = set(sales[(sales.sale_date < SEAM) & (sales.channel == 'Dine-In') & sales.item_id.isin(GF_ITEMS)].item_id)     # GrabFood-category dishes that the generator sold at Dine-In price
syn['t'] = syn.sale_date.map(di); syn['i'] = syn.item_id.map(W.iidx)
Dr = np.zeros_like(W.served_old)                      # rejected lines (sales_dropped): they consume stock but are not sales lines
for r_ in d['dropped'].itertuples():
    Dr[di[pd.Timestamp(r_.sale_date)], W.iidx[int(r_.item_id)]] += r_.quantity_sold
lost_new = (W.Q - sim.Qs).astype(np.int64); lost_new[W.real_t, :] = 0
drop_lost = np.minimum(lost_new, Dr); sold_lost = lost_new - drop_lost            # lost units are taken from rejected lines first
sold_new = (W.Q - Dr) - sold_lost
diff = sold_new - W.served_old; diff[W.real_t, :] = 0
cells = list(zip(*np.nonzero(diff)))
groups = {k: v.index.tolist() for k, v in syn.groupby(['t', 'i'])}
new_rows, drop_idx = [], []
for t, i in cells:
    delta = int(diff[t, i]); idx = groups.get((t, i), [])
    has_dine = any(syn.at[x, 'channel'] == 'Dine-In' for x in idx)      # v13: served units are added to a Dine-In line only; a cell that has only GrabFood lines gets a new row (no stacking of GrabFood quantities)
    if delta > 0 and idx and has_dine:
        j = next(x for x in idx if syn.at[x, 'channel'] == 'Dine-In'); q0 = syn.at[j, 'quantity_sold']; q1 = q0 + delta
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
    elif delta > 0 and not has_dine:
        it = int(W.items[i]); m = menu.loc[it]; price = round(float(W.Pm[t, i]), 2)
        ch = 'GrabFood' if (m.category == 'GrabFood' and it not in MARKUP_ITEMS) else 'Dine-In'      # dishes listed under GrabFood but priced at Dine-In level are re-channelled below
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
# ---- channel normalisation (synthetic days only; real lines are never touched)
syn_m = out.sale_date < SEAM
def _reprice(df, f):
    df['unit_price'] = (df.unit_price * f).round(2); df['gross_sales'] = (df.quantity_sold * df.unit_price).round(2)
    df['discount'] = np.where(df.is_revenue, np.minimum((df.discount * f).round(2), df.gross_sales), df.gross_sales); df['net_sales'] = (df.gross_sales - df.discount).round(2)
    return df
A = syn_m & (out.channel == 'Dine-In') & out.item_id.isin(GF_ITEMS)
a_rows = _reprice(out[A].copy(), 1.25); a_rows['channel'] = 'GrabFood'; out = pd.concat([out[~A], a_rows], ignore_index=True)
real_part = out[out.sale_date >= SEAM]; target = real_part[real_part.is_revenue & (real_part.channel == 'GrabFood')].net_sales.sum() / real_part[real_part.is_revenue].net_sales.sum()
# per calendar year the synthetic GrabFood revenue share is brought to the real share (the earlier design kept it flat; the relabelled dishes appear in different years)
for yr in ([] if os.environ.get('GF_NORM', '1') == '0' else sorted(out[out.sale_date < SEAM].sale_date.dt.year.unique())):   # v13: GF_NORM=0 keeps the added GrabFood sales (no rebalance to the real 3.2 % share)
    ym = (out.sale_date.dt.year == yr) & (out.sale_date < SEAM) & out.is_revenue
    Gs, Ts = out[ym & (out.channel == 'GrabFood')].net_sales.sum(), out[ym].net_sales.sum()
    if Gs > target * Ts:                                  # too much GrabFood: move regular-dish GrabFood lines to Dine-In (price / 1.25); a moved line leaves GrabFood, total falls by 0.2 x
        need = (Gs - target * Ts) / (1 - 0.2 * target); pool = out[ym & (out.channel == 'GrabFood') & ~out.item_id.isin(GF_ITEMS)]; f, new_ch = 1 / 1.25, 'Dine-In'
    else:                                                 # too little: move regular-dish Dine-In lines to GrabFood (price x 1.25): G + 1.25 x, T + 0.25 x
        need = (target * Ts - Gs) / (1.25 - 0.25 * target); pool = out[ym & (out.channel == 'Dine-In') & ~out.item_id.isin(GF_ITEMS)]; f, new_ch = 1.25, 'GrabFood'
    order = rng.permutation(len(pool)); cs = pool.net_sales.to_numpy()[order].cumsum(); take = pool.index[order][: int(np.searchsorted(cs, max(need, 0))) + 1] if need > 0 else []
    mv = _reprice(out.loc[take].copy(), f); mv['channel'] = new_ch; out = pd.concat([out.drop(index=take), mv], ignore_index=True)
# ---- merge duplicate synthetic lines (same day, item, channel, price, revenue flag)
sy = out[out.sale_date < SEAM]; rl = out[out.sale_date >= SEAM]
sy = sy.groupby(['sale_date', 'item_id', 'channel', 'unit_price', 'is_revenue'], as_index=False).agg(sale_id=('sale_id', 'first'), quantity_sold=('quantity_sold', 'sum'), gross_sales=('gross_sales', 'sum'), discount=('discount', 'sum'), net_sales=('net_sales', 'sum'))
for c_ in ('gross_sales', 'discount', 'net_sales'):
    sy[c_] = sy[c_].round(2)
out = pd.concat([sy[cols], rl[cols]], ignore_index=True)
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

# sales_dropped.csv: rejected lines that were not served because of a shortage are reduced (synthetic days only)
dr_new = d['dropped'].copy(); red = {(int(t_), int(i_)): int(drop_lost[t_, i_]) for t_, i_ in zip(*np.nonzero(drop_lost))}
keep = []
for r_ in dr_new.itertuples():
    key = (di[pd.Timestamp(r_.sale_date)], W.iidx[int(r_.item_id)]); q = int(r_.quantity_sold)
    if key in red and red[key] > 0:
        take_ = min(q, red[key]); red[key] -= take_; q -= take_
    keep.append(q)
dr_new['quantity_sold'] = keep; dr_new = dr_new[dr_new.quantity_sold > 0]
assert all(v == 0 for v in red.values()), red
dr_new.to_csv(G / 'sales_dropped.csv', index=False, lineterminator='\n')
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
    s_ = dly[r.storage_type] if r.storage_type in dly.columns else pd.Series(0.0, index=dly.index)          # v14: a storage type can hold no in-scope ingredient (ambient)
    cap.at[k, 'baseline_stock_p95_l'] = round(float(np.percentile(s_, 95)), 1); cap.at[k, 'baseline_stock_max_l'] = round(float(s_.max()), 1)
    cap.at[k, 'baseline_days_above_dedicated'] = int((s_ > r.capacity_dedicated_l).sum())
cap.to_csv(G / 'storage_capacity.csv', index=False, lineterminator='\n')
json.dump(dict(cu_mult=CU_MULT, seed=SEED, sales_rows_old=len(sales), sales_rows_new=len(out), cells_changed=len(cells), rows_added=len(new_rows), rows_dropped=len(drop_idx),
               units_old=int(sales.quantity_sold.sum()), units_new=int(out.quantity_sold.sum()), lost_units_new=int(W.Q.sum() - sim.Qs.sum())), open(HERE / 'build_info_v11.json', 'w'), indent=1)
print(open(HERE / 'build_info_v11.json').read())
