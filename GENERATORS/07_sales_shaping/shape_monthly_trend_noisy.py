"""v14 (2026-10-15/16, team requirements): realistic monthly sales trend of 2021-2026, and (2026-10-16, audit TEMP-009, TEMP-005/006) generated years aligned to the real period.
Three phases on the generated lines only (< 2025-12-01); real months (>= 2025-12-01) are never touched.

Phase 0  weekday profile: the generated years follow the REAL weekday profile (net per open day by weekday, 2025-12-01 .. 2026-09-08). Per (month, weekday) group the lines are thinned / topped up by
         f = real index / generated index (global), which removes the scenario weekend peak (team choice 2026-10-16: align the generated years with the real ones). Paydays keep their lift.
Phase 1  monthly trend: net sales per open day of every generated month = L x S x (1 + e)
           L  log-linear between mid-year anchors 2021-07 5.7, 2022-07 6.6, 2023-07 7.6, 2024-07 8.65, 2025-07 9.8, 2026-07 11.35 (PHP k; growth 13-16 % a year; no start-up ramp, the restaurant has operated since 2013)
           S  seasonal index Jan..Dec 0.97 0.95 1.00 0.95 0.98 0.93 0.92 0.95 1.05 1.12 1.33 1.30 (November and December are the two peak months)
           e  AR(1) 0.4 noise, SD 3.5 %, seeded.
Phase 0c basket size: units per dine-in line of the generated months = the real 1.43.
Phase 0b December basket: the generated Decembers get the real December 2025 category mix (party platters, baked sushi): fewer, larger-ticket lines.
Phase 4  holiday eves: Dec 24 and Dec 31 of the generated Decembers get the real peaks (2.74x and 4.47x the median of Dec 8-20), paid for by the other days of Dec 15-31.
Phase 2  late-November / early-December window (TEMP-006): the real Dec 1-14 mean is 1.05 x the Nov 17-30 mean; in every generated year Dec 1-14 / Nov 17-30 is set to 1.05 +/- 0.04 (seeded) by moving sales inside
         November (late down, early up) and December (early up, late down) with the month totals unchanged.
Top-ups are paid lines of the same group re-dated to another open day of the same group with the same weekday (never onto a day that already has the same item / channel / price / revenue flag: build_v11 would merge
such lines and break the GrabFood order shape). RATIOS (final / pre-build per month, from build_v11) convert the month targets to the pre-build scale.
Year variation (2026-10-20, user request: the repeated yearly shape made the generated sales too learnable; YEARVARY=0 reproduces the earlier fixed-template version, backup v14/pre_yearvary_backup/):
         every generated year 2021-2025 draws its own growth, seasonal amplitude and month jitter (seeded SEED+7, SYNTHETIC_ASSUMPTION, written to <package>/year_variation.json); the monthly noise is larger and more persistent
         (AR(1) rho 0.55 SD ~6 % plus a slow wander); Nov / Dec stay the two peak months (a draw is rejected until each year's Nov and Dec exceed every other month by 4 %); the Phase 2 window ratio is 1.05 +/- 0.10 and the Phase 4 eve peaks carry a
         +/- 25 % factor. The 2025-07 and 2026-07 anchors, the real months and the seam level are unchanged.
Level plan (2026-10-20, team scenario "2026 crisis / inflation", LEVEL_PLAN=0 reproduces the earlier version, backup v14/pre_crisis_gap_backup/): the generated 2024-01 .. 2025-11 level sits about 25 % above the real Jan-Aug 2026 level
         (PHP k per open day, mid-year anchors 2021-07 5.18 | 2022-07 8.0 | 2023-07 10.2 | 2024-07 13.0 | 2025-07 13.8 | 2025-11 14.0, all x LP_SCALE except 2021-07), flat until the seam, then the real months (the crisis) fall below it. 2021 is locked: every
         generated line before 2022-01-01 is replaced by v14/stock_rebuild/locked_2021_prebuild.csv (the shipped 2021 lines). Phase 2 skips 2025 (no forced continuity at the seam); the Nov / Dec peak rule of 2025 looks at Nov only (the real Dec 2025 is below the
         generated Sep-Nov 2025 by design). Seasonal and noise draws are the shipped ones (attempt 6). Provenance: SYNTHETIC_ASSUMPTION.
Usage: py shape_monthly_trend.py <scratch package folder> [ratios.json] [window_corr.json]   (ALIGN_WEEKDAY=0 skips phase 0; shape_monthly_trend_v1_month_only.py is the earlier version)"""
import json, os, sys
import numpy as np, pandas as pd

PK = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'; SEAM = pd.Timestamp('2025-12-01'); SEED = int(os.environ.get('TREND_SEED', '20261017'))
S_IDX = [0.97, 0.95, 1.00, 0.95, 0.98, 0.93, 0.92, 0.95, 1.05, 1.12, 1.33, 1.30]
LP_ANCH = {'2021-07': 5.18, '2022-07': 8.0, '2023-07': 10.2, '2024-07': 13.0, '2025-07': 13.8, '2025-11': 14.0}      # PHP k per open day (deseasonalised level); see the docstring
ANCH = {'2021-07': 5.18, '2022-07': 6.06, '2023-07': 7.09, '2024-07': 8.29, '2025-07': 9.70, '2026-07': 11.35}      # constant 17 % a year, the median growth of the real months (audit TEMP-003); 2026-07 anchored on the real months
FLAT = os.environ.get('LEVEL_FLAT', '0') == '1'; L_BASE = float(os.environ.get('L_BASE', '11.2')); LEVEL_SD = float(os.environ.get('LEVEL_SD', '0.09')); SHOCK_DAYS = set()
# ---- External factors on the monthly level (2026-10-22, user: research Philippine happenings). Mild multipliers on the month target; SYNTHETIC_ASSUMPTION informed by public facts (confidence per row in external_factors.json):
#  * COVID reopening 2022: NCR Alert Level 3 on Jan 3-15 2022 (indoor dine-in 30 %, vaccinated only) [confirmed: ABS-CBN, Inquirer]; Alert Level 1, full capacity, from Mar 1 2022 [confirmed: Inquirer, GMA]. The 2021 months stay locked (GrabFood far above dine-in under restrictions).
#    Jan 0.22, Feb 0.38, Mar 0.60, Apr 0.80, May 0.91, Jun 0.97: recovery from the very low 2021 level (user: 2021 total PHP 180-200k); consumer confidence returns gradually (USDA 2022: foot traffic rising from a low base) [assumption on the shape].
#  * Inflation squeeze: annual average 3.9 / 5.8 / 6.0 / 3.2 / 1.7 % in 2021-2025, 8.1 % in Dec 2022 and 8.7 % in Jan 2023, the highest since Nov 2008 [confirmed: PSA, Focus Economics]. Factor = 1 - 0.006 x (inflation - 3 %) when above 3 % (peak -3.4 %), month inflation interpolated between the anchors below.
#  * Typhoon months with Luzon landfalls: Egay Jul 2023, Carina Jul 2024, Kristine Oct 2024, Man-yi Nov 2024, Ragasa Sep 2025, Fung-wong / Uwan Nov 2025 [confirmed]; Paeng Oct 2022 [background knowledge, not verified]: factor 0.97-0.98.
#  * Dated storm days with a documented work / class suspension: Carina Jul 24-25 2024 (Metro Manila), Kristine Oct 23 2024 (Luzon): sales kept 45 / 70 / 50 %.
#  Prices are not changed (the data has one price per dish); inflation acts on volume only.
EXTERNAL = os.environ.get('EXTERNAL', '0') == '1'
_INF = {'2021-09': 4.5, '2022-01': 3.0, '2022-12': 8.1, '2023-01': 8.7, '2023-12': 3.9, '2024-12': 2.9, '2025-12': 1.8}
_REOPEN = {'2022-01': 0.22, '2022-02': 0.38, '2022-03': 0.60, '2022-04': 0.80, '2022-05': 0.91, '2022-06': 0.97}      # from the 2021 level (about PHP 190k for the year) back to the normal level as restrictions lift
_TYPH = {'2022-10': 0.97, '2023-07': 0.97, '2024-07': 0.97, '2024-10': 0.97, '2024-11': 0.98, '2025-09': 0.98, '2025-11': 0.97}
def ext_factor(p):
    if not EXTERNAL: return 1.0
    ax = np.array([pd.Period(k).ordinal for k in _INF], float); infl = float(np.interp(p.ordinal, ax, list(_INF.values())))
    return (1 - 0.006 * max(0.0, infl - 3.0)) * _REOPEN.get(str(p), 1.0) * _TYPH.get(str(p), 1.0)
