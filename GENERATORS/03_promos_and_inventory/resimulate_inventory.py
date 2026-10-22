"""Regenerates inventory.csv, inventory_batches.csv and waste.csv in generated_v4_pre_stg_trim/ after the sales changed.

Why: the warehouse load reconciles ingredient consumption with sales x recipes (03_transform.sql). The promotion
reorganisation (reorganize_anniversary_promos.py) adds sale lines, which consume stock, so the inventory simulation has to
see them. The simulation is the project's own (makisushi_datagen_v2.simulate_inventory through build_v4_supply_ur.build);
nothing is edited by hand. It is deterministic: before this work a control run with unchanged sales reproduced the existing
inventory and batch files exactly (waste differed only by a lineage column the stg-trim step had dropped).

What it does:
  * the added lines are found by comparing the current sales source with the pristine copy in generated_v4_pre_promo_reorg/
    and are appended to the simulation's consumption table only, so every other table rebuilt by the run still equals generated_v3;
  * the two recipe edits that existed only in recipes.csv (item 63 Ebi Tempura 3 -> 2 shrimp, item 179 Upgrade to Mango
    Shake 180 -> 142 g) are applied to the simulation's recipes (any other difference stops the run);
  * it asserts that POS consumption changed by exactly (added lines x recipes + the recipe edit) on every ingredient-day, and
    writes a before / after metrics table to generated_v4_audit/anniversary_promo_inventory_resim.csv.

Note: the simulation draws from one random stream shared by all ingredients, so any extra order shifts every later draw:
consumption is exact, while receipts, waste and emergency purchases are a new draw (see the change summary).

Run:  py resimulate_inventory.py [--src DIR] [--basis DIR] [--out DIR]   (defaults: the project folder, its generated_v4_pre_promo_reorg/, the project folder)
"""
import argparse
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import build_v4_supply_ur as b
import client_answers as ca
import makisushi_datagen_v2 as v2
import workbook_fixes as wf

ROOT = Path(__file__).resolve().parent
PRE_NAME = 'generated_v4_pre_stg_trim'
FILES = ('inventory.csv', 'inventory_batches.csv', 'waste.csv')


