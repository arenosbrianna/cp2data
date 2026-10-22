"""v13 GrabFood channel redesign (final correction, 2026-10-14). Replaces add_grabfood.py. Operates on the scratch stock-rebuild package (old item ids), after add_weekend_payday.py.
Usage: py gen_grabfood_channel.py <scratch package folder>      env SEEDX = seed offset (default 0)

What it does to the GENERATED years only (real POS lines >= 2025-12-01 are never read for editing):
 0. v13 seasonality: the monthly share is no longer flat 8 %: base_share (pandemic decline towards the real 3.2 %) x MONTH_F x Holy-Week bump, and holiday days get more delivery-active days and lines.
 1. Pool of existing GrabFood demand = (a) lines of GrabFood-menu items (sold 'Dine-In' at 0.8 x list in the legacy generator; the build used to relabel them) and
    (b) legacy GrabFood-channel lines of regular dishes (98.8 % of the legacy GrabFood lines; the legacy generator labelled random regular lines GrabFood).
 2. Regular-dish GrabFood demand is capped at REG_SHARE of GrabFood net (real POS: 17.5 %). Legacy regular GrabFood lines beyond the cap are re-labelled Dine-In
    (same dish, same quantity, price / 1.25: a channel change of existing demand, nothing deleted, nothing added).
 3. GrabFood net per month = SHARE x the month's total net sales. The shortfall versus the pool is filled with NEW GrabFood-menu lines (added demand, as you requested earlier).
 4. Delivery-day schedule: every open day is delivery-active with probability P_ACTIVE (real: 33 %, no weekday effect, chi-square p = 0.29); the month's GrabFood lines are spread over
    its active days (>= 1 each, extras random, at most MAX_PER_DAY a day). The pool lines are re-dated within their month; their prices are re-read for the new date.
 5. New lines: dishes drawn with weights ~ sqrt(popularity), only dishes that sold within +-120 days of the date, quantity 1 (97 %) or 2, discount from existing GrabFood lines."""
import os, sys
import numpy as np
import pandas as pd

PK = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'
P_ACTIVE, REG_SHARE, MAX_PER_DAY, P_QTY2 = 0.50, 0.17, 14, 0.03
# v13 seasonality (user decision 2026-10-14; ASSUMPTIONS, not client data): GrabFood share of a month's net sales falls from the pandemic years (delivery-heavy 2021-22) to a plateau by mid-2023, then eases only slightly
# towards the share seen in the real POS (3.2 %, Dec 2025 onward); a holiday factor lifts the share in the Philippine holiday months and concentrates lines on holiday days.
ANCHORS = [('2021-09-15', 0.125), ('2022-06-15', 0.110), ('2022-12-15', 0.075), ('2023-05-15', 0.056), ('2024-06-15', 0.050), ('2025-11-15', 0.042)]     # (date, base share of net sales); linear between anchors
MONTH_F = {1: 1.08, 9: 1.05, 10: 1.10, 11: 1.15, 12: 1.30}                                                                       # Jan (New Year), 'ber' months, Christmas season; other months 1.0
HOLY_F, DAY_W_MAX = 1.10, 2.0                                                                                                      # Holy Week month bump; max relative weight of a holiday day
def base_share(m):
    x = m.to_timestamp() + pd.Timedelta(days=14); a = [(pd.Timestamp(d), v) for d, v in ANCHORS]
    return float(np.interp(x.value, [d.value for d, _ in a], [v for _, v in a]))
