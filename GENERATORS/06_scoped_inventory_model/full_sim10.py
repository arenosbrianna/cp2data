"""v10 full-world simulator (copy of v7/full_sim.py with: HI-TOP small-bundle same-day purchases, per-delivery trim/yield variability, delivery diagnostics): the v5 engine's stock + lost-sales day loop, rebuilt in the CURRENT (renumbered) id space, with a pluggable ordering policy.

What is reused unchanged from v5_engine.simulate (same equations, same parameters from v5_params.py):
  kitchen variance, off-POS staff meals and tuna bulk prep, FEFO consumption, expiry binning (and the closure rule), same-day emergency purchase
  with probability p_cure (always on real-POS days), lost units q' = floor(q * min_k stock_k/need_k), shortage cost = lost margin + premium,
  batch unit cost = standard cost x U(0.94, 1.08), lead time max(nominal, round(lt (1 + 0.35 w) + N(0, sd))).
What changes: the ordering decision (policy object: v6 optimiser, or the old (R,s,S) for the regression test).
Demand: the PRE-LOSS item demand of the shipped world is recovered exactly = served units in sales.csv + lost units in the pre-renumber
lost_sales_events.csv (real-POS days: sales + dropped lines, never changed).  The 2025-12-01.. client lines are never touched.
"""
import math, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'v6'))
from common import load, PKG
from policy_sim import Env, Sim, SEED, SEAM

BK_LOST = PKG.parent / 'generated_v4_supabase_ready_20261010_pre_renumber_backup' / 'generated_v4'
GAMMA_SHAPE, LOSS_NOISE = 4.0, 0.01
OFF_POS_DAILY = {'GB': 342.8571}; OFF_POS_RATIO = {'TUN': 2.0}; BULK_DOW = (1, 4)
import os as _os2
TUN_OFFPOS_G_WEEK = float(_os2.environ.get('TUN_OFFPOS_G_WEEK', '2000'))      # 0 = the earlier rule (2.0 x the POS tuna use)
KITCHEN_LOSS = {'vegetable': .05, 'fruit': .05, 'seafood': .04, 'tofu': .04, 'chicken': .03, 'pork': .03, 'beef': .03, 'dairy': .03, 'egg': .03,
                'noodle': .02, 'rice': .02, 'sauce': .02, 'condiment': .02, 'dry goods': .02, 'packaging': .02, 'beverage': .02}


class World:
    def __init__(self, d=None):
        d = d or load(); self.d = d
        menu, rec, ing, sales, inv = d['menu'], d['rec'], d['ing'].sort_values('ingredient_id').reset_index(drop=True), d['sales'], d['inv']
        self.days = pd.DatetimeIndex(sorted(inv.snapshot_date.unique())); self.nd = len(self.days)
        self.items = menu.item_id.to_numpy(); self.ni = len(self.items); self.iidx = {int(i): k for k, i in enumerate(self.items)}
        self.ng = len(ing); gidx = {int(g): k for k, g in enumerate(ing.ingredient_id)}
        B = np.zeros((self.ni, self.ng))
        for r in rec.itertuples():
            B[self.iidx[r.item_id], gidx[r.ingredient_id]] += r.qty_base
        self.B = B; self.item_cost = B @ ing.standard_unit_cost.to_numpy(float)
        di = {x: k for k, x in enumerate(self.days)}
        served = np.zeros((self.nd, self.ni), dtype=np.int64)
        g = sales.groupby(['sale_date', 'item_id']).quantity_sold.sum()
        for (dt, it), v in g.items():
            served[di[dt], self.iidx[int(it)]] = v
        self.served_old = served
        # old lost units: pre-renumber item ids -> current ids (order-preserving, names verified)
        mb = pd.read_csv(BK_LOST / 'menu_items.csv').sort_values('item_id').reset_index(drop=True)
        assert (mb.item_name.values == menu.item_name.values).all() and (mb.list_price.values == menu.list_price.values).all()
        omap = dict(zip(mb.item_id, menu.item_id))
        lost = pd.read_csv(BK_LOST / 'lost_sales_events.csv', parse_dates=['sale_date'])
        Q = served.copy()
        for r in lost.itertuples():
            Q[di[r.sale_date], self.iidx[omap[r.item_id]]] += r.lost_units
        real_t = np.asarray(self.days >= SEAM)
        for r in d['dropped'].itertuples():
            Q[di[pd.Timestamp(r.sale_date)], self.iidx[int(r.item_id)]] += r.quantity_sold
        self.Q = Q; self.real_t = real_t
        # price matrix (Dine-In list price over time, forward/back filled), used only for the lost-margin part of the shortage cost
        px = sales[sales.channel == 'Dine-In'].groupby(['sale_date', 'item_id']).unit_price.median().unstack().reindex(self.days)
        px = px.reindex(columns=self.items).ffill().bfill()
        lp = menu.set_index('item_id').list_price.reindex(self.items)
        px = px.fillna(lp)
        self.Pm = px.to_numpy(float)


