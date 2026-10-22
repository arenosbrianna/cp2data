"""Supplier tables of generated_v4 as three normalized tables (team structure, 2026-10-08):

  suppliers.csv         one row per vendor: id, name, delivery lead time and the other delivery terms, with provenance.
                        No product list: what a vendor sells is its rows in supplier_catalog.csv.
  ingredients.csv       the master list (unit = uom); gains expected_yield (the usable share of what is bought).
  supplier_catalog.csv  the junction table: one row per (supplier, ingredient) with the price and the purchasing unit.

The simulation still works on its in-memory frames (supplier_item_terms, ingredient_suppliers, term assumptions);
build_v4_supply_ur.build() turns them into these three tables just before writing. legacy_views() rebuilds the old
shapes from the written files for the audits and scenario scripts.

Contact details are not stored: the price sheet has none and the supplier names are not contact records.
A backup supplier for an ingredient is one more catalog row; the simulation takes exactly one supplier per ingredient,
so the catalog has exactly one row per ingredient today.
"""
import numpy as np
import pandas as pd

import client_answers as ca

YIELD_COLS = ['expected_yield', 'expected_yield_provenance', 'expected_yield_basis']

# ingredients whose price is not a SUPPLY-UR rate: code -> (provenance, source)
PRICE_SOURCE = {
    'SAL': ('SOURCE_DERIVED', 'INGREDIENTS.xlsx Squid C11 (Salmon Whole Norwegian, PHP 590 a kg) x 5 kg a fish; team '
                              'decision 2026-10-07 (the client said PHP 5,000)'),
    'TUN': ('CLIENT_PROVIDED', 'Q4 / O1: about PHP 5,000 a whole tuna'),
    'TEP': ('SOURCE_DERIVED', 'COSTING row 44 (Teppanyaki Sauce - Grams)'),
    'TER': ('SOURCE_DERIVED', 'COSTING row 33 (Teriyaki Sauce, PHP 709.57 / 45 servings)'),
    'B+B': ('SOURCE_DERIVED', 'COSTING row 61 (Batter, per serving)'),
    'TAM': ('SOURCE_DERIVED', 'COSTING row 610 (Tamago, 6 eggs = 390 g)'),
    'KAL': ('SOURCE_DERIVED', 'COSTING row 229 (Kalamansi PHP 1) / MENU2 10 g each'),
    'GIN': ('SOURCE_DERIVED', 'COSTING row 27 (ginger, PHP 2 for 10 g); 250 g pack assumed'),
    'OYS': ('SOURCE_DERIVED', 'COSTING row 19 (oyster sauce, PHP 234 a bottle)'),
    'SES': ('SOURCE_DERIVED', 'COSTING row 39 (Sesame Oil, PHP 636 a liter)'),
    'GZW': ('SYNTHETIC_ASSUMPTION', 'team decision 2026-10-08: PHP 50 for 50 wrappers; SUPPLY-UR row 9 records no price'),
    'SLT': ('SYNTHETIC_ASSUMPTION', 'no workbook price; PHP 30 a kg assumed'),
}
ESTIMATED = ('SAS', 'TUF', 'CHE', 'ENOD', 'SOT', 'VMO', 'BSG', 'TEM', 'TSS', 'GZA', 'ICT', 'BAR')
ESTIMATED_SOURCE = ('SYNTHETIC_ASSUMPTION', 'team market estimate (makisushi_generator.ESTIMATED_COST); no owner price')


def purchasing_unit(r, uom):
    """Readable purchasing unit, e.g. 'pack of 50 pc', '1 kg', 'bottle of 1.8 L (1890 g)', '1 whole fish (5 kg)'."""
    ou, ps, pu, base = r.order_unit, r.pack_size, r.pack_unit, r.pack_size_base
    if ou == 'whole fish':
        return f'1 whole fish ({base / 1000:g} kg as bought)'
    core = f'{ps:g} {pu}' if ou in (pu, 'kg', 'L') else f'{ou} of {ps:g} {pu}'
    return core if pu == uom else f'{core} ({base:g} {uom})'


def suppliers_table(assume):
    """suppliers.csv from the delivery-term assumptions (lead times, fill rate, delivery interval) and their provenance."""
    s = assume.rename(columns={'lead_time_days': 'delivery_lead_time_days', 'terms_status': 'delivery_terms_provenance',
                               'basis': 'delivery_terms_basis'})
    return s[['supplier_id', 'supplier_name', 'delivery_lead_time_days', 'lead_time_sd_days', 'fill_rate',
              'delivery_interval_days', 'delivery_terms_provenance', 'delivery_terms_basis']].reset_index(drop=True)


