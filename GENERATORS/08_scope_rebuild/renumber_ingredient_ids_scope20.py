"""Scope change of 2026-10-19, last step: after Moyashi Portion (ingredient 42) was removed, ingredient ids above 42 move down by one so that ids stay contiguous 1..n (same practice as the item merge of v12).
Runs on the PORTED datasets folder (after v14/port_scope_rebuild.py) and on v14/ingredient_scope_register.csv. Only the ingredient_id column changes; refuses to run twice.
Usage (package folder): py v14/renumber_ingredient_ids_scope20.py datasets"""
import sys
import pandas as pd
D = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'; GAP = 42
ing = pd.read_csv(D + 'ingredients.csv')
if ing.ingredient_id.max() == len(ing):
    sys.exit('ingredient ids are already contiguous: nothing to do')
assert GAP not in set(ing.ingredient_id), 'ingredient 42 still present: run apply_scope20_inputs.py first'
mp = lambda s: s.where(s < GAP, s - 1)
for f in ('ingredients', 'ingredient_volume', 'inventory', 'inventory_batches', 'recipes', 'stockout_events', 'supplier_item_terms', 'waste'):
    t = pd.read_csv(D + f + '.csv'); t['ingredient_id'] = mp(t.ingredient_id); t.to_csv(D + f + '.csv', index=False, lineterminator=chr(10))
r = pd.read_csv('v14/ingredient_scope_register.csv'); r['ingredient_id'] = mp(r.ingredient_id); r.to_csv('v14/ingredient_scope_register.csv', index=False, lineterminator=chr(10))
ing = pd.read_csv(D + 'ingredients.csv'); assert list(ing.ingredient_id) == list(range(1, len(ing) + 1)); print('ingredient ids renumbered 1..', len(ing))
