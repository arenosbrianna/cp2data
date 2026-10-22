"""Puts the SUPPLY-UR suppliers (supply_ur_to_csv.py) into generated_v4.

Each ingredient gets the supplier of its SUPPLY-UR product, written to
generated_v4/ingredient_suppliers.csv with the basis:
  * the product its unit_cost is priced from (makisushi_generator.SUPPLY_UR_COST and
    synthetic_recipes/ingredient_additions.csv), or
  * for an ingredient with no SUPPLY-UR price, the product in OTHER.
A product sold by more than one supplier goes to the supplier supply_ur_to_csv chose
(is_chosen_supplier: the first row in sheet order): 'Chicken Legs - boneless' (Chicken Thigh, CT)
is sold by FRANCESCO and SHOKURYOHIN at the same PHP 0.35/g; FRANCESCO supplies it.
Nobashi is ordered in SUPPLY-UR's 25-piece pack. All other pack terms are unchanged; where they
differ from SUPPLY-UR they are flagged in supplier_pack_size_check.csv, not changed.

The simulation's delivery terms are the SYNTHETIC ones in supplier_term_assumptions.csv;
suppliers.csv holds only what SUPPLY-UR records (terms_status NOT_RECORDED).

The client's answers and the owner's follow-up (client_answers.py) are applied before the simulation
runs: frozen / chilled storage and shelf life (28-day frozen raw fish and meat), KAL = kalamansi (3
synthetic lines that used it as squash removed), whole salmon / tuna at the owner's weight and yield,
usable units per pack (SUPPLY-UR Wastage/ Fluctuation is a yield loss: the simulation receives
usable_qty_per_pack), and mango lines in California maki and kani salads (recipes.csv = generated_v3's
lines minus the removed ones plus the mango lines, with line / quantity provenance). After it:
inventory.qty_thawed and storage_state on batches and waste, the per-ingredient shelf-life provenance,
thaw rule and storage location, and the registers: client_answers_applied, client_parameters,
client_answer_impact, client_answer_issues, client_answer_checks, client_budget_diagnosis,
storage_locations, ingredient_storage, recipe_lines_removed.

inventory, inventory_batches and waste come from the simulation, so the generated_v3 pipeline is
re-run (same seed) with these suppliers into a scratch folder. Every other re-run table must equal
generated_v3 (ingredients: apart from the client-answer cells). The replaced generated_v4 files are
first copied to generated_v4_pre_supply_ur/.
Also written: supply_ur_row_audit.csv (every sheet row and its fate) and
supply_ur_formula_audit.csv (every formula cell).
Run:  py build_v4_supply_ur.py [scratch_dir]
"""
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

import client_answers as ca
import makisushi_datagen_v2 as v2
import makisushi_datagen_v3 as v3
import makisushi_generator as gen
import supply_ur_to_csv as sur
import supplier_model as sm
import workbook_fixes as wf

ROOT = Path(__file__).resolve().parent
V3, V4 = ROOT / 'generated_v3', ROOT / 'generated_v4'
BACKUP, ORIGINAL = ROOT / 'generated_v4_pre_supply_ur', ROOT / 'generated_v4_pre_francesco'
CHANGED = ['suppliers.csv', 'supplier_item_terms.csv', 'inventory.csv', 'inventory_batches.csv', 'waste.csv']
OBSOLETE = ['supplier_item_terms.csv', 'ingredient_suppliers.csv', 'supplier_term_assumptions.csv']
UNCHANGED = ['recipe_review', 'calendar', 'closure_day_sales_removed', 'sales_artifact_log',
             'menu_items', 'sales']

