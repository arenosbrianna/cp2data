"""Independent consistency audit of datasets/ (sales, recipes, inventory, batches, waste, stockouts). Pure pandas, no database, separate from the checks in 03_transform.sql.
Usage (package folder): py audit_consistency.py [datasets]      Exit code 1 if any check fails."""
import sys
import numpy as np, pandas as pd
D = (sys.argv[1] if len(sys.argv) > 1 else 'datasets').rstrip('/') + '/'
rd = lambda f, **k: pd.read_csv(D + f + '.csv', **k)
S = rd('sales', parse_dates=['sale_date']); R = rd('recipes'); I = rd('ingredients'); INV = rd('inventory', parse_dates=['snapshot_date']); B = rd('inventory_batches', parse_dates=['snapshot_date', 'received_date', 'expiry_date'])
W = rd('waste', parse_dates=['waste_date']); SO = rd('stockout_events', parse_dates=['event_date']); DR = rd('sales_dropped', parse_dates=['sale_date']); CAL = rd('calendar_ext', parse_dates=['date']).set_index('date'); M = rd('menu_items')
res = []


def check(name, ok, detail=''):
    res.append((name, bool(ok), detail)); print(('PASS  ' if ok else 'FAIL  ') + name + (('  | ' + detail) if detail else ''))