def main(src_root, basis_root, out_root):
    """src_root: folder whose generated_v4_pre_stg_trim/ is read (sales, recipes, menu, calendar, ...);
    basis_root: the original basis the 'before' figures and hand-set register values come from;
    out_root: folder that receives the regenerated generated_v4_pre_stg_trim/{inventory,inventory_batches,waste}.csv,
    the client-answer registers and the metrics table (its generated_v4_pre_stg_trim/ and generated_v4_audit/ must exist)."""
    global BACKUP, PRE
    src = Path(src_root) / PRE_NAME
    BACKUP = Path(basis_root) / PRE_NAME
    PRE = src
    out_pre, out_audit = Path(out_root) / PRE_NAME, Path(out_root) / 'generated_v4_audit'
    assert out_pre.is_dir() and out_audit.is_dir(), 'the output folder needs generated_v4_pre_stg_trim/ and generated_v4_audit/'
    b.V4 = src
    # menu / sales / split-review fix-ups only shape tables this script does not write (the menu has been merged
    # since they ran); stock does not depend on them
    wf.fix_menu = lambda m: m
    wf.fix_sales = lambda s, v3: s
    wf.fix_split_review = lambda d: d
    wf.recipe_review_v4 = lambda d: d

    old = pd.read_csv(BACKUP / 'sales.csv', usecols=['sale_id', 'sale_date', 'item_id', 'quantity_sold'])
    cur = pd.read_csv(src / 'sales.csv', usecols=['sale_id', 'sale_date', 'item_id', 'quantity_sold'])
    added = cur[~cur['sale_id'].isin(old['sale_id'])]
    removed = old[~old['sale_id'].isin(cur['sale_id'])]     # sale lines dropped from the source: they must stop consuming stock
    print(f'{len(added)} added and {len(removed)} removed sale lines change the consumption table')

    orig = v2.build_consumption

    def with_added(sales, dropped, bom, closed):
        for r in removed.itertuples():          # one simulated line matches each removed source line (date, item, quantity)
            hit = sales.index[(sales['date'] == pd.Timestamp(r.sale_date)) & (sales['item_id'] == r.item_id)
                              & (sales['quantity_sold'] == r.quantity_sold) & ~sales['_dup_copy'] & ~sales['_closure_adjusted']]
            assert len(hit) == 1, f'removed line {r.sale_id}: {len(hit)} matching simulated lines'
            sales = sales.drop(index=hit[0])
        extra = pd.DataFrame({'date': pd.to_datetime(added['sale_date']).astype(sales['date'].dtype),
                              'item_id': added['item_id'].astype(sales['item_id'].dtype),
                              'quantity_sold': added['quantity_sold'].astype(sales['quantity_sold'].dtype),
                              '_dup_copy': False, '_closure_adjusted': False})
        cols = ['date', 'item_id', 'quantity_sold', '_dup_copy', '_closure_adjusted']
        return orig(pd.concat([sales[cols], extra], ignore_index=True), dropped, bom, closed)

    v2.build_consumption = with_added

    # Recipe edits made after the simulation ran (DATA_NOTES, 2026-10-09: item 63 Ebi Tempura 3 -> 2 shrimp, item 179
    # Upgrade to Mango Shake 180 -> 142 g mango) exist only in generated_v4_pre_stg_trim/recipes.csv, so the stock
    # still consumed the old amounts and the load's consumption check failed on 10 ingredient-days (also in the
    # pristine data). The simulation now reads the current recipe quantities; only those two items may differ.
    cur_recipe = pd.read_csv(src / 'recipes.csv').set_index(['item_id', 'ingredient_id'])['qty_per_item']
    edited, orig_v4 = {}, ca.v4_recipe_lines

    def v4_with_current_quantities(df, qty, *args, **kw):
        res = orig_v4(df, qty, *args, **kw)
        rec = res[0]
        want = cur_recipe.reindex(pd.MultiIndex.from_frame(rec[['item_id', 'ingredient_id']])).to_numpy()
        have = rec[qty].to_numpy(dtype=float)
        diff = ~np.isnan(want) & ~np.isclose(want, have)
        assert set(rec.loc[diff, 'item_id']) <= {63, 179}, f'unexpected recipe differences: {sorted(set(rec.loc[diff, "item_id"]))}'
        for i, w in zip(rec.index[diff], want[diff]):
            edited[(int(rec.at[i, 'item_id']), int(rec.at[i, 'ingredient_id']))] = (float(rec.at[i, qty]), float(w))
        rec.loc[diff, qty] = want[diff]
        return (rec,) + tuple(res[1:])

    ca.v4_recipe_lines = v4_with_current_quantities
    scratch = Path(tempfile.mkdtemp()) / 'promo_run'
    out, extra = b.build(scratch)          # includes build()'s own check: inventory consumption = sales x BOM (+ off-POS)

    waste = out['waste.csv'].drop(columns=['data_source'], errors='ignore')
    # the existing waste file spells the closure reason in lower case (build_stg_extract.py maps it to the schema's label)
    waste['waste_reason'] = waste['waste_reason'].replace({'EXPIRED_DURING_CLOSURE': 'expired during closure'})
    new = {'inventory.csv': out['inventory.csv'], 'inventory_batches.csv': out['inventory_batches.csv'], 'waste.csv': waste}
    for f in FILES:
        old_df = pd.read_csv(BACKUP / f)
        assert list(new[f].columns) == list(old_df.columns), f'{f}: columns changed'
        print(f'{f}: {len(old_df):,} -> {len(new[f]):,} rows')

    # Consumption is demand, whatever the stock: the only change must be the added lines x recipes plus the recipe edit, day by day.
    # (Everything else about stock - orders, lead-time draws, receipts, expiry - is re-rolled: the simulation draws
    # from one random stream shared by all ingredients, so one extra order shifts every later draw.)
    inv_old, inv_new = pd.read_csv(BACKUP / 'inventory.csv'), new['inventory.csv']
    bom = pd.read_csv(PRE / 'recipes.csv')[['item_id', 'ingredient_id', 'qty_per_item']]
    dem = added.merge(bom, on='item_id').assign(qty=lambda d: d['quantity_sold'] * d['qty_per_item'])
    dem = dem.groupby(['sale_date', 'ingredient_id'])['qty'].sum()
    gone = removed.merge(bom, on='item_id').assign(qty=lambda d: d['quantity_sold'] * d['qty_per_item'])
    dem = dem.sub(gone.groupby(['sale_date', 'ingredient_id'])['qty'].sum(), fill_value=0)     # removed lines consume nothing now
    # plus the recipe edit: every line of an edited item (sales and lost POS lines) now uses (new - old) more per unit
    ed = pd.DataFrame([dict(item_id=i, ingredient_id=g, per_unit=new_q - old_q) for (i, g), (old_q, new_q) in edited.items()])
    lines = pd.concat([pd.read_csv(PRE / 'sales.csv', usecols=['sale_date', 'item_id', 'quantity_sold']),
                       pd.read_csv(PRE / 'sales_artifact_log.csv').query('in_consumption and not in_pos_export')[['sale_date', 'item_id', 'quantity_sold']]])
    eff = lines.merge(ed, on='item_id').assign(qty=lambda d: d['quantity_sold'] * d['per_unit']).groupby(['sale_date', 'ingredient_id'])['qty'].sum()
    dem = dem.add(eff, fill_value=0)
    key = ['inventory_date', 'ingredient_id']
    # POS consumption = qty_consumed less the use outside the POS (staff meals, tuna off-POS use; separate column)
    pos = lambda d: d.set_index(key)['qty_consumed'] - d.set_index(key)['qty_off_pos_use']
    delta = pos(inv_new) - pos(inv_old)
    delta.index = pd.MultiIndex.from_arrays([delta.index.get_level_values(0).astype(str), delta.index.get_level_values(1)])
    dem = dem.reindex(delta.index).fillna(0)
    gap = (delta - dem).abs().max()
    assert gap < 1e-3, f'POS consumption changed by something other than the added / removed lines or the recipe edit (max gap {gap})'
    off = (inv_new.set_index(key)['qty_off_pos_use'] - inv_old.set_index(key)['qty_off_pos_use'])
    print(f'recipe edits applied to the simulation: {edited}')
    print(f'POS consumption delta = added lines x recipes + recipe edit on every ingredient-day (max gap {gap:.2e}); '
          f'{int((delta.abs() > 1e-9).sum())} ingredient-days changed, {len(set(i for _, i in delta[delta.abs() > 1e-9].index))} ingredients; '
          f'off-POS use changed on {int((off.abs() > 1e-9).sum())} ingredient-days')

    def metrics(inv, bat, w):
        return {'inventory rows': len(inv), 'batch snapshot rows': len(bat), 'waste rows': len(w),
                'quantity consumed (all ingredients, base units)': round(float(inv['qty_consumed'].sum()), 1),
                'quantity received': round(float(inv['qty_received'].sum()), 1),
                'quantity bought as emergency': round(float(inv['qty_emergency'].sum()), 1),
                'emergency purchases (PHP)': round(float(inv['emergency_cost_php'].sum()), 2),
                'days with an emergency purchase (stockout_flag)': int(inv['stockout_flag'].sum()),
                'waste value (PHP)': round(float(w['waste_value_php'].sum()), 2)}
    m_old = metrics(inv_old, pd.read_csv(BACKUP / 'inventory_batches.csv'), pd.read_csv(BACKUP / 'waste.csv'))
    m_new = metrics(inv_new, new['inventory_batches.csv'], new['waste.csv'])
    tbl = pd.DataFrame({'before': m_old, 'after': m_new})
    tbl['change'] = (tbl['after'] - tbl['before']).round(2)
    print(tbl.to_string())
    tbl.rename_axis('metric').to_csv(out_audit / 'inventory_resim_metrics.csv')
    for f in FILES:
        new[f].to_csv(out_pre / f, index=False)
    print('written to', out_pre)
    regenerate_registers(extra, out_pre, out_audit)


