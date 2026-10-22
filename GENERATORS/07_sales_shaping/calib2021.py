import json, sys, pandas as pd
want = {'2021-09': 39500, '2021-10': 43500, '2021-11': 48000, '2021-12': 52000}; aim = json.load(open('aim2021.json'))
def mm(f): s = pd.read_csv(f, parse_dates=['sale_date']); r = s[s.is_revenue & (s.net_sales > 0)]; return r.groupby(r.sale_date.dt.to_period('M')).net_sales.sum()
fin = mm('generated_v4/sales.csv'); new = {k: aim[k] * want[k] / float(fin[pd.Period(k)]) for k in want}; json.dump(new, open('aim2021.json', 'w')); print('final:', {k: int(fin[pd.Period(k)]) for k in want}, '-> new aim', {k: int(v) for k, v in new.items()})
