"""v12 step 6 (user decision 2026-10-13): two real POS lines were PAID sales on items the client's menu files under 'Management'
(sale 39568: item 7 'Ebi Tempura (1 pc)', SKU 10410, list price 86; sale 40471: item 120 'Philadelphia', SKU 10539, list price 305, GrabFood).
They are now ordinary sales: the two items become normal sale items (is_complimentary FALSE, category 'All Time Favorites' for item 7 - like the other
Ebi Tempura (n pcs) - and 'Maki Rolls' for item 120 - like Philadelphia Roll), and the two paid lines are is_revenue TRUE. The items' other lines are zero-price
staff lines and stay non-revenue lines (same pattern as Free Sola / Free California Maki). Stock files are unchanged (recipes and quantities do not move).
Also: the KNOWN-exception rows SAL05, SAL08 and DAT11 are removed from validation (DAT11: the data simply ends 2026-09-08)."""
import pandas as pd

G = 'generated_v4/'
m = pd.read_csv(G + 'menu_items.csv', dtype=str, keep_default_na=False)
s = pd.read_csv(G + 'sales.csv', dtype=str, keep_default_na=False)
NEW = {'7': 'All Time Favorites', '120': 'Maki Rolls'}
for i, c in NEW.items():
    row = m[m.item_id == i].iloc[0]
    assert row.category == 'Management' and row.is_complimentary == 'True', row
    assert c in set(m.category), c
    m.loc[m.item_id == i, ['category', 'is_complimentary']] = [c, 'False']
for sid, it in (('39568', '7'), ('40471', '120')):
    l = s[s.sale_id == sid].iloc[0]
    assert l.item_id == it and l.is_revenue == 'False' and float(l.net_sales) > 0, l
    s.loc[s.sale_id == sid, 'is_revenue'] = 'True'
m.to_csv(G + 'menu_items.csv', index=False, lineterminator='\n')
s.to_csv(G + 'sales.csv', index=False, lineterminator='\n')


def load(p):
    return open(p, encoding='utf-8', newline='').read().replace('\r\n', '\n')


p = 'validation/post_load_validation.sql'; t = load(p)
i = t.index("    ('SAL05', 1,"); j = t.index("    ('SUP07', 3,"); t = t[:i] + t[j:]
a = "    ('DAT11', 22, 'the source data ends 2026-09-08; 2026-09-09 .. 2026-09-30 do not exist and are not invented')\n"
assert a in t
t = t.replace("    ('SUP07', 3, 'storage capacities are litres per unit and no site survey exists; LP storage constraint input is missing'),\n" + a,
              "    ('SUP07', 3, 'storage capacities are litres per unit and no site survey exists; LP storage constraint input is missing')\n")
i = t.index("  union all select 'DAT11'"); j = t.index("\n", t.index("\n", i) + 1) + 1
print(repr(t[i:j][:400]))
t = t[:i] + t[j:]
open(p, 'w', encoding='utf-8', newline='').write(t.replace('\n', '\r\n'))
print('ok')
