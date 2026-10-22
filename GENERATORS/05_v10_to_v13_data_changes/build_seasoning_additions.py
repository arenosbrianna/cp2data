"""Builds v13/recipe_additions_seasoning.csv (hondashi, sesame oil, salt lines) - revision 2 (team answers of 2026-10-14).
Rule: a seasoning line exists only where the client workbook (makisushi_Jan_2026.xlsx, COSTING sheet) lists that seasoning for that dish or batch recipe.
Quantity status is stated per line:  WORKBOOK_AMOUNT = gram amount taken from the workbook;  WORKBOOK_BATCH = per-serving share of a workbook batch recipe;
REFERENCE_ESTIMATE = ingredient is listed by the workbook but with no usable amount, so the grams are an online reference-recipe estimate (provisional, not a verified Makisushi quantity).
Removed in revision 2: sesame oil and salt in Seafood Fried Rice (the workbook's fried-rice recipe, rows 63-70, does not list them; they came only from online chahan recipes).
Run from the package folder; reads generated_v4/menu_items.csv and v13/pre_seasoning_backup/recipes.csv (the recipes before any v13 line)."""
import pandas as pd

M = pd.read_csv('generated_v4/menu_items.csv').set_index('item_id'); R = pd.read_csv('v13/pre_seasoning_backup/recipes.csv'); I = pd.read_csv('generated_v4/ingredients.csv').set_index('ingredient_code')
HON, SES, SLT, TER, TEP, CF = (int(I.loc[c, 'ingredient_id']) for c in ('HON', 'SES', 'SLT', 'TER', 'TEP', 'CF'))
has = set(R.item_id); nm = M.item_name; rows = []
def add(i, ing, q, src): rows.append((int(i), ing, q, src))
for i in M[nm.str.contains('Shoyu Seafood Ramen', case=False) & M.index.isin(has)].index:
    add(i, HON, 5.0, 'WORKBOOK_AMOUNT COSTING r422 (5 g)'); add(i, SES, 4.5, 'REFERENCE_ESTIMATE (listed r429 without amount; 1 tsp = 4.5 g, shoyu ramen recipes use 1 tsp to 1 Tbsp)')
for i in M[nm.str.contains('Seafood Fried Rice', case=False) & M.index.isin(has)].index:
    add(i, HON, 0.18, 'WORKBOOK_AMOUNT COSTING r66 (PHP 0.10 / 0.5625 per g)')
cf = R[R.ingredient_id == CF].set_index('item_id').qty_base
for i in M[nm.str.contains('Torikatsu', case=False) & M.index.isin(has)].index:
    if i in cf.index:
        g = float(cf[i]); add(i, HON, 0.89 * g / 120, 'WORKBOOK_AMOUNT COSTING r10 (PHP 0.50 per 120 g chicken, scaled)'); add(i, SLT, 1.5 * g / 120, 'REFERENCE_ESTIMATE (listed r11 as PHP 0.25, about 8 g, rejected as too high; 1 tsp salt per lb chicken = 1.5 g per 120 g)')
for r in R[R.ingredient_id == TER].itertuples():                       # teriyaki batch r22: 40 g hondashi per 45 servings; recipe quantity is in servings
    add(r.item_id, HON, r.qty_base * 40.0 / 45.0, 'WORKBOOK_BATCH COSTING r22 (40 g hondashi per 45 servings)')
for r in R[R.ingredient_id == TEP].itertuples():                       # teppanyaki batch r38-39: 45 servings x 45 g = 2,025 g; hondashi 40 g, sesame oil PHP 1.06 = 1.53 g at PHP 0.6913 per g
    add(r.item_id, HON, r.qty_base * 40.0 / 2025.0, 'WORKBOOK_BATCH COSTING r38 (40 g hondashi per 2,025 g sauce)'); add(r.item_id, SES, r.qty_base * (1.06 / 0.6913) / 2025.0, 'WORKBOOK_BATCH COSTING r39 (sesame oil PHP 1.06 = 1.53 g per 2,025 g sauce)')
A = pd.DataFrame(rows, columns=['item_id', 'ingredient_id', 'qty_base', 'source'])
g = A.groupby(['item_id', 'ingredient_id'], as_index=False).agg(qty_base=('qty_base', 'sum'), source=('source', lambda s: ' + '.join(sorted(set(s)))))
g['qty_base'] = g.qty_base.round(5); g.to_csv('v13/recipe_additions_seasoning.csv', index=False)
print(len(A), '->', len(g), 'lines;', g.item_id.nunique(), 'dishes'); print(g.groupby('ingredient_id').qty_base.agg(['count', 'sum']).round(2))