# the client-answer registers the build derives from the simulation (applied answers, parameters, impact, issues,
# checks, budget diagnosis, storage and recipe-line registers). They are written to both places that hold a copy.
REGISTERS = ['client_answers_applied.csv', 'client_parameters.csv', 'client_answer_impact.csv', 'client_answer_issues.csv',
             'client_answer_checks.csv', 'client_budget_diagnosis.csv', 'storage_locations.csv', 'ingredient_storage.csv',
             'recipe_lines_removed.csv']


def regenerate_registers(extra, out_pre, audit):
    rows = []
    for f in REGISTERS:
        new = extra[f].copy()
        old = pd.read_csv(BACKUP / f, dtype=str, keep_default_na=False)      # the pristine copy: repeatable, keeps hand-set values
        for c in [c for c in old.columns if c not in new.columns]:      # columns added by hand after the build (e.g. primary_function)
            key = old.columns[0]
            new = new.merge(old[[key, c]], on=key, how='left')
        new = new[[c for c in old.columns if c in new.columns] + [c for c in new.columns if c not in old.columns]]
        if f == 'storage_locations.csv':        # a capacity set after the build (Dry storage 500 L) must survive a blank from the build
            prev = old.set_index(old.columns[0])
            for c in ('capacity_l',):
                blank = new[c].isna() | new[c].astype(str).isin(['', 'nan'])
                new.loc[blank, c] = new.loc[blank, new.columns[0]].map(prev[c]).replace('', pd.NA)
        txt = new.astype(str).replace({'nan': '', '<NA>': '', 'None': ''})
        same_shape = txt.shape == old.shape and list(txt.columns) == list(old.columns)
        cells = int((txt.values != old.values).sum()) if same_shape else -1
        cols = [c for c in old.columns if same_shape and (txt[c].values != old[c].values).any()]
        rows.append(dict(register=f, rows_before=len(old), rows_after=len(new), columns_changed=', '.join(cols[:8]) if same_shape else 'layout changed',
                         cells_changed=cells))
        new.to_csv(out_pre / f, index=False)
        new.to_csv(audit / f, index=False)
    rep = pd.DataFrame(rows)
    rep.to_csv(audit / 'client_answers_regeneration_diff.csv', index=False)
    print('client-answer registers regenerated (before -> after):')
    print(rep.to_string(index=False))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Re-run the inventory simulation and regenerate stock files and client-answer registers.')
    ap.add_argument('--src', default=str(ROOT), help='folder holding the generated_v4_pre_stg_trim/ to read (default: the project folder)')
    ap.add_argument('--basis', default=str(ROOT / 'generated_v4_pre_promo_reorg'), help='original basis: source of the before figures and hand-set values')
    ap.add_argument('--out', default=str(ROOT), help='folder that receives the regenerated files (default: the project folder)')
    a = ap.parse_args()
    main(a.src, a.basis, a.out)
