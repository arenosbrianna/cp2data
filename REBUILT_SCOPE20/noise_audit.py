"""Noise and learnability audit of datasets/ (2026-10-22): is any table too clean, and do ordinary forecasting methods behave on the generated years as on the real months?
Usage (package folder): py noise_audit.py [datasets]      Prints the numbers; compare 'generated' with 'real' where a real counterpart exists (sales only: Dec 2025 - Sep 2026)."""
import sys, warnings
import numpy as np, pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing
warnings.filterwarnings('ignore')
D = (sys.argv[1] if len(sys.argv) > 1 else 'datasets').rstrip('/') + '/'
S = pd.read_csv(D + 'sales.csv', parse_dates=['sale_date']); R = pd.read_csv(D + 'recipes.csv'); I = pd.read_csv(D + 'ingredients.csv'); INV = pd.read_csv(D + 'inventory.csv', parse_dates=['snapshot_date'])
B = pd.read_csv(D + 'inventory_batches.csv', parse_dates=['snapshot_date', 'received_date', 'expiry_date']); C = pd.read_csv(D + 'calendar_ext.csv', parse_dates=['date']).set_index('date')
sc = set(I.ingredient_id[I.is_perishable.astype(str) == 'True']); P = S[S.is_revenue & (S.net_sales > 0)]; op = C.index[C.is_open.astype(str) == 'True']


def wmape(y, p): return 100 * np.abs(np.asarray(y) - np.asarray(p)).sum() / np.abs(np.asarray(y)).sum()


# 1 recorded use against recipe demand, per ingredient and day (portioning noise)
u = S.merge(R[['item_id', 'ingredient_id', 'qty_base']], on='item_id'); u = u[u.ingredient_id.isin(sc)]; u['q'] = u.quantity_sold * u.qty_base
th = u.groupby([u.sale_date.rename('d'), 'ingredient_id']).q.sum().rename('theo')
X = INV.rename(columns={'snapshot_date': 'd'}).set_index(['d', 'ingredient_id'])[['qty_consumed', 'qty_off_pos_use']].join(th).fillna(0)
r = ((X.qty_consumed - X.qty_off_pos_use) / X.theo.replace(0, np.nan)).dropna()
print(f'1) recorded use / recipe demand per ingredient-day: mean {r.mean():.3f}, SD {r.std():.3f}, 5th-95th percentile {r.quantile(.05):.3f}-{r.quantile(.95):.3f}   (before 2026-10-22: SD 0.023)')
# 2 unit cost per delivery
B1 = B[B.snapshot_date == B.received_date]; cv = B1.groupby('ingredient_id').unit_cost.agg(lambda s: s.std() / s.mean()); ac = []
for _, g_ in B1.groupby('ingredient_id'):
    s_ = g_.set_index('received_date').unit_cost.resample('D').mean().dropna()
    if len(s_) > 200: ac.append(s_.autocorr(1))
