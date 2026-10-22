import pandas as pd, numpy as np
names = {'v0': 'now (100 g portions, 2-portion floor)', 'v1': '50 g portions, floor kept', 'v2': '100 g portions, bought as needed', 'v3': '50 g portions, bought as needed'}
rows = []
for v, label in names.items():
    d = f'variant_{v}/'
    I = pd.read_csv(d + 'ingredients.csv'); W = pd.read_csv(d + 'waste.csv'); INV = pd.read_csv(d + 'inventory.csv'); SO = pd.read_csv(d + 'stockout_events.csv'); S = pd.read_csv(d + 'sales.csv')
    code = I.set_index('ingredient_id').ingredient_code; cost = I.set_index('ingredient_id').standard_unit_cost
    INV['rec'] = INV.qty_received * INV.ingredient_id.map(cost); r = {'variant': label}
    for c in ('TAM', 'TOG'):
        iid = int(I[I.ingredient_code == c].ingredient_id.iloc[0]); rec = INV[INV.ingredient_id == iid]
        wq = W[W.ingredient_id == iid].waste_qty.sum(); r[c + ' waste % of bought'] = round(100 * wq / rec.qty_received.sum(), 1)
        e = SO[SO.ingredient_id == iid]; r[c + ' stockouts (lost)'] = f"{len(e)} ({int((e.outcome == 'LOST_SALES').sum())})"
        r[c + ' zero-stock days %'] = round(100 * (rec.closing_qty <= 1e-9).mean(), 1)
    r['all waste PHP k'] = round(W.waste_value_php.sum() / 1e3); r['all waste % purchases'] = round(100 * W.waste_value_php.sum() / INV.rec.sum(), 2)
    r['lost-sales events'] = int((SO.outcome == 'LOST_SALES').sum()); r['sale lines'] = len(S); r['net sales PHP'] = round(S[S.is_revenue & (S.net_sales > 0)].net_sales.sum())
    rows.append(r)
print(pd.DataFrame(rows).set_index('variant').T.to_string())