FIXED_STORMS = [('2024-07-24', 0.45), ('2024-07-25', 0.70), ('2024-10-23', 0.50)]
YV = os.environ.get('YEARVARY', '1') == '1'; LP = YV and os.environ.get('LEVEL_PLAN', '1') == '1'; LP_SCALE = float(os.environ.get('LP_SCALE', '1.0')); rng = np.random.default_rng(SEED); KEY = ['item_id', 'channel', 'unit_price', 'is_revenue']
S = pd.read_csv(PK + 'generated_v4_pre_v7/sales.csv', parse_dates=['sale_date']); ALIGN = os.environ.get('ALIGN_WEEKDAY', '1') == '1'
# ---- Prices follow the original sources (2026-10-22, user): every generated paying line is priced from the real POS (most common real price of that dish and channel) or else the menu table (list price; GrabFood x 1.25), see price_sources.py.
# The generator's own older, cheaper price history is dropped (it gave the generated years 1-7 % lower prices than the sources); the monthly plan below keeps the sales level, so the higher prices mean slightly fewer units.
if os.environ.get('PRICE_SOURCES', '1') == '1':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import price_sources as _ps
    _menu = pd.read_csv(PK + 'generated_v4/menu_items.csv').set_index('item_id'); _pm, _gr = _ps.build_price_map(S, _menu); _G = S[S.sale_date < SEAM]; _H = _ps.apply_prices(_G, _pm, _gr, _menu)
    _chg = int((_H.unit_price != _G.unit_price).sum()); S.loc[_G.index, ['unit_price', 'gross_sales', 'discount', 'net_sales']] = _H[['unit_price', 'gross_sales', 'discount', 'net_sales']]; print('prices set from the real POS / menu table on', _chg, 'generated lines')


def paid(df): return df.is_revenue & (df.net_sales > 0)


def daily(df): return df[paid(df)].groupby('sale_date').net_sales.sum()


def apply_groups(df, groups):
    """groups: list of (index array of the group's paid lines, factor f on its net sales). f < 1 thins, f > 1 tops up (re-dated clones). Returns (new frame, lines removed, lines added)."""
    seen = set(zip(df.sale_date.dt.strftime('%Y-%m-%d'), df.item_id.astype(str), df.channel.astype(str), df.unit_price.astype(str), df.is_revenue.astype(str))); drop = []; new = []
    net = df.net_sales.to_numpy()
    for idx, f in groups:
        idx = np.asarray(idx)
        if len(idx) == 0 or abs(f - 1) < 0.002: continue
        tot = net[idx].sum()
        if f < 1:
            need = (1 - f) * tot; order = rng.permutation(idx); cs = net[order].cumsum(); k = int(np.searchsorted(cs, need))
            if k < len(cs) and abs(cs[k] - need) < abs((cs[k - 1] if k else 0) - need): k += 1
            drop += order[:k].tolist()
        else:
            need = (f - 1) * tot; pick = rng.choice(idx, size=int(np.ceil(need / net[idx].mean() * 1.3)) + 5, replace=True); cs = net[pick].cumsum(); k = int(np.searchsorted(cs, need))
            if k < len(cs) and abs(cs[k] - need) < abs((cs[k - 1] if k else 0) - need): k += 1
            dates = pd.to_datetime(df.sale_date[idx].unique()); gfdates = pd.to_datetime(df.sale_date[idx][df.channel[idx] == 'GrabFood'].unique())      # level plan: a GrabFood top-up stays on a day that already has GrabFood lines (keeps the delivery-active days / operating days share)
            for j in pick[:k]:
                r = df.loc[j].copy(); pool_ = gfdates if (LP and r.channel == 'GrabFood' and len(gfdates)) else dates
                cands = [dt for dt in pool_ if dt != r.sale_date and dt.dayofweek == r.sale_date.dayofweek] or [dt for dt in dates if dt != r.sale_date and dt.dayofweek == r.sale_date.dayofweek]; rng.shuffle(cands)
                for dt in cands:
                    kk = (dt.strftime('%Y-%m-%d'), str(r.item_id), str(r.channel), str(r.unit_price), str(r.is_revenue))
                    if kk not in seen: r['sale_date'] = dt; seen.add(kk); new.append(r); break
    out = pd.concat([df.drop(index=drop), pd.DataFrame(new)], ignore_index=True)
    out['_o'] = np.arange(len(out)); out = out.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); out['sale_id'] = np.arange(1, len(out) + 1)
    return out, len(drop), len(new)


# ---- Phase 0: weekday profile of the generated years = the real weekday profile
log0 = None
if ALIGN:
    d = daily(S); real = d[d.index >= SEAM]; gen = d[d.index < SEAM]
    ri = real.groupby(real.index.dayofweek).mean() / real.mean(); gi = gen.groupby(gen.index.dayofweek).mean() / gen.mean(); f_dow = (ri / gi)
    ym = S.sale_date.dt.to_period('M'); dw = S.sale_date.dt.dayofweek; groups = []
    for p in sorted(ym[S.sale_date < SEAM].unique()):
        for k in range(7):
            groups.append((S.index[paid(S) & (ym == p) & (dw == k)].to_numpy(), float(f_dow[k])))
    S, nd, na = apply_groups(S, groups); log0 = ([round(float(x), 2) for x in ri], [round(float(x), 2) for x in gi], nd, na)