SEAM = pd.Timestamp('2025-12-01'); rng = np.random.default_rng(20261016 + int(os.environ.get('SCEN', '0')))
s = pd.read_csv(PK + 'generated_v4_pre_v7/sales.csv', parse_dates=['sale_date'])
M = pd.read_csv(PK + 'generated_v4/menu_items.csv').set_index('item_id'); R = pd.read_csv(PK + 'generated_v4/recipes.csv')
cal = pd.read_csv(PK + 'generated_v4/calendar_ext.csv', parse_dates=['date']).set_index('date')
gf_items = set(M.index[M.category == 'GrabFood'])
sellable = set(M.index[(M.category != 'Management') & (~M.is_complimentary) & (M.list_price > 0)]) & set(R.item_id)
syn = s[s.sale_date < SEAM].copy(); real = s[s.sale_date >= SEAM]
paid = syn.is_revenue & (syn.net_sales > 0)
is_pool_sp = paid & syn.item_id.isin(gf_items)
is_pool_rg = paid & (syn.channel == 'GrabFood') & ~syn.item_id.isin(gf_items)
sp = syn[is_pool_sp].copy(); rg = syn[is_pool_rg].copy(); rest = syn[~(is_pool_sp | is_pool_rg)].copy()

# ---- holiday weights per day: is_holiday days and the day before / after, 16 Dec - 2 Jan, Holy Week (the days around the Thursday / Friday closures), Nov 1-2
def day_weight(d):
    w = 1.0
    if cal.at[d, 'is_holiday'] or any((d + pd.Timedelta(days=k)) in cal.index and cal.at[d + pd.Timedelta(days=k), 'is_holiday'] for k in (-1, 1)): w = 1.6
    if (d.month == 12 and d.day >= 16) or (d.month == 1 and d.day <= 2): w = DAY_W_MAX
    return w
holy_months = set()
for y in sorted(set(cal.index.year)):
    cl = cal[(cal.index.year == y) & (~cal.is_open.astype(bool)) & (cal.index.month.isin([3, 4]))].index
    holy_months |= {c.to_period('M') for c in cl}
# ---- price helper (same rule as before)
rev = syn[paid]; by_item = {i: g.sort_values('sale_date') for i, g in rev.groupby('item_id')}
def price(i, d, w=120):
    if i not in by_item: return None
    g = by_item[i]; lo = g.sale_date.searchsorted(d - pd.Timedelta(days=w)); hi = g.sale_date.searchsorted(d + pd.Timedelta(days=w), side='right'); g = g.iloc[lo:hi]
    if len(g) == 0: return None
    if i in gf_items:
        gg = g[g.channel == 'GrabFood']; p = gg.unit_price.median() if len(gg) else 1.25 * g[g.channel == 'Dine-In'].unit_price.median()
    else:
        dd = g[g.channel == 'Dine-In']; p = 1.25 * (dd.unit_price.median() if len(dd) else g.unit_price.median())
    return round(float(p), 2)
def reprice(df, f):
    df = df.copy(); df['unit_price'] = (df.unit_price * f).round(2); df['gross_sales'] = (df.quantity_sold * df.unit_price).round(2)
    df['discount'] = np.minimum((df.discount * f).round(2), df.gross_sales); df['net_sales'] = (df.gross_sales - df.discount).round(2); return df

grab_hist = rev[rev.channel == 'GrabFood']
disc_frac = (grab_hist[grab_hist.discount > 0].discount / grab_hist[grab_hist.discount > 0].gross_sales).to_numpy(); P_DISC = float((grab_hist.discount > 0).mean())
pop_all = rev.groupby('item_id').quantity_sold.sum(); pop_gf = rev[rev.item_id.isin(gf_items)].groupby('item_id').quantity_sold.sum()
gf_list = sorted(i for i in gf_items if i in sellable and i in by_item); w_gf = np.array([np.sqrt(pop_gf.get(i, 0) + 1.0) for i in gf_list]); w_gf /= w_gf.sum()
reg_list = sorted(i for i in sellable if i not in gf_items and i in by_item); w_rg = np.array([float(pop_all.get(i, 0)) for i in reg_list]); w_rg /= w_rg.sum()

