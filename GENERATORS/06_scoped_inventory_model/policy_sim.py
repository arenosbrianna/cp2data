"""v6 policy simulator: replays ONE common ingredient-demand sequence (taken from the validated generated_v4 tables) through different
ordering policies under identical environment rules, so policies differ only in their ordering decisions.

Common environment (identical for every policy compared):
  demand      need[t,k] = qty_consumed + qty_unmet of generated_v4/inventory.csv  (unconstrained ingredient need, base units; includes
              kitchen variance and off-POS use).  SYNTHETIC history until 2025-11-30, client POS from 2025-12-01.
  opening     one batch per ingredient with positive POS-driven use: ceil(max(warm*review*1.5, pack)/pack)*pack, expiry = shelf life (engine rule)
  suppliers   pack, MOQ (packs), nominal lead time max(1, lead_time_days), delivery_interval_days and offset sid % interval (engine rules);
              realised lead time = max(nominal, round(lt*(1+0.35*weather)+z*sd)), z drawn once per (day, ingredient) and shared by all policies
  shortage    need > usable stock: on a real-POS day always bought the same day (client sales are fixed); on a synthetic day bought with
              probability p_cure (0.95 walk-in HI-TOP, 0.60 others; SYNTHETIC_ASSUMPTION), uniform u drawn once per (day, ingredient) and
              shared by all policies; otherwise the gap is unmet demand (lost).  Whole-fish items (SAL, TUN) are emergency-bought in whole packs.
  expiry      a batch is usable through its expiry date and binned the next morning; FEFO consumption
  costs       every policy is costed at standard unit cost (batch-level price noise of the original engine is not replicated)
"""
import math, os
from pathlib import Path
import numpy as np, pandas as pd
from common import *

SEED = 20261010
SEAM = pd.Timestamp('2025-12-01')
WALK_IN = ('HI-TOP',)
WHOLE = ('SAL', 'TUN')
PREMIUM = 0.25
SERVICE_Z, LEAD_KAPPA, FRESH_REVIEW, DRY_REVIEW = 1.41, 0.35, 1, 7
SPARSE_FRAC, PERISH_COVER, COVER_FLOOR = 0.50, 0.70, 0.5


