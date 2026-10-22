"""Scope change of 2026-10-19 (team decision): the generator inputs lose Moyashi Portion (VMO, ingredient 42), a duplicate of Togue (TOG, ingredient 38).
Recipe lines of ingredient 42 become Togue, 100 g per serving (cost-equivalent: PHP 10 per portion at PHP 0.10 per g); the ingredient, its supplier terms and its volume row are removed.
Works on a folder holding ingredients.csv, recipes.csv, supplier_item_terms.csv, ingredient_volume.csv (the package datasets/ or a scratch generated_v4/; ingredient ids are the same in both).
Usage: py v14/apply_scope20_inputs.py <folder> [register csv]   (the register, if given, also sets is_perishable from in_inventory_scope). Safe to rerun."""
import sys
import pandas as pd
D = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'; VMO, TOG = 42, 38
_ing = pd.read_csv(D + 'ingredients.csv')
if not (_ing[_ing.ingredient_id == VMO].ingredient_code == 'VMO').any():
    sys.exit('ingredient 42 is not Moyashi Portion (already removed and the ids renumbered): nothing to do')
rec = pd.read_csv(D + 'recipes.csv'); n = int((rec.ingredient_id == VMO).sum())
if n:
    assert not set(rec[rec.ingredient_id == VMO].item_id) & set(rec[rec.ingredient_id == TOG].item_id), 'an item holds both'
    m = rec.ingredient_id == VMO; rec.loc[m, 'ingredient_id'] = TOG; rec.loc[m, 'qty_base'] = 100.0; rec.loc[m, 'uom'] = 'g'
    rec.to_csv(D + 'recipes.csv', index=False, lineterminator=chr(10))
print('recipe lines moved to Togue:', n)
for f in ('ingredients', 'supplier_item_terms', 'ingredient_volume'):
    t = pd.read_csv(D + f + '.csv'); k = len(t); t = t[t.ingredient_id != VMO]
    if len(t) != k:
        t.to_csv(D + f + '.csv', index=False, lineterminator=chr(10))
    print(f, 'rows removed:', k - len(t))
if len(sys.argv) > 2:
    reg = pd.read_csv(sys.argv[2]).set_index('ingredient_code'); t = pd.read_csv(D + 'ingredients.csv')
    t['is_perishable'] = t.ingredient_code.map(reg.in_inventory_scope).astype(bool).map({True: 'True', False: 'False'}); t.to_csv(D + 'ingredients.csv', index=False, lineterminator=chr(10))
    print('is_perishable set from the register:', int((t.is_perishable == 'True').sum()), 'in scope of', len(t))
