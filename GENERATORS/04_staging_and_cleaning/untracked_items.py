"""Menu items with no recipe line -> generated_v4_audit/menu_items_without_recipe.csv.

The owner's MENU2 gives no recipe for these items and the ingredient master holds no input for them
(bought-in drinks, desserts, sauces, add-ons, complimentary and promo lines), so their sales cannot reach an
ingredient. No recipe is invented for them. Run after build_stg_extract.py and clean_sales.py:  py untracked_items.py
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
V4 = ROOT / 'generated_v4'
REASON = {
    'DRINKS & SHAKES': 'bought-in drink: no beverage input in the ingredient master',
    'DESSERT': 'dessert: no MENU2 recipe',
    'DESSERTS': 'dessert: no MENU2 recipe',
    'OTHER': 'add-on / sauce / extra: no MENU2 recipe',
    'MANAGEMENT': 'complimentary (staff / management) line: no MENU2 recipe',
    'STARDEALS': 'promo bundle: no MENU2 recipe',
    'GRABFOOD': 'delivery add-on: no MENU2 recipe',
}

m = pd.read_csv(V4 / 'menu_items.csv')
rec = pd.read_csv(V4 / 'recipes.csv')
s = pd.read_csv(V4 / 'sales.csv')
no = m[~m['item_id'].isin(rec['item_id'])].copy()
no['category_raw'] = no['category']      # menu_items.csv carries the menu category as 'category' since 2026-10-10
by = s.groupby('item_id').agg(quantity_sold=('quantity_sold', 'sum'), net_sales=('net_sales', 'sum'), lines=('sale_id', 'size'))
no = no.join(by, on='item_id').fillna({'quantity_sold': 0, 'net_sales': 0, 'lines': 0})
no['reason'] = no['category_raw'].str.upper().map(REASON).fillna('no MENU2 recipe')
out = no[['item_id', 'item_name', 'category_raw', 'is_complimentary', 'lines', 'quantity_sold', 'net_sales', 'reason']]
out = out.sort_values('net_sales', ascending=False)
(ROOT / 'generated_v4_audit').mkdir(exist_ok=True)
out.to_csv(ROOT / 'generated_v4_audit' / 'menu_items_without_recipe.csv', index=False, encoding='utf-8')
sold = out[out['lines'] > 0]
print(f'{len(out)} items without a recipe, {len(sold)} sold: {int(sold.quantity_sold.sum())} units, '
      f'PHP {sold.net_sales.sum():,.2f} net = {100 * sold.net_sales.sum() / s.net_sales.sum():.2f}% of net sales')
print(out.groupby('reason')[['lines', 'quantity_sold', 'net_sales']].sum().round(0).to_string())