SEAM = pd.Timestamp('2025-12-01'); sc = set(I.ingredient_id[I.is_perishable.astype(str) == 'True'])
# ---------------------------------------------------------------- sales
k = ['sale_date', 'item_id', 'channel', 'unit_price', 'is_revenue']
check('S1 no duplicate sale lines (date, dish, channel, price, revenue flag)', not S.duplicated(k).any())
g = S[S.sale_date < SEAM]; check('S2 generated years: one line per date x dish x channel x revenue flag', not g.duplicated(['sale_date', 'item_id', 'channel', 'is_revenue']).any())
check('S3 gross - discount = net, quantity > 0, discount <= gross', (abs(S.net_sales - (S.gross_sales - S.discount)) <= 0.02).all() and (S.quantity_sold > 0).all() and (S.discount <= S.gross_sales + 0.005).all())
check('S4 sale_id contiguous 1..n and unique', list(S.sale_id) == list(range(1, len(S) + 1)))
check('S5 every sold dish is on the menu; every sale date is in the calendar', S.item_id.isin(M.item_id).all() and S.sale_date.isin(CAL.index).all())
op = CAL.is_open.astype(str).eq('True'); check('S6 sales only on open days', S.sale_date.map(op).all(), f"{int((~S.sale_date.map(op)).sum())} lines on closed days")
# ---------------------------------------------------------------- recipe use vs consumption
rc = R[['item_id', 'ingredient_id', 'qty_base']]; use = S.merge(rc, on='item_id'); use['q'] = use.quantity_sold * use.qty_base; theo = use[use.ingredient_id.isin(sc)].groupby(['sale_date', 'ingredient_id']).q.sum().rename('theo').rename_axis(['snapshot_date', 'ingredient_id'])
dr = DR.merge(rc, on='item_id'); dr['q'] = dr.quantity_sold * dr.qty_base; drop = dr[dr.ingredient_id.isin(sc)].groupby(['sale_date', 'ingredient_id']).q.sum().rename('dropped').rename_axis(['snapshot_date', 'ingredient_id'])
X = INV.set_index(['snapshot_date', 'ingredient_id']).join(theo).join(drop).fillna({'theo': 0, 'dropped': 0})
X['implied'] = X.qty_consumed - X.qty_off_pos_use - X.theo - X.dropped        # kitchen variance (prep loss, yield, portioning)
t = X.groupby('ingredient_id').agg(theo=('theo', 'sum'), imp=('implied', 'sum')); t['pct'] = 100 * t.imp / t.theo
check('C1 kitchen variance per ingredient between 0 and 10 % of recipe use (all years)', ((t.pct >= -0.1) & (t.pct <= 10)).all(), f"range {t.pct.min():.1f} .. {t.pct.max():.1f} %, overall {100 * t.imp.sum() / t.theo.sum():.1f} %")
Xy = X.reset_index(); Xy['year'] = Xy.snapshot_date.dt.year; ty = Xy.groupby('year').agg(theo=('theo', 'sum'), imp=('implied', 'sum')); ty['pct'] = 100 * ty.imp / ty.theo
check('C2 the variance share is stable across years (no drift between sales and stock)', ty.pct.max() - ty.pct.min() < 3.0, 'by year ' + ', '.join(f'{y}: {v:.1f} %' for y, v in ty.pct.items()))
xm = Xy.assign(m=Xy.snapshot_date.dt.to_period('M')).groupby('m').agg(theo=('theo', 'sum'), cons=('qty_consumed', 'sum')); cr = np.corrcoef(xm.theo, xm.cons)[0, 1]
check('C3 monthly stock use follows monthly sales x recipes (correlation >= 0.98)', cr >= 0.98, f'r = {cr:.4f}')
sd = Xy[Xy.theo > 0]; check('C4 no recipe use on a day without stock recorded (ingredient in scope)', len(sd) == int((Xy.theo > 0).sum()))
oos = use[~use.ingredient_id.isin(sc)]; check('C5 ingredients outside the perishable scope: recipes stay, no stock rows', len(oos) > 0 and not INV.ingredient_id.isin(set(I.ingredient_id) - sc).any() and not B.ingredient_id.isin(set(I.ingredient_id) - sc).any() and not W.ingredient_id.isin(set(I.ingredient_id) - sc).any())
# ---------------------------------------------------------------- inventory ledger
# the load books an expired batch on the ledger day after its last usable day (stg.waste.expired_on_date = expiry + 1); the waste row itself may be dated later when the batch expired during a closure
EXPK = ['over_ordering', 'expiry']; LOSS = ['spoilage', 'shrinkage']
W['ledger_day'] = np.where(W.waste_reason.isin(LOSS), W.waste_date, W.batch_id.map(B.groupby('batch_id').expiry_date.first()) + pd.Timedelta(days=1))      # a loss inside the shelf life leaves stock on its own day
INV = INV.merge(W.groupby(['ledger_day', 'ingredient_id']).waste_qty.sum().rename('qty_wasted').rename_axis(['snapshot_date', 'ingredient_id']).reset_index(), on=['snapshot_date', 'ingredient_id'], how='left').fillna({'qty_wasted': 0})
INV = INV.sort_values(['ingredient_id', 'snapshot_date']); imb = (INV.opening_qty + INV.qty_received + INV.qty_emergency - INV.qty_consumed - INV.qty_wasted - INV.closing_qty).abs()
check('I1 daily flow: opening + received + emergency - consumed - wasted = closing', imb.max() <= 0.01, f'max {imb.max():.4f}')
INV['prev_close'] = INV.groupby('ingredient_id').closing_qty.shift(); chain = (INV.opening_qty - INV.prev_close).abs().dropna(); check('I2 opening stock = previous closing stock', chain.max() <= 0.01, f'max {chain.max():.4f}')
check('I3 complete grid: every in-scope ingredient has a row for every day', INV.groupby('ingredient_id').size().nunique() == 1 and INV.ingredient_id.nunique() == len(sc))
bs = B.groupby(['snapshot_date', 'ingredient_id']).qty_on_hand.sum().rename('b'); Y = INV.set_index(['snapshot_date', 'ingredient_id']).join(bs).fillna({'b': 0}); dif = (Y.b - Y.closing_qty).abs()
check('I4 batch quantities add up to closing stock', dif.max() <= 0.01, f'max {dif.max():.4f}')
rb = B.groupby(['received_date', 'ingredient_id']).qty_on_hand.max()  # first-day quantity of each batch is not stored separately; compare receipts with batches first seen on the receipt day
first = B[B.snapshot_date == B.received_date].groupby(['received_date', 'ingredient_id']).qty_on_hand.sum(); rec = INV[INV.qty_received + INV.qty_emergency > 0].set_index(['snapshot_date', 'ingredient_id'])
j = rec.join(first.rename_axis(['snapshot_date', 'ingredient_id']).rename('first_day_batches'), how='left'); gap = (j.qty_received + j.qty_emergency - j.first_day_batches.fillna(0)).abs()
check('I5 every receipt and emergency purchase appears as batch stock on its day (before that day\'s use)', (gap.dropna() >= -1e-9).all() and (gap.max() <= j[['qty_received', 'qty_emergency']].sum(axis=1).max()), 'receipts reconcile to batches that day, less same-day use')
dsl = (B.expiry_date - (B.received_date + pd.to_timedelta(B.ingredient_id.map(I.set_index('ingredient_id').shelf_life_days) - 1, unit='D'))).dt.days
check('I6 expiry = received + shelf life - 1, give or take the one-day batch variation', (dsl.abs() <= 1).all() and (B.expiry_date >= B.received_date).all(), f'offset -1 / 0 / +1 days: {(dsl == -1).mean():.2f} / {(dsl == 0).mean():.2f} / {(dsl == 1).mean():.2f} of batch-days')
check('I7 nothing in stock after its last usable day', (B.snapshot_date <= B.expiry_date).all() and (B.snapshot_date >= B.received_date).all())
# ---------------------------------------------------------------- waste
check('W1 every waste row falls on an inventory day of its ingredient (waste_date is a ledger day)', W.merge(INV[['snapshot_date', 'ingredient_id']], left_on=['waste_date', 'ingredient_id'], right_on=['snapshot_date', 'ingredient_id'], how='left').snapshot_date.notna().all())
last = B.sort_values('snapshot_date').groupby('batch_id').agg(last_day=('snapshot_date', 'max'), qty=('qty_on_hand', 'last'), exp=('expiry_date', 'max'), ing=('ingredient_id', 'first'), uc=('unit_cost', 'first'))
jw = W.join(last, on='batch_id'); ex_ = jw.waste_reason.isin(EXPK); lo_ = jw.waste_reason.isin(LOSS); check('W2 every waste row is a batch of the batch table, same ingredient', jw.last_day.notna().all() and (jw.ing == jw.ingredient_id).all())
check('W3 expiry waste = what was left of the batch on its last day', (jw[ex_].waste_qty - jw[ex_].qty).abs().max() <= 0.01, f"max {(jw[ex_].waste_qty - jw[ex_].qty).abs().max():.4f}")
check('W4 a batch expires only after its last usable day and only once; losses inside the shelf life fall inside it', (jw[ex_].waste_date > jw[ex_].exp).all() and W[W.waste_reason.isin(EXPK)].batch_id.is_unique and ((jw[lo_].waste_date <= jw[lo_].exp) & (jw[lo_].waste_date >= jw[lo_].batch_id.map(B.groupby('batch_id').received_date.first()))).all(), f"{int(lo_.sum())} losses inside the shelf life ({W.waste_reason.eq('spoilage').sum()} spoilage, {W.waste_reason.eq('shrinkage').sum()} shrinkage)")
wv = (W.waste_value_php - (W.waste_qty * jw.uc).round(2)).abs(); check('W5 waste value = quantity x batch unit cost', wv.max() <= 0.011, f'max {wv.max():.4f}')
# every batch that was left to expire has a waste row: batches whose last stock day is the expiry day with quantity left
ex = last[(last.last_day == last.exp) & (last.qty > 0.0005) & (last.exp < INV.snapshot_date.max())]; check('W6 every batch still in stock on its last usable day has an expiry waste row (batches expiring after the data end excepted)', ex.index.isin(W[W.waste_reason.isin(EXPK)].batch_id).all(), f'{int((~ex.index.isin(W[W.waste_reason.isin(EXPK)].batch_id)).sum())} missing of {len(ex)}')
# ---------------------------------------------------------------- stockouts
SOk = SO.merge(INV[['snapshot_date', 'ingredient_id', 'qty_emergency']], left_on=['event_date', 'ingredient_id'], right_on=['snapshot_date', 'ingredient_id'], how='left')
check('T1 every stockout event is on an inventory day of that ingredient', SOk.snapshot_date.notna().all())
check('T2 emergency events have an emergency purchase; lost-sales events have unmet quantity', ((SOk.outcome != 'EMERGENCY_PURCHASE') | (SOk.qty_emergency > 0)).all() and ((SO.outcome != 'LOST_SALES') | (SO.unmet_qty > 0)).all())
em = SO[SO.outcome == 'EMERGENCY_PURCHASE']; lo = SO[SO.outcome == 'LOST_SALES']
check('T3 an emergency purchase covers the gap (whole packs, so at least the shortfall) and has a cost; a lost sale has a shortage cost', (em.emergency_qty >= em.shortfall_qty - 0.01).all() and (em.emergency_cost_php > 0).all() and (lo.shortage_cost_php >= 0).all() and (lo.unmet_qty > 0).all())
check('T4 one event per ingredient and day', not SO.duplicated(['event_date', 'ingredient_id']).any())
# ---------------------------------------------------------------- volume consistency over time (sales <-> stock <-> waste)
Iv = I.set_index('ingredient_id').standard_unit_cost; INV['rec_php'] = INV.qty_received * INV.ingredient_id.map(Iv); INV['year'] = INV.snapshot_date.dt.year; Wy = W.assign(year=W.waste_date.dt.year).groupby('year').waste_value_php.sum()
netp = S[S.is_revenue & (S.net_sales > 0)].assign(year=S.sale_date.dt.year).groupby('year').net_sales.sum(); ry = INV.groupby('year').rec_php.sum(); cy = Xy.groupby('year').theo.sum()
tab = pd.DataFrame({'net_sales_M': netp / 1e6, 'purchases_k': ry / 1e3, 'purchases_pct_net': 100 * ry / netp, 'waste_k': Wy / 1e3, 'waste_pct_purchases': 100 * Wy / ry}).round(2)
print('\nBy year (sales, purchases at standard cost, waste):\n' + tab.to_string())
full = tab.loc[2022:2025]; check('V1 purchases follow sales: purchases / net sales stays within +-35 % of its 2022-2025 mean', ((full.purchases_pct_net / full.purchases_pct_net.mean() - 1).abs() < 0.35).all())
check('V2 waste share of purchases is in a plausible band (2-12 %) every full year', ((full.waste_pct_purchases > 2) & (full.waste_pct_purchases < 12)).all())
print(f"\n{sum(ok for _, ok, _ in res)} PASS, {sum(not ok for _, ok, _ in res)} FAIL")
sys.exit(0 if all(ok for _, ok, _ in res) else 1)
