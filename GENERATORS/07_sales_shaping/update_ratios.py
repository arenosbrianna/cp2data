"""Writes ratios.json = final / pre-build monthly mean net per open day (paid lines) from a scratch package. Usage: py update_ratios.py <scratch pkg> <out.json>"""
import json, sys, pandas as pd
PK = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'
def mm(f):
    s = pd.read_csv(f, parse_dates=['sale_date']); r = s[s.is_revenue & (s.net_sales > 0)]; d = r.groupby('sale_date').net_sales.sum(); return d.groupby(d.index.to_period('M')).mean()
a, b = mm(PK + 'generated_v4/sales.csv'), mm(PK + 'generated_v4_pre_v7/sales.csv'); json.dump({str(p): float(a[p] / b[p]) for p in b.index if p in a.index}, open(sys.argv[2], 'w'))
