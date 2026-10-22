"""v6 optimiser policy: rolling-horizon replenishment, solved at each order opportunity.

Same information and same ordering opportunities as the baseline (review cadence, supplier delivery days, nominal lead time, trailing-28-day
mean/sd of served need).  Only the quantity decision differs.

For each ingredient k with an order opportunity on day t (all quantities in base units):
    a      planned arrival day (nominal lead time, next supplier delivery day)
    Hc     cover window = max(review days, supplier delivery interval)
    P_s    scenario demand between tomorrow and arrival ;  W_s demand in [a, a+Hc) ;  Dl_s demand over the lot's shelf life
    B_s    usable stock that survives to arrival (FEFO; batches expiring before a are lost) incl. units already on order
    decision m_k  integer packs (0, or >= MOQ packs)
    shortage_s >= W_s - B_s - pack*m        (priced at the effective shortage penalty, PHP per unit)
    waste_s    >= B_s + pack*m - Dl_s       (units that cannot be consumed within the shelf life, priced at standard unit cost)
    min  mean_s( cu*shortage_s + co*waste_s )    s = 1..S equally likely demand quantiles of a normal(mu*h, sd*sqrt(h))
Coupled constraints (optional): litres by storage type (dedicated + FR2 shared pool), rolling 7-day purchase budget.
Without coupling the problem separates by ingredient and is solved exactly by enumerating m; with coupling it is one MILP per day (HiGHS).
"""
import math
import numpy as np
from scipy.stats import norm
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import lil_matrix

BIG = 1e6


import os as _os
STAPLE_COVER = float(_os.environ.get('STAPLE_COVER', '1.5'))      # cycles of average use a staple must cover one delivery cycle ahead
STAPLE_COVER_CHEAP = float(_os.environ.get('STAPLE_COVER_CHEAP', '2.5'))
STAPLE_COVER_SHORT = float(_os.environ.get('STAPLE_COVER_SHORT', '2.0'))
LOWVOL_END = _os.environ.get('LOWVOL_END')      # 2026-10-22 (user: fix 2021 waste): before this date the restaurant is tiny (about 5 paying units a day), so stock floors are scaled to the use (SYNTHETIC_ASSUMPTION)


def _lowvol(sim, t):
    return bool(LOWVOL_END) and sim.e.days[t] < __import__('pandas').Timestamp(LOWVOL_END)


MOVING_DAYS = int(_os.environ.get('MOVING_DAYS', '0'))      # 0 = a staple is always kept on hand (also very short-life items)


