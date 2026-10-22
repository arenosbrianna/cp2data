"""Small packs for tamago and bean sprouts (2026-10-22, user: they must be bought only in small packs).
Both are 3-day items bought as needed at the walk-in market (HI-TOP). supplier_item_terms.csv listed the client packs (tamago 250 g, bean sprouts 0.25 kg gross = 150 g usable); the simulation buys them in 50 g (usable) portions and never
more than 4 portions in one purchase (MAX_PACKS_ITEM=TAM:4,TOG:4). This step writes the small pack into the terms so that the data, the load and the optimiser input (dw.v_lp_ingredient_week_input uses pack_size_base) agree with the purchases:
pack_size_base = 50 usable g, min_order_packs 1, order_unit 'portion', pack_size = the gross grams of that portion (50 / the item's usable share, so bean sprouts keep their 60 % yield: 83.33 g gross), pack_unit g.
The pack size is an ASSUMPTION (SYNTHETIC_ASSUMPTION: buying by the portion at a walk-in market), not a client figure.
Run after renumber_ingredient_ids_scope20.py.   Usage (package folder): py set_small_packs.py datasets"""
import sys
import pandas as pd
D = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'
I = pd.read_csv(D + 'ingredients.csv'); T = pd.read_csv(D + 'supplier_item_terms.csv'); INV = pd.read_csv(D + 'inventory.csv'); SMALL = {'TAM': 50.0, 'TOG': 50.0}; MAXP = 4
for code, pk in SMALL.items():
    iid = int(I.loc[I.ingredient_code == code, 'ingredient_id'].iloc[0]); m = T.ingredient_id == iid; row = T.loc[m].iloc[0]
    print(code, 'terms before:', row[['order_unit', 'pack_size', 'pack_unit', 'pack_size_base', 'min_order_packs']].to_dict())
    gross_before_g = float(row.pack_size) * (1000.0 if row.pack_unit == 'kg' else 1.0); usable_share = float(row.pack_size_base) / gross_before_g       # e.g. 150 / 250 = 0.6 for bean sprouts
    T.loc[m, ['order_unit', 'pack_size', 'pack_unit', 'pack_size_base', 'min_order_packs']] = ['portion', round(pk / usable_share, 2), 'g', pk, 1]
    rec = INV.loc[(INV.ingredient_id == iid) & (INV.qty_received > 0), 'qty_received']
    assert ((rec / pk).round(6) % 1 == 0).all() and rec.max() <= MAXP * pk + 1e-6, f'{code}: a scheduled purchase is not a whole number of small packs or exceeds {MAXP} packs'
    print(code, f'-> pack {pk:g} g usable ({round(pk / usable_share, 2)} g gross); {len(rec)} scheduled purchases, all whole packs, largest {rec.max():g} g ({rec.max() / pk:g} packs)')
T.to_csv(D + 'supplier_item_terms.csv', index=False, lineterminator='\n')
