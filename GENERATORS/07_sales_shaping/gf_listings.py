"""GrabFood follows the real POS and the menu table (2026-10-22, user: follow the original sources).
In the real POS 85 % of GrabFood lines sit on the dedicated GrabFood-category listings (price = list price) and only 15 % on regular dishes (price = list x 1.25).
same_name_map: regular dish -> its GrabFood listing of the same name WITH AN IDENTICAL RECIPE (so a line can move to the listing without changing ingredient use; safe after the stock build too).
remap_to_listings: before the stock build, generated GrabFood lines on regular dishes are moved to listings until the listing share reaches the real one: the same-name listing when there is one, else a listing drawn with the real listing mix.
Quantities, days and discount rates do not change; the price becomes the listing's source price."""
import numpy as np, pandas as pd
SEAM = pd.Timestamp('2025-12-01'); TARGET = 0.85


def paid(df): return df.is_revenue & (df.net_sales > 0)


def same_name_map(menu, recipes):
    """menu: frame indexed by item_id with item_name, category; recipes: item_id, ingredient_id, qty_base."""
    rs = recipes.groupby('item_id').apply(lambda d: tuple(sorted(zip(d.ingredient_id.astype(int), d.qty_base.round(2))))).to_dict(); out = {}
    gl = menu[menu.category == 'GrabFood']
    for lid, r in gl.iterrows():
        for i in menu.index[(menu.item_name == r.item_name) & (menu.category != 'GrabFood')]:
            if rs.get(i) is not None and rs.get(i) == rs.get(lid) and i not in out: out[int(i)] = int(lid)
    return out


def listing_weights(S, menu):
    gl = list(menu.index[menu.category == 'GrabFood']); r = S[paid(S) & (S.sale_date >= SEAM) & (S.channel == 'GrabFood') & S.item_id.isin(gl)]
    w = r.groupby('item_id').size().reindex(gl).fillna(0).to_numpy() + 1.0; return np.array(gl), w / w.sum()


def remap_to_listings(S, menu, real_ref, rng, ps, pm, gr, mask, target=TARGET, name_map=None):
    """S: sales frame (index arbitrary); mask: boolean Series of the lines that may change (generated period). Returns the frame and the number of lines moved."""
    S = S.copy(); gl, w = listing_weights(real_ref, menu); gfcat = set(gl.tolist()); nm = name_map or {}
    seen = set(zip(S.sale_date, S.item_id, S.channel, S.unit_price, S.is_revenue)); moved = []
    ym = S.sale_date.dt.to_period('M')
    for p in sorted(ym[mask].unique()):
        g = mask & paid(S) & (S.channel == 'GrabFood') & (ym == p); n = int(g.sum())
        if n == 0: continue
        onl = int(S.item_id[g].isin(gfcat).sum()); q = (target * n - onl) / max(n - onl, 1)
        if q <= 0: continue
        cand = S.index[g & ~S.item_id.isin(gfcat)].to_numpy(); take = cand[rng.random(len(cand)) < q]
        for j in take:
            r = S.loc[j]; tries = [nm[int(r.item_id)]] if int(r.item_id) in nm else []; tries += [int(x) for x in rng.choice(gl, size=6, p=w)]
            for L in tries:
                pr = ps.price_for(pm, gr, menu, L, 'GrabFood')
                if pr is None or (r.sale_date, L, 'GrabFood', pr, r.is_revenue) in seen: continue
                rate = float(r.discount) / float(r.gross_sales); gross = round(float(r.quantity_sold) * pr, 2); disc = min(round(rate * gross, 2), gross)
                seen.discard((r.sale_date, r.item_id, r.channel, r.unit_price, r.is_revenue)); seen.add((r.sale_date, L, 'GrabFood', pr, r.is_revenue))
                S.loc[j, ['item_id', 'unit_price', 'gross_sales', 'discount', 'net_sales']] = [L, pr, gross, disc, round(gross - disc, 2)]; moved.append(j); break
    return S, len(moved)
