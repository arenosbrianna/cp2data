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
YV = os.environ.get('YEARVARY', '1') == '1'; LP = YV and os.environ.get('LEVEL_PLAN', '1') == '1'; LP_SCALE = float(os.environ.get('LP_SCALE', '1.0')); rng = np.random.default_rng(SEED); KEY = ['item_id', 'channel', 'unit_price', 'is_revenue']
S = pd.read_csv(PK + 'generated_v4_pre_v7/sales.csv', parse_dates=['sale_date']); ALIGN = os.environ.get('ALIGN_WEEKDAY', '1') == '1'


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
        b = np.clip(r.normal(1.0, 0.25, 5), 0.55, 1.5); c = r.normal(0, 0.045, (5, 12)); si = np.array(S_IDX)
        sy = np.exp(b[:, None] * np.log(si)[None, :] + c); sy *= si.mean() / sy.mean(axis=1, keepdims=True)    # per-year seasonal index, same annual mean as the template
        n = len(months); z = r.normal(0, 0.0501, n); w_ = r.normal(0, 0.012, n); e_ = np.zeros(n); w = np.zeros(n)
        for i in range(n):
            e_[i] = (0.55 * e_[i - 1] if i else 0) + z[i]; w[i] = (0.92 * w[i - 1] if i else 0) + w_[i]
        return anch, lg, b, c, sy, np.clip(e_ + w, -0.14, 0.14)
    def lvl(anch, p):
        ax_ = np.array([q.ordinal for q in map(pd.Period, anch)], float); ay_ = np.log(np.array(list(anch.values())))
        return float(np.exp(np.interp(p.ordinal, ax_, ay_))) if ax_[0] <= p.ordinal <= ax_[-1] else float(np.exp(ay_[0] + (p.ordinal - ax_[0]) * (ay_[1] - ay_[0]) / (ax_[1] - ax_[0])))
    START_ATT = int(os.environ.get('START_ATT', '6' if LP else '0'))
    for att in range(START_ATT, 400):
        anch, lg, b, c, sy, ee = year_draw(att)
        tg = {p: lvl(anch, p) * sy[p.year - 2021][p.month - 1] * (1 + ee[i]) for i, p in enumerate(months)}
        if 2025 <= max(p.year for p in months): tg[pd.Period('2025-12')] = float(mon.get(pd.Period('2025-12'), np.nan)) / 1e3          # real December 2025 (per open day, PHP k)
        ok = True
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
if YV: tgt = {p: L(p) * 1e3 * sy[p.year - 2021][p.month - 1] * (1 + ee[i]) for i, p in enumerate(months)}
else: tgt = {p: L(p) * 1e3 * S_IDX[p.month - 1] * (1 + e[i]) for i, p in enumerate(months)}
ym = S.sale_date.dt.to_period('M'); groups = []; log1 = []
for p in months:
    cur = mon[p] * rh(p); f = tgt[p] / cur; groups.append((S.index[paid(S) & (ym == p)].to_numpy(), f)); log1.append((str(p), round(cur), round(tgt[p]), round(f, 3)))
S, nd, na = apply_groups(S, groups)

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
# same weekday (real activity share, lines per day, dish choice restricted to dishes that also exist in the generated years; 17 dishes appear only in the real months)
log3 = None
if os.environ.get('ALIGN_MGMT', '1') == '1' and os.path.exists(PK + 'generated_v4/menu_items.csv'):
    menu = pd.read_csv(PK + 'generated_v4/menu_items.csv'); mgid = set(menu[menu.category == 'Management'].item_id); isg = S.item_id.isin(mgid); gen_items = set(S[isg & (S.sale_date < SEAM)].item_id)
    real_days = sorted(S[(S.sale_date >= SEAM) & paid(S)].sale_date.unique()); rl = S[isg & (S.sale_date >= SEAM)]; bundles = {k: [] for k in range(7)}
    for dt in real_days:
        b = rl[(rl.sale_date == dt) & rl.item_id.isin(gen_items) & (rl.net_sales == 0) & (rl.unit_price == 0)]
        bundles[pd.Timestamp(dt).dayofweek].append(b[['item_id', 'channel', 'quantity_sold', 'unit_price', 'gross_sales', 'discount', 'net_sales', 'is_revenue']].to_dict('records'))
    rng3 = np.random.default_rng(SEED + 3); gdays = sorted(S[(S.sale_date < SEAM) & paid(S)].sale_date.unique()); before = S[isg & (S.sale_date < SEAM)]
    S = S[~(isg & (S.sale_date < SEAM))]; new = []
    for dt in gdays:
        pool = bundles[pd.Timestamp(dt).dayofweek]; b = pool[int(rng3.integers(len(pool)))]
        for rec_ in b: new.append(dict(rec_, sale_date=pd.Timestamp(dt), sale_id=0))
    S = pd.concat([S, pd.DataFrame(new)[list(S.columns)]], ignore_index=True); S['_o'] = np.arange(len(S)); S = S.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)
    log3 = (len(before), len(new), int(before.quantity_sold.sum()), int(sum(r_['quantity_sold'] for r_ in new)))
if LP and os.environ.get('LOCK_2021', '1') == '1':      # 2021 locked: the shipped 2021 lines replace whatever the phases made of them
    lk = pd.read_csv(os.environ.get('LOCK_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'locked_2021_prebuild.csv')), parse_dates=['sale_date'])[list(S.columns)]
    assert lk.sale_date.max() < pd.Timestamp('2022-01-01')
    S = pd.concat([lk, S[S.sale_date >= pd.Timestamp('2022-01-01')]], ignore_index=True); S['_o'] = np.arange(len(S)); S = S.sort_values(['sale_date', '_o'], kind='stable').drop(columns='_o').reset_index(drop=True); S['sale_id'] = np.arange(1, len(S) + 1)
S.to_csv(PK + 'generated_v4_pre_v7/sales.csv', index=False, lineterminator='\n')
print('phase0c units per dine-in line (target, lines raised):', log0c); print('phase0b December basket (removed, added):', log0b); print('phase4 holiday-eve peaks (year, day, before, target, added):', log4); print('phase3 management lines (before, after, units before, units after):', log3)
print('phase0 weekday (real idx, generated idx, removed, added):', log0); print('phase1 month: month, now, target, factor'); print(log1[:3], '...'); print('phase2 Dec/Nov ratios (year, before, target):', log2); print('rows', len(S))
