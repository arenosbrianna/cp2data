import sys
import numpy as np, pandas as pd
d = sys.argv[1] if len(sys.argv) > 1 else 'generated_v4'
s = pd.read_csv(f'{d}/sales.csv', parse_dates=['sale_date']); r = s[s.is_revenue & (s.net_sales > 0)]
day = r.groupby('sale_date').net_sales.sum(); m = day.groupby(day.index.to_period('M')).mean()
ja = {y: float(np.mean([m[pd.Period(f'{y}-{k:02d}')] for k in range(1, 9)])) for y in (2022, 2023, 2024, 2025, 2026)}
js = {y: float(np.mean([m[pd.Period(f'{y}-{k:02d}')] for k in range(9, 13)])) for y in (2021, 2022, 2023, 2024, 2025)}
print('Jan-Aug mean per open day:', {y: round(v) for y, v in ja.items()})
print('  vs real 2026 (%):', {y: round(100 * (v / ja[2026] - 1), 1) for y, v in ja.items() if y < 2026})
print('Sep-Dec mean per open day:', {y: round(v) for y, v in js.items()})
g = np.array([ja[2023], ja[2024], ja[2025]]); print('  2023-2025 Jan-Aug: slope', round(100 * (np.exp(np.polyfit(np.arange(3), np.log(g), 1)[0]) - 1), 1), '%/yr | spread max/min', round(g.max() / g.min(), 3))
yr = day.groupby(day.index.year).mean(); print('annual mean per open day (raw):', {int(y): round(v) for y, v in yr.items()})