def catalog_tables(terms, isup, ing, rates, used_ingredient_ids=(), pack_status=None):
    """(ingredients with expected_yield, supplier_catalog) from the simulation's frames.
    terms: supplier_item_terms (with usable_fraction*); isup: ingredient_suppliers; ing: ingredients (unit_cost);
    used_ingredient_ids: ingredients some recipe uses (-> in_use); pack_status: ingredient_id -> status of the pack
    against the SUPPLY-UR row (supplier_pack_size_check.csv)."""
    t = terms.copy()
    for c in ('supplier_id', 'ingredient_id', 'pack_size', 'pack_size_base', 'min_order_packs', 'usable_fraction',
              'usable_qty_per_pack', 'density_g_per_ml'):
        t[c] = pd.to_numeric(t[c])
    t['supplier_id'], t['ingredient_id'] = t['supplier_id'].astype(int), t['ingredient_id'].astype(int)
    t['min_order_packs'] = t['min_order_packs'].astype(int)
    y = t[['ingredient_id', 'usable_fraction', 'usable_fraction_provenance', 'usable_fraction_basis']].rename(
        columns=dict(zip(['usable_fraction', 'usable_fraction_provenance', 'usable_fraction_basis'], YIELD_COLS)))
    ingredients = ing.merge(y, on='ingredient_id', how='left')
    assert ingredients['expected_yield'].notna().all()
    pos = list(ing.columns).index('uom') + 1
    cols = [c for c in ingredients.columns if c not in YIELD_COLS]
    ingredients = ingredients[cols[:pos] + YIELD_COLS + cols[pos:]]

    m = t.merge(ing[['ingredient_id', 'ingredient_code', 'uom', 'unit_cost']], on='ingredient_id').merge(
        isup[['ingredient_id', 'sheet_row', 'sheet_product', 'basis']], on='ingredient_id', how='left')
    r = rates.set_index('source_row')
    rows = []
    for x in m.itertuples():
        code = x.ingredient_code
        if code in ('SAL', 'TUN'):
            price, (prov, src) = float(ca.WHOLE_FISH_PHP[code]), PRICE_SOURCE[code]
        elif code in PRICE_SOURCE:
            price, (prov, src) = x.unit_cost * x.usable_qty_per_pack, PRICE_SOURCE[code]
        elif code in ESTIMATED:
            price, (prov, src) = x.unit_cost * x.usable_qty_per_pack, ESTIMATED_SOURCE
        else:                                              # priced from a SUPPLY-UR row: use the sheet's own rate
            sr = r.loc[x.sheet_row]
            rate = sr['unit_rate_per_gms']
            if not rate > 0:                               # row 49 Wasabi: the sheet's per-g column is 0
                rate = sr['unit_rate_php'] / (1000 * (1 - sr['wastage_fluctuation']))
            price, prov, src = rate * x.usable_qty_per_pack, 'SOURCE_DERIVED', f'SUPPLY-UR row {int(x.sheet_row)} ({x.sheet_product})'
            # unit_cost is stored to 4 decimals, so it can differ by up to 0.00005 a base unit
            assert abs(price - x.unit_cost * x.usable_qty_per_pack) < 0.01 + 0.00006 * x.usable_qty_per_pack, (code, price)
        rows.append(dict(supplier_id=x.supplier_id, ingredient_id=x.ingredient_id, current_price=round(price, 2),
                         purchasing_unit=purchasing_unit(x, x.uom), price_provenance=prov, price_source=src,
                         order_unit=x.order_unit, pack_size=x.pack_size, pack_unit=x.pack_unit,
                         pack_size_base=x.pack_size_base, min_order_packs=x.min_order_packs,
                         usable_qty_per_pack=x.usable_qty_per_pack, density_g_per_ml=x.density_g_per_ml,
                         density_provenance=x.density_provenance,
                         in_use=x.ingredient_id in set(used_ingredient_ids),
                         pack_vs_sheet=(pack_status or {}).get(x.ingredient_id),
                         sheet_row=x.sheet_row, sheet_product=x.sheet_product, mapping_basis=x.basis))
    cat = pd.DataFrame(rows).sort_values(['supplier_id', 'ingredient_id']).reset_index(drop=True)
    cat.insert(0, 'catalog_id', range(1, len(cat) + 1))
    cat['sheet_row'] = cat['sheet_row'].astype('Int64')
    assert cat['ingredient_id'].is_unique and len(cat) == len(ing)
    return ingredients, cat


def legacy_views(suppliers, ingredients, catalog):
    """(terms, isup, assume) in the shape of the former supplier_item_terms / ingredient_suppliers /
    supplier_term_assumptions files, rebuilt from the written tables (audits and scenario scripts read these)."""
    y = ingredients.set_index('ingredient_id')[YIELD_COLS]
    terms = catalog.merge(y, left_on='ingredient_id', right_index=True)
    terms = terms.rename(columns=dict(zip(YIELD_COLS, ['usable_fraction', 'usable_fraction_provenance',
                                                       'usable_fraction_basis'])))
    terms = terms[['supplier_id', 'ingredient_id', 'order_unit', 'pack_size', 'pack_unit', 'pack_size_base',
                   'min_order_packs', 'usable_fraction', 'usable_fraction_provenance', 'usable_fraction_basis',
                   'usable_qty_per_pack', 'density_g_per_ml', 'density_provenance']]
    isup = (catalog.merge(ingredients[['ingredient_id', 'ingredient_code', 'ingredient_name']], on='ingredient_id')
            .merge(suppliers[['supplier_id', 'supplier_name']], on='supplier_id')
            .rename(columns={'mapping_basis': 'basis'})
            [['ingredient_id', 'ingredient_code', 'ingredient_name', 'supplier_id', 'supplier_name', 'sheet_row',
              'sheet_product', 'basis']])
    assume = suppliers.rename(columns={'delivery_lead_time_days': 'lead_time_days', 'delivery_terms_basis': 'basis',
                                       'delivery_terms_provenance': 'terms_status'})
    return terms, isup, assume