# ingredients with no SUPPLY-UR price: code -> (SUPPLY-UR product, or a supplier name, basis)
OTHER = {
    'BAR':  ('Baran', 'product of the same name'),
    'BSG':  ('Benishoga', 'product of the same name'),
    'TUF':  ('Tufo', "product of the same name (the sheet spells tofu 'Tufo')"),
    'ICT':  ('Sola', 'Sola is a bottled iced tea sold by the 24-bottle case, the same case as ICT'),
    'GZA':  ('Gyoza Wrapper', 'gyoza are made from the gyoza wrapper'),
    'ENOD': ('Ramen Noodles', 'noodles: same supplier as the sheet\'s noodles'),
    'SOT':  ('Ramen Noodles', 'noodles: same supplier as the sheet\'s noodles'),
    'TAM':  ('Egg', 'tamago is made from egg (its cost is the Egg rate)'),
    'B+B':  ('All purpose Flour', 'batter mix is flour and panko'),
    'SAS':  ('Salmon', 'sashimi trim is cut from the whole salmon in-house (owner round 4, I11); not bought'),
    'VMO':  ('Togue', 'a moyashi portion is bean sprouts (togue)'),
    'KAL':  ('Cabbage', 'produce not in the sheet (kalamansi): same supplier as the sheet\'s other produce'),
    'CHE':  ('SHOKURYOHIN', 'not in the sheet: the supplier with the widest range'),
    'TEP':  ('SHOKURYOHIN', 'ready-made sauce: SHOKURYOHIN sells the sheet\'s ready-made sauces'),
    'TER':  ('SHOKURYOHIN', 'ready-made sauce: SHOKURYOHIN sells the sheet\'s ready-made sauces'),
    'TSS':  ('SHOKURYOHIN', 'ready-made sauce: SHOKURYOHIN sells the sheet\'s ready-made sauces'),
    # round 5, in-house gyoza (client_answers.NEW_INGREDIENTS)
    'GZW':  ('Gyoza Wrapper', 'product of the same name (SUPPLY-UR row 9, no price recorded)'),
    'GIN':  ('HI-TOP', 'fresh produce: the supplier filled for the sheet\'s other produce'),
    'OYS':  ('SHOKURYOHIN', 'bottled sauce: SHOKURYOHIN sells the sheet\'s ready-made sauces'),
    'SES':  ('SHOKURYOHIN', 'bottled oil / sauce: SHOKURYOHIN sells the sheet\'s ready-made sauces'),
    'SLT':  ('HI-TOP', 'grocery staple: Hi-Top Supermart, the walk-in grocery (team decision 2026-10-08)'),
}
NOBASHI = {'order_unit': 'pack', 'pack_size': '25', 'pack_unit': 'pc', 'pack_size_base': '25'}
_STATE = {}


def ingredient_suppliers(ing, sup, rates):
    add = pd.read_csv(ROOT / 'synthetic_recipes' / 'ingredient_additions.csv')
    priced = {**gen.SUPPLY_UR_COST, **dict(zip(add['ingredient_code'], add['supply_ur_product'])), **ca.NEW_PRICED}
    sid = dict(zip(sup['supplier_name'], sup['supplier_id']))
    rows = []
    for r in ing.itertuples():
        if r.ingredient_code in priced:
            product, basis = priced[r.ingredient_code], 'its unit_cost is this product\'s rate'
        else:
            product, basis = OTHER[r.ingredient_code]
        if product in sid:
            hits = [(None, product, product)]
        else:
            m = rates[rates['product'] == product]
            assert len(m), f'{r.ingredient_code}: {product} not in SUPPLY-UR'
            if len(m) > 1:
                keep = m.loc[m['is_chosen_supplier'], 'supplier_name'].item()
                others = ', '.join(sorted(set(m['supplier_name']) - {keep}))
                m = m[m['is_chosen_supplier']]
                basis += f'; also sold by {others}, supplied by {keep} only'
            hits = list(zip(m['source_row'], m['product'], m['supplier_name']))
        (row, prod, name), = hits
        rows.append(dict(ingredient_id=r.ingredient_id, ingredient_code=r.ingredient_code,
                         ingredient_name=r.ingredient_name, supplier_id=sid[name], supplier_name=name,
                         sheet_row=row, sheet_product=prod if row else None, basis=basis))
    out = pd.DataFrame(rows).astype({'sheet_row': 'Int64'})
    assert out['ingredient_id'].is_unique
    return out


