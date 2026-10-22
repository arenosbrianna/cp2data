"""GrabFood above dine-in in 2021 (2026-10-22, user requirement), enforced on the FINAL sales after the stock build (the build adds dine-in lines, so a share set earlier does not survive).
Dine-In lines of Sep-Dec 2021 are converted to GrabFood lines of the same dish and day (price and discount x 1.25, the GrabFood markup) until each month reaches its target share of paid net sales. Quantities do not change, so
consumption, stock and waste stay consistent with sales. Run before dedupe_sales_lines.py.   Usage (package folder): py enforce_covid_channel_mix.py datasets"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '07_sales_shaping')); import gf_rebalance as g
D = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'; S = pd.read_csv(D + 'sales.csv', parse_dates=['sale_date']); M = pd.read_csv(D + 'menu_items.csv'); gfi = set(M.item_id[M.category == 'GrabFood'])
T21 = {'2021-09': 0.64, '2021-10': 0.64, '2021-11': 0.63, '2021-12': 0.62}
before = S[S.is_revenue & (S.net_sales > 0) & (S.sale_date.dt.year == 2021)].net_sales.sum(); units = S.quantity_sold.sum()
import gf_listings as gl, price_sources as ps
Mi = M.set_index('item_id'); lm = gl.same_name_map(Mi, pd.read_csv(D + 'recipes.csv')); pm, gr = ps.build_price_map(S, Mi); lp = {int(L): ps.price_for(pm, gr, Mi, L, 'GrabFood') for L in Mi.index[Mi.category == 'GrabFood']}      # same-name listing with the identical recipe: ingredient use does not change
S, log = g.rebalance(S, np.random.default_rng(20261023), gfi, False, T21, lm, lp); S['sale_date'] = S.sale_date.dt.strftime('%Y-%m-%d')
assert S.quantity_sold.sum() == units
S.to_csv(D + 'sales.csv', index=False, lineterminator='\n'); r = S[S.is_revenue & (S.net_sales > 0) & (S.sale_date < '2022-01-01')]
print('channel mix 2021 (share, lines converted):', log, '| 2021 paid net', round(before), '->', round(r.net_sales.sum()), '| GrabFood', round(r[r.channel == 'GrabFood'].net_sales.sum()), 'vs Dine-In', round(r[r.channel != 'GrabFood'].net_sales.sum()))
