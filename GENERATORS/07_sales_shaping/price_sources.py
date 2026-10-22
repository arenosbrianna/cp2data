"""Prices of the generated years follow the original sources: the real POS data and the menu table (2026-10-22, user instruction).
Price of a dish on a channel:
  1. the most common price in the REAL POS lines (Dec 2025 onward) of that dish and channel, when there are at least MIN_REAL such lines;
  2. otherwise the menu table price: Dine-In = list_price; GrabFood = list_price x 1.25 (the project's GrabFood markup; for GrabFood-only listings the ratio the real POS uses for such listings).
Every generated paying line gets that price; gross = quantity x price; the line's discount RATE is kept (discount = rate x gross), net = gross - discount. Zero-price lines (staff meals, complimentary) and the real lines are not touched."""
import numpy as np, pandas as pd
MIN_REAL = 5
SEAM = pd.Timestamp('2025-12-01')


def build_price_map(S, menu):
    """S: sales with item_id, channel, unit_price, net_sales, is_revenue, sale_date; menu: frame indexed by item_id with list_price and category."""
    paying = S[S.is_revenue & (S.net_sales > 0) & (S.unit_price > 0)]; real = paying[paying.sale_date >= SEAM]
    mode = real.groupby(['item_id', 'channel']).unit_price.agg(lambda s: s.round(2).mode().iloc[0]); cnt = real.groupby(['item_id', 'channel']).size()
    # GrabFood-only listings: the ratio of the real POS price to the list price
    gfcat = set(menu.index[menu.category == 'GrabFood']); rr = real[(real.channel == 'GrabFood') & real.item_id.isin(gfcat)]
    gf_ratio = float((rr.unit_price / rr.item_id.map(menu.list_price)).round(2).mode().iloc[0]) if len(rr) else 1.25
    pm = {}
    for (i, ch), n in cnt.items():
        if n >= MIN_REAL: pm[(i, ch)] = float(mode[(i, ch)])
    return pm, gf_ratio


def price_for(pm, gf_ratio, menu, item_id, channel):
    if (item_id, channel) in pm: return pm[(item_id, channel)]
    lp = float(menu.list_price.get(item_id, 0))
    if lp <= 0: return None
    if channel == 'Dine-In': return round(lp, 2)
    return round(lp * (gf_ratio if menu.category.get(item_id) == 'GrabFood' else 1.25), 2)


def apply_prices(G, pm, gf_ratio, menu):
    """G: generated lines (copy returned). Only paying lines with a positive price change."""
    G = G.copy(); m = G.is_revenue & (G.net_sales > 0) & (G.unit_price > 0); idx = G.index[m]
    newp = np.array([price_for(pm, gf_ratio, menu, i, c) or np.nan for i, c in zip(G.item_id[idx], G.channel[idx])], float); ok = ~np.isnan(newp); idx = idx[ok]; newp = newp[ok]
    rate = (G.discount[idx] / G.gross_sales[idx]).to_numpy(); gross = np.round(G.quantity_sold[idx].to_numpy() * newp, 2); disc = np.minimum(np.round(rate * gross, 2), gross)
    G.loc[idx, 'unit_price'] = newp; G.loc[idx, 'gross_sales'] = gross; G.loc[idx, 'discount'] = disc; G.loc[idx, 'net_sales'] = np.round(gross - disc, 2)
    return G


if __name__ == '__main__':      # preview on a finished dataset folder: py price_sources.py <datasets>
    import sys
    D = (sys.argv[1] if len(sys.argv) > 1 else 'datasets').rstrip('/') + '/'; S = pd.read_csv(D + 'sales.csv', parse_dates=['sale_date']); M = pd.read_csv(D + 'menu_items.csv').set_index('item_id')
    pm, gr = build_price_map(S, M); print('price points from the real POS (dish x channel with >= %d real lines): %d | GrabFood-only listing ratio %.2f' % (MIN_REAL, len(pm), gr))
    G = S[S.sale_date < SEAM]; H = apply_prices(G, pm, gr, M); m = G.is_revenue & (G.net_sales > 0)
    by = pd.DataFrame({'old': G.net_sales[m].groupby(G.sale_date[m].dt.year).sum(), 'new': H.net_sales[m].groupby(H.sale_date[m].dt.year).sum()}); by['change_%'] = (100 * (by.new / by.old - 1)).round(1); print(by.round(0).to_string())
    ch = (H.unit_price[m] != G.unit_price[m]); print('lines whose price changes: %d of %d (%.0f %%)' % (ch.sum(), m.sum(), 100 * ch.mean()))
