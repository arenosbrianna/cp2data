"""Builds locked_2021_gf.csv from the shipped 2021 lines: COVID channel mix (GrabFood above dine-in), then each month scaled to the aim in aim2021.json (PHP paid net, before the stock build).
Usage: py gen_lock2021.py [aim2021.json]"""
import sys, json
sys.path.insert(0, '.')
import numpy as np, pandas as pd, gf_rebalance as g
aim = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else g.SALES_2021
lk = pd.read_csv('locked_2021_prebuild.csv', parse_dates=['sale_date']); m = pd.read_csv('generated_v4/menu_items.csv'); gfi = set(m.item_id[m.category == 'GrabFood']); rng = np.random.default_rng(20261022)
import price_sources as ps
_all = pd.read_csv('pre_shape_sales.csv', parse_dates=['sale_date']); _menu = m.set_index('item_id'); _pm, _gr = ps.build_price_map(_all, _menu); lk = ps.apply_prices(lk, _pm, _gr, _menu)      # 2021 prices from the real POS / menu table too
import gf_listings as gl
_lm = gl.same_name_map(_menu, pd.read_csv('generated_v4/recipes.csv')); _lp = {int(L): ps.price_for(_pm, _gr, _menu, L, 'GrabFood') for L in _menu.index[_menu.category == 'GrabFood']}
S, _ = g.rebalance(lk, rng, gfi, True, {k: v for k, v in g.GF_TARGET.items() if k < '2022'}, _lm, _lp)
S, _nm = gl.remap_to_listings(S, _menu, _all, rng, ps, _pm, _gr, S.sale_date < '2022-01-01', name_map=_lm); print('2021 GrabFood lines moved onto listings:', _nm)
for ym, t in aim.items(): S, _ = g.scale_month(S, ym, t, rng)
# 2026-10-22 (user): staff meals scale with the business. The shipped 2021 lines carry 1.4 staff units a day on only about 5 paying units a day (26 %); aim at about half a unit a day (the same floor as the 2022 ramp).
npay = ~(S.is_revenue & (S.net_sales > 0)); target_u = int(round(0.5 * S.sale_date.nunique())); idx = S.index[npay].to_numpy(); order = rng.permutation(idx); cs = S.quantity_sold[order].cumsum().to_numpy(); keep = set(order[cs <= target_u].tolist())
S = S.drop(index=[i for i in idx if i not in keep]); print('2021 staff / non-paying units kept:', int(S.quantity_sold[~(S.is_revenue & (S.net_sales > 0))].sum()), 'of target', target_u)
S = S.sort_values('sale_date', kind='stable').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1); S.to_csv('locked_2021_gf.csv', index=False, lineterminator='\n')
r = S[S.is_revenue & (S.net_sales > 0)]; print('lock input monthly paid net:', {str(k): int(v) for k, v in r.groupby(r.sale_date.dt.to_period('M')).net_sales.sum().items()})