# ---- Phase 0b: December basket (audit TEMP-005): the real December 2025 sold many more party platters and baked sushi (Platters 21 % of net against 6 % in the generated Decembers), i.e. fewer, larger-ticket
# lines. The generated Decembers 2021-2024 get the real December category mix (category factor = real share / generated share, clipped to 0.25-4); phase 1 then restores the month total.
log0b = None
if os.environ.get('ALIGN_DEC_MIX', '1') == '1' and os.path.exists(PK + 'generated_v4/menu_items.csv'):
    cat = pd.read_csv(PK + 'generated_v4/menu_items.csv').set_index('item_id').category; cS = S.item_id.map(cat); pm = paid(S) & (S.channel != 'GrabFood')      # GrabFood keeps its own designed holiday lift (team scenario): only the dine-in basket is aligned
    rr = S[pm & (S.sale_date >= '2025-12-01') & (S.sale_date < '2026-01-01')]; rs = rr.groupby(rr.item_id.map(cat)).net_sales.sum(); rs = rs / rs.sum()
    ymm = S.sale_date.dt.to_period('M'); yy_ = S.sale_date.dt.year; groups = []; ups = []
    gf_before = {}
    for y in range(2021, 2025):
        dd_ = paid(S) & (ymm == pd.Period(f'{y}-12')); gf_before[y] = (S.net_sales[dd_ & (S.channel == 'GrabFood')].sum(), S.net_sales[dd_ & (S.channel != 'GrabFood')].sum())
    for y in range(2021, 2025):
        sel = pm & (ymm == pd.Period(f'{y}-12')); gs = S[sel].groupby(cS[sel]).net_sales.sum()
        if len(gs) == 0: continue
        gs = gs / gs.sum()
        for c in gs.index:
            f = float(np.clip(rs.get(c, gs[c] * 0.5) / gs[c], 0.25, 4.0))
            if f < 1: groups.append((S.index[sel & (cS == c)].to_numpy(), f))
            elif f > 1.02: ups.append((y, c, f, S.net_sales[sel & (cS == c)].sum()))
        # categories that must grow (party platters, baked sushi): lines of the same category from the whole year, re-dated to a random December open day (a December has too few of them to resample)
    S, nd, na = apply_groups(S, groups); seen0 = set(zip(S.sale_date.dt.strftime('%Y-%m-%d'), S.item_id.astype(str), S.channel.astype(str), S.unit_price.astype(str), S.is_revenue.astype(str))); new0 = []; rng0 = np.random.default_rng(SEED + 5)
    cS = S.item_id.map(cat); pm = paid(S) & (S.channel != 'GrabFood')
    for y, c, f, base_net in ups:
        pool = S.index[pm & (cS == c) & (S.sale_date.dt.year == y) & (S.sale_date < f'{y}-12-01')].to_numpy(); ddays = pd.to_datetime(S[pm & (S.sale_date >= f'{y}-12-01') & (S.sale_date <= f'{y}-12-31')].sale_date.unique())
        if len(pool) == 0: continue
        need = (f - 1) * base_net; tries = 0
        while need > 0 and tries < 6000:
            tries += 1; j = int(rng0.choice(pool)); r_ = S.loc[j]; dt = pd.Timestamp(ddays[int(rng0.integers(len(ddays)))]); kk = (dt.strftime('%Y-%m-%d'), str(r_.item_id), str(r_.channel), str(r_.unit_price), str(r_.is_revenue))
            if kk in seen0: continue
            seen0.add(kk); rn = r_.copy(); rn['sale_date'] = dt; new0.append(rn); need -= float(r_.net_sales); na += 1
    if new0:
        S = pd.concat([S, pd.DataFrame(new0)], ignore_index=True); S['_o'] = np.arange(len(S)); S = S.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)
    # keep the GrabFood December lift of the channel scenario: the dine-in basket change must not dilute the GrabFood share of December (GrabFood lines of the same year are added to restore the ratio GrabFood / dine-in)
    pm2 = paid(S); ym2 = S.sale_date.dt.to_period('M'); new1 = []
    for y in range(2021, 2025):
        dec = pm2 & (ym2 == pd.Period(f'{y}-12')); gfd = S.net_sales[dec & (S.channel == 'GrabFood')].sum(); ndn = S.net_sales[dec & (S.channel != 'GrabFood')].sum(); b0 = gf_before.get(y)
        if b0 is None or gfd == 0: continue
        need = b0[0] / b0[1] * ndn - gfd; pool = S.index[pm2 & (S.channel == 'GrabFood') & (S.sale_date.dt.year == y) & (S.sale_date < f'{y}-12-01')].to_numpy(); ddays = pd.to_datetime(S[dec].sale_date.unique()); tries = 0
        while need > 0 and tries < 4000 and len(pool):
            tries += 1; j = int(rng0.choice(pool)); r_ = S.loc[j]; dt = pd.Timestamp(ddays[int(rng0.integers(len(ddays)))]); kk = (dt.strftime('%Y-%m-%d'), str(r_.item_id), str(r_.channel), str(r_.unit_price), str(r_.is_revenue))
            if kk in seen0: continue
            seen0.add(kk); rn = r_.copy(); rn['sale_date'] = dt; new1.append(rn); need -= float(r_.net_sales); na += 1
    if new1:
        S = pd.concat([S, pd.DataFrame(new1)], ignore_index=True); S['_o'] = np.arange(len(S)); S = S.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)
    log0b = (nd, na)

# ---- Phase 0c: basket size. Dine-in lines of the real period carry 1.43 units each; the generated months started at 1.30 (2022) and drifted up. In every generated month the quantity of random dine-in lines is raised by one
# (1 -> 2, 2 -> 3, ...) until the month's units per dine-in line equal the real value; price, discount rate and channel are unchanged (gross, discount and net scale with the quantity). Phase 1 then restores the month total
# by removing lines, so the months have fewer, larger lines and the same net sales. GrabFood lines keep their own order shape; they are topped up by the same factor as the dine-in net grew, so the channel ratio of every month is kept.
log0c = None
if os.environ.get('ALIGN_UPL', '1') == '1':
    pmask = paid(S) & (S.channel == 'Dine-In'); realm = pmask & (S.sale_date >= SEAM); upl_t = S.quantity_sold[realm].sum() / realm.sum() + float(os.environ.get('UPL_ADJ', '-0.04')); gf_f = {}; rng6 = np.random.default_rng(SEED + 6); ymq = S.sale_date.dt.to_period('M'); tot_add = 0      # UPL_ADJ: the build adds about 0.04 units per line when it serves the simulated demand, so the target is set 0.04 below the real value
    for pm_ in sorted(ymq[S.sale_date < SEAM].unique()):
        ix = S.index[pmask & (ymq == pm_)].to_numpy()
        if len(ix) == 0: continue
        dn0 = S.net_sales[ix].sum()
        extra = int(round((upl_t - S.quantity_sold[ix].sum() / len(ix)) * len(ix)))
        if extra <= 0: continue
        w_ = 1.0 / np.sqrt(S.quantity_sold[ix].to_numpy().astype(float)); pick = rng6.choice(ix, size=min(extra, len(ix)), replace=False, p=w_ / w_.sum()); q0 = S.quantity_sold[pick].to_numpy().astype(float); q1 = q0 + 1
        S.loc[pick, 'quantity_sold'] = q1.astype(int); S.loc[pick, 'gross_sales'] = np.round(q1 * S.unit_price[pick].to_numpy(), 2); S.loc[pick, 'discount'] = np.round(S.discount[pick].to_numpy() * q1 / q0, 2)
        S.loc[pick, 'discount'] = np.minimum(S.discount[pick].to_numpy(), S.gross_sales[pick].to_numpy()); S.loc[pick, 'net_sales'] = np.round(S.gross_sales[pick].to_numpy() - S.discount[pick].to_numpy(), 2); tot_add += len(pick)
        gf_f[pm_] = S.net_sales[ix].sum() / dn0
    # keep the GrabFood / dine-in ratio of every month (the designed channel scenario and its holiday lift): GrabFood lines are topped up by the same factor as the dine-in net grew
    S, _, _ = apply_groups(S, [(S.index[paid(S) & (S.channel == 'GrabFood') & (ymq == pm_)].to_numpy(), f_) for pm_, f_ in gf_f.items()])
    log0c = (round(float(upl_t), 3), tot_add)

# ---- Phase 0e (2026-10-22, user: GrabFood above dine-in in 2021): the COVID-era delivery share tapers off through Jan-Jun 2022 (Omicron alert level 3 in January, full dine-in capacity from March 1). Dine-In lines of those months are converted to GrabFood
# lines of the same dish and day (gf_rebalance.py; targets in GF_TARGET); Phase 1 then restores the month totals. 2021 itself comes from the locked file (locked_2021_gf.csv, same conversion with the month total kept).
log0e = None
if os.environ.get('GF_COVID', '0') == '1':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import gf_rebalance as _gfr
    _m = pd.read_csv(PK + 'generated_v4/menu_items.csv'); _gfi = set(_m.item_id[_m.category == 'GrabFood'])
    import gf_listings as _gl
    _mm0 = pd.read_csv(PK + 'generated_v4/menu_items.csv').set_index('item_id'); _lm = _gl.same_name_map(_mm0, pd.read_csv(PK + 'generated_v4/recipes.csv')); _pm0, _gr0 = _ps.build_price_map(S, _mm0); _lp = {int(L): _ps.price_for(_pm0, _gr0, _mm0, L, 'GrabFood') for L in _mm0.index[_mm0.category == 'GrabFood']}
    S, log0e = _gfr.rebalance(S, np.random.default_rng(SEED + 10), _gfi, False, _gfr.decay_targets(), _lm, _lp); print('phase0e GrabFood share fades from 50 % (Jan 2022) to a steady ~4 % (first months):', {k_: v_[0] for k_, v_ in list(log0e.items())[:3]}, '...')