print(f'2) unit cost per delivery: CV by ingredient median {cv.median():.3f}; lag-1 autocorrelation median {np.median(ac):.2f} (independent noise = 0; real prices drift in spells; before 2026-10-22: -0.02)')
# 3 gaps between deliveries
rv = INV[INV.qty_received > 0].sort_values(['ingredient_id', 'snapshot_date']); gp = rv.groupby('ingredient_id').snapshot_date.diff().dt.days
print(f'3) days between deliveries: CV by ingredient median {(gp.groupby(rv.ingredient_id).std() / gp.groupby(rv.ingredient_id).mean()).median():.2f}')
# 3b shelf life per batch, deliveries, waste mix
B0 = B.drop_duplicates('batch_id'); off = (B0.expiry_date - B0.received_date).dt.days + 1 - B0.ingredient_id.map(I.set_index('ingredient_id').shelf_life_days)
print(f'3b) shelf life of a batch vs nominal (-1 / 0 / +1 day): {(off == -1).mean():.2f} / {(off == 0).mean():.2f} / {(off == 1).mean():.2f}; receipts / orders {INV.qty_received.sum() / INV.order_qty.sum():.3f} (short or rejected deliveries); waste value by reason: ' + str((100 * pd.read_csv(D + 'waste.csv').groupby('waste_reason').waste_value_php.sum() / pd.read_csv(D + 'waste.csv').waste_value_php.sum()).round(1).to_dict()) + ' %')
# 3c prices of the generated years against the sources (real POS price points / menu list price, GrabFood x 1.25)
M_ = pd.read_csv(D + 'menu_items.csv').set_index('item_id'); P_ = S[S.is_revenue & (S.net_sales > 0)].copy(); P_['lp'] = P_.item_id.map(M_.list_price); rp_ = P_[P_.sale_date >= '2025-12-01'].groupby(['item_id', 'channel']).unit_price.agg(lambda s: set(s.round(2)))
g_ = P_[P_.sale_date < '2025-12-01']; ok_ = [(round(r.unit_price, 2) in rp_.get((r.item_id, r.channel), set())) or abs(r.unit_price - r.lp) < 0.01 or abs(r.unit_price - r.lp * 1.25) < 0.01 for r in g_.itertuples()]
print(f'3c) generated paying lines priced from the real POS or the menu table: {100 * np.mean(ok_):.1f} % (before 2026-10-22: 56.8 %)')
# 4 dish-day dispersion (variance / mean), 1 = Poisson
pay = P[P.channel == 'Dine-In']; top = pay.groupby('item_id').quantity_sold.sum().nlargest(20).index


def disp(a, b):
    days = op[(op >= a) & (op < b)]; out = []
    for i in top:
        s = pay[(pay.item_id == i) & (pay.sale_date >= a) & (pay.sale_date < b)].groupby('sale_date').quantity_sold.sum().reindex(days).fillna(0)
        if s.mean() > 0: out.append(s.var() / s.mean())
    return np.median(out)


print(f"4) dish-day dispersion, top-20 dishes: real {disp('2025-12-01', '2026-09-09'):.2f} | generated 2023 {disp('2023-01-01', '2024-01-01'):.2f}, 2024 {disp('2024-01-01', '2025-01-01'):.2f}, 2025 {disp('2025-01-01', '2025-12-01'):.2f}")
# 5 daily and weekly forecasting skill


def daily(df): return df.groupby('sale_date').net_sales.sum().reindex(op).dropna()


def day_test(y, h, label):
    tr, te = y[:-h], y[-h:]; a4 = (y.shift(7) + y.shift(14) + y.shift(21) + y.shift(28)) / 4; hw = ExponentialSmoothing(np.log(tr.values), seasonal='add', seasonal_periods=7).fit()
    print(f'   {label}: mean {wmape(te, np.full(h, tr.mean())):.0f} % | last week {wmape(te, y.shift(7)[-h:]):.0f} % | mean of last 4 same weekdays {wmape(te, a4[-h:]):.0f} % | Holt-Winters {wmape(te.values, np.exp(hw.forecast(h))):.0f} %')


print('5) daily net sales, test WMAPE (a lower number than the plain mean = skill):')
day_test(daily(P[(P.sale_date >= '2023-01-01') & (P.sale_date < '2025-12-01')]), 90, 'generated 2023-01..2025-11, last 90 days'); day_test(daily(P[P.sale_date >= '2025-12-01']), 60, 'real Dec 2025..Sep 2026, last 60 days')


def week_test(y, h, label):
    tr, te = y[:-h], y[-h:]; hist = list(tr.values); f = []
    for t in te.values: f.append(np.mean(hist[-4:])); hist.append(t)
    print(f'   {label}: mean {wmape(te, np.full(h, tr.mean())):.0f} % | rolling mean of last 4 weeks {wmape(te, f):.0f} %')


wk = lambda df: df.set_index('sale_date').net_sales.resample('W-SUN').sum()
print('6) weekly net sales, test WMAPE:')
week_test(wk(P[(P.sale_date >= '2022-09-01') & (P.sale_date < '2025-12-01')]), 13, 'generated, last 13 weeks'); week_test(wk(P[(P.sale_date >= '2025-12-01') & (P.sale_date < '2026-09-07')]), 8, 'real, last 8 weeks')