class Env:
    def __init__(self, d=None, pack_alt=None, pen=None):
        d = d or load()
        ing = d['ing'].sort_values('ingredient_id').reset_index(drop=True)
        inv = d['inv'].sort_values(['snapshot_date', 'ingredient_id'])
        self.days = pd.DatetimeIndex(sorted(inv.snapshot_date.unique())); self.nd = len(self.days); self.ng = len(ing)
        self.gids = ing.ingredient_id.to_numpy(); self.code = ing.ingredient_code.to_numpy()
        def _grid(col):          # v14: the stock tables hold only the perishable scope; the demand history is read on the full ingredient grid (zero for ingredients without stock rows)
            return inv.pivot(index='snapshot_date', columns='ingredient_id', values=col).reindex(index=self.days, columns=self.gids).fillna(0.0).to_numpy()
        self.N = _grid('qty_consumed') + _grid('qty_unmet')
        self.OFF = _grid('qty_off_pos_use')
        self.CONS0 = _grid('qty_consumed')
        self.closed = self.N.sum(axis=1) <= 0
        self.real_t = (self.days >= SEAM)
        self.cost = ing.standard_unit_cost.to_numpy(float)
        self.shelf = ing.shelf_life_days.to_numpy(float); self.life = np.maximum(self.shelf.astype(int), 1)
        self.perish = ing.is_perishable.to_numpy(bool); self.managed = np.ones(self.ng, bool)
        # v14 perishable-inventory scope (2026-10-15): dim_ingredient.is_perishable is now the INVENTORY SCOPE (v14/ingredient_scope_register.csv). The ordering rules below (daily review of fresh items, sparse rule, par cap)
        # keep the legacy modelling flag (shelf <= 7 d / dairy / mushroom / egg and the other chilled produce and noodles), which the register preserves as legacy_is_perishable, so managed ingredients behave exactly as before.
        _reg = PKG / 'v14' / 'ingredient_scope_register.csv'
        if os.environ.get('SCOPE', 'on') == 'on' and _reg.exists():
            reg = pd.read_csv(_reg).set_index('ingredient_code').reindex(self.code)
            self.perish = reg.legacy_is_perishable.to_numpy(bool); self.managed = ing.is_perishable.to_numpy(bool)
            assert (self.managed == reg.in_inventory_scope.to_numpy(bool)).all(), 'ingredients.csv is_perishable differs from the scope register'
        self.count_unit = ing.base_uom.isin(['pc', 'serving']).to_numpy()
        self.storage = ing.storage_type.to_numpy()
        t = d['terms'].set_index('ingredient_id').reindex(self.gids); sup = d['sup'].set_index('supplier_id')
        self.pack = t.pack_size_base.to_numpy(float).copy(); self.moq_packs = t.min_order_packs.to_numpy(float).copy()
        if pack_alt:                                            # what-if: smaller order step (hypothetical, never the client baseline)
            for c, step in pack_alt.items():
                k = int(np.flatnonzero(self.code == c)[0]); self.pack[k] = step; self.moq_packs[k] = 1.0
        self.moq = self.moq_packs * self.pack
        self.sid = t.supplier_id.astype(int).to_numpy()
        self.lt_mean = np.maximum(1, sup.loc[self.sid, 'lead_time_days'].to_numpy(float))
        self.lt_nom = np.maximum(1, np.round(self.lt_mean)).astype(int)
        self.lt_sd = sup.loc[self.sid, 'lead_time_sd_days'].to_numpy(float)
        self.interval = sup.loc[self.sid, 'delivery_interval_days'].to_numpy(int).copy()
        self.offset = self.sid % np.maximum(self.interval, 1)
        walk = np.isin(sup.loc[self.sid, 'supplier_name'].to_numpy(), WALK_IN)
        self.walk = walk; self.p_cure = np.where(walk, 0.95, 0.60)
        self.whole = np.isin(self.code, WHOLE)
        self.prem = np.where(self.whole, 0.0, np.where(walk, 0.0, PREMIUM))
        self.fresh = self.perish & (self.shelf <= 21)          # v11: every refrigerated perishable (up to 3 weeks) is reviewed daily
        self.review_n = np.where(self.fresh, FRESH_REVIEW, DRY_REVIEW)
        self.replace_k = [int(np.flatnonzero(self.code == 'TUN')[0])]
        vol = d['vol'].set_index('ingredient_id').reindex(self.gids)
        self.litres = vol.litres_per_base_unit.to_numpy(float)
        self.pen = pen if pen is not None else np.zeros(self.ng)
        # engine latents (weather w, manager bias m): same construction and stream as v5_engine.simulate
        r_l = np.random.default_rng(SEED + 2); nd = self.nd
        r_l.normal(0, 0.25, nd)
        doy = self.days.dayofyear.to_numpy(); seas = 0.70 * np.sin(2 * np.pi * (doy - 100) / 365.25); resid = np.zeros(nd)
        etw = r_l.normal(0, 0.80 * math.sqrt(1 - 0.55 ** 2), nd)
        for i in range(1, nd):
            resid[i] = 0.55 * resid[i - 1] + etw[i]
        w_all = seas + resid; self.w_all = (w_all - w_all.mean()) / w_all.std()
        self.m_all = np.clip(0.18 * np.exp(-np.arange(nd) / (3 * 365.0)) + np.cumsum(r_l.normal(0, 0.010, nd)), -0.15, 0.80)
        warm = np.maximum((self.CONS0[:28] - self.OFF[:28]).mean(axis=0), 0)
        self.warm = warm

    def draws(self, seed):
        r = np.random.default_rng(seed)
        return r.random((self.nd, self.ng)), r.normal(0, 1, (self.nd, self.ng))