# ---- Phase 0d (2026-10-22, user: realistic restaurant noise): random disruption and surge days in the generated years (SYNTHETIC_ASSUMPTION, logged in noise_events.json).
# Disruption: a storm / typhoon, flood, brownout or similar closes part of the day: that day keeps 30-65 % of its sales (lines are dropped), the next day 80-95 % half of the time; about 5 a year, three times more likely Jun-Nov
# (typhoon season). Surge: a busy day (graduation, family gathering, local event): +25-55 % (random dine-in lines get one more unit); about 4 a year, Friday to Sunday more likely. Paydays, Dec 24 / 31 are left alone.
log0d = None
if os.environ.get('SHOCKS', '0') == '1':
    rs = np.random.default_rng(SEED + 9); cal0 = pd.read_csv(PK + 'generated_v4/calendar_ext.csv', parse_dates=['date']).set_index('date'); payd0 = set(cal0.index[cal0.is_payday.astype(str) == 'True'])
    eve0 = {pd.Timestamp(f'{y_}-12-{d_}') for y_ in range(2021, 2026) for d_ in (24, 31)}; dnet0 = daily(S); days0 = [d_ for d_ in dnet0.index if d_ < SEAM and d_ not in payd0 and d_ not in eve0]
    events = []; used = set()
    if EXTERNAL:
        for d0_, f0_ in FIXED_STORMS:
            d0_ = pd.Timestamp(d0_)
            if d0_ in dnet0.index and d0_ not in payd0 and d0_ not in eve0: events.append(('storm', d0_, f0_)); used.add(d0_)
    for y_ in range(2021, 2026):
        dy = [d_ for d_ in days0 if d_.year == y_]
        if len(dy) < 30: continue
        wst = np.array([3.0 if 6 <= d_.month <= 11 else 1.0 for d_ in dy]); wsu = np.array([2.0 if d_.dayofweek >= 4 else 1.0 for d_ in dy]); span = len(dy) / 365.0
        for kind, lam, w_ in (('storm', 5.0, wst), ('surge', 4.0, wsu)):
            n_ = int(rs.poisson(lam * span))
            for _ in range(n_):
                cand = [i_ for i_ in range(len(dy)) if dy[i_] not in used]; pr = w_[cand] / w_[cand].sum(); d_ = dy[int(rs.choice(cand, p=pr))]; used.add(d_)
                events.append((kind, d_, float(rs.uniform(0.30, 0.65) if kind == 'storm' else rs.uniform(1.25, 1.55))))
    for kind, d_, f_ in events:
        todo = [(d_, f_)] + ([(d_ + pd.Timedelta(days=1), float(rs.uniform(0.80, 0.95)))] if kind == 'storm' and rs.random() < 0.5 and (d_ + pd.Timedelta(days=1)) in dnet0.index and (d_ + pd.Timedelta(days=1)) not in used and str(d_.date()) not in [x[0] for x in FIXED_STORMS] else [])
        for dd_, ff_ in todo:
            idx = S.index[paid(S) & (S.sale_date == dd_)].to_numpy()
            if len(idx) == 0: continue
            tot_ = S.net_sales[idx].sum(); SHOCK_DAYS.add(dd_)
            if ff_ < 1:
                order = rs.permutation(idx); need = (1 - ff_) * tot_; cs = S.net_sales[order].to_numpy().cumsum(); k_ = min(int(np.searchsorted(cs, need)) + 1, max(0, len(idx) - 6)); S = S.drop(index=order[:k_]).reset_index(drop=True)      # a storm day keeps at least 6 lines
            else:
                pk_ = S.index[paid(S) & (S.sale_date == dd_) & (S.channel == 'Dine-In')].to_numpy(); need = (ff_ - 1) * tot_; pk_ = rs.permutation(pk_); got = 0.0
                for j_ in pk_:
                    if got >= need: break
                    q0_ = float(S.at[j_, 'quantity_sold']); q1_ = q0_ + 1; S.at[j_, 'quantity_sold'] = int(q1_); S.at[j_, 'gross_sales'] = round(q1_ * float(S.at[j_, 'unit_price']), 2)
                    S.at[j_, 'discount'] = min(round(float(S.at[j_, 'discount']) * q1_ / q0_, 2), float(S.at[j_, 'gross_sales'])); new_ = round(float(S.at[j_, 'gross_sales']) - float(S.at[j_, 'discount']), 2); got += new_ - float(S.at[j_, 'net_sales']); S.at[j_, 'net_sales'] = new_
    S['_o'] = np.arange(len(S)); S = S.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)
    log0d = {'storm': sum(1 for e_ in events if e_[0] == 'storm'), 'surge': sum(1 for e_ in events if e_[0] == 'surge')}
    json.dump([{'kind': k_, 'date': str(d_.date()), 'factor': round(f_, 3), 'documented_event': str(d_.date()) in [x[0] for x in FIXED_STORMS]} for k_, d_, f_ in events], open(PK + 'noise_events.json', 'w'), indent=1); print('phase0d disruption / surge days:', log0d)

# ---- Phase 1: monthly trend x seasonality x noise
d = daily(S); mon = d.groupby(d.index.to_period('M')).mean()
rho = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}; rh = lambda p: float(rho.get(str(p), 1.0))
months = [p for p in mon.index if p.to_timestamp() < SEAM]
YV_LOG = None
if YV:
    def year_draw(att):
        r = np.random.default_rng(SEED + 7 + 1000 * att)
        lg = np.log(1 + np.clip(r.normal(0.17, 0.045, 4), 0.08, 0.25)); lg += np.log(1.17) - lg.mean()      # growth 2021->22 .. 2024->25, mean log growth kept at 17 %
        lv = {2025: np.log(9.70)}
        for y in (2024, 2023, 2022, 2021): lv[y] = lv[y + 1] - lg[y - 2021]
        anch = {f'{y}-07': float(np.exp(lv[y])) for y in range(2021, 2026)}; anch['2026-07'] = ANCH['2026-07']
        if LP: anch = {k_: (v_ if k_ == '2021-07' else v_ * LP_SCALE) for k_, v_ in LP_ANCH.items()}; anch['2026-07'] = ANCH['2026-07']
        if FLAT:
            # 2026-10-22 (user: a steady yearly upward trend is unrealistic): the deseasonalised level of every generated year is drawn around the REAL level (11.2 PHP k per open day, Dec 2025 - Aug 2026), with no drift:
            # independent year deviations (SD LEVEL_SD), so years go up AND down. A draw is accepted only if the 5-year slope is small and the years are not monotone (see the acceptance test below).
            dev = np.clip(r.normal(0, LEVEL_SD, 5), -2 * LEVEL_SD, 2 * LEVEL_SD); anch = {f'{y_}-07': float(L_BASE * np.exp(dev[y_ - 2021])) for y_ in range(2021, 2026)}; anch['2026-07'] = ANCH['2026-07']
        b = np.clip(r.normal(1.0, 0.25, 5), 0.55, 1.5); c = r.normal(0, 0.045, (5, 12)); si = np.array(S_IDX)
        sy = np.exp(b[:, None] * np.log(si)[None, :] + c); sy *= si.mean() / sy.mean(axis=1, keepdims=True)    # per-year seasonal index, same annual mean as the template
        n = len(months); NM = float(os.environ.get('NOISE_MULT', '1.0')); z = r.normal(0, 0.0501 * NM, n); w_ = r.normal(0, 0.012 * NM, n); e_ = np.zeros(n); w = np.zeros(n)
        for i in range(n):
            e_[i] = (0.55 * e_[i - 1] if i else 0) + z[i]; w[i] = (0.92 * w[i - 1] if i else 0) + w_[i]
        return anch, lg, b, c, sy, np.clip(e_ + w, -0.14 * NM, 0.14 * NM)
    def lvl(anch, p):
        ax_ = np.array([q.ordinal for q in map(pd.Period, anch)], float); ay_ = np.log(np.array(list(anch.values())))
        return float(np.exp(np.interp(p.ordinal, ax_, ay_))) if ax_[0] <= p.ordinal <= ax_[-1] else float(np.exp(ay_[0] + (p.ordinal - ax_[0]) * (ay_[1] - ay_[0]) / (ax_[1] - ax_[0])))
    START_ATT = int(os.environ.get('START_ATT', '0' if FLAT else ('6' if LP else '0')))
    for att in range(START_ATT, 400):
        anch, lg, b, c, sy, ee = year_draw(att)
        tg = {p: lvl(anch, p) * sy[p.year - 2021][p.month - 1] * (1 + ee[i]) * ext_factor(p) for i, p in enumerate(months)}
        if 2025 <= max(p.year for p in months): tg[pd.Period('2025-12')] = float(mon.get(pd.Period('2025-12'), np.nan)) / 1e3          # real December 2025 (per open day, PHP k)
        ok = True
        if FLAT:
            # 2021 is locked, so the test looks at 2022-2025 and at the EFFECTIVE yearly level (anchor x the mean external factor of the year): no steady climb (slope <= 1.5 % a year), at least one rise and one fall, a visible spread, 2025 near the real level
            # 2022 is the reopening year (the external ramp lifts it from the 2021 level), so the trend test covers 2023-2025 and the anchors of 2022-2025 must stay within 35 % of each other
            lv_ = np.array([anch[f'{y_}-07'] * np.mean([ext_factor(pd.Period(f'{y_}-{m_:02d}')) for m_ in range(1, 13)]) for y_ in range(2023, 2026)]); sl_ = np.polyfit(np.arange(3), np.log(lv_), 1)[0]; dl_ = np.diff(lv_); an_ = np.array([anch[f'{y_}-07'] for y_ in range(2022, 2026)])
            if abs(sl_) > 0.02 or not ((dl_ > 0).any() and (dl_ < 0).any()) or not (1.06 <= lv_.max() / lv_.min() <= 1.20) or an_.max() / an_.min() > 1.25 or abs(np.log(anch['2025-07'] / L_BASE)) > 0.10: continue
        for y in range(2021, 2026):
            v = {p.month: tg[p] for p in tg if p.year == y}
            if LP and y == 2025: v.pop(12, None)       # the real December 2025 is below the generated Sep-Nov 2025 by design
            if 11 not in v or (12 not in v and not (LP and y == 2025)): ok = False; break
            oth = max(x for m_, x in v.items() if m_ not in (11, 12))
            if min(v[m_] for m_ in (11, 12) if m_ in v) < 1.04 * oth: ok = False; break
        if ok: break
    else: raise SystemExit('year variation: no draw satisfied the Nov / Dec peak rule')
    YV_LOG = {'seed': SEED + 7 + 1000 * att, 'attempt': att, 'provenance': 'SYNTHETIC_ASSUMPTION', 'level_plan': ({'enabled': True, 'scale': LP_SCALE, 'anchors_php_k_before_scale': LP_ANCH, 'locked_2021_file': 'locked_2021_prebuild.csv'} if LP else {'enabled': False}), 'anchors_php_k': anch, 'growth_2021_to_2025': [round(float(np.exp(x) - 1), 4) for x in lg],
              'amplitude_b': [round(float(x), 3) for x in b], 'seasonal_index_by_year': {str(2021 + i): [round(float(x), 3) for x in sy[i]] for i in range(5)}}
    json.dump(YV_LOG, open(PK + 'year_variation.json', 'w'), indent=1)
    L = lambda p: lvl(anch, p)