class FullSim(Sim):
    def __init__(self, env, policy, W, seed=SEED, tun_off_pos=True, cfg=None):
        self.cfg = cfg or {}
        self.e, self.policy, self.W = env, policy, W
        self.u, self.z = env.draws(seed)
        r = np.random.default_rng(seed + 11); self.ucn = r.uniform(0.94, 1.08, (env.nd, env.ng))
        self.rng = np.random.default_rng(seed + 1)
        self.p_cure = env.p_cure.copy()
        if 'p_cure_walk' in self.cfg:
            self.p_cure[env.walk] = self.cfg['p_cure_walk']
        self.lead_extra = 0; self.init_mult = 1.0; self.bias_scale = 1.0; self.N = env.N
        # yield model: code -> (mean usable share of the gross purchase, sd). Matched draws: one Beta draw per (day, ingredient) for scheduled arrivals and one for same-day buys
        self.ymod = {}; ng = env.ng; nd = env.nd
        self.Y1 = np.full((nd, ng), 1.0); self.Y2 = np.full((nd, ng), 1.0); ry = np.random.default_rng(seed + 21)
        for code_, (m_, sd_) in self.cfg.get('yield', {}).items():
            k_ = int(np.flatnonzero(env.code == code_)[0]); kk = m_ * (1 - m_) / sd_ ** 2 - 1; a_, b_ = m_ * kk, (1 - m_) * kk
            self.ymod[k_] = m_; self.Y1[:, k_] = np.clip(ry.beta(a_, b_, nd), 0.40, 0.95); self.Y2[:, k_] = np.clip(ry.beta(a_, b_, nd), 0.40, 0.95)
        self.deliveries = []; self.managed = env.managed.copy()
        self.proc_regular = 0.0; self.proc_emerg = 0.0; self.lost_margin = 0.0; self.prem_total = 0.0
        self.run()

    def place(self, t, k, qty, lt=None):
        if not self.managed[k]:          # v14: out-of-scope ingredients never enter purchasing
            return t
        lt = self.real_lt(t, k) if lt is None else lt
        arr = self.arrival_day(t, lt, k)
        self.pipe.setdefault(arr, []).append((k, qty, round(float(self.e.cost[k] * self.ucn[t, k]), 4)))
        self.on_order[k] += qty; self.order_qty[t, k] += qty
        return arr

    def run(self):
        e, W, rng = self.e, self.W, self.rng; nd, ng, ni = e.nd, e.ng, W.ni
        code, cost, whole, walk, prem = e.code, e.cost, e.whole, e.walk, e.prem
        B = W.B; Bpos = B > 0; loss = np.array([KITCHEN_LOSS[c] for c in self.W.d['ing'].sort_values('ingredient_id').category])
        gb, tun = int(np.flatnonzero(code == 'GB')[0]), int(np.flatnonzero(code == 'TUN')[0])
        theo_all = W.Q @ B; warm = np.maximum(theo_all[:28].mean(axis=0), 0)
        closed_t = set(np.flatnonzero(e.closed).tolist()); open_days = np.array([t not in closed_t for t in range(nd)])
        next_open = np.empty(nd, int); nxt = nd
        for t in range(nd - 1, -1, -1):
            if open_days[t]:
                nxt = t
            next_open[t] = nxt
        self.orig = {}      # batch id -> quantity when it entered stock (waste_reason)
        self.batches = [[] for _ in range(ng)]; self.pipe = {}; self.on_order = np.zeros(ng); self.next_review = np.zeros(ng, int); self.since_recv = np.zeros(ng)
        self.hist = np.zeros((nd, ng)); pos_hist = theo_all.copy()
        self.closing = np.zeros((nd, ng)); self.received = np.zeros((nd, ng)); self.order_qty = np.zeros((nd, ng)); self.open0 = np.zeros((nd, ng))
        self.Qs = np.zeros_like(W.Q); self.Qs[:] = 0
        d0 = e.days[0]; sid = e.sid; nb = 1; gid = W.d['ing'].sort_values('ingredient_id').ingredient_id.to_numpy()
        for k in range(ng):
            if self.managed[k] and (warm[k] > 0 or str(code[k]) in getattr(self.policy, 'staples', ())):     # v12: a staple starts with one pack on hand
                q0 = float(np.ceil(max(warm[k] * e.review_n[k] * 1.5, e.pack[k]) / e.pack[k]) * e.pack[k])
                self.batches[k].append([q0, int(e.life[k]) - 1, nb, 0, float(cost[k])]); nb += 1; self.orig[nb - 1] = self.batches[k][-1][0]
        self.policy.start(self)
        inv_rows, waste_rows, batch_rows, stock_events, lost_rows = [], [], [], [], []
        waste_id = 1; last_prep = -10 ** 6; rp = np.zeros(ng)
        self.reorder_point = np.zeros((nd, ng)); self.on_order_t = np.zeros((nd, ng))
        rec_cols = {}
        T = {k: np.zeros((nd, ng)) for k in ('emerg', 'consumed', 'off_served', 'unmet', 'short_cost', 'emerg_cost', 'waste', 'kv', 'emc')}
        flag = np.zeros((nd, ng), bool)
        for t in range(nd):
            day = e.days[t]
            for ent in self.pipe.pop(t, []):
                k, q, uc = ent
                qn = q; self.proc_regular += uc * qn
                if k in self.ymod:                                   # q is the ordered quantity in USABLE grams at the mean yield; the delivery trims differently
                    gross = qn / self.ymod[k]; y = float(self.Y1[t, k]); q = gross * y; uc = round(uc * qn / q, 4)       # stored with the 4 decimals of the schema
                    self.deliveries.append(dict(day=day.date(), ingredient=str(code[k]), supplier=int(e.sid[k]), channel='scheduled', gross_g=round(gross, 2), trim_pct=round((1 - y) * 100, 2), usable_g=round(q, 2),
                                                trim_loss_g=round(gross - q, 2), purchase_cost_php=round(uc * q, 2), effective_unit_cost=round(uc, 4)))
                self.batches[k].append([q, t + int(e.life[k]) - 1, nb, t, uc]); nb += 1; self.orig[nb - 1] = self.batches[k][-1][0]; self.received[t, k] += q
                self.on_order[k] = max(0.0, self.on_order[k] - qn)
            opening = np.array([sum(b[0] for b in self.batches[k]) for k in range(ng)])
            opening_rec = opening - self.received[t]            # engine reports opening before the morning receipt
            self.open0[t] = opening
            mean_prev = self.hist[max(0, t - 28):t].mean(axis=0) if t else np.zeros(ng)
            for k in range(ng):
                expd = [b for b in self.batches[k] if t > b[1]]
                if not expd:
                    continue
                use90 = float(self.hist[max(0, t - 90):t, k].mean()) if t else 0.0      # v12 step 8: trailing 90-day mean use
                for b in expd:
                    T['waste'][t, k] += b[0]
                    wd = e.days[next_open[t]] if t in closed_t and next_open[t] < nd else day
                    waste_rows.append(dict(waste_id=waste_id, waste_date=wd, ingredient_id=int(gid[k]), batch_id=b[2],
                                           waste_qty=round(b[0], 4), waste_reason=('overstock' if self.orig[b[2]] > int(e.life[k]) * use90 + 1e-9 else 'expiry'), waste_value_php=round(round(b[0], 4) * b[4], 2)))
                    waste_id += 1
                self.batches[k] = [b for b in self.batches[k] if t <= b[1]]
            onhand = np.array([sum(b[0] for b in self.batches[k]) for k in range(ng)])
            q = W.Q[t].copy(); is_open = open_days[t]; real_day = bool(W.real_t[t])
            theo = q @ B
            varf = np.where(theo > 0, np.maximum(1 + loss * rng.gamma(GAMMA_SHAPE, 1 / GAMMA_SHAPE, ng) + rng.normal(0, LOSS_NOISE, ng), 0.97), 1.0)
            off = np.zeros(ng); ev = []
            if is_open:
                for c, per_day in OFF_POS_DAILY.items():
                    kk = int(np.flatnonzero(code == c)[0]); x = per_day * rng.uniform(0.85, 1.15); off[kk] += x; ev.append((kk, x))
                if day.dayofweek in BULK_DOW and t > 6:
                    for c, ratio in OFF_POS_RATIO.items():
                        kk = int(np.flatnonzero(code == c)[0]); gap = min(t - last_prep, 7) if last_prep > 0 else 3
                        if TUN_OFFPOS_G_WEEK > 0 and c == 'TUN':      # client T1: staff meals, trimmings, off-menu kinilaw / belly specials, comps / tasting / catering and cutting loss take about 2.0 kg a week whatever the till sells (a fish lasts about 25 days): independent of POS volume
                            x = TUN_OFFPOS_G_WEEK / 7.0 * gap * rng.uniform(0.9, 1.1)
                        else:
                            x = ratio * pos_hist[max(0, t - 28):t, kk].mean() * gap * rng.uniform(0.9, 1.1)
                        if x > 0:
                            off[kk] += x; ev.append((kk, x)); last_prep = t
            need = np.where(self.managed, theo * varf + off, 0.0)         # v14: out-of-scope ingredients are not stocked, so they can never be short or cut a dish
            sk = np.ones(ng); uncured = np.zeros(ng, bool); short = need > onhand + 1e-6
            for k in np.flatnonzero(short):
                if real_day or self.u[t, k] < self.p_cure[k]:
                    continue
                sk[k] = onhand[k] / need[k]; uncured[k] = True
            qs = q.copy(); lost_day = []
            if uncured.any():
                Smat = np.where(Bpos & uncured[None, :], sk[None, :], 1.0); f_i = Smat.min(axis=1); bind = Smat.argmin(axis=1)
                qs = np.where(f_i < 1, np.floor(q * f_i + 1e-9), q).astype(np.int64)
                for ii in np.flatnonzero(qs < q):
                    lu = int(q[ii] - qs[ii]); price = W.Pm[t, ii]
                    lost_day.append((bind[ii], lu * (price * 0.978 - W.item_cost[ii])))
            self.Qs[t] = qs
            theo2 = qs @ B; need2 = np.where(self.managed, theo2 * varf + off * sk, 0.0); kv = theo2 * (varf - 1); off_served = np.where(self.managed, off * sk, 0.0)
            self.hist[t] = need2; pos_hist[t] = theo2
            consumed = np.zeros(ng); emergency = np.zeros(ng); unmet = np.zeros(ng); em_cost = np.zeros(ng); em_prem = np.zeros(ng)
            for k in range(ng):
                if need2[k] <= 0:
                    continue
                consumed[k] = self._fefo(k, need2[k])
                if consumed[k] < need2[k] - 1e-6:
                    flag[t, k] = True
                    if code[k] in self.cfg.get('inc', {}):                 # HI-TOP small bundles: whole bundles of inc usable-equivalent grams, price per gross gram
                        gap = need2[k] - consumed[k]; inc_u = float(self.cfg['inc'][code[k]]); ymn = self.ymod.get(k, 1.0); gross_inc = inc_u / ymn
                        price_g = cost[k] * ymn * float(self.cfg.get('bundle_price_mult', 1.0)); n_b = 0; got = 0.0
                        while got < gap - 1e-9 and n_b < 50:
                            n_b += 1; got += gross_inc * float(self.Y2[t, k]) if k in self.ymod else inc_u
                        tot = n_b * gross_inc * price_g; uc2 = round(tot / got, 4)
                        self.batches[k].append([got, t + int(e.life[k]) - 1, nb, t, uc2]); nb += 1; self.orig[nb - 1] = self.batches[k][-1][0]
                        emergency[k] = got; consumed[k] += self._fefo(k, gap); em_cost[k] = tot; em_prem[k] = max(0.0, tot - got * cost[k]); self.proc_emerg += tot
                        if k in self.ymod:
                            self.deliveries.append(dict(day=day.date(), ingredient=str(code[k]), supplier=int(e.sid[k]), channel='walk-in small bundle', gross_g=round(n_b * gross_inc, 2), trim_pct=round((1 - got / (n_b * gross_inc)) * 100, 2),
                                                        usable_g=round(got, 2), trim_loss_g=round(n_b * gross_inc - got, 2), purchase_cost_php=round(tot, 2), effective_unit_cost=round(uc2, 4)))
                        continue
                    if whole[k]:
                        n = math.ceil((need2[k] - consumed[k]) / e.pack[k] - 1e-9)
                        self.batches[k].append([n * e.pack[k], t + int(e.life[k]) - 1, nb, t, float(cost[k])]); nb += 1; self.orig[nb - 1] = self.batches[k][-1][0]
                        emergency[k] = n * e.pack[k]; consumed[k] += self._fefo(k, need2[k] - consumed[k]); continue
                    emergency[k] = need2[k] - consumed[k]; consumed[k] = need2[k]
            short_cost = np.zeros(ng)
            for k in np.flatnonzero(short | uncured):
                lost_c = sum(c for b_, c in lost_day if b_ == k) if uncured[k] else 0.0
                unmet[k] = (need[k] - need2[k]) if uncured[k] else 0.0
                if emergency[k] <= 1e-9 and unmet[k] <= 1e-9:      # the shortage vanished (dishes were cut because of another ingredient): nothing bought, nothing lost, no event
                    continue
                pr_ = em_prem[k] if em_cost[k] > 0 else emergency[k] * cost[k] * prem[k]; short_cost[k] = lost_c + pr_; flag[t, k] = True; self.lost_margin += lost_c; self.prem_total += pr_
                stock_events.append(dict(event_date=day, ingredient_id=int(gid[k]), need_qty=round(need[k], 4), available_qty=round(onhand[k], 4),
                                         shortfall_qty=round(max(need[k] - onhand[k], 0), 4), outcome='LOST_SALES' if uncured[k] else 'EMERGENCY_PURCHASE', emergency_qty=round(emergency[k], 4),
                                         emergency_cost_php=round(em_cost[k] if em_cost[k] > 0 else emergency[k] * cost[k] * (1 + prem[k]), 2), unmet_qty=round(unmet[k], 4), shortage_cost_php=round(short_cost[k], 2)))
            closing = np.array([sum(b[0] for b in self.batches[k]) for k in range(ng)]); self.closing[t] = closing
            for k in range(ng):
                for b in self.batches[k]:
                    if round(b[0], 4) > 0:      # v12: a residue that rounds to 0.0000 is not a batch row (the schema requires qty_on_hand > 0)
                        batch_rows.append((day, b[2], int(gid[k]), int(sid[k]), d0 + pd.Timedelta(days=int(b[3])), d0 + pd.Timedelta(days=int(b[1])), round(b[0], 4), b[4]))
            T['emerg'][t] = emergency; T['consumed'][t] = consumed; T['off_served'][t] = off_served; T['unmet'][t] = unmet; T['short_cost'][t] = short_cost; T['emc'][t] = np.where(em_cost > 0, em_cost, emergency * cost * (1 + prem))
            self.policy.day(self, t) if hasattr(self.policy, 'day') else [self.policy.decide(self, t, k) for k in range(ng)]
            self.on_order_t[t] = self.on_order
            rp = self.policy.reorder_levels(self, t) if hasattr(self.policy, 'reorder_levels') else rp
            self.reorder_point[t] = rp
            self._flag_unused = None
        self.T, self.flag = T, flag
        self.waste_rows, self.stock_events, self.batch_rows, self.lost_rows = waste_rows, stock_events, batch_rows, lost_rows
        self.n_batches_total = nb - 1

    def _fefo(self, k, want):
        b = self.batches[k]; b.sort(key=lambda x: (x[3], x[2])); taken = 0.0
        for x in b:
            if want <= 1e-9:
                break
            y = min(x[0], want); x[0] -= y; want -= y; taken += y
        self.batches[k] = [x for x in b if x[0] > 1e-9]
        return taken

    # ------------------------------------------------------------------ output tables in the current schema
    def tables(self):
        e, W, T = self.e, self.W, self.T
        gid = W.d['ing'].sort_values('ingredient_id').ingredient_id.to_numpy()
        rows = []
        nd, ng = e.nd, e.ng
        cost = e.cost
        T_prem = e.prem
        inv = pd.DataFrame({
            'snapshot_date': np.repeat(e.days.values, ng), 'ingredient_id': np.tile(gid, nd),
            'opening_qty': (self.open0 - self.received).ravel().round(4), 'qty_received': self.received.ravel().round(4), 'qty_emergency': T['emerg'].ravel().round(4),
            'qty_consumed': T['consumed'].ravel().round(4), 'qty_off_pos_use': T['off_served'].ravel().round(4), 'closing_qty': self.closing.ravel().round(4),
            'reorder_point': self.reorder_point.ravel().round(4), 'order_qty': self.order_qty.ravel().round(4), 'on_order_qty': self.on_order_t.ravel().round(4),
            'stockout_flag': self.flag.ravel(), 'emergency_cost_php': T['emc'].ravel().round(2),
            'qty_unmet': T['unmet'].ravel().round(4), 'shortage_cost_php': T['short_cost'].ravel().round(2)})
        inv = inv[inv.ingredient_id.isin(gid[self.managed])].reset_index(drop=True)          # v14: inventory facts exist only for the perishable scope
        bat = pd.DataFrame(self.batch_rows, columns=['snapshot_date', 'batch_id', 'ingredient_id', 'supplier_id', 'received_date', 'expiry_date', 'qty_on_hand', 'unit_cost'])
        return inv, bat, pd.DataFrame(self.waste_rows), pd.DataFrame(self.stock_events)