class Sim:
    """one run: env + policy + draw seed (+ optional scenario knobs)"""

    def __init__(self, env, policy, seed=1, demand_scale=1.0, p_cure_shift=0.0, lead_extra=0, init_mult=1.0, bias_scale=1.0, storage_cap=None, strict_pack=False):
        self.e = env; self.policy = policy
        self.u, self.z = env.draws(seed)
        self.N = env.N * demand_scale
        self.p_cure = np.clip(env.p_cure + p_cure_shift, 0, 1)
        self.lead_extra = lead_extra; self.init_mult = init_mult; self.bias_scale = bias_scale; self.storage_cap = storage_cap
        self.strict_pack = strict_pack            # v8 sensitivity: same-day purchases must also be whole packs (default: exact gap, as in the engine)
        self.run()

    # ---- calendar helpers (engine rules)
    def is_closed(self, t):
        return bool(self.e.closed[t]) if t < self.e.nd else False

    def delivery_day(self, t, k):
        return ((t - self.e.offset[k]) % self.e.interval[k] == 0) and not self.is_closed(t)

    def arrival_day(self, t0, lt, k):
        t = t0 + lt
        while not self.delivery_day(t, k):
            t += 1
        return t

    def order_day(self, t, k):
        return (not self.is_closed(t)) and self.delivery_day(t + self.e.lt_nom[k] + self.lead_extra, k)

    def real_lt(self, t, k):
        e = self.e
        base = e.lt_mean[k] * (1 + LEAD_KAPPA * e.w_all[t]) + self.z[t, k] * e.lt_sd[k]
        return int(max(e.lt_nom[k], round(base))) + self.lead_extra

    def place(self, t, k, qty, lt=None):
        lt = self.real_lt(t, k) if lt is None else lt
        arr = self.arrival_day(t, lt, k)
        self.pipe.setdefault(arr, []).append((k, qty)); self.on_order[k] += qty
        self.order_qty[t, k] += qty
        return arr

    def run(self):
        e = self.e; nd, ng = e.nd, e.ng
        self.batches = [[] for _ in range(ng)]; self.pipe = {}; self.on_order = np.zeros(ng); self.next_review = np.zeros(ng, int)
        self.hist = np.zeros((nd, ng)); self.since_recv = np.zeros(ng)
        self.closing = np.zeros((nd, ng)); self.received = np.zeros((nd, ng)); self.emerg = np.zeros((nd, ng)); self.consumed = np.zeros((nd, ng))
        self.unmet = np.zeros((nd, ng)); self.waste_q = np.zeros((nd, ng)); self.order_qty = np.zeros((nd, ng)); self.flag = np.zeros((nd, ng), bool)
        self.stockout_event = np.zeros((nd, ng), bool); self.n_batches = np.zeros(ng, int); self.n_wasted = np.zeros(ng, int)
        self.n_expired_on_arrival_gap = 0
        self.open0 = np.zeros((nd, ng)); self.litres_t = np.zeros((nd, 3))
        bid = 0
        for k in range(ng):
            if e.warm[k] > 0:
                q0 = float(np.ceil(max(e.warm[k] * e.review_n[k] * 1.5 * self.init_mult, e.pack[k]) / e.pack[k]) * e.pack[k])
                self.batches[k].append([q0, e.life[k] - 1]); self.n_batches[k] += 1
        self.policy.start(self)
        for t in range(nd):
            for k, q in self.pipe.pop(t, []):
                self.batches[k].append([q, t + e.life[k] - 1]); self.n_batches[k] += 1; self.received[t, k] += q
                self.on_order[k] = max(0.0, self.on_order[k] - q)
            for k in range(ng):
                b = self.batches[k]
                self.open0[t, k] = sum(x[0] for x in b)
                if b and any(x[1] < t for x in b):
                    for x in b:
                        if x[1] < t:
                            self.waste_q[t, k] += x[0]; self.n_wasted[k] += 1
                    self.batches[k] = [x for x in b if x[1] >= t]
                on = sum(x[0] for x in self.batches[k])
                need = self.N[t, k]
                if need > 0:
                    got = self._fefo(k, need)
                    if got < need - 1e-9:
                        self.flag[t, k] = True
                        if e.real_t[t] or self.u[t, k] < self.p_cure[k]:
                            gap = need - got                                  # emergency purchase, same day
                            if e.whole[k] or self.strict_pack:
                                n = math.ceil(gap / e.pack[k] - 1e-9)
                                self.batches[k].append([n * e.pack[k], t + e.life[k] - 1]); self.n_batches[k] += 1
                                self.emerg[t, k] = n * e.pack[k]; got += self._fefo(k, need - got)
                            else:
                                self.emerg[t, k] = gap; got = need
                        else:
                            self.unmet[t, k] = need - got; self.stockout_event[t, k] = True
                    self.consumed[t, k] = got
                self.hist[t, k] = self.consumed[t, k]
                self.closing[t, k] = sum(x[0] for x in self.batches[k])
            if hasattr(self.policy, 'day'):
                self.policy.day(self, t)
            else:
                for k in range(ng):
                    self.policy.decide(self, t, k)

    def _fefo(self, k, want):
        b = self.batches[k]; b.sort(key=lambda x: x[1]); taken = 0.0
        for x in b:
            if want <= 1e-9:
                break
            y = min(x[0], want); x[0] -= y; want -= y; taken += y
        self.batches[k] = [x for x in b if x[0] > 1e-9]
        return taken

    # ---- metrics (window = [t0, nd))
    def metrics(self, t0=0, pen=None, cost=None):
        e = self.e; s = slice(t0, None)
        pen = e.pen if pen is None else pen
        cost = e.cost if cost is None else cost
        rec = (self.received[s] * cost).sum(); emg = (self.emerg[s] * cost).sum()
        emg_prem = (self.emerg[s] * cost * e.prem).sum()
        waste_v = (self.waste_q[s] * cost).sum(); waste_q = self.waste_q[s]
        consumed_v = (self.consumed[s] * cost).sum()
        need_q = self.N[s]
        used = need_q > 0
        zero = self.closing[s] <= 1e-9
        r = dict(
            purchases_php=rec + emg, regular_purchases_php=rec, emergency_purchases_php=emg, emergency_premium_php=emg_prem,
            waste_php=waste_v, waste_pct_of_purchases_php=waste_v / (rec + emg), waste_pct_of_consumption_php=waste_v / consumed_v,
            lost_sales_cost_php=(self.unmet[s] * pen).sum(), unmet_units_pct_of_need=(self.unmet[s] * cost).sum() / (need_q * cost).sum(),
            stockout_ing_days_pct=self.flag[s].mean() * 100, lost_event_ing_days_pct=self.stockout_event[s].mean() * 100,
            zero_close_all_pct=zero.mean() * 100, zero_close_on_used_days_pct=(zero & used).sum() / used.sum() * 100,
            service_level_value_pct=(1 - (self.unmet[s] * cost).sum() / (need_q * cost).sum()) * 100,
            avg_inventory_php=(self.closing[s] * cost).sum(axis=1).mean(), days_of_supply_value=(self.closing[s] * cost).sum(axis=1).mean() / (consumed_v / e_len(self.closing[s])),
            n_orders=int((self.order_qty[s] > 0).sum()), batches=int(self.n_batches.sum()),
        )
        r['modelled_cost_php'] = r['waste_php'] + r['emergency_premium_php'] + r['lost_sales_cost_php']
        return r