def load_dimensions(cfg):
    dims = v3.load_dimensions(cfg)
    sup, rates = sur.build()
    ing = dims['ingredients'] = ca.v4_ingredients(dims['ingredients'], rates)
    isup = ingredient_suppliers(ing, sup, rates)
    usable = ca.usable_fractions(ing, isup, rates)
    usable_by_code = usable.assign(code=usable['ingredient_id'].map(ing.set_index('ingredient_id')['ingredient_code'])
                                   ).set_index('code')['usable_fraction']
    tuna_g = ca.fish_basis(rates).set_index('ingredient_code').loc['TUN', 'usable_g_per_fish']
    sales = pd.read_csv(V4 / 'sales.csv')
    dims['bom'], dropped, ctx = ca.v4_recipe_lines(dims['bom'], 'qty_base', dims['menu'], ing, sales, usable_by_code, tuna_g)
    terms = pd.concat([dims['terms'], ca.new_terms(ing, dims['terms'].columns)], ignore_index=True)
    terms['supplier_id'] = terms['ingredient_id'].map(isup.set_index('ingredient_id')['supplier_id'])
    code = terms['ingredient_id'].map(ing.set_index('ingredient_id')['ingredient_code'])
    gb_pack = float(terms.loc[code == 'GB', 'pack_size_base'].item())
    packs = pack_updates(ing, rates, terms.assign(code=code))
    for iid, vals in packs.items():
        for col, val in vals.items():
            terms.loc[terms['ingredient_id'] == iid, col] = float(val) if col.startswith('pack_size') else val
    # O2: a pack as bought delivers pack x usable_fraction stock units; the simulation receives those
    terms['pack_size_base'] = terms['pack_size_base'].astype(float) * terms['ingredient_id'].map(
        usable.set_index('ingredient_id')['usable_fraction'])
    assume = ca.walk_in_terms(sur.term_assumptions(sup))
    _STATE.update(isup=isup, sup=sup, rates=rates, packs=packs, assume=assume, ing=ing, menu=dims['menu'], sales=sales,
                  usable=usable, usable_by_code=usable_by_code, tuna_g=tuna_g, ctx=ctx, gb_pack=gb_pack,
                  dropped=dropped, sim_pack=terms.set_index('ingredient_id')['pack_size_base'])
    dims.update(suppliers=assume[['supplier_id', 'supplier_name'] + sur.TERM_COLS].copy(), terms=terms)
    return dims


def pack_updates(ing, rates, terms):
    """ingredient_id -> supplier_item_terms values: Nobashi's SUPPLY-UR pack, whole salmon / tuna (client),
    the three litre sauces in grams (I18) and the owner's ground beef pack (round 3, when answered)."""
    by_code = {'EBI': NOBASHI, **ca.whole_fish_terms(rates), **ca.sauce_terms(terms)}
    gb = ca.owner_answers()['ground_beef_pack_g']
    if gb['status'] == 'ANSWERED':
        g = float(gb['value'])
        by_code['GB'] = {'order_unit': 'pack', 'pack_size': f'{g / 1000:g}', 'pack_unit': 'kg', 'pack_size_base': f'{g:g}'}
    iid = ing.set_index('ingredient_code')['ingredient_id']
    return {int(iid[c]): v for c, v in by_code.items()}


def recipes_out(scratch):
    """generated_v3 recipes through the same v4 pipeline as the simulation's bom, with provenance."""
    rec, dropped, _ = ca.v4_recipe_lines(pd.read_csv(V3 / 'recipes.csv'), 'qty_per_item', _STATE['menu'], _STATE['ing'],
                                         _STATE['sales'], _STATE['usable_by_code'], _STATE['tuna_g'], ctx=_STATE['ctx'])
    _STATE['dropped_out'] = dropped
    rec = rec.sort_values(['item_id', 'ingredient_id'])
    sim = pd.read_csv(scratch / 'recipes.csv')     # what the simulation used
    key = ['item_id', 'ingredient_id', 'ingredient_code', 'qty_per_item']
    pd.testing.assert_frame_equal(rec[key].reset_index(drop=True), sim[key].reset_index(drop=True), obj='recipes')
    return ca.recipe_provenance(rec.reset_index(drop=True))


def suppliers_out(sup, isup):
    """The vendor list the build's checks use while the simulation tables are still in their working shape;
    build() replaces it with supplier_model.suppliers_table (delivery terms included) before returning."""
    return sup[['supplier_id', 'supplier_name']].copy()


