"""One line per sale date x dish x channel x revenue flag in the generated years (2026-10-22, user: there can be no duplicate sale lines).
The generator can leave two lines of the same dish, channel and day, usually at two prices of a price-history window (e.g. 180 and 190 PHP). A POS does not sell one dish at two prices on one day, so each such group is merged into ONE line:
all lines take the price of the largest-quantity line (ties: the higher price), gross = quantity x price, the discount amounts are kept (capped at gross), net = gross - discount; quantities are summed, so consumption, inventory and waste are unchanged.
Real POS lines (sale_date >= 2025-12-01) are never touched. A paid line and a complimentary line of the same dish and day (different is_revenue) are different lines and stay apart. sale_id is renumbered in the canonical order of port_scope_rebuild.py.
Usage (package folder): py dedupe_sales_lines.py datasets"""
import sys
import numpy as np, pandas as pd
D = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'; SEAM = '2025-12-01'
s = pd.read_csv(D + 'sales.csv'); n0, net0 = len(s), s.net_sales.sum(); key = ['sale_date', 'item_id', 'channel', 'is_revenue']
gen = s.sale_date < SEAM; dup = gen & s.duplicated(key, keep=False)
rows = []; repriced = 0
for _, g in s[dup].groupby(key):
    g = g.sort_values(['quantity_sold', 'unit_price'], ascending=[False, False]); p = float(g.unit_price.iloc[0]); repriced += int(g.unit_price.nunique() > 1)
    q = int(g.quantity_sold.sum()); gross = round(q * p, 2); disc = min(round(float(g.discount.sum()), 2), gross)
    rows.append(dict(sale_id=0, sale_date=g.sale_date.iloc[0], item_id=g.item_id.iloc[0], channel=g.channel.iloc[0], quantity_sold=q, unit_price=p, gross_sales=gross, discount=disc, net_sales=round(gross - disc, 2), is_revenue=g.is_revenue.iloc[0]))
out = pd.concat([s[~dup]] + ([pd.DataFrame(rows)[list(s.columns)]] if rows else []), ignore_index=True)      # no groups to merge once every dish has one price per channel and day
out = out.sort_values(['sale_date', 'item_id', 'channel', 'is_revenue', 'unit_price', 'quantity_sold', 'gross_sales', 'discount', 'net_sales'], kind='stable').reset_index(drop=True); out['sale_id'] = range(1, len(out) + 1)
assert out.quantity_sold.sum() == s.quantity_sold.sum() and not out[out.sale_date < SEAM].duplicated(key).any()
out.to_csv(D + 'sales.csv', index=False, lineterminator='\n')
print(f'groups merged {len(rows)} (with two prices: {repriced}); lines {n0} -> {len(out)}; units unchanged {int(out.quantity_sold.sum())}; net sales PHP {net0:,.2f} -> {out.net_sales.sum():,.2f}; real POS lines untouched')