def e_len(a):
    return a.shape[0]


# =============================================================================================== baseline policy (engine replica)
class EnginePolicy:
    """(R, s, S) with manager-bias distortion exactly as in v5_engine.simulate (order rules), reading only information available at day t.
    fix_sparse=False reproduces the engine's dead branch (`since_recv` is never incremented, so the 'sparse perishable' rule can never fire);
    fix_sparse=True restores the v2 generator's `since_recv += need`."""

    def __init__(self, fix_sparse=False, bias=True, tun_rule=True):
        self.fix_sparse, self.bias, self.tun_rule = fix_sparse, bias, tun_rule

    def start(self, sim):
        pass

    def decide(self, sim, t, k):
        e = sim.e
        if self.fix_sparse:
            sim.since_recv[k] = (0.0 if sim.received[t, k] > 0 else sim.since_recv[k]) + sim.hist[t, k]
        if k in e.replace_k and self.tun_rule:
            self.replacement(sim, t, k)
        if not sim.order_day(t, k):
            return
        lo = max(0, t - 27); win = sim.hist[lo:t + 1, k]; mu = max(win.mean(), 0.0); sd = win.std()
        gap = max(e.review_n[k], e.interval[k]); prot = e.lt_mean[k] + gap
        s_lvl = mu * prot + SERVICE_Z * math.sqrt(max(prot, 1) * sd ** 2 + (mu * e.lt_sd[k]) ** 2)
        S_lvl = s_lvl + mu * gap
        shelf = max(e.shelf[k], 1.0)
        if e.perish[k]:
            cap_days = e.lt_mean[k] + max(shelf * PERISH_COVER, min(gap, shelf) + COVER_FLOOR)
            S_lvl = min(S_lvl, mu * cap_days)
        s_lvl = min(s_lvl, S_lvl)
        position = sim.closing[t, k] + sim.on_order[k]
        sparse = e.perish[k] and (mu * shelf < SPARSE_FRAC * e.pack[k])
        if sparse:
            if sim.since_recv[k] > 1e-9 and position <= 1e-6:
                qq = float(math.ceil(max(e.pack[k], e.moq[k]) / e.pack[k]) * e.pack[k])
                sim.place(t, k, qq, lt=e.lt_nom[k])
            return
        if t < sim.next_review[k]:
            return
        sim.next_review[k] = max(sim.next_review[k] + e.review_n[k], t + 1)
        if mu <= 0 or position > s_lvl:
            return
        m_t = sim.e.m_all[t] * sim.bias_scale if self.bias else 0.0
        raw_q = max(S_lvl - position, 0.0) * (1 + m_t)
        qq = float(math.ceil(max(raw_q, e.moq[k]) / e.pack[k]) * e.pack[k])
        if qq > 0:
            sim.place(t, k, qq)

    def replacement(self, sim, t, k):
        e = sim.e
        if not sim.order_day(t, k) or sim.on_order[k] > 1e-9:
            return
        arr = t + int(e.lt_nom[k])
        if arr >= e.nd:
            return
        nx = next((x for x in range(t + 1, e.nd - int(e.lt_nom[k])) if sim.order_day(x, k)), None)
        if nx is None:
            return
        first_day = arr - 1; last_day = nx + int(e.lt_nom[k]) - 2
        lo = max(0, t - 27); mu = max(sim.hist[lo:t + 1, k].mean(), 0.0); sd = sim.hist[lo:t + 1, k].std()
        gap = max(e.review_n[k], e.interval[k]); prot = e.lt_mean[k] + gap
        s_lvl = mu * prot + SERVICE_Z * math.sqrt(max(prot, 1) * sd ** 2 + (mu * e.lt_sd[k]) ** 2)
        S_lvl = s_lvl + mu * gap
        shelf = max(e.shelf[k], 1.0)
        S_lvl = min(S_lvl, mu * (e.lt_mean[k] + max(shelf * PERISH_COVER, min(gap, shelf) + COVER_FLOOR))) if e.perish[k] else S_lvl
        s_lvl = min(s_lvl, S_lvl)
        keep = sum(b[0] for b in sim.batches[k] if b[1] > last_day)
        if any(first_day <= b[1] <= last_day for b in sim.batches[k]) and keep - mu * e.lt_nom[k] <= s_lvl:
            sim.place(t, k, float(e.pack[k]), lt=e.lt_nom[k])