else:
    ap = [pd.Period(k) for k in ANCH]; ax = np.array([p.ordinal for p in ap], float); ay = np.log(np.array(list(ANCH.values())))
    L = lambda p: float(np.exp(np.interp(p.ordinal, ax, ay))) if ax[0] <= p.ordinal <= ax[-1] else float(np.exp(ay[0] + (p.ordinal - ax[0]) * (ay[1] - ay[0]) / (ax[1] - ax[0])))
rngN = np.random.default_rng(SEED + 1); e = np.zeros(len(months)); z = rngN.normal(0, 0.035, len(months))      # own stream: adding or removing other phases must not change the monthly noise
for i in range(len(months)): e[i] = (0.4 * e[i - 1] if i else 0) + z[i] * 0.92
e = np.clip(e, -0.07, 0.07)
if YV: tgt = {p: L(p) * 1e3 * sy[p.year - 2021][p.month - 1] * (1 + ee[i]) * ext_factor(p) for i, p in enumerate(months)}
else: tgt = {p: L(p) * 1e3 * S_IDX[p.month - 1] * (1 + e[i]) for i, p in enumerate(months)}
# ---- Flat yearly level (2026-10-22, user: flatten it). The Jan-Aug mean per open day of every generated year 2023-2025 is set to the REAL Jan-Aug 2026 level +- a few percent (same months in every year, so seasonality cannot
# fake a trend); the deviations are drawn at random (SD 2.5 %, within +-4 %) and must go up AND down. 2022: the second half is set to the same level (+-5 %) and the first half keeps the reopening ramp relative to it.
# The within-year shape (seasonal index, monthly noise, external effects, Nov / Dec peaks) is kept: every month of a year is scaled by the same factor. Inflation and typhoon effects therefore show as dips inside a year, not as a level shift between years.
FLAT_YEARS = FLAT and os.environ.get('FLAT_YEARS', '1') == '1'; flat_log = None
if FLAT_YEARS:
    r26 = float(np.mean([mon[pd.Period(f'2026-{m_:02d}')] for m_ in range(1, 9)])); rf = np.random.default_rng(SEED + 12)
    while True:
        dev3 = np.clip(rf.normal(0, 0.025, 3), -0.04, 0.04); dd3 = np.diff(dev3)
        if (dd3 > 0).any() and (dd3 < 0).any() and abs(dev3.mean()) < 0.015 and abs(dev3[2] - dev3[0]) < 0.015 and dev3.max() - dev3.min() > 0.02: break      # up AND down, first and last year within 1.5 %: slope about zero
    dev22 = float(np.clip(rf.normal(0, 0.03), -0.05, 0.05)); flat_log = {'real_jan_aug_2026_per_open_day': round(r26), 'deviation': {}}
    for y_, dv in zip((2023, 2024, 2025), dev3):
        goal = r26 * (1 + dv); f_ = goal / np.mean([tgt[p] for p in tgt if p.year == y_ and p.month <= 8])
        for p in [p for p in tgt if p.year == y_]: tgt[p] *= f_
        flat_log['deviation'][y_] = round(float(dv), 4)
    h2 = np.mean([np.mean([tgt[p] for p in tgt if p.year == y_ and p.month >= 7]) for y_ in (2023, 2024, 2025)]); f22 = h2 * (1 + dev22) / np.mean([tgt[p] for p in tgt if p.year == 2022 and p.month >= 7])
    for p in [p for p in tgt if p.year == 2022]: tgt[p] *= f22
    flat_log['deviation'][2022] = round(dev22, 4); print('flat yearly level (deviation from the real Jan-Aug 2026 level):', flat_log['deviation'])
ym = S.sale_date.dt.to_period('M'); groups = []; log1 = []
for p in months:
    cur = mon[p] * rh(p); f = tgt[p] / cur; groups.append((S.index[paid(S) & (ym == p)].to_numpy(), f)); log1.append((str(p), round(cur), round(tgt[p]), round(f, 3)))
S, nd, na = apply_groups(S, groups); json.dump({m_: {"now": n_, "target": g_} for m_, n_, g_, f_ in log1}, open(PK + "plan_log.json", "w"))      # monthly plan (per open day, PHP) for the calibration check