def pack_size_check(terms, isup, rates):
    """Each ingredient's order pack (supplier_item_terms) next to its SUPPLY-UR row's quantity."""
    m = terms.merge(isup[['ingredient_id', 'ingredient_code', 'sheet_row', 'basis']], on='ingredient_id', how='left')
    src = rates[['source_row', 'product', 'quantity', 'unit_source', 'detailed_quantity']].rename(
        columns={c: f'source_{c}' for c in ('product', 'quantity', 'detailed_quantity')})
    m = m.merge(src, left_on='sheet_row', right_on='source_row', how='left').drop(columns='source_row')

    def status(r):
        if pd.isna(r.sheet_row):
            return 'NO_SOURCE_ROW'
        if pd.isna(r.source_detailed_quantity):
            return 'SOURCE_PACK_SIZE_NOT_RECORDED'
        if r.pack_unit == 'serving':
            return 'NOT_COMPARABLE_UNIT'
        return 'MATCH' if float(r.pack_size_base) == float(r.source_detailed_quantity) else 'PACK_SIZE_CONFLICT'
    m['status'] = [status(r) for r in m.itertuples()]
    m['resolution'] = m['status'].map({'PACK_SIZE_CONFLICT': 'not resolved: both values kept; terms unchanged'}).fillna('')
    fish = m['ingredient_code'].isin(list(ca.WHOLE_FISH_PHP))
    m.loc[fish, 'resolution'] = ('terms set from client Q4 / owner O2-O3: one whole fish at PHP 5,000; pack_size_base = '
                                 'whole grams as bought, usable_qty_per_pack = grams after the yield')
    return m.rename(columns={'sheet_row': 'source_row', 'basis': 'mapping_basis'}).astype({'source_row': 'Int64'})


def terms_out(sup):
    """v4's own terms file (columns and number formatting) with the new supplier ids."""
    isup = _STATE['isup']
    t = pd.read_csv(ORIGINAL / 'supplier_item_terms.csv', dtype=str)
    t = pd.concat([t, ca.new_terms(_STATE['ing'], t.columns).astype(str)], ignore_index=True)
    t['ingredient_id'] = t['ingredient_id'].astype(int)
    for iid, vals in _STATE['packs'].items():
        for col, val in vals.items():
            t.loc[t['ingredient_id'] == iid, col] = val
    t = t.drop(columns='supplier_id').merge(isup[['ingredient_id', 'supplier_id']], on='ingredient_id')
    u = _STATE['usable'][['ingredient_id', 'usable_fraction', 'usable_fraction_provenance', 'usable_fraction_basis']]
    t = t.merge(u, on='ingredient_id')
    t['usable_qty_per_pack'] = (t['pack_size_base'].astype(float) * t['usable_fraction']).round(4)
    sim = t['ingredient_id'].map(_STATE['sim_pack'])
    assert ((t['usable_qty_per_pack'] - sim).abs() < 1e-3).all(), 'written usable pack differs from the simulated one'
    code = t['ingredient_id'].map(_STATE['ing'].set_index('ingredient_id')['ingredient_code'])
    t['density_g_per_ml'] = code.map({c: d for c, (d, _, _) in ca.SAUCE_DENSITY.items()})
    t['density_provenance'] = code.map({c: p for c, (_, p, _) in ca.SAUCE_DENSITY.items()})
    return t[['supplier_id'] + [c for c in t.columns if c != 'supplier_id']].sort_values(
        ['supplier_id', 'ingredient_id']).reset_index(drop=True)


