"""v14 LEVEL-NEUTRAL version of v13/add_weekend_payday.py (audit option A, 2026-10-15): after the weekend / payday lines are added, ordinary Dine-In regular-menu lines are removed at random inside every synthetic month until that month's net sales equal the pre-lift total. The lifts therefore reshape each month (weekends and paydays up, other days down) without raising its level. Real POS lines are never touched.
v13 scenario (user decision 2026-10-14): more sales on paydays and weekends, ADDED to the generated sales; the real POS (>= 2025-12-01) is never touched.
Input: the pre-loss sales of the stock rebuild (scratch generated_v4_pre_v7/sales.csv, old item ids). For every open synthetic day with a lift, extra revenue lines are cloned
from revenue lines of the same synthetic period (+-30 days, same price era, channel, discount, quantity), until the day's extra net sales reach (lift x the day's net sales).
Usage: py add_weekend_payday.py <scratch package folder>"""
import os, sys, numpy as np, pandas as pd
PK = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'
SAT, SUN, PAY = 0.20, 0.35, 0.15            # extra share of the day's sales on Saturday, Sunday, and on a payday (15th, month-end = dim_date.is_payday); multiplied when they coincide
SEAM = pd.Timestamp('2025-12-01'); rng = np.random.default_rng(20261014 + int(os.environ.get('SCEN', '0')))
s = pd.read_csv(PK + 'generated_v4_pre_v7/sales.csv', parse_dates=['sale_date'])
cal = pd.read_csv(PK + 'generated_v4/calendar_ext.csv', parse_dates=['date']).set_index('date')
syn = s[(s.sale_date < SEAM)]
M = pd.read_csv(PK + 'generated_v4/menu_items.csv').set_index('item_id')
rev = syn[syn.is_revenue & (syn.net_sales > 0)]
clone_ok = (rev.channel == 'Dine-In') & (rev.item_id.map(M.category) != 'GrabFood')      # v13 final: clones are Dine-In regular-menu lines only (the GrabFood channel is generated separately)
day_net = rev.groupby('sale_date').net_sales.sum()
rows = []
for d, net in day_net.items():
    dow = d.dayofweek; lift = (1 + (SAT if dow == 5 else SUN if dow == 6 else 0)) * (1 + (PAY if bool(cal.at[d, 'is_payday']) else 0)) - 1
    if lift <= 0:
        continue
    target = lift * net
    pool = rev[clone_ok & (rev.sale_date >= d - pd.Timedelta(days=30)) & (rev.sale_date <= d + pd.Timedelta(days=30)) & (rev.sale_date != d)]
    order = rng.permutation(len(pool)); cs = pool.net_sales.to_numpy()[order].cumsum()
    k = int(np.searchsorted(cs, target)); k = k + 1 if (k < len(cs) and abs(cs[k] - target) < abs(cs[k - 1] - target if k else target)) else k
    pick = pool.iloc[order[:max(k, 1)]].copy(); pick['sale_date'] = d; rows.append(pick)
add = pd.concat(rows, ignore_index=True)
out = pd.concat([s, add], ignore_index=True)
# ---- v14 level-neutral thinning (random whole Dine-In regular-menu lines, same month, until the month's net equals its pre-lift total)
if os.environ.get('LEVEL_NEUTRAL', '1') == '1':
    rng2 = np.random.default_rng(20261015 + int(os.environ.get('SCEN', '0')))
    ym = out.sale_date.dt.to_period('M'); pre_m = s[(s.sale_date < SEAM) & s.is_revenue].groupby(s.sale_date.dt.to_period('M')).net_sales.sum()
    cur_m = out[(out.sale_date < SEAM) & out.is_revenue].groupby(ym[(out.sale_date < SEAM) & out.is_revenue]).net_sales.sum()
    thin = (out.sale_date < SEAM) & out.is_revenue & (out.channel == 'Dine-In') & (out.item_id.map(M.category) != 'GrabFood') & (out.net_sales > 0); drop = []
    for m_, excess in (cur_m - pre_m).items():
        if excess <= 0: continue
        pool = out.index[thin & (ym == m_)].to_numpy(); order = rng2.permutation(pool); cs = out.net_sales.to_numpy()[order].cumsum(); k = int(np.searchsorted(cs, excess))
        k = k + 1 if (k < len(cs) and abs(cs[k] - excess) < abs((cs[k - 1] if k else 0) - excess)) else k; drop += order[:k].tolist()
    print('level-neutral: removed', len(drop), 'lines, net', round(out.net_sales.iloc[drop].sum()), 'of lifted', round((cur_m - pre_m).clip(lower=0).sum())); out = out.drop(index=drop)
out = out.sort_values(['sale_date', 'item_id', 'channel'], kind='stable').reset_index(drop=True); out['sale_id'] = np.arange(1, len(out) + 1)
out.to_csv(PK + 'generated_v4_pre_v7/sales.csv', index=False, lineterminator='\n')
print('days lifted', add.sale_date.nunique(), 'lines added', len(add), 'net added', round(add.net_sales.sum()), 'on synthetic net', round(syn[syn.is_revenue].net_sales.sum()), 'share', round(add.net_sales.sum() / syn[syn.is_revenue].net_sales.sum() * 100, 1), '%')