E_NEW = float((w_gf * M.loc[gf_list].list_price.to_numpy()).sum()) * (1 + P_QTY2) * (1 - P_DISC * float(disc_frac.mean()))     # expected net of one new GrabFood-menu line
# GrabFood-menu pool: relabel Dine-In lines to GrabFood price (x 1.25), re-priced again per new date below
sp_dine = sp.channel == 'Dine-In'; sp.loc[sp_dine] = reprice(sp[sp_dine], 1.25).assign(channel='GrabFood')
sp['m'] = sp.sale_date.dt.to_period('M'); rg['m'] = rg.sale_date.dt.to_period('M'); rest['m'] = rest.sale_date.dt.to_period('M')
open_days = cal.index[(cal.index < SEAM) & cal.is_open.astype(bool) & cal.index.isin(syn.sale_date.unique())]
months = sorted(set(open_days.to_period('M')))
out_grab, out_dine_re = [], []
for m in months:
    days = open_days[open_days.to_period('M') == m]
    SHARE = base_share(m) * MONTH_F.get(m.month, 1.0) * (HOLY_F if m in holy_months else 1.0)
    dw = np.array([day_weight(d) for d in days]); dw_n = dw / dw.mean()
    spm, rgm, restm = sp[sp.m == m], rg[rg.m == m], rest[rest.m == m]
    rest_net = restm[restm.is_revenue].net_sales.sum()
    # regular legacy lines: keep a random subset up to the cap, the others become Dine-In (fixed point on the cap, which depends on the month's Dine-In total)
    order = rng.permutation(len(rgm)); rgp = rgm.iloc[order]
    sp_net = spm.net_sales.sum()
    G = SHARE / (1 - SHARE) * rest_net                       # first guess of the month's GrabFood net
    for _ in range(6):
        cap = REG_SHARE * G; cs = rgp.net_sales.cumsum().to_numpy(); n_keep = int(np.searchsorted(cs, cap, side='right'))
        kept, back = rgp.iloc[:n_keep], rgp.iloc[n_keep:]
        back_dine = reprice(back, 1 / 1.25).assign(channel='Dine-In')
        G = SHARE / (1 - SHARE) * (rest_net + back_dine.net_sales.sum())
    need = max(G - sp_net - kept.net_sales.sum(), 0.0)
    out_dine_re.append(back_dine)
    # delivery-active days of the month
    act = days[rng.random(len(days)) < np.minimum(P_ACTIVE * dw_n, 0.95)]
    pool = pd.concat([spm, kept], ignore_index=True)
    # new GrabFood-menu lines (dates assigned below, after the schedule is known)
    n_pool = len(pool); mean_net = E_NEW
    n_new = int(round(need / mean_net)); n_tot = n_pool + n_new
    n_act = max(len(act), int(np.ceil(n_tot / MAX_PER_DAY)), 1) if n_tot else 0
    if len(act) < n_act: act = days[np.sort(rng.choice(len(days), n_act, replace=False, p=dw / dw.sum()))]
    if n_tot == 0: continue
    n_act = min(len(act), n_tot); act = act[:n_act] if len(act) > n_tot else act
    cnt = np.ones(len(act), dtype=int); aw = np.array([dw[days.get_loc(a)] for a in act]); aw = aw / aw.sum()        # extra lines favour holiday days
    for _ in range(n_tot - len(act)):
        j = rng.choice(len(act), p=aw)
        while cnt[j] >= MAX_PER_DAY: j = rng.choice(len(act), p=aw)
        cnt[j] += 1
    slots = np.repeat(act.to_numpy(), cnt); rng.shuffle(slots)
    # pool lines first (re-dated), new lines fill the rest, then new lines are sized to the net still missing
    pl = pool.copy().reset_index(drop=True)
    free = list(slots); dates = []; taken = set()                      # pool lines go to random slots of the month, avoiding a second line of the same dish on one day
    for _k in rng.permutation(len(pl)) if len(pl) else []:
        it = int(pl.at[_k, 'item_id']); cand = [x for x in range(len(free)) if (free[x], it) not in taken]
        ch = cand[int(rng.integers(len(cand)))] if cand else int(rng.integers(len(free)))
        dates.append((_k, free[ch])); taken.add((free[ch], it)); free.pop(ch)
    for _k, d_ in dates: pl.at[_k, 'sale_date'] = d_
    slots = np.array(free, dtype='datetime64[ns]')
    n_pool = 0
    newp = []
    got = 0.0
    used = set(zip(pd.to_datetime(pl.sale_date), pl.item_id.astype(int)))      # one line per dish and day (the build merges same-day same-dish lines, which would stack quantities)
    for d in slots[n_pool:]:
        d = pd.Timestamp(d)
        for _t in range(40):
            i = int(gf_list[rng.choice(len(gf_list), p=w_gf)]); p = price(i, d)
            if p is not None and p > 0 and (d, i) not in used: break
        else:
            i = int(reg_list[rng.choice(len(reg_list), p=w_rg)]); p = price(i, d)
            if p is None or p <= 0: continue
        used.add((d, i)); q = 2 if rng.random() < P_QTY2 else 1; gross = round(q * p, 2); disc = round(float(rng.choice(disc_frac)) * gross, 2) if rng.random() < P_DISC else 0.0
        newp.append(dict(sale_id=0, sale_date=d, item_id=i, channel='GrabFood', quantity_sold=q, unit_price=p, gross_sales=gross, discount=disc, net_sales=round(gross - disc, 2), is_revenue=True)); got += gross - disc
    # re-price the re-dated pool lines for their new date
    for k in range(len(pl)):
        i = int(pl.at[k, 'item_id']); p = price(i, pd.Timestamp(pl.at[k, 'sale_date']))
        if p is not None and p > 0 and abs(p - pl.at[k, 'unit_price']) > 0.005:
            f = p / pl.at[k, 'unit_price']; row = reprice(pl.iloc[[k]], f); row['unit_price'] = p; row['gross_sales'] = round(p * pl.at[k, 'quantity_sold'], 2)
            row['net_sales'] = round(row.gross_sales.iloc[0] - row.discount.iloc[0], 2); pl.loc[k, ['unit_price', 'gross_sales', 'discount', 'net_sales']] = row[['unit_price', 'gross_sales', 'discount', 'net_sales']].iloc[0].to_numpy()
    out_grab.append(pl.drop(columns=['m'])); out_grab.append(pd.DataFrame(newp))
