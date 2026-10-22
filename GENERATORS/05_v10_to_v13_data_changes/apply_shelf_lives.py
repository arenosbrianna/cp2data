"""v11: shelf-life review. Only generator-guessed values that published sources clearly contradict are changed (client-derived values untouched).
Writes v11/shelf_life_review.csv and updates generated_v4/ingredients.csv (shelf_life_days; ENOD name). No column added."""
from pathlib import Path
import pandas as pd
R = Path(__file__).resolve().parent; V = R / 'v11'; V.mkdir(exist_ok=True)
G = R / 'generated_v4' / 'ingredients.csv'
ing = pd.read_csv(G)
SRC = {
 'NOD': (14, 'fresh ramen noodles 2-3 weeks refrigerated (user-supplied; also 1-2 weeks in other guides); low end of 2-3 weeks used', 'savoreveryeat.com; texasrealfood.com/food-shelf-life/ramen-noodles; northernnester.com', 'CHANGED 3 -> 14 (client team instruction + sources)'),
 'ENOD': (14, 'fresh egg noodles 2-3 weeks refrigerated, best within a week (user-supplied); identity of ENOD (client MENU2 code) not confirmed', 'allrecipesbeginner.com; shortfoodblog.com', 'CHANGED 3 -> 14 (assumption, to confirm with client)'),
 'CAB': (21, 'whole cabbage 3-4 weeks refrigerated (user-supplied); 3-6 weeks in the WA chart', 'fridge.com; cms.agr.wa.gov Produce Basics Chart', 'CHANGED 7 -> 21'),
 'CAR': (21, 'whole carrots 3-4 weeks refrigerated (user-supplied); 2-4 weeks in other guides', 'safeorexpired.com; extension.usu.edu; greenhealthymaine.com', 'CHANGED 7 -> 21'),
 'KAL': (14, 'fresh calamansi 14-21 days refrigerated (user-supplied)', 'ok2eat.com; atr.vsu.edu.ph article 1022', 'CHANGED 7 -> 14'),
 'TAM': (None, 'cooked tamagoyaki 2-4 days refrigerated', 'justonecookbook.com; shinagawa-japanese-cooking.com; aisleprompt.com', 'KEPT (supported)'),
 'TUF': (None, 'tofu: opened 3-5 days, unopened 5-10 days', 'thekitchenprofessor.com; thetakeout.com', 'KEPT (supported)'),
 'CUC': (None, 'cucumbers 3-6 days (extension) to 1-2 weeks (Utah State)', 'journals.flvc.org; healthyfamilyct.cahnr.uconn.edu; extension.usu.edu', 'KEPT (inside range)'),
 'BEL': (None, 'bell peppers 3-5 days (extension) to 2-3 weeks (WA)', 'journals.flvc.org; cms.agr.wa.gov', 'KEPT (inside range)'),
 'PCH': (None, 'bok choy / Chinese cabbage 2-3 days to 1 week', 'journals.flvc.org; cms.agr.wa.gov', 'KEPT (inside range)'),
 'MNG': (None, 'ripe mango 4-7 days refrigerated', 'mango.org', 'KEPT (inside range)'),
 'GIN': (None, 'fresh ginger 2-4 weeks', 'spice.alibaba.com guides', 'KEPT (inside range)'),
 'EGG': (None, 'shell eggs 3-5 weeks refrigerated', 'healthline.com; chowhound.com', 'KEPT (inside range)'),
 'TOG': (None, 'bean sprouts: no figure found in the search', '-', 'KEPT (unverified guess)'),
 'VMO': (None, 'moyashi portion (bean sprouts): no figure found', '-', 'KEPT (unverified guess)'),
 'MUS': (None, 'client: bought "to last a couple of weeks"', 'client Q2', 'KEPT (client-derived)'),
}
rows = []
for code, (new, basis, src, status) in SRC.items():
    sel = ing.ingredient_code == code
    old = int(ing.loc[sel, 'shelf_life_days'].iloc[0])
    if new is not None:
        ing.loc[sel, 'shelf_life_days'] = new
    rows.append(dict(code=code, name=ing.loc[sel, 'ingredient_name'].iloc[0], old_days=old, new_days=int(ing.loc[sel, 'shelf_life_days'].iloc[0]), basis=basis, sources=src, status=status))
# ENOD = egg noodles (confirmed by the user 2026-10-12): the ingredient name is kept as Egg Noodles
ing.to_csv(G, index=False, lineterminator='\n')
pd.DataFrame(rows).to_csv(V / 'shelf_life_review.csv', index=False)
print(pd.DataFrame(rows)[['code', 'old_days', 'new_days', 'status']].to_string(index=False))
