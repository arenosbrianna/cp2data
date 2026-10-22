"""Monthly correction ratios from the PLAN (not from final / pre-build): rho_new = rho_old x final / plan, so that after the phases that run after the monthly scaling (storm days, December eves, Nov / Dec window, day noise) and the stock build
every month lands on its plan. Usage: py update_ratios_plan.py <prev ratios.json> <out ratios.json>   (reads plan_log.json and generated_v4/sales.csv in the current folder)"""
import json, sys
import pandas as pd
prev = json.load(open(sys.argv[1])); plan = json.load(open('plan_log.json'))
s = pd.read_csv('generated_v4/sales.csv', parse_dates=['sale_date']); r = s[s.is_revenue & (s.net_sales > 0)]; d = r.groupby('sale_date').net_sales.sum(); fin = d.groupby(d.index.to_period('M')).mean()
out = dict(prev); worst = 0.0
for m, v in plan.items():
    p = pd.Period(m)
    if p < pd.Period('2022-01') or p not in fin.index: continue
    q = float(fin[p]) / v['target']; worst = max(worst, abs(q - 1)); out[m] = min(1.6, max(0.5, float(prev.get(m, 1.0)) * q))
json.dump(out, open(sys.argv[2], 'w')); print('plan-based ratios written; worst month deviation from plan before this update:', round(worst, 3))
