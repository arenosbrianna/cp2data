"""v13 scenario (user decision 2026-10-14): more GrabFood sales, ADDED to the generated years; real POS (>= 2025-12-01) is never touched.
Run AFTER add_weekend_payday.py on the same scratch package (it edits generated_v4_pre_v7/sales.csv, old item ids).
Usage: py add_grabfood.py <scratch package folder>

Volume: per calendar year, GrabFood net sales are raised to TARGET_SHARE of the year's total net sales by adding lines (x = (s*T - G) / (1 - s)).
Days: lines are spread over the open generated days in proportion to each day's net sales (so weekend / payday days get more).
Dishes (spread, mirrors the real GrabFood mix): 85 % of new lines are GrabFood-menu listings (real POS: 83-85 % of GrabFood net sales), drawn with weights ~ sqrt(popularity)
(flattened so no single dish dominates), 15 % are regular dishes drawn with weights ~ their overall demand, sold at list price x 1.25 (the GrabFood markup rule).
Only dishes with sales within +-120 days of the day are used (menu lifecycle), prices come from the same window, quantity 1 (97 %) or 2, discount drawn from the existing GrabFood lines."""
import sys
import numpy as np
import pandas as pd

PK = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'
TARGET_SHARE = 0.063
P_GF_LISTING, P_QTY2 = 0.85, 0.03
SEAM = pd.Timestamp('2025-12-01'); rng = np.random.default_rng(20261015)
s = pd.read_csv(PK + 'generated_v4_pre_v7/sales.csv', parse_dates=['sale_date'])
M = pd.read_csv(PK + 'generated_v4/menu_items.csv').set_index('item_id')
R = pd.read_csv(PK + 'generated_v4/recipes.csv')
syn = s[s.sale_date < SEAM]; rev = syn[syn.is_revenue & (syn.net_sales > 0)].copy()
gf_items = set(M.index[M.category == 'GrabFood'])
sellable = set(M.index[(M.category != 'Management') & (~M.is_complimentary) & (M.list_price > 0)]) & set(R.item_id)
grab = rev[rev.channel == 'GrabFood']
disc_frac = (grab[grab.discount > 0].discount / grab[grab.discount > 0].gross_sales).to_numpy()
P_DISC = float((grab.discount > 0).mean())
# popularity
pop_all = rev.groupby('item_id').quantity_sold.sum()
pop_gf = rev[rev.item_id.isin(gf_items)].groupby('item_id').quantity_sold.sum()
by_item = {i: g.sort_values('sale_date') for i, g in rev.groupby('item_id')}
gf_list = sorted(i for i in gf_items if i in sellable and i in by_item)
reg_list = sorted(i for i in sellable if i not in gf_items and i in by_item)


def active(i, d, w=120):
    g = by_item[i]; lo = g.sale_date.searchsorted(d - pd.Timedelta(days=w)); hi = g.sale_date.searchsorted(d + pd.Timedelta(days=w), side='right')
    return g.iloc[lo:hi]


def price(i, d):
    g = active(i, d)
    if len(g) == 0:
        return None
    if i in gf_items:
        gg = g[g.channel == 'GrabFood']
        p = gg.unit_price.median() if len(gg) else 1.25 * g[g.channel == 'Dine-In'].unit_price.median()
    else:
        dd = g[g.channel == 'Dine-In']; p = 1.25 * (dd.unit_price.median() if len(dd) else g.unit_price.median())
    return round(float(p), 2)


w_gf = np.array([np.sqrt(pop_gf.get(i, 0) + 1.0) for i in gf_list]); w_gf /= w_gf.sum()       # +1: dishes never sold on GrabFood still get a (small) chance
w_rg = np.array([float(pop_all.get(i, 0)) for i in reg_list]); w_rg /= w_rg.sum()
day_net = rev.groupby('sale_date').net_sales.sum()
rows = []
for yr in sorted(day_net.index.year.unique()):
    dn = day_net[day_net.index.year == yr]; T = dn.sum(); G = rev[(rev.sale_date.dt.year == yr) & (rev.channel == 'GrabFood')].net_sales.sum()
    need = (TARGET_SHARE * T - G) / (1 - TARGET_SHARE)
    if need <= 0:
        continue
    got = 0.0
    p_day = (dn / dn.sum()).to_numpy()
    while got < need:
        d = dn.index[rng.choice(len(dn), p=p_day)]
        for _ in range(10):
            if rng.random() < P_GF_LISTING:
                i = int(gf_list[rng.choice(len(gf_list), p=w_gf)])
            else:
                i = int(reg_list[rng.choice(len(reg_list), p=w_rg)])
            p = price(i, d)
            if p is not None and p > 0:
                break
        else:
            continue
        q = 2 if rng.random() < P_QTY2 else 1
        gross = round(q * p, 2); disc = round(float(rng.choice(disc_frac)) * gross, 2) if rng.random() < P_DISC else 0.0
        rows.append(dict(sale_id=0, sale_date=d, item_id=i, channel='GrabFood', quantity_sold=q, unit_price=p, gross_sales=gross, discount=disc, net_sales=round(gross - disc, 2), is_revenue=True))
        got += gross - disc
add = pd.DataFrame(rows)
out = pd.concat([s, add], ignore_index=True)
out = out.sort_values(['sale_date', 'item_id', 'channel'], kind='stable').reset_index(drop=True); out['sale_id'] = np.arange(1, len(out) + 1)
out.to_csv(PK + 'generated_v4_pre_v7/sales.csv', index=False, lineterminator='\n')
print('lines added', len(add), 'net added', round(add.net_sales.sum()), 'dishes', add.item_id.nunique(), 'GrabFood-menu share of added net', round(add[add.item_id.isin(gf_items)].net_sales.sum() / add.net_sales.sum(), 3))