# ---- Phase 1b (2026-10-22, user request: more noise): day-to-day variation. The real days vary more than the generated ones (within-month SD of log daily net sales 0.40 real vs 0.25-0.37 generated, shrinking with volume).
# Inside every (year, month, weekday) group of the generated years 2022-2025 the lines are moved between the days of the group (same weekday, same month: the weekday profile, the month total and the basket size are unchanged)
# until the year's within-month SD reaches DAY_SD. Paydays, Dec 24 / 31 and GrabFood-free days (for GrabFood lines) are left alone. DAY_SD=0 skips this phase. Provenance: SYNTHETIC_ASSUMPTION.
log1b = None
DAY_SD = float(os.environ.get('DAY_SD', '0'))
if DAY_SD > 0:
    cal_ = pd.read_csv(PK + 'generated_v4/calendar_ext.csv', parse_dates=['date']).set_index('date'); payd = set(cal_.index[cal_.is_payday.astype(str) == 'True']) | SHOCK_DAYS
    def within_sd(df):
        dd = daily(df); x = np.log(dd[dd > 0]); x = x - x.groupby(x.index.dayofweek).transform('mean'); return float((x - x.groupby(x.index.to_period('M')).transform('mean')).std())
    def jitter(df, y, s, seed):
        rj = np.random.default_rng(seed); out = df.sale_date.copy()
        seen = set(zip(df.sale_date, df.item_id, df.channel, df.unit_price, df.is_revenue)); net = df.net_sales.to_numpy(); pay = paid(df).to_numpy(); it_ = df.item_id.to_numpy(); ch_ = df.channel.to_numpy(); up_ = df.unit_price.to_numpy(); rv_ = df.is_revenue.to_numpy()
        ysel = (df.sale_date.dt.year == y).to_numpy() & (df.sale_date < SEAM).to_numpy()
        eve = {pd.Timestamp(f'{y}-12-24'), pd.Timestamp(f'{y}-12-31')}
        gkey = (df.sale_date.dt.month * 10 + df.sale_date.dt.dayofweek).to_numpy()
        for k in np.unique(gkey[ysel & pay]):
            sel = ysel & pay & (gkey == k); days = sorted(pd.Timestamp(d_) for d_ in df.sale_date[sel].unique() if pd.Timestamp(d_) not in payd and pd.Timestamp(d_) not in eve)
            if len(days) < 2: continue
            byday = {d_: list(df.index[sel & (df.sale_date == d_).to_numpy()]) for d_ in days}; cur = {d_: float(net[v].sum()) for d_, v in byday.items()}; T = sum(cur.values())
            w = np.exp(s * rj.normal(0, 1, len(days))); w = w / w.sum(); tgt = {d_: T * w[i] for i, d_ in enumerate(days)}
            gfdays = {d_ for d_, v in byday.items() if (ch_[v] == 'GrabFood').any()}
            for _ in range(400):
                sur = max(days, key=lambda d_: cur[d_] - tgt[d_]); dfc = max(days, key=lambda d_: tgt[d_] - cur[d_]); gap = min(cur[sur] - tgt[sur], tgt[dfc] - cur[dfc])
                if gap < 150 or sur == dfc: break
                cand = [j for j in byday[sur] if net[j] <= gap * 1.5 and (ch_[j] != 'GrabFood' or dfc in gfdays) and (dfc, it_[j], ch_[j], up_[j], rv_[j]) not in seen]
                if not cand: break
                j = int(rj.choice(cand)); seen.discard((sur, it_[j], ch_[j], up_[j], rv_[j])); seen.add((dfc, it_[j], ch_[j], up_[j], rv_[j]))
                byday[sur].remove(j); byday[dfc].append(j); cur[sur] -= net[j]; cur[dfc] += net[j]; out.iloc[j] = dfc
        return out
    log1b = {}
    for y in range(2022, 2026):
        ysel = (S.sale_date.dt.year == y) & (S.sale_date < SEAM); before = within_sd(S[ysel]); lo, hi, best = 0.0, 1.2, None
        for it in range(7):
            s = (lo + hi) / 2; T_ = S.copy(); T_['sale_date'] = jitter(S, y, s, SEED + 80 + y); sd = within_sd(T_[ysel])
            if best is None or abs(sd - DAY_SD) < abs(best[1] - DAY_SD): best = (s, sd, T_['sale_date'])
            if abs(sd - DAY_SD) < 0.01: break
            lo, hi = (s, hi) if sd < DAY_SD else (lo, s)
        S['sale_date'] = best[2]; log1b[y] = (round(before, 3), round(best[1], 3), round(best[0], 3))
    S['_o'] = np.arange(len(S)); S = S.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)
    print('phase1b day noise (year: SD before, SD after, spread s):', log1b)

# ---- Phase 2: Nov 17-30 / Dec 1-14 window
d = daily(S); groups = []; log2 = []; rng2 = np.random.default_rng(SEED + 2); WCORR = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else {}   # WCORR: per-year multiplier on the window target that compensates what build_v11 changes afterwards


def win(a, b): return S.index[paid(S) & (S.sale_date >= a) & (S.sale_date <= b)].to_numpy()


def tot(a, b): return S.net_sales[win(a, b)].sum()


def comp(a_tot, b_tot, fa): return (a_tot + b_tot - fa * a_tot) / b_tot


for y in range(2021, 2026):
    nl, dl = d[f'{y}-11-17':f'{y}-11-30'], d[f'{y}-12-01':f'{y}-12-14']
    if len(nl) == 0 or len(dl) == 0: continue
    if LP and y == 2025: continue      # level plan: no forced continuity at the seam
    rt = 1.05 + rng2.uniform(-1, 1) * (0.10 if YV else 0.04); rtc = rt * float(WCORR.get(str(y), 1.0)); r = dl.mean() / nl.mean(); g = rtc / r
    nlT, neT = tot(f'{y}-11-17', f'{y}-11-30'), tot(f'{y}-11-01', f'{y}-11-16')
    if y < 2025:
        dlT, deT = tot(f'{y}-12-01', f'{y}-12-14'), tot(f'{y}-12-15', f'{y}-12-31'); fn, fd = g ** -0.5, g ** 0.5
        groups += [(win(f'{y}-11-17', f'{y}-11-30'), fn), (win(f'{y}-11-01', f'{y}-11-16'), comp(nlT, neT, fn)), (win(f'{y}-12-01', f'{y}-12-14'), fd), (win(f'{y}-12-15', f'{y}-12-31'), comp(dlT, deT, fd))]
    else:
        fn = (dl.mean() / rtc) / nl.mean(); groups += [(win(f'{y}-11-17', f'{y}-11-30'), fn), (win(f'{y}-11-01', f'{y}-11-16'), comp(nlT, neT, fn))]
    log2.append((y, round(r, 2), round(rt, 2)))
S, nd2, na2 = apply_groups(S, groups)
# ---- Phase 4: holiday-eve peaks (audit REAL-011): the real December 2025 had Dec 24 at 2.74x and Dec 31 at 4.47x the median of Dec 8-20. The generated Decembers 2021-2024 get the same peaks (x a seeded +/-10 %
# lognormal factor); the added sales are taken from the dine-in lines of the other days of Dec 15-31 so the December total and the GrabFood December lift are unchanged. The peak lines are December lines of the same year re-dated to the peak day.
log4 = []
if os.environ.get('ALIGN_EVE', '1') == '1':
    d_ = daily(S); base_r = d_['2025-12-08':'2025-12-20'].median(); pk = {24: d_[pd.Timestamp('2025-12-24')] / base_r, 31: d_[pd.Timestamp('2025-12-31')] / base_r}; rng4 = np.random.default_rng(SEED + 4); plan = []; groups = []
    for y in range(2021, 2025):
        d_ = daily(S); base = d_[f'{y}-12-08':f'{y}-12-20'].median(); tgt_ = {dd: pk[dd] * base * float(np.exp(rng4.normal(0, 0.25 if YV else 0.10))) for dd in (24, 31)}
        need = sum(max(0.0, tgt_[dd] - float(d_.get(pd.Timestamp(f'{y}-12-{dd}'), 0.0))) for dd in tgt_)
        oth = paid(S) & (S.channel != 'GrabFood') & (S.sale_date >= f'{y}-12-15') & (S.sale_date <= f'{y}-12-31') & ~S.sale_date.isin([pd.Timestamp(f'{y}-12-24'), pd.Timestamp(f'{y}-12-31')])
        groups.append((S.index[oth].to_numpy(), max(0.5, 1 - need / S.net_sales[oth].sum()))); plan.append((y, tgt_))
    S, nd4, na4 = apply_groups(S, groups); seen4 = set(zip(S.sale_date.dt.strftime('%Y-%m-%d'), S.item_id.astype(str), S.channel.astype(str), S.unit_price.astype(str), S.is_revenue.astype(str))); new4 = []
    for y, tgt_ in plan:
        d_ = daily(S); pool = S.index[paid(S) & (S.channel != 'GrabFood') & (S.sale_date >= f'{y}-12-01') & (S.sale_date <= f'{y}-12-31') & ~S.sale_date.isin([pd.Timestamp(f'{y}-12-24'), pd.Timestamp(f'{y}-12-31')])].to_numpy()
        for dd, tv in tgt_.items():
            day = pd.Timestamp(f'{y}-12-{dd}'); got = float(d_.get(day, 0.0)); need = tv - got; tries = 0
            while need > 0 and tries < 4000:
                tries += 1; j = int(rng4.choice(pool)); r_ = S.loc[j]; kk = (day.strftime('%Y-%m-%d'), str(r_.item_id), str(r_.channel), str(r_.unit_price), str(r_.is_revenue))
                if kk in seen4: continue
                seen4.add(kk); rn = r_.copy(); rn['sale_date'] = day; new4.append(rn); need -= float(r_.net_sales)
            log4.append((y, dd, round(got), round(tv), round(tv - need - got)))
    if new4:
        S = pd.concat([S, pd.DataFrame(new4)], ignore_index=True); S['_o'] = np.arange(len(S)); S = S.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)