cols = ['sale_id', 'sale_date', 'item_id', 'channel', 'quantity_sold', 'unit_price', 'gross_sales', 'discount', 'net_sales', 'is_revenue']
out = pd.concat([real[cols], rest.drop(columns=['m'])[cols], pd.concat(out_dine_re)[cols]] + [x[cols] for x in out_grab if len(x)], ignore_index=True)
out['sale_date'] = pd.to_datetime(out.sale_date)
out = out.sort_values(['sale_date', 'item_id', 'channel'], kind='stable').reset_index(drop=True); out['sale_id'] = np.arange(1, len(out) + 1)
out.to_csv(PK + 'generated_v4_pre_v7/sales.csv', index=False, lineterminator='\n')
g = out[(out.sale_date < SEAM) & (out.channel == 'GrabFood') & out.is_revenue]; t = out[(out.sale_date < SEAM) & out.is_revenue]
print('generated GrabFood lines', len(g), 'net share %.2f %%' % (g.net_sales.sum() / t.net_sales.sum() * 100), 'special share of net %.1f %%' % (g[g.item_id.isin(gf_items)].net_sales.sum() / g.net_sales.sum() * 100),
      'active days %.1f %%' % (g.sale_date.nunique() / t.sale_date.nunique() * 100), 'lines/active day %.2f' % (len(g) / g.sale_date.nunique()), 'reclassified to Dine-In', sum(len(x) for x in out_dine_re))
