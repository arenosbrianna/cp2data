"""v8 shortage cost per base unit, in the unit of the optimiser's shortage variable (grams / pieces / servings of the ingredient).

    lam_k  = lost contribution per base unit  = sum_i max(0, m_i) u_i / sum_i q_ik u_i
             m_i = mean net price per unit of dish i (sales lines) - standard recipe cost, u_i = units sold, q_ik = base units of k per serving
             (PHP per serving / base units per serving = PHP per base unit; a serving that lacks any one recipe ingredient cannot be sold, so one
             missing recipe quantity costs one serving margin; negative margins are floored at 0 per dish before aggregating)
    pi_k   = emergency premium PHP per base unit = premium_k x unit cost  (0 for the walk-in grocery and whole-fish packs, 25 % elsewhere)
    rho_s  = recovery rate of supplier s = share of its shortage events that were cured by a same-day purchase (baseline shortage log)
    cu_k   = (1 - rho_s) lam_k + rho_s pi_k          expected cost of one base unit of shortfall; this is what the optimiser's shortage variable multiplies
The V7 optimiser used lam_k (derived from lost-sales events of the old policy) as if every shortfall unit were lost, i.e. rho = 0."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'v6'))
from common import PKG, load

BASE = PKG / 'generated_v4_pre_v7'          # policy-independent baseline: shipped sales and shortage log


def shortage_costs(d=None, rho_override=None, source='baseline'):
    d = d or load()
    SRC = BASE if source == 'baseline' else (PKG / 'generated_v4')
    ing = d['ing'].sort_values('ingredient_id').reset_index(drop=True); rec, menu = d['rec'], d['menu']
    sales = pd.read_csv(SRC / 'sales.csv'); so = pd.read_csv(SRC / 'stockout_events.csv')
    import os as _os
    scope = ing.set_index('ingredient_id').is_perishable if _os.environ.get('SCOPE', 'on') == 'on' and _os.environ.get('SCOPE_PEN', 'managed') == 'managed' else ing.set_index('ingredient_id').is_perishable | True
    so = so[so.ingredient_id.map(scope).fillna(False).astype(bool)]          # v14: stockouts of out-of-scope ingredients do not set recovery rates or premiums
    cost = ing.set_index('ingredient_id').standard_unit_cost
    ic = rec.assign(c=rec.qty_base * rec.ingredient_id.map(cost)).groupby('item_id').c.sum()
    rev = sales[sales.is_revenue & (sales.quantity_sold > 0)].groupby('item_id').agg(u=('quantity_sold', 'sum'), net=('net_sales', 'sum'))
    m = pd.DataFrame(dict(u=rev.u, price=rev.net / rev.u)); m['margin'] = (m.price - ic.reindex(m.index)).clip(lower=0)
    r = rec.merge(m, left_on='item_id', right_index=True)
    g = r.assign(num=r.margin * r.u, den=r.qty_base * r.u).groupby('ingredient_id')[['num', 'den']].sum()
    lam = (g.num / g.den).reindex(ing.ingredient_id)
    t = d['terms'].set_index('ingredient_id').reindex(ing.ingredient_id); sup = d['sup'].set_index('supplier_id')
    em = so[so.outcome == 'EMERGENCY_PURCHASE'].merge(d['ing'][['ingredient_id', 'standard_unit_cost']], on='ingredient_id')
    pi_k = (em.groupby('ingredient_id').emergency_cost_php.sum() - (em.emergency_qty * em.standard_unit_cost).groupby(em.ingredient_id).sum()) / em.groupby('ingredient_id').emergency_qty.sum()
    pi = pi_k.reindex(ing.ingredient_id).fillna(0.0).clip(lower=0).to_numpy()          # measured premium per unit from the shortage log (0 when none was ever paid)
    ev = so.assign(sup=so.ingredient_id.map(d['terms'].set_index('ingredient_id').supplier_id))
    rho_s = ev.groupby('sup').apply(lambda x: (x.outcome == 'EMERGENCY_PURCHASE').mean())
    rho = t.supplier_id.map(rho_s).to_numpy() if rho_override is None else np.full(len(ing), rho_override)
    _ratio = pd.Series((lam / ing.set_index('ingredient_id').standard_unit_cost.reindex(ing.ingredient_id).to_numpy()).to_numpy(), index=ing.ingredient_id); pooled = float(_ratio[scope.reindex(ing.ingredient_id).to_numpy()].dropna().median())
    lam = np.where(np.isnan(lam.to_numpy()), pooled * ing.standard_unit_cost.to_numpy(), lam.to_numpy())          # ingredient in no sold recipe: pooled multiple of unit cost (stated assumption)
    cu = (1 - rho) * lam + rho * pi
    out = pd.DataFrame(dict(code=ing.ingredient_code.to_numpy(), unit_cost=ing.standard_unit_cost.to_numpy(), lam_php_per_unit=lam, premium_php_per_unit=pi, recovery_rate=rho, expected_cu=cu))
    return out