class OptPolicy:
    def __init__(self, S=21, cu_mult=1.0, co_mult=1.0, storage=None, budget_week=None, force_milp=False, lit_mult=1.0, guard_shelf_stable=False, report_reorder_point=True, lead_z=0.0, par_alpha=None, staples=()):
        self.staples = tuple(staples)                # v12 staple rule (user decision 2026-10-13): these ingredients are kept on hand, a pack is re-ordered before the last one expires or runs out
        self.S, self.cu_mult, self.co_mult = S, cu_mult, co_mult
        self.storage, self.budget_week, self.force_milp, self.lit_mult = storage, budget_week, force_milp, lit_mult
        self.par_alpha = par_alpha                   # v10 par level: stock after the order must cover the (1 - alpha) quantile of the cover-window demand, but never more than the median demand over the shelf life
        self.lead_z = lead_z                         # v9: plan the pre-arrival period on a late-delivery quantile of the supplier lead time (0 = nominal lead time only)
        self.report_rp = report_reorder_point        # the reorder-point bisection is only needed for the reported column; sweeps switch it off
        self.guard = guard_shelf_stable          # v7 availability rule: a shelf-stable ingredient is never left at zero stock with nothing on order
        self.z = norm.ppf((np.arange(S) + 0.5) / S)
        self.stats = dict(milp_solves=0, milp_status={}, enum_solves=0, mismatches=0, infeasible_relaxed=0, storage_binding_days=0, orders_cut_by_storage=0, budget_binding_days=0)
        self.obj_total = 0.0

    def start(self, sim):
        self.spend = np.zeros(sim.e.nd); self.rp = np.zeros(sim.e.ng)

    def reorder_levels(self, sim, t):
        return self.rp

    def trigger(self, p, position):
        """stock position at which the optimiser starts ordering (smallest carry for which one MOQ lot lowers the expected cost): the reported reorder point"""
        q = p['mp'] * p['pack']
        def f(dl):
            B = p['B'] + dl
            j0 = (p['cu'] * np.maximum(0, p['W'] - B) + p['co'] * np.maximum(0, B - p['Dl'])).mean()
            j1 = (p['cu'] * np.maximum(0, p['W'] - B - q) + p['co'] * np.maximum(0, B + q - p['Dl'])).mean()
            return j1 - j0
        lo, hi = -position, 2 * float(p['W'].max()) + q
        if f(lo) >= 0:
            return 0.0
        if f(hi) < 0:
            return position + hi
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
        return max(0.0, position + (lo + hi) / 2)

    # ---- problem data for one ingredient / day
    def prep(self, sim, t, k):
        e = sim.e
        lo = max(0, t - 27); win = sim.hist[lo:t + 1, k]; mu = max(win.mean(), 0.0); sd = win.std()
        if mu <= 1e-12:
            return None
        lt_p = int(e.lt_nom[k])
        if self.lead_z > 0:
            lt_p = max(lt_p, int(math.ceil(e.lt_mean[k] * (1 + 0.35 * self.lead_z) + self.lead_z * e.lt_sd[k] - 1e-9)))
        a = sim.arrival_day(t, lt_p + sim.lead_extra, k)
        Hc = max(int(e.review_n[k]), int(e.interval[k]))
        Pd = max(a - t - 1, 0)
        D = lambda h: np.maximum(0.0, mu * h + self.z * sd * math.sqrt(max(h, 0)))
        P, W, Dl = D(Pd), D(Hc), D(int(e.life[k]))
        total = sum(b[0] for b in sim.batches[k]); Ea = sum(b[0] for b in sim.batches[k] if b[1] <= a - 1)
        inbound = sim.on_order[k]
        cons = np.minimum(P, total + 0.0)
        B = np.maximum(0.0, total - cons - np.maximum(0.0, Ea - P)) + inbound
        pack, mp = float(e.pack[k]), float(e.moq_packs[k])
        if _os.environ.get('SAL_DEMAND_LOT', '1') == '1' and str(e.code[k]) == 'SAL':       # client: whole salmon, PHP 5k a purchase, once or twice a month DEPENDING ON DEMAND: two fish per purchase when 28 days of use reach 1.8 fish, else one (v14, 2026-10-16)
            mp = 2.0 if mu * 28 >= 1.8 * pack else 1.0
        mmax = int(min(500, math.ceil(W.max() / pack) + math.ceil(mp) + 1))
        for kv in filter(None, _os.environ.get('MAX_PACKS_ITEM', '').split(',')):      # 2026-10-22 (user): small-pack items are bought a few packs at a time, never in big lots (env MAX_PACKS_ITEM=TAM:4,TOG:4)
            if kv.split(':')[0] == str(e.code[k]): mmax = max(int(math.ceil(mp)), min(mmax, int(kv.split(':')[1])))
        lv = _lowvol(sim, t) and bool(e.walk[k])
        return dict(k=k, code=str(e.code[k]), B=B, W=W, Dl=Dl, lowvol=lv, cu=float(e.pen[k]) * self.cu_mult, co=float(e.cost[k]) * self.co_mult, pack=pack, mp=mp, mmax=mmax)

    def enum(self, p):
        if p.get('lowvol'):      # tiny first months, same-day walk-in item: buy what the median cover-window demand needs beyond the usable stock, in portions (no 95 % safety stock)
            m_ = int(max(0, math.ceil((min(float(np.median(p['W'])), float(np.median(p['Dl']))) - float(np.median(p['B']))) / p['pack'])))
            return (int(math.ceil(p['mp'])) if 0 < m_ < p['mp'] else m_), 0.0
        ms = np.concatenate([[0], np.arange(math.ceil(p['mp']), p['mmax'] + 1)]).astype(float)
        if self.par_alpha is not None:
            pa = self.par_alpha
            for kv in filter(None, _os.environ.get('PAR_ALPHA_ITEM', '').split(',')):      # 2026-10-22: a lower service level for walk-in items with a 3-day life and lumpy use (env PAR_ALPHA_ITEM=TAM:0.5,TOG:0.5)
                if kv.split(':')[0] == p.get('code'): pa = float(kv.split(':')[1])
            iq = min(len(self.z) - 1, int(math.ceil((1 - pa) * len(self.z))) - 1)
            req = min(float(np.sort(p['W'])[iq]), float(np.median(p['Dl'])))          # par level, in base units, available after the order arrives
            keep = ms * p['pack'] + float(np.median(p['B'])) >= req - 1e-9
            if keep.any():
                ms = ms[keep]
        q = ms[:, None] * p['pack']
        J = (p['cu'] * np.maximum(0, p['W'][None, :] - p['B'][None, :] - q) + p['co'] * np.maximum(0, p['B'][None, :] + q - p['Dl'][None, :])).mean(axis=1)
        i = int(np.argmin(J))
        return int(ms[i]), float(J[i])

    # ---- joint MILP (storage / budget)
    def milp_day(self, sim, t, items):
        e = sim.e; S = self.S; n = len(items)
        nv = n + n * 2 * S + n          # m_j, then s_js, v_js, y_j
        im = lambda j: j; isv = lambda j, s: n + j * 2 * S + s; ivv = lambda j, s: n + j * 2 * S + S + s; iy = lambda j: n + n * 2 * S + j
        c = np.zeros(nv); integ = np.zeros(nv); lb = np.zeros(nv); ub = np.full(nv, np.inf)
        rows, rl, ru = [], [], []
        A = lil_matrix((n * 2 * S + 3 * n + 8, nv)); r = 0
        for j, p in enumerate(items):
            integ[im(j)] = 1; ub[im(j)] = p['mmax']; integ[iy(j)] = 1; ub[iy(j)] = 1
            for s in range(S):
                c[isv(j, s)] = p['cu'] / S; c[ivv(j, s)] = p['co'] / S
                A[r, isv(j, s)] = 1; A[r, im(j)] = p['pack']; rl.append(p['W'][s] - p['B'][s]); ru.append(np.inf); r += 1       # s + pack m >= W - B
                A[r, ivv(j, s)] = 1; A[r, im(j)] = -p['pack']; rl.append(p['B'][s] - p['Dl'][s]); ru.append(np.inf); r += 1     # v - pack m >= B - Dl
            A[r, im(j)] = 1; A[r, iy(j)] = -p['mp']; rl.append(0); ru.append(np.inf); r += 1                                    # m >= MOQ y
            A[r, im(j)] = 1; A[r, iy(j)] = -p['mmax']; rl.append(-np.inf); ru.append(0); r += 1                                 # m <= mmax y
        bind_info = {}
        if self.storage is not None:
            cap = self.storage
            stock_l = {}
            for tp in ('ambient', 'chilled', 'frozen'):
                kk = np.flatnonzero(e.storage == tp)
                stock_l[tp] = float(sum(e.litres[k] * self.lit_mult * (sim.closing[t, k] + sim.on_order[k]) for k in kk))
            sl = {}
            nslack = 0
            def add_row(types, limit):
                nonlocal r
                for j, p in enumerate(items):
                    if e.storage[p['k']] in types:
                        A[r, im(j)] = e.litres[p['k']] * self.lit_mult * p['pack']
                used = sum(stock_l[x] for x in types)
                rl.append(-np.inf); ru.append(max(limit - used, 0.0)); bind_info[tuple(types)] = (limit, used); r += 1
            add_row(('ambient',), cap['ambient']); add_row(('chilled',), cap['chilled'] + cap['pool']); add_row(('frozen',), cap['frozen'] + cap['pool'])
            add_row(('chilled', 'frozen'), cap['chilled'] + cap['frozen'] + cap['pool'])
        if self.budget_week is not None:
            for j, p in enumerate(items):
                A[r, im(j)] = p['pack'] * e.cost[p['k']]
            spent = float(self.spend[max(0, t - 6):t].sum()); rl.append(-np.inf); ru.append(max(self.budget_week - spent, 0.0)); r += 1
        A = A[:r].tocsr()
        res = milp(c, constraints=LinearConstraint(A, np.array(rl), np.array(ru)), integrality=integ, bounds=Bounds(lb, ub), options=dict(time_limit=20, mip_rel_gap=1e-9))
        self.stats['milp_solves'] += 1
        st = self.stats['milp_status']; st[res.status] = st.get(res.status, 0) + 1
        if res.x is None:
            return [0] * n, None
        return [int(round(res.x[im(j)])) for j in range(n)], float(res.fun)

    # ---- called by Sim for every day (after consumption of all ingredients)
    def day(self, sim, t):
        e = sim.e
        items = []
        for k in range(e.ng):
            if not getattr(sim, 'managed', None) is None and not sim.managed[k]:
                continue          # v14: out-of-scope ingredient
            if not sim.order_day(t, k) or t < sim.next_review[k]:
                continue
            sim.next_review[k] = max(sim.next_review[k] + e.review_n[k], t + 1)
            p = self.prep(sim, t, k)
            if p is not None:
                items.append(p)
                if self.report_rp:
                    self.rp[k] = self.trigger(p, sim.closing[t, k] + sim.on_order[k])
        if not items:
            if self.staples:
                self.staple_orders(sim, t)
            return
        coupled = self.storage is not None or self.budget_week is not None
        if coupled or self.force_milp:
            ms, obj = self.milp_day(sim, t, items)
            if not coupled and obj is not None:                  # validation mode: compare with exact enumeration
                for p, m in zip(items, ms):
                    m0, j0 = self.enum(p)
                    jm = (p['cu'] * np.maximum(0, p['W'] - p['B'] - m * p['pack']) + p['co'] * np.maximum(0, p['B'] + m * p['pack'] - p['Dl'])).mean()
                    if jm > j0 + 1e-6 * max(1.0, abs(j0)):
                        self.stats['mismatches'] += 1
            if coupled:
                free = [self.enum(p)[0] for p in items]
                cut = sum(1 for a, b in zip(free, ms) if b < a)
                if cut:
                    self.stats['orders_cut_by_storage'] += cut
                    self.stats['storage_binding_days' if self.storage is not None else 'budget_binding_days'] += 1
        else:
            ms = []
            for p in items:
                m, j = self.enum(p); ms.append(m); self.obj_total += j; self.stats['enum_solves'] += 1
        if self.guard:
            ms = [max(m, math.ceil(p['mp'])) if (not sim.e.perish[p['k']] and sim.closing[t, p['k']] + sim.on_order[p['k']] <= 1e-9) else m for p, m in zip(items, ms)]
        for p, m in zip(items, ms):
            if m > 0:
                q = m * p['pack']
                sim.place(t, p['k'], q)
                self.spend[t] += q * e.cost[p['k']]
        if self.staples:
            self.staple_orders(sim, t)

    def staple_orders(self, sim, t):
        """a kitchen keeps these on hand: on an order day, if the stock that is still usable one delivery cycle from now (batches that do not expire before then,
        plus what is already on order) is below its floor (two packs for very cheap packs, else one) or cannot cover 1.5 cycles of average use, order the packs that close the gap (at least the minimum order)."""
        e = sim.e
        for k in self.staple_idx(e):
            if not sim.order_day(t, k) or t >= e.nd - 1:
                continue
            cyc = int(e.lt_nom[k]) + int(max(e.interval[k], 1))
            mu = float(sim.hist[max(0, t - 28):t, k].mean()) if t else 0.0
            mu = max(mu, float(e.warm[k]) if hasattr(e, 'warm') and not (_lowvol(sim, t) and t >= 28) else 0.0)      # the start-up demand proxy (first 28 days of the unshaped template) only until the history exists, in the tiny first months
            if MOVING_DAYS and e.life[k] <= 3 and sim.hist[max(0, t - MOVING_DAYS):t, k].sum() <= 0:
                continue                      # a 3-day item is only kept on hand while it is moving (used in the last 30 days)
            eff = sum(b[0] for b in sim.batches[k] if b[1] >= t + cyc) + sim.on_order[k]
            pk = e.pack[k] * e.cost[k]
            floor = (2.0 if pk <= 25.0 else 1.0) * float(e.pack[k])
            if _lowvol(sim, t): floor = 0.0      # two packs only for very cheap packs (<= PHP 25); otherwise one (v12 step 8: fewer expiring packs)
            cover = (STAPLE_COVER_CHEAP if e.life[k] >= 7 else STAPLE_COVER_SHORT) if e.pack[k] * e.cost[k] <= 100.0 else STAPLE_COVER      # cheap packs are covered more generously than dear ones; very short-life produce only moderately
            need = max(mu * cyc * cover, floor)      # a staple always has a floor of full packs (two for very cheap packs, else one) usable one delivery cycle ahead, even when it has not been used lately
            if eff + 1e-9 < need:
                packs = max(math.ceil((need - eff) / e.pack[k]), int(e.moq_packs[k]))
                if _os.environ.get('SAL_DEMAND_LOT', '1') == '1' and str(e.code[k]) == 'SAL' and mu * 28 >= 1.8 * e.pack[k]:
                    packs = max(packs, 2)      # same demand-dependent salmon lot as in prep(): two fish per purchase when 28 days of use reach 1.8 fish (client: PHP 5k a purchase, once or twice a month)
                q = packs * e.pack[k]
                sim.place(t, k, q)
                self.spend[t] += q * e.cost[k]
                self.stats['staple_orders'] = self.stats.get('staple_orders', 0) + 1

    def staple_idx(self, e):
        if not hasattr(self, '_sidx'):
            self._sidx = [int(i) for c in self.staples for i in __import__('numpy').flatnonzero(e.code == c)]
            self._sidx = [i for i in self._sidx if bool(e.managed[i])] if hasattr(e, 'managed') else self._sidx          # v14: staples only in scope
        return self._sidx

    def decide(self, sim, t, k):
        pass