# ---- Phase 3: food for management (POS category Management, zero-price lines) follows the real pattern (team request 2026-10-16): the generated open days get bootstrap draws of real open days of the
# same weekday (real activity share, lines per day, quantities). 2026-10-22 (user: make it similar to the real data):
#  * a real line whose dish is not available in the generated years is no longer dropped (that lost 6-9 % of the units, most of it on Mondays and Tuesdays): it is re-assigned to an available dish drawn in proportion to the real
#    staff-meal frequency, with the same quantity; a dish becomes available from the first paying sale of the same-named dish (6 of the 19 real-only dishes join from their own first-sale date; 13 never sold before the real months);
#  * in low-volume months staff meals scale with the business: a line is kept with probability clip(month level / (0.7 x real Jan-Aug 2026 level), 0.29, 1) (0.29 = a floor of about half a unit a day), so the 2021 trough and the first
#    months of 2022 do not carry full-size staff meals.
log3 = None
if os.environ.get('ALIGN_MGMT', '1') == '1' and os.path.exists(PK + 'generated_v4/menu_items.csv'):
    menu = pd.read_csv(PK + 'generated_v4/menu_items.csv'); mgid = set(menu[menu.category == 'Management'].item_id); name_of = menu.set_index('item_id').item_name
    # 2026-10-22: every zero-price non-paying line is copied from the real days, not only the Management ones: staff meals (Management) AND complimentary lines of ordinary dishes (real: 0.24 units a day, generated had 0.06)
    npz = ~paid(S) & (S.net_sales == 0) & (S.unit_price == 0)
    gen_items = set(S[npz & S.item_id.isin(mgid) & (S.sale_date < SEAM)].item_id)
    first_paid = S[(S.net_sales > 0) & ~S.item_id.isin(mgid)].assign(nm=lambda d: d.item_id.map(name_of)).groupby('nm').sale_date.min(); first_paid_id = S[paid(S) & ~S.item_id.isin(mgid)].groupby('item_id').sale_date.min()
    real_days = sorted(S[(S.sale_date >= SEAM) & paid(S)].sale_date.unique()); rl = S[npz & (S.sale_date >= SEAM)]; bundles = {k: [] for k in range(7)}
    for dt in real_days:
        b = rl[rl.sale_date == dt]
        bundles[pd.Timestamp(dt).dayofweek].append(b[['item_id', 'channel', 'quantity_sold', 'unit_price', 'gross_sales', 'discount', 'net_sales', 'is_revenue']].to_dict('records'))
    freq = rl.groupby('item_id').quantity_sold.sum(); avail_from = {}
    for it_ in freq.index:
        if it_ in mgid: avail_from[it_] = pd.Timestamp('1900-01-01') if it_ in gen_items else first_paid.get(name_of[it_], pd.NaT)      # a staff dish: from the first paying sale of the same-named dish
        else: avail_from[it_] = first_paid_id.get(it_, pd.NaT)                                                                             # a complimentary dish: from its own first paying sale
    r26_ = float(np.mean([mon[pd.Period(f'2026-{m_:02d}')] for m_ in range(1, 9)]))
    rng3 = np.random.default_rng(SEED + 3); gdays = sorted(S[(S.sale_date < SEAM) & paid(S)].sale_date.unique()); before = S[npz & (S.sale_date < SEAM)]
    S = S[~(npz & (S.sale_date < SEAM))]; new = []; n_re = 0; n_thin = 0; queues = {k_: [] for k_ in range(7)}
    for dt in gdays:
        dt = pd.Timestamp(dt); qd = queues[dt.dayofweek]
        if not qd: qd.extend(rng3.permutation(len(bundles[dt.dayofweek])).tolist())      # real days are drawn in shuffled rounds (no repeats until all have been used), so every weekday averages the real average instead of drifting by sampling luck
        b = bundles[dt.dayofweek][qd.pop()]
        el = {True: [it_ for it_ in freq.index if it_ in mgid and pd.notna(avail_from[it_]) and avail_from[it_] <= dt], False: [it_ for it_ in freq.index if it_ not in mgid and pd.notna(avail_from[it_]) and avail_from[it_] <= dt]}
        wt = {c_: (lambda w_: w_ / w_.sum() if len(w_) else w_)(np.array([float(freq[it_]) for it_ in el[c_]])) for c_ in (True, False)}
        fkeep = min(1.0, max(0.29, tgt.get(dt.to_period('M'), r26_) / r26_ / 0.7)) if 'tgt' in globals() else 1.0      # only months below 70 % of the real level are thinned (the reopening ramp); normal seasonal lows are not
        for rec_ in b:
            if fkeep < 1.0 and rng3.random() > fkeep: n_thin += 1; continue
            c_ = rec_['item_id'] in mgid
            if rec_['item_id'] not in el[c_]:
                if not el[c_]: continue
                rec_ = dict(rec_, item_id=int(el[c_][int(rng3.choice(len(el[c_]), p=wt[c_]))])); n_re += 1
            new.append(dict(rec_, sale_date=dt, sale_id=0))
    S = pd.concat([S, pd.DataFrame(new)[list(S.columns)]], ignore_index=True); S['_o'] = np.arange(len(S)); S = S.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)
    log3 = (len(before), len(new), int(before.quantity_sold.sum()), int(sum(r_['quantity_sold'] for r_ in new)), 're-assigned', n_re, 'thinned', n_thin)