def build(scratch, inventory_seed=None):
    """Run the simulation into `scratch` and assemble every generated_v4 table; nothing is written to V4.
    run_v4_scenarios.py calls this with client_answers.SCENARIO changed; run_v4_seeds.py with inventory_seed."""
    v2.load_dimensions = load_dimensions
    v2.run(v2.Config(out_dir=scratch, remove_closure_days=True, whole_unit_emergency=ca.WHOLE_UNIT_EMERGENCY,
                     whole_unit_emergency_premium=ca.WHOLE_UNIT_EMERGENCY_PREMIUM,
                     planned_replacement=ca.PLANNED_REPLACEMENT, off_pos_use_ratio=ca.off_pos_use_ratio(),
                     off_pos_use_daily=ca.off_pos_use_daily(),
                     walk_in_suppliers=tuple(sur.build()[0].set_index('supplier_name').loc[list(ca.WALK_IN), 'supplier_id']),
                     inventory_seed=inventory_seed))
    assert abs(_STATE['usable_by_code']['GB'] - ca.GB_USABLE_FRACTION) < 1e-9, 'GB usable fraction changed'
    drift = ca.owner_current_drift(_STATE['ctx'], _STATE['rates'], _STATE['gb_pack'])
    assert not drift, 'owner_answers_pending.json current_value out of date: ' + '; '.join(drift)

    for name in UNCHANGED:
        pd.testing.assert_frame_equal(pd.read_csv(scratch / f'{name}.csv'), pd.read_csv(V3 / f'{name}.csv'), obj=name)
    sup, isup, rates = _STATE['sup'], _STATE['isup'], _STATE['rates']
    ing = pd.read_csv(scratch / 'ingredients.csv')
    pd.testing.assert_frame_equal(ing, ca.v4_ingredients(pd.read_csv(V3 / 'ingredients.csv'), rates), obj='ingredients')
    ing = ca.ingredient_columns(ing)

    out = {'suppliers.csv': suppliers_out(sup, isup), 'supplier_item_terms.csv': terms_out(sup)}
    for f in CHANGED[2:]:
        out[f] = pd.read_csv(scratch / f)
    out['inventory.csv'], out['inventory_batches.csv'], out['waste.csv'] = ca.thaw_columns(
        out['inventory.csv'], out['inventory_batches.csv'], out['waste.csv'], ing)
    rows = sur.row_audit(rates)
    recipes = recipes_out(scratch)
    storage, istore = ca.storage_table(), ca.ingredient_storage_table(ing)
    fish = ca.fish_basis(rates)
    use = ca.usage_by_line(_STATE['sales'], pd.read_csv(V4 / 'sales_artifact_log.csv'), recipes)
    out['inventory.csv'] = ca.off_pos_column(out['inventory.csv'], use, ing)
    same = lambda d: d[['item_id', 'ingredient_code']].sort_values(['item_id', 'ingredient_code']).reset_index(drop=True)
    pd.testing.assert_frame_equal(same(_STATE['dropped_out']), same(_STATE['dropped']))   # same lines (input order differs)
    chk = ca.checks(out['inventory.csv'], ing, fish, use, istore, storage, out['supplier_item_terms.csv'], _STATE['sales'])
    real = chk[chk['period'] == 'real POS window'].set_index('check_id')['simulated_value']
    extra = {'supply_unit_rates.csv': rates, 'ingredient_suppliers.csv': isup,
             'supplier_term_assumptions.csv': _STATE['assume'], 'supply_ur_row_audit.csv': rows,
             'supply_ur_formula_audit.csv': sur.formula_audit(),
             'supplier_pack_size_check.csv': pack_size_check(out['supplier_item_terms.csv'], isup, rates),
             'ingredients.csv': ing, 'recipes.csv': recipes,
             'client_answers_applied.csv': ca.log_table(), 'client_answer_impact.csv': ca.impact_table(),
             'client_answer_issues.csv': ca.issues_table(),
             'client_parameters.csv': ca.parameters_table(fish, storage, {'consumption': real['C02'],
                                                                          'purchases': real['C01']},
                                                          _STATE['ctx']['budget_factor']),
             'storage_locations.csv': storage, 'ingredient_storage.csv': istore, 'client_answer_checks.csv': chk,
             'client_budget_diagnosis.csv': ca.budget_diagnosis(out['inventory.csv'], ing, rates, isup, use),
             'recipe_lines_removed.csv': ca.removed_lines_table(_STATE['dropped_out']),
             # workbook audit 2026-10-07 (workbook_fixes.py): printed-menu prices, POS SKU / taxes, export names
             'menu_items.csv': wf.fix_menu(pd.read_csv(V4 / 'menu_items.csv')),
             'sales.csv': wf.fix_sales(pd.read_csv(V4 / 'sales.csv'), pd.read_csv(V3 / 'sales.csv', dtype={'sku': str})),
             'item_name_split_review.csv': wf.fix_split_review(pd.read_csv(V4 / 'item_name_split_review.csv')),
             'recipe_review.csv': wf.recipe_review_v4(pd.read_csv(V4 / 'recipe_review.csv'))}
    # the simulation's POS consumption is exactly recorded sales + lost POS lines x BOM (off-POS use is separate)
    sim_use = use.groupby(['date', 'ingredient_id'])['qty'].sum()
    i_ = out['inventory.csv']
    inv_use = (i_['qty_consumed'] - i_['qty_off_pos_use']).set_axis(
        pd.MultiIndex.from_arrays([pd.to_datetime(i_['inventory_date']), i_['ingredient_id']], names=['date', 'ingredient_id']))
    gap = (inv_use - sim_use.reindex(inv_use.index).fillna(0)).abs().max()
    assert gap < 1e-3, f'inventory.qty_consumed differs from sales x BOM by {gap}'

    # every product row is in supply_unit_rates; every sheet row has a fate; every vendor is a supplier
    kept = rows[(rows['row_kind'] == 'PRODUCT') & (rows['fate'] != 'EXCLUDED')]
    assert set(kept['excel_row']) == set(rates['source_row'])
    assert rows['fate'].notna().all() and rates['row_fate'].notna().all()
    assert set(rates['supplier_name']) == set(out['suppliers.csv']['supplier_name'])
    assert rates.loc[rates['is_chosen_supplier'], 'product'].is_unique

    pairs = set(zip(isup['ingredient_id'], isup['supplier_id']))
    for f in CHANGED[1:]:
        df = out[f]
        bad = ~pd.Series(list(zip(df['ingredient_id'].astype(int), df['supplier_id'].astype(int)))).isin(pairs)
        assert not bad.any(), f'{f}: {bad.sum()} rows with a supplier that does not sell the ingredient'
        assert set(df['supplier_id'].astype(int)) <= set(sup['supplier_id'])
    inv = out['inventory.csv']
    assert not inv.duplicated(['inventory_date', 'ingredient_id']).any()
    assert len(out['supplier_item_terms.csv']) == out['supplier_item_terms.csv']['ingredient_id'].nunique()
    # team structure 2026-10-08: suppliers / ingredients / supplier_catalog (supplier_model.py)
    terms = out.pop('supplier_item_terms.csv')
    isup_out, assume = extra.pop('ingredient_suppliers.csv'), extra.pop('supplier_term_assumptions.csv')
    extra['ingredients.csv'], extra['supplier_catalog.csv'] = sm.catalog_tables(
        terms, isup_out, extra['ingredients.csv'], rates, set(extra['recipes.csv']['ingredient_id']),
        extra['supplier_pack_size_check.csv'].set_index('ingredient_id')['status'].to_dict())
    out['suppliers.csv'] = sm.suppliers_table(assume)
    assert set(extra['supplier_catalog.csv']['supplier_id']) <= set(out['suppliers.csv']['supplier_id'])
    return out, extra


