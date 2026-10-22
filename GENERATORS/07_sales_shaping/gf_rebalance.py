"""COVID-era channel mix (2026-10-22, user: in 2021 GrabFood sales must be GREATER than dine-in).
Under the 2021 restrictions (and the Omicron alert level of Jan 2022) delivery carried the restaurant. For the months in GF_TARGET the share of GrabFood in paid net sales is raised to the target by converting
regular Dine-In lines into GrabFood lines of the same dish and day (price and discount x 1.25, the project's GrabFood markup, GrabFood-only listings are not touched). The conversion raises the month total by 0.25 x the converted net;
with keep_total the same amount of random Dine-In lines is dropped so the month total is unchanged. After the restrictions ease the share fades smoothly (decay_targets) to a steady level of about 4 %.
Shares are SYNTHETIC_ASSUMPTION (the restaurant's real 2021 channel split is not in the sources); the direction (GrabFood above dine-in in 2021) is a team requirement."""
import numpy as np, pandas as pd
GF_TARGET = {'2021-09': 0.62, '2021-10': 0.62, '2021-11': 0.60, '2021-12': 0.56}      # 2021 (locked file); 2022 onwards: decay_targets()


def decay_targets(s0=0.50, s_inf=0.04, tau=9.0, start='2022-01', end='2025-11'):
    """GrabFood share of paid net sales, month by month: starts at s0 in Jan 2022 and falls smoothly (time constant tau months) to the steady share s_inf, so 2022 keeps a high delivery share that fades gently
    (about 26 % in Jul 2022, 14 % in Jan 2023, 6 % in Jan 2024, then steady near 4 %; the real Dec 2025 - Aug 2026 share is 3.3 %). SYNTHETIC_ASSUMPTION (user: more GrabFood in 2022, then subtly lower, then steady)."""
    return {str(p_): round(s_inf + (s0 - s_inf) * float(np.exp(-i / tau)), 4) for i, p_ in enumerate(pd.period_range(start, end, freq='M'))}


MARKUP = 1.25


def paid(df): return df.is_revenue & (df.net_sales > 0)


def rebalance(S, rng, gf_items, keep_total, targets=None, listing_map=None, lprice=None):
    """listing_map: regular dish -> same-name GrabFood listing with the same recipe (gf_listings.same_name_map); lprice: listing -> source price. A converted line moves onto the listing at its source price instead of dish price x 1.25."""
    S = S.copy(); log = {}; lmap = listing_map or {}; lprice = lprice or {}
    for ym_s, q in (targets or GF_TARGET).items():
        ym = pd.Period(ym_s); pm = paid(S) & (S.sale_date.dt.to_period('M') == ym)
        if not pm.any(): continue
        G = S.net_sales[pm & (S.channel == 'GrabFood')].sum(); T = S.net_sales[pm].sum(); x = (q * T - G) / (MARKUP if keep_total else MARKUP - (MARKUP - 1) * q)      # keep_total: the month total is restored afterwards, so the share is G' / T
        if x <= 0: continue
        seen = set(zip(S.sale_date, S.item_id, S.channel, S.unit_price, S.is_revenue))
        elig = rng.permutation(S.index[pm & (S.channel == 'Dine-In') & ~S.item_id.isin(gf_items)].to_numpy()); conv = []; got = 0.0; gfnew = 0.0; delta = 0.0
        for j in elig:
            if (G + gfnew) / (T if keep_total else T + delta) >= q: break
            r = S.loc[j]; L = lmap.get(int(r.item_id)); use = L is not None and L in lprice; nid = L if use else r.item_id; np_ = lprice[L] if use else round(float(r.unit_price) * MARKUP, 2)
            if (r.sale_date, nid, 'GrabFood', np_, r.is_revenue) in seen: continue
            seen.add((r.sale_date, nid, 'GrabFood', np_, r.is_revenue)); seen.discard((r.sale_date, r.item_id, r.channel, r.unit_price, r.is_revenue))
            gross = round(r.quantity_sold * np_, 2); rate = float(r.discount) / float(r.gross_sales) if float(r.gross_sales) else 0.0; disc = min(round(rate * gross, 2), gross); S.loc[j, ['item_id', 'channel', 'unit_price', 'gross_sales', 'discount', 'net_sales']] = [nid, 'GrabFood', np_, gross, disc, round(gross - disc, 2)]
            got += float(r.net_sales); gfnew += float(S.net_sales[j]); delta += float(S.net_sales[j]) - float(r.net_sales); conv.append(j)
        if keep_total:
            extra = delta; rest = rng.permutation(S.index[paid(S) & (S.sale_date.dt.to_period('M') == ym) & (S.channel == 'Dine-In')].to_numpy()); cs = S.net_sales[rest].cumsum().to_numpy(); k = int(np.searchsorted(cs, extra))
            if k < len(cs) and abs(cs[k] - extra) < abs((cs[k - 1] if k else 0) - extra): k += 1
            S = S.drop(index=rest[:k])
        pm2 = paid(S) & (S.sale_date.dt.to_period('M') == ym); log[ym_s] = (round(S.net_sales[pm2 & (S.channel == 'GrabFood')].sum() / S.net_sales[pm2].sum(), 3), len(conv))
    S = S.sort_values(['sale_date'], kind='stable').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)
    return S, log


# ---- 2021 level (2026-10-22, user: 2021 total sales range from PHP 180k to 200k)
SALES_2021 = {'2021-09': 41000, '2021-10': 45000, '2021-11': 50000, '2021-12': 54000}      # user: the TOTAL paid net sales of 2021 (Sep-Dec in the data) are PHP 180-200k; aim 190k, the stock build later changes a month by a few percent


def scale_month(S, ym_s, target, rng):
    """Brings the paid net sales of one month to `target` (PHP): drops random paid lines of both channels when above, re-dates clones of random paid lines onto other days of the same weekday and month when below.
    Channel mix, dish mix and weekday profile follow the existing lines; no key (date, dish, channel, price, revenue flag) is duplicated."""
    S = S.copy(); ym = pd.Period(ym_s); pm = paid(S) & (S.sale_date.dt.to_period('M') == ym); T = S.net_sales[pm].sum(); need = target - T
    if abs(need) < 200: return S, T
    idx = S.index[pm].to_numpy()
    if need < 0:
        order = rng.permutation(idx); cs = S.net_sales[order].cumsum().to_numpy(); k = int(np.searchsorted(cs, -need))
        if k < len(cs) and abs(cs[k] + need) < abs((cs[k - 1] if k else 0) + need): k += 1
        return S.drop(index=order[:k]), T
    seen = set(zip(S.sale_date, S.item_id, S.channel, S.unit_price, S.is_revenue)); days = pd.to_datetime(S.sale_date[pm].unique()); new = []; got = 0.0; tries = 0
    while got < need and tries < 20000:
        tries += 1; j = int(rng.choice(idx)); r = S.loc[j]; cand = [d for d in days if d != r.sale_date and d.dayofweek == r.sale_date.dayofweek]
        if not cand: continue
        d = cand[int(rng.integers(len(cand)))]; kk = (d, r.item_id, r.channel, r.unit_price, r.is_revenue)
        if kk in seen: continue
        seen.add(kk); rn = r.copy(); rn['sale_date'] = d; new.append(rn); got += float(r.net_sales)
    S = pd.concat([S, pd.DataFrame(new)], ignore_index=True)
    return S, T
