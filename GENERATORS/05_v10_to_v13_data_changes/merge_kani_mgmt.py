"""v12 (user decision 2026-10-12): merge the two Management listings of 'Kani Tempura (3 pcs)' (item 13 SKU 10816, item 14 SKU 10624) into item 13.
Item 14's one real POS line (sale 37908, 2026-01-20, staff meal, net 0) is repointed to item 13; item 14 and its 2 recipe lines are removed;
item ids stay contiguous 1..n by shifting every id above 14 down by 1 (menu_items, recipes, sales, sales_dropped). Backup: v12/pre_kani_merge_backup/."""
import pandas as pd
G = 'generated_v4/'
OLD, KEEP = 14, 13
def shift(s): return s.where(s < OLD, s - 1)
def rd(n): return pd.read_csv(G + n + '.csv', dtype=str, keep_default_na=False)
def wr(d, n): d.to_csv(G + n + '.csv', index=False, lineterminator='\n')
m, r, s, sd = rd('menu_items'), rd('recipes'), rd('sales'), rd('sales_dropped')
a = m[m.item_id == str(OLD)].iloc[0]; b = m[m.item_id == str(KEEP)].iloc[0]
assert a.item_name == b.item_name and a.category == b.category == 'Management' and a.list_price == b.list_price
ra = r[r.item_id == str(OLD)].drop(columns='item_id').reset_index(drop=True); rb = r[r.item_id == str(KEEP)].drop(columns='item_id').reset_index(drop=True)
assert ra.equals(rb), 'recipes of the two listings differ'
n_sales = (s.item_id == str(OLD)).sum(); assert n_sales == 1
m = m[m.item_id != str(OLD)]; r = r[r.item_id != str(OLD)]
s.loc[s.item_id == str(OLD), 'item_id'] = str(KEEP)
for d in (m, r, s, sd):
    d['item_id'] = shift(d['item_id'].astype(int)).astype(str)
assert sorted(m.item_id.astype(int)) == list(range(1, len(m) + 1))
wr(m, 'menu_items'); wr(r, 'recipes'); wr(s, 'sales'); wr(sd, 'sales_dropped')
print('menu', len(m), 'recipes', len(r), 'sales', len(s), 'dropped', len(sd))