def main():
    for f in V4.glob('*.csv'):                    # fail now, not after the simulation, if a file is open in Excel
        try:
            open(f, 'r+b').close()
        except PermissionError:
            sys.exit(f'{f} is open in another program (Excel?); close it and re-run')
    scratch = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()) / 'supply_ur_run'
    assert all(ca.SCENARIO[k] == v[0] for k, v in ca.SCENARIOS.items()), 'the dataset is built with default scenarios'
    out, extra = build(scratch)
    inv, isup = out['inventory.csv'], _STATE['isup']
    BACKUP.mkdir(exist_ok=True)
    for f in CHANGED:
        if not (BACKUP / f).exists() and (V4 / f).exists():
            shutil.copy2(V4 / f, BACKUP / f)
    for f, df in {**out, **extra}.items():
        df.to_csv(V4 / f, index=False)
    for f in OBSOLETE:                    # replaced by suppliers.csv / ingredients.csv / supplier_catalog.csv
        (V4 / f).unlink(missing_ok=True)
    pd.set_option('display.width', 250)
    pd.set_option('display.max_colwidth', 70)
    print(extra['client_answer_checks.csv'].drop(columns=['source', 'basis']).to_string(index=False))
    print(isup.groupby('supplier_name')['ingredient_code'].apply(', '.join).to_string())
    print(f'inventory rows {len(inv)}; waste rows {len(out["waste.csv"])}; batch rows {len(out["inventory_batches.csv"])}')
    print(f'scratch run: {scratch}')


if __name__ == '__main__':
    main()
