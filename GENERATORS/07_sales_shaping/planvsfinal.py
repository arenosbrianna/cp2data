import json, pandas as pd, numpy as np
plan = json.load(open('plan_log.json')); s = pd.read_csv('generated_v4/sales.csv', parse_dates=['sale_date']); r = s[s.is_revenue & (s.net_sales > 0)]; d = r.groupby('sale_date').net_sales.sum()
fin = d.groupby(d.index.to_period('M')).mean(); rows = []
for m, v in plan.items():
    p = pd.Period(m)
    if p >= pd.Period('2022-01') and p in fin.index: rows.append((p, v['target'], fin[p]))
t = pd.DataFrame(rows, columns=['m', 'plan', 'final']).set_index('m'); t['r'] = t.final / t.plan
print('final / plan per open day by year (mean ratio, worst month deviation):', {int(y): (round(g.r.mean(), 3), round(float(g.r.sub(1).abs().max()), 3)) for y, g in t.groupby(t.index.year)})
print('plan level by year (PHP k per open day, mean of months):', {int(y): round(g.plan.mean() / 1e3, 2) for y, g in t.groupby(t.index.year)}, '| final:', {int(y): round(g.final.mean() / 1e3, 2) for y, g in t.groupby(t.index.year)})