if LP and os.environ.get('LOCK_2021', '1') == '1':      # 2021 locked: the shipped 2021 lines replace whatever the phases made of them
    lk = pd.read_csv(os.environ.get('LOCK_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'locked_2021_prebuild.csv')), parse_dates=['sale_date'])[list(S.columns)]
    assert lk.sale_date.max() < pd.Timestamp('2022-01-01')
    S = pd.concat([lk, S[S.sale_date >= pd.Timestamp('2022-01-01')]], ignore_index=True); S['_o'] = np.arange(len(S)); S = S.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)
# ---- California Maki follows the real POS (2026-10-22, user): in the real months it is the top dish (8.25 % of Dine-In units) but the generated years had 6.6-7.0 %. At the very end of the shaping (so that no later phase can undo it) every generated
# month from 2022 gets whole lines moved from the other maki rolls (same category, platters excluded) to California Maki until its share of the month's Dine-In units equals the real share. The moved lines are priced at California Maki's source price.
if os.environ.get('CM_ALIGN', '1') == '1':
    _mm = pd.read_csv(PK + 'generated_v4/menu_items.csv').set_index('item_id'); CM = int(_mm.index[(_mm.item_name == 'California Maki') & (_mm.category == 'Maki Rolls')][0])
    _dine = S.is_revenue & (S.net_sales > 0) & (S.channel == 'Dine-In'); _rs = S.quantity_sold[_dine & (S.sale_date >= SEAM) & (S.item_id == CM)].sum() / S.quantity_sold[_dine & (S.sale_date >= SEAM)].sum()
    _el = set(_mm.index[(_mm.category == 'Maki Rolls') & ~_mm.item_name.str.contains('Platter') & (_mm.index != CM)]); _rcm = np.random.default_rng(SEED + 13); _ym = S.sale_date.dt.to_period('M'); _moved = 0; _all_sel = []
    for _p in sorted(_ym[(S.sale_date < SEAM) & (S.sale_date >= '2022-01-01')].unique()):
        _mk = _dine & (_ym == _p); _U = S.quantity_sold[_mk].sum(); _cur = S.quantity_sold[_mk & (S.item_id == CM)].sum(); _need = (_rs - float(os.environ.get('CM_ADJ', '0.004'))) * _U - _cur      # aim 0.4 points below the real share: the stock build afterwards restores about 0.4 points of California Maki units
        if _need <= 0: continue
        _cand = _rcm.permutation(S.index[_mk & S.item_id.isin(_el)].to_numpy()); _cs = S.quantity_sold[_cand].cumsum().to_numpy(); _k = int(np.searchsorted(_cs, _need)) + 1; _sel = _cand[:_k]
        S.loc[_sel, 'item_id'] = CM; _moved += int(S.quantity_sold[_sel].sum()); _all_sel += list(_sel)
    if _all_sel and os.environ.get('PRICE_SOURCES', '1') == '1':
        _H2 = _ps.apply_prices(S.loc[_all_sel], _pm, _gr, _menu); S.loc[_all_sel, ['unit_price', 'gross_sales', 'discount', 'net_sales']] = _H2[['unit_price', 'gross_sales', 'discount', 'net_sales']]
    print('California Maki aligned to the real share (%.2f %% of Dine-In units): %d units moved from other maki rolls' % (100 * _rs, _moved))
# ---- Payday and holiday effects follow the real POS (2026-10-22, user: follow the real data). Compared with the other days of the same month and weekday the real paydays sell about +5 to +10 % more (generated +16 %), and the real holidays
# fewer (real about -20 to -37 % on only 11 days, so the direction is used, not the size; generated -4 %). Whole lines move from the payday / holiday to other days of the same month and weekday (month totals, weekday profile and basket unchanged) until the
# generated years show PAY_LIFT (+8 %) and HOL_LIFT (-12 %). Dec 24 / 31 (real peak days), storm / surge days and the real POS months are left alone. Provenance: SYNTHETIC_ASSUMPTION (direction from the real POS).
if os.environ.get('PAYHOL', '1') == '1':
    PAY_LIFT = float(os.environ.get('PAY_LIFT', '0.08')); HOL_LIFT = float(os.environ.get('HOL_LIFT', '-0.12')); _cal = pd.read_csv(PK + 'generated_v4/calendar_ext.csv', parse_dates=['date']).set_index('date')
    _pay = set(_cal.index[_cal.is_payday.astype(str) == 'True']); _hol = set(_cal.index[_cal.is_holiday.astype(str) == 'True']); _eve = {pd.Timestamp(f'{y_}-12-{d_}') for y_ in range(2021, 2027) for d_ in (24, 31)}
    _rph = np.random.default_rng(SEED + 15); _gen = (S.sale_date >= '2022-01-01') & (S.sale_date < SEAM)
    def _rel(S):
        d = S[_gen & paid(S)].groupby('sale_date').net_sales.sum(); d = d[[x for x in d.index if x not in _eve and x not in SHOCK_DAYS]]; k = pd.Series(list(zip(d.index.to_period('M'), d.index.dayofweek)), index=d.index); rel = d / d.groupby(k).transform('median')
        return rel, d
    def _lift(S, days):
        rel, _ = _rel(S); a = rel[[x for x in rel.index if x in days]]; b_ = rel[[x for x in rel.index if x not in days]]; return a.mean() / b_.mean() - 1
    pay_before, hol_before = _lift(S, _pay), _lift(S, _hol); movedn = {}
    for nm_, days, tgt in (('payday', _pay, PAY_LIFT), ('holiday', _hol - _pay, HOL_LIFT)):
        for _ in range(3):
            cur = _lift(S, days); f = 1 - 0.6 * (1 - (1 + tgt) / (1 + cur)) if cur > tgt else 1.0
            if (nm_ == 'payday' and f >= 0.99) or (nm_ == 'holiday' and f >= 0.99): break
            seen = set(zip(S.sale_date, S.item_id, S.channel, S.unit_price, S.is_revenue)); mv = 0; sel = _gen & paid(S); dd = S.sale_date.dt.normalize()
            allowed = [x for x in S.sale_date[sel].unique() if x not in _eve and x not in SHOCK_DAYS and x not in _pay and x not in _hol]
            alw = pd.DataFrame({'d': pd.to_datetime(allowed)}); alw['k'] = list(zip(alw.d.dt.to_period('M'), alw.d.dt.dayofweek)); bydst = alw.groupby('k').d.apply(list).to_dict()
            for dday in sorted(x for x in S.sale_date[sel].unique() if x in days and x not in _eve and x not in SHOCK_DAYS):
                kk_ = (pd.Timestamp(dday).to_period('M'), pd.Timestamp(dday).dayofweek); dest = bydst.get(kk_)
                if not dest: continue
                idx = S.index[sel & (dd == dday)].to_numpy(); need = (1 - f) * S.net_sales[idx].sum(); order = _rph.permutation(idx); acc = 0.0
                for j in order:
                    if acc >= need: break
                    r = S.loc[j]; nd = dest[int(_rph.integers(len(dest)))]; key = (nd, r.item_id, r.channel, r.unit_price, r.is_revenue)
                    if key in seen: continue
                    seen.discard((r.sale_date, r.item_id, r.channel, r.unit_price, r.is_revenue)); seen.add(key); S.loc[j, 'sale_date'] = nd; acc += float(r.net_sales); mv += 1
            movedn[nm_] = movedn.get(nm_, 0) + mv
    print('payday / holiday effect vs same month and weekday (before -> after): payday %+.1f %% -> %+.1f %% | holiday %+.1f %% -> %+.1f %% | lines moved %s' % (100 * pay_before, 100 * _lift(S, _pay), 100 * hol_before, 100 * _lift(S, _hol - _pay), movedn))
# ---- GrabFood follows the real POS and the menu table (2026-10-22, user): 85 % of the real GrabFood lines are on the dedicated GrabFood listings (list price), only 15 % on regular dishes; the generated years had 46 % / 2 % on listings and
# GrabFood lines on dishes that never go through GrabFood in the real data. Generated GrabFood lines on regular dishes are moved to listings (the same-name listing, else the real listing mix) until the listing share is 85 % in every month; days, quantities and discount rates stay.
if os.environ.get('GF_LISTINGS', '1') == '1' and os.environ.get('PRICE_SOURCES', '1') == '1':
    import gf_listings as _gl
    _g = (S.sale_date >= '2022-01-01') & (S.sale_date < SEAM); S, _nmv = _gl.remap_to_listings(S, _menu, S, np.random.default_rng(SEED + 14), _ps, _pm, _gr, _g, name_map=_gl.same_name_map(_menu, pd.read_csv(PK + 'generated_v4/recipes.csv')))
    _gp = S[_g & paid(S) & (S.channel == 'GrabFood')]; print('GrabFood lines moved onto listings: %d | share on listings 2022-2025: %.1f %%' % (_nmv, 100 * _gp.item_id.isin(set(_menu.index[_menu.category == 'GrabFood'])).mean()))
# ---- floor (2026-10-22): an open day of the generated years never ends without sales (the load expects only the two real POS gap days to be empty). A day with no paid line gets two random paid lines of the same weekday and month, re-dated onto it.
calF = pd.read_csv(PK + 'generated_v4/calendar_ext.csv', parse_dates=['date']).set_index('date'); opF = [d_ for d_ in calF.index[calF.is_open.astype(str) == 'True'] if pd.Timestamp('2021-09-01') <= d_ < SEAM]; cntF = S[paid(S)].groupby('sale_date').size(); rF = np.random.default_rng(SEED + 11); newF = []
seenF = set(zip(S.sale_date, S.item_id, S.channel, S.unit_price, S.is_revenue))
for d_ in opF:
    have = int(cntF.get(d_, 0))
    if have >= 1: continue
    pool_ = S.index[paid(S) & (S.sale_date.dt.to_period('M') == d_.to_period('M')) & (S.sale_date.dt.dayofweek == d_.dayofweek) & (S.channel == 'Dine-In')].to_numpy()
    if len(pool_) < 2: pool_ = S.index[paid(S) & (S.sale_date.dt.to_period('M') == d_.to_period('M')) & (S.sale_date.dt.dayofweek == d_.dayofweek)].to_numpy()      # any channel, same weekday and month
    if len(pool_) < 2: pool_ = S.index[paid(S) & (S.sale_date.dt.to_period('M') == d_.to_period('M'))].to_numpy()                                                   # any line of the month
    for j_ in rF.permutation(pool_):
        if have >= 2: break
        r_ = S.loc[j_]; kk = (d_, r_.item_id, r_.channel, r_.unit_price, r_.is_revenue)
        if kk in seenF: continue
        seenF.add(kk); rn = r_.copy(); rn['sale_date'] = d_; newF.append(rn); have += 1
if newF: S = pd.concat([S, pd.DataFrame(newF)], ignore_index=True); S['_o'] = np.arange(len(S)); S = S.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)
print('floor: lines added to near-empty open days:', len(newF))
S.to_csv(PK + 'generated_v4_pre_v7/sales.csv', index=False, lineterminator='\n')
print('phase0c units per dine-in line (target, lines raised):', log0c); print('phase0b December basket (removed, added):', log0b); print('phase4 holiday-eve peaks (year, day, before, target, added):', log4); print('phase3 management lines (before, after, units before, units after):', log3)
print('phase0 weekday (real idx, generated idx, removed, added):', log0); print('phase1 month: month, now, target, factor'); print(log1[:3], '...'); print('phase2 Dec/Nov ratios (year, before, target):', log2); print('rows', len(S))
