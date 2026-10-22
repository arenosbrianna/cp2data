"""SYNTHETIC recipe supplement for Makisushi (transparent, reviewable).

Makisushi's MENU2 sheet has no recipe for 158 sold items, no rice in any rice bowl,
and no miso soup although the printed menu serves one with every set. This script
fills those gaps with SYNTHETIC recipe lines. Nothing here is an owner recipe:

  * every added line carries recipe_source = 'SYNTHETIC:<rule>' and a written basis;
  * existing MENU2-derived lines are never changed, only missing lines are added;
  * items that consume no raw material the kitchen stocks (bottled drinks, bought-in
    cakes) are marked RESALE_NO_BOM instead of getting an invented recipe;
  * items whose content cannot be known ('Additional', 'STARDEALS') are marked
    PLACEHOLDER_NO_BOM.

Run:  py synthetic_recipes/build_synthetic_recipes.py
Reads generated_v2/ (menu_items, recipes, ingredients) and the owner workbook for
prices; writes the CSVs next to this file. makisushi_datagen_v3.py applies them.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE = ROOT / "generated_v2"

# ---------------------------------------------------------------- new ingredients (SYNTHETIC master rows)
# code: (name, category, storage, uom, shelf_life_days, is_perishable, SUPPLY-UR product used for unit_cost,
#        supplier, order_unit, pack_size, pack_unit, pack_size_base, min_order_packs, basis)
NEW_INGREDIENTS = {
    "RIC": ("Japanese Rice (plain)", "rice", "ambient", "g", 365, False, "Rice",
            "HI-TOP", "sack", 25, "kg", 25000, 1,
            "SUPPLY-UR 'Rice' 25 kg sack PHP 1,600 (row 21); owner's own portion note 150 g = PHP 9.60"),
    "MSO": ("Miso Paste", "condiment", "chilled", "g", 180, False, "Miso",
            "FUJI MART JAPANESE FOOD STORE", "pack", 1, "kg", 1000, 1,
            "SUPPLY-UR 'Miso' 1 kg pack PHP 150 (row 36); catalogue lists 1 kg miso"),
    "MNG": ("Mango", "fruit", "chilled", "g", 5, True, "Mango",
            "KYOTO MART", "kg", 1, "kg", 1000, 1,
            "SUPPLY-UR 'Mango' PHP 300/kg, 50% wastage (row 73)"),
    "GB": ("Ground Beef", "beef", "frozen", "g", 30, False, "Ground Beef",
           "UMA'I JAPANESE GROCERY", "pack", 1, "kg", 1000, 1,
           "SUPPLY-UR 'Ground Beef' PHP 385/kg (row 51); SUM-SALES25 has GB_050/GB_060 columns"),
}

# ---------------------------------------------------------------- synthetic portions (assumptions)
RICE_BOWL_G = 150      # SUPPLY-UR row 21: owner prices a 150 g rice portion (col N = 150, col O = 9.6)
SUSHI_RICE_G = 100     # MENU2's standard sushi-rice line on maki and baked sushi (SUS x 100)
BURRITO_RICE_G = 150   # a burrito is larger than one maki roll: assumption
MISO_SMALL = {"MSO": 15, "TUF": 1}     # one small miso soup: assumption
MISO_LARGE = {"MSO": 30, "TUF": 2}

RESALE = "RESALE_NO_BOM"
PLACEHOLDER = "PLACEHOLDER_NO_BOM"

# ---------------------------------------------------------------- rule A: items with no recipe
# item_id: ("copy", source_item_id, scale, {code: qty override/add}, basis)
#        | ("new", {code: qty}, basis) | (RESALE, basis) | (PLACEHOLDER, basis)
A = {
    # --- variants of dishes that already have a recipe (comp / GrabFood / spelling)
    17: ("copy", 209, 1, {}, "same dish as [BS] 4in1 Baked Sushi"),
    54: ("copy", 213, 1, {}, "same dish as [BS] Creamy Chicken"),
    55: ("copy", 213, 1, {}, "same dish as [BS] Creamy Chicken"),
    82: ("copy", 385, 1, {}, "same dish as [RM] Katsu Ramen"),
    143: ("copy", 386, 1, {}, "same dish as [RM] Shoyu Beef Ramen"),
    161: ("copy", 393, 1, {}, "same dish as [RM] Tonkotsu Ramen"),
    162: ("copy", 393, 1, {}, "same dish as [RM] Tonkotsu Ramen"),
    167: ("copy", 394, 1, {}, "same dish as [RM] Torikatsu Ramen"),
    184: ("copy", 361, 1, {}, "same dish as [MR] Yellow Kimono"),
    212: ("copy", 211, 1, {}, "same dish as [BS] Cheesy Beef"),
    215: ("copy", 214, 1, {}, "same dish as [BS] Creamy Salmon"),
    217: ("copy", 216, 1, {}, "same dish as [BS] Mixed Seafood"),
    336: ("copy", 39, 1, {}, "same dish as 'Cheesy cowboy roll'"),
    382: ("copy", 383, 1, {}, "same dish as [RM] Curry Beef Ramen"),
    26: ("copy", 214, 1, {}, "same dish as [BS] Creamy Salmon (pie form)"),
    137: ("copy", 214, 1, {}, "same dish as [BS] Creamy Salmon"),
    219: ("copy", 210, 1, {}, "same dish as [BS] California Baked"),
    56: ("copy", 235, 1, {}, "comp version of Crispy Chicken w/ Egg (Set A)"),
    59: ("copy", 342, 1, {}, "Crunchy Salmon: modelled on [MR] Crunchy Salmon Aburi"),
    341: ("copy", 342, 1, {}, "Crunchy Salmon: modelled on [MR] Crunchy Salmon Aburi"),
    63: ("copy", 190, 1, {}, "GrabFood Ebi Tempura = [ATF] Ebi Tempura (3pcs)"),
    79: ("copy", 408, 1, {}, "comp version of [SL] Special Kani Salad (Regular)"),
    80: ("copy", 246, 1, {}, "karaage a la carte = Karaagedon chicken without the rice bowl"),
    186: ("copy", 246, 1, {}, "karaage a la carte = Karaagedon chicken without the rice bowl"),
    92: ("copy", 320, 1, {}, "GrabFood version of [MM] JR w/ Beef Misono & Kani Tempura"),
    94: ("copy", 328, 1, {}, "GrabFood version of [MM] SF w/ Tuna & Salmon Sashimi & Kani Tempura"),
    95: ("copy", 328, 1, {}, "GrabFood version of [MM] SF w/ Tuna & Salmon Sashimi & Kani Tempura"),
    96: ("copy", 321, 1, {}, "GrabFood version of [MM] JR w/ Tuna Misono & Ebi Tempura"),
    97: ("copy", 322, 1, {}, "GrabFood version of [MM] JR w/ Tuna Misono & Kani Tempura"),
    98: ("copy", 330, 1, {}, "GrabFood version of [MM] SF w/ Yakitori & Kani Tempura"),
    103: ("copy", 329, 1, {}, "comp version of [MM] SF w/ Yakitori & Ebi Tempura"),
    318: ("copy", 327, 1, {}, "comp version of [MM] SF w/ Tuna & Salmon Sashimi & Ebi Tempura"),
    99: ("copy", 367, 1, {}, "comp version of [PL] Medium Party Tray"),
    366: ("copy", 367, 1.5, {}, "Large tray = 1.5 x Medium tray (size ratio assumed)"),
    368: ("copy", 316, 2, {}, "platter = 2 x [HS] Mixed Sashimi (size assumed)"),
    127: ("copy", 264, 1, {}, "comp Pork Teppan = [DB] Pork Teppanyaki/Misono (Set A)"),
    176: ("copy", 204, 1, {}, "GrabFood Tuna Teppan = [ATF] Tuna Teppanyaki/Teriyaki"),
    227: ("copy", 228, 1, {}, "GrabFood = [DB] Beef Teppanyaki/Misono (Set A)"),
    45: ("copy", 42, 1, {"CF": 90}, "Chicken Misono with the 90 g stated in the name"),
    48: ("copy", 46, 1, {"CF": 120}, "Chicken Teppan with the 120 g stated in the name"),
    49: ("copy", 46, 1, {"CF": 60}, "Chicken Teppan with the 60 g stated in the name"),
    152: ("copy", 390, 1, {}, "same dish as [RM] Spicy Roast Pork Tomato Ramen"),
    391: ("copy", 390, 1, {}, "same dish as [RM] Spicy Roast Pork Tomato Ramen"),
    165: ("copy", 397, 1, {}, "comp version of [SB] Cheesy Torikatsu Burrito"),
    132: ("copy", 401, 1, {}, "comp version of [SB] Sweet Spicy Salmon Burrito"),
    403: ("copy", 404, 1, {}, "GrabFood version of [SH] Salmon (Sake) 100 g"),
    134: ("copy", 404, 1, {}, "comp salmon sashimi = [SH] Salmon (Sake) 100 g"),
    446: ("copy", 155, 1, {}, "'supreme' read as 'Super supreme' (name similarity)"),
    109: ("copy", 425, 1, {}, "unnamed promo Okonomiyaki = [ST] Okonomiyaki (Cheesy Beef) (Regular)"),
    112: ("copy", 425, 2, {}, "Sharing = 2 x Regular (ratio assumed)"),
    426: ("copy", 425, 2, {}, "Sharing = 2 x Regular (ratio assumed)"),
    117: ("copy", 116, 2, {"CHE": 1}, "Sharing = 2 x Regular + cheese (name says cheese)"),
    173: ("copy", 342, 1, {"SAL": 0, "TUN": 50}, "Tuna Aburi = Crunchy Salmon Aburi with tuna"),
    359: ("copy", 352, 1, {"SAL": 0, "TUN": 30, "MNG": 30}, "Tuna Mango Roll = Salmon Mango Roll with tuna"),
    18: ("copy", 363, 40 / 48, {}, "40 pcs = 40/48 of the 48 pcs California Maki Platter"),
    21: ("copy", 363, 4 / 48, {}, "4 pcs = 4/48 of the 48 pcs California Maki Platter"),
    71: ("copy", 363, 4 / 48, {}, "4 pcs = 4/48 of the 48 pcs California Maki Platter"),
    # --- new synthetic recipes (composition from the item name / printed menu)
    8: ("new", {"GZA": 2}, "2 pcs gyoza (name)"),
    9: ("new", {"CF": 240}, "240 g chicken (name)"),
    164: ("new", {"CF": 60, "B+B": 1}, "torikatsu 60 g (name), breaded"),
    10: ("new", {"KNI": 2, "B+B": 2}, "2 pcs kani tempura (name); 1 batter serving per piece as in [ATF] Kani Tempura"),
    11: ("new", {"KNI": 30, "B+B": 30}, "30 pcs kani tempura (name)"),
    23: ("new", {"TUF": 4}, "4 pcs tofu (name)"),
    375: ("new", {"TUF": 4}, "4 pcs tofu (name)"),
    24: ("new", {"TAM": 90, "SUS": 120}, "6 pcs tamago sushi: 15 g tamago + 20 g sushi rice per piece (assumed)"),
    27: ("new", {"SAL": 50, "SUS": 100}, "salmon baked sushi 50 g (name)"),
    29: ("new", {"GB": 50, "SUS": 100, "CHE": 1, "NOR": 0.5}, "nachos beef roll: ground beef, cheese, maki rice + nori (assumed)"),
    348: ("new", {"GB": 50, "SUS": 100, "CHE": 1, "NOR": 0.5}, "nachos beef roll: ground beef, cheese, maki rice + nori (assumed)"),
    41: ("new", {"CF": 100, "SUS": BURRITO_RICE_G, "NOR": 1}, "chicken inasal burrito: chicken, rice, nori (assumed)"),
    400: ("new", {"CF": 100, "SUS": BURRITO_RICE_G, "NOR": 1}, "chicken inasal burrito: chicken, rice, nori (assumed)"),
    399: ("new", {"EBI": 3, "B+B": 3, "MAY": 10, "SUS": BURRITO_RICE_G, "NOR": 1},
          "ebi spicy burrito: 3 ebi tempura, spicy mayo, rice, nori (assumed)"),
    60: ("new", {"CUC": 30, "CAR": 20, "KAL": 10, "MAY": 10, "B+B": 1, "SUS": 100, "NOR": 0.5},
         "crunchy veggie roll (assumed)"),
    343: ("new", {"CUC": 30, "CAR": 20, "KAL": 10, "MAY": 10, "B+B": 1, "SUS": 100, "NOR": 0.5},
          "crunchy veggie salad roll (assumed)"),
    344: ("new", {"CUC": 30, "CAR": 20, "KAL": 10, "MAY": 10, "B+B": 1, "SUS": 100, "NOR": 0.5},
          "crunchy veggie salad roll (assumed)"),
    340: ("new", {"KNI": 2, "B+B": 1, "MAY": 5, "SUS": 100, "NOR": 0.5}, "crunchy kani roll (assumed)"),
    355: ("new", {"EBI": 2, "B+B": 2, "MAY": 10, "SUS": 100, "NOR": 0.5},
          "spicy ebi tempura roll, modelled on [MR] Crunchy Ebi (EBI 2) (assumed)"),
    151: ("new", {"EBI": 2, "B+B": 2, "MAY": 10, "SUS": 100, "NOR": 0.5},
          "spicy ebi tempura roll, modelled on [MR] Crunchy Ebi (EBI 2) (assumed)"),
    356: ("new", {"TAM": 30, "SUS": 100, "NOR": 0.5}, "tamago roll (assumed)"),
    405: ("new", {"TAM": 100}, "tamago sashimi, 100 g like the printed salmon/tuna sashimi"),
    407: ("new", {"SAL": 80, "B+B": 1, "CUC": 30, "CAB": 50, "MAY": 15}, "crispy salmon salad (assumed)"),
    201: ("new", {"SQD": 150, "TEP": 45}, "squid teppanyaki, 150 g like [ATF] Tuna Teppanyaki"),
    369: ("new", {"SAL": 500}, "salmon platter 500 g (name)"),
    221: ("new", {"PB": 120, "TER": 1, "BEL": 5, "CAB": 150, "CAR": 30, "ONI": 15, "TOG": 40},
          "printed 'SWEET PORK BELLY TERRIYAKI' built like [DB] Beef Terriyaki with pork belly"),
    222: ("new", {"PB": 120, "TER": 1, "BEL": 5, "CAB": 150, "CAR": 30, "ONI": 15, "TOG": 40},
          "printed 'SWEET PORK BELLY TERRIYAKI' built like [DB] Beef Terriyaki with pork belly"),
    223: ("new", {"PB": 120, "TER": 1, "BEL": 5, "CAB": 150, "CAR": 30, "ONI": 15, "TOG": 40},
          "printed 'SWEET PORK BELLY TERRIYAKI' built like [DB] Beef Terriyaki with pork belly"),
    224: ("new", {"PB": 120, "TER": 1, "BEL": 5, "CAB": 150, "CAR": 30, "ONI": 15, "TOG": 40},
          "printed 'SWEET PORK BELLY TERRIYAKI' built like [DB] Beef Terriyaki with pork belly"),
    266: ("new", {"PB": 120, "TER": 1, "BEL": 5, "CAB": 150, "CAR": 30, "ONI": 15, "TOG": 40},
          "printed 'SWEET PORK BELLY TERRIYAKI' built like [DB] Beef Terriyaki with pork belly"),
    66: ("new", {"RIC": RICE_BOWL_G, "EGG": 1}, "egg fried rice: rice portion + 1 egg"),
    307: ("new", {"RIC": RICE_BOWL_G, "EGG": 1}, "egg fried rice: rice portion + 1 egg"),
    68: ("new", {"RIC": RICE_BOWL_G}, "extra Japanese rice = one rice portion"),
    308: ("new", {"RIC": RICE_BOWL_G}, "extra Japanese rice = one rice portion"),
    70: ("new", {"RIC": RICE_BOWL_G}, "extra rice = one rice portion"),
    178: ("new", {"EGG": 1, "SQD": 10}, "upgrade plain rice -> seafood fried rice: the fried-rice add-ons (EGG 1, SQD 10)"),
    440: ("new", {"EGG": 1, "SQD": 10}, "upgrade plain rice -> seafood fried rice: the fried-rice add-ons (EGG 1, SQD 10)"),
    100: ("new", dict(MISO_LARGE), "miso soup (large), synthetic portion"),
    195: ("new", dict(MISO_LARGE), "miso soup (large), synthetic portion"),
    101: ("new", dict(MISO_SMALL), "miso soup (small), synthetic portion"),
    102: ("new", dict(MISO_SMALL), "miso soup (small), synthetic portion"),
    196: ("new", dict(MISO_SMALL), "miso soup (small), synthetic portion"),
    106: ("new", {"VMO": 1}, "printed 'MOYASHI (mung bean sprouts)' = one moyashi portion"),
    198: ("new", {"VMO": 1}, "printed 'MOYASHI (mung bean sprouts)' = one moyashi portion"),
    115: ("new", {"CAB": 300, "ONI": 15, "EGG": 1, "OKO": 20, "CHE": 2}, "okonomiyaki garlic & cheese: base as mixed-seafood okonomiyaki + cheese (garlic not in master)"),
    121: ("new", {"CAB": 300, "ONI": 15, "EGG": 1, "OKO": 20, "CHE": 2}, "okonomiyaki garlic & cheese (see 115)"),
    379: ("new", {"CAB": 300, "ONI": 15, "EGG": 1, "OKO": 20, "CHE": 2}, "okonomiyaki garlic & cheese (see 115)"),
    427: ("new", {"CAB": 300, "ONI": 15, "EGG": 1, "OKO": 20, "CHE": 2}, "okonomiyaki garlic & cheese (see 115)"),
    129: ("new", {"MZN": 45}, "ramen soup = one ramen soup-base serving as in [RM] Katsu Ramen"),
    311: ("new", {"NOD": 100}, "extra ramen noodles = one noodle serving"),
    38: ("new", {"CHE": 1}, "extra cheese = one slice"),
    309: ("new", {"MAY": 20}, "extra mayo (assumed 20 g)"),
    158: ("new", {"TER": 1}, "teriyaki sauce add-on = one serving"),
    86: ("new", {"EGG": 2}, "leche flan: eggs only are in the master (milk, sugar are not)"),
    87: ("new", {"EGG": 2}, "leche flan: eggs only are in the master (milk, sugar are not)"),
    298: ("new", {"MNG": 150}, "mango shake (150 g mango assumed)"),
    179: ("new", {"MNG": 150}, "upgrade to mango shake (150 g mango assumed)"),
    297: ("new", {"MNG": 120}, "mango juice (120 g mango assumed)"),
    292: ("new", {"ICT": 1}, "iced tea regular = 1 iced-tea unit"),
    76: ("new", {"ICT": 1}, "iced tea regular = 1 iced-tea unit"),
    293: ("new", {"ICT": 2}, "iced tea sharing = 2 units (assumed)"),
    75: ("new", {"ICT": 2}, "bottomless iced tea = 2 units (assumed)"),
    303: ("new", {"ICT": 1}, "red iced tea = 1 iced-tea unit"),
    304: ("new", {"ICT": 1}, "red iced tea shake = 1 iced-tea unit"),
}
for i in [288, 300, 301, 287, 5, 290, 296, 299, 295, 439, 291, 294, 302, 305, 72, 88, 89, 149, 441, 69,
          30, 52, 51, 37, 123, 130, 306, 32, 33, 159, 313, 67, 108, 310, 107]:
    A[i] = (RESALE, "bought-in / resale item (bottled drink, coffee, cake, packaged snack, sauce "
                    "or milk): no stocked raw material in the ingredient master")
A[25] = (PLACEHOLDER, "'Additional' - content unknown")
A[131] = (PLACEHOLDER, "'STARDEALS' - content unknown")

# ---------------------------------------------------------------- rules B-D (added to every item)
RICE_BOWL_CATS = r"DON BURI|MIX & MATCH|TEMPURA MEALS"
RICE_BOWL_NAMES = (r"\bdon\b|don\b|donburi|misono|curry|fried rice|\bsfr?\b|\bjr\b|m&m|mix\s*&\s*match|\bmm\b|"
                   r"set\s*[ab]\b|\([ab]\)|oyako|gyudon|sukiyakidon|katsudon|torikatsudon|karaagedon")
NOT_RICE_BOWL = r"\[rm\]|upgrade|chirashi|ramen|okonomiyaki|burrito|maki|roll|sushi|baked|noodle|yakisoba|sukiyaki soup|teppanyaki/teriyaki|\[atf\]|platter|tray"
SUSHI_CATS = r"MAKI ROLLS|BAKED SUSHI|SUSHI BURRITO"
SUSHI_NAMES = r"maki|roll|sushi|baked|burrito|burito|\bbsp\b|chirashi"
SET_A = r"set\s*a\b|\(a\)"
SET_B = r"set\s*b\b|\(b\)"


def build():
    menu = pd.read_csv(BASE / "menu_items.csv")
    rec = pd.read_csv(BASE / "recipes.csv")
    ing = pd.read_csv(BASE / "ingredients.csv")
    code_of = dict(zip(ing.ingredient_id, ing.ingredient_code))
    uom = dict(zip(ing.ingredient_code, ing.uom))
    uom.update({c: v[3] for c, v in NEW_INGREDIENTS.items()})
    rec["code"] = rec.ingredient_id.map(code_of)
    lines = {i: dict(zip(d.code, d.qty_per_item)) for i, d in rec.groupby("item_id")}
    names = dict(zip(menu.item_id, menu.item_name))
    cats = dict(zip(menu.item_id, menu.category))

    no_recipe = set(menu.item_id) - set(lines)
    missing_rule = sorted(no_recipe - set(A))
    extra_rule = sorted(set(A) - no_recipe)
    if missing_rule or extra_rule:
        raise ValueError(f"rule A must cover exactly the items with no recipe: missing {missing_rule}, extra {extra_rule}")

    add, status = [], {}

    def put(item, code, qty, rule, basis, source=None):
        if qty <= 0:
            return
        add.append(dict(item_id=item, item_name=names[item], ingredient_code=code, qty_per_item=round(float(qty), 4),
                        uom=uom[code], rule=rule, basis=basis, copied_from_item_id=source))

    # rule A
    for item, spec in A.items():
        kind = spec[0]
        if kind == "copy":
            _, src, scale, override, basis = spec
            base = {c: q * scale for c, q in lines[src].items()}
            base.update(override)
            for c, q in base.items():
                put(item, c, q, "A_copy_variant", basis, src)
            status[item] = "SYNTHETIC (copied from a variant)"
        elif kind == "new":
            _, comp, basis = spec
            for c, q in comp.items():
                put(item, c, q, "A_new_recipe", basis)
            status[item] = "SYNTHETIC (new recipe)"
        else:
            status[item] = kind
    after = {i: dict(d) for i, d in lines.items()}
    for a in add:
        after.setdefault(a["item_id"], {})[a["ingredient_code"]] = a["qty_per_item"]

    # rule B: rice
    for item, comp in list(after.items()):
        nm, cat = names[item].lower(), str(cats[item]).upper()
        if "RIC" in comp or "SUS" in comp:
            continue
        mult = 3 if "good for 3" in nm else (6 if "good for 6" in nm else 1)
        if "PLATTERS" in cat:
            continue                                     # platter size unknown: left as is
        if "VALUE MEALS" in cat:                         # printed: misono (rice bowl) x N (+ 8 pc California maki)
            put(item, "RIC", RICE_BOWL_G * mult, "B_rice_bowl",
                f"value meal: printed misono = rice bowl, {RICE_BOWL_G} g x {mult}")
            comp["RIC"] = RICE_BOWL_G * mult
            if "maki" in nm:
                put(item, "SUS", SUSHI_RICE_G, "B_sushi_rice", "value meal: printed '(8pcs) CALIFORNIA MAKI' = one maki roll of rice")
                comp["SUS"] = SUSHI_RICE_G
            continue
        if (re.search(RICE_BOWL_CATS, cat) or re.search(RICE_BOWL_NAMES, nm) or "VALUE MEALS" in cat) \
                and not re.search(NOT_RICE_BOWL, nm):
            put(item, "RIC", RICE_BOWL_G * mult, "B_rice_bowl",
                f"rice bowl / fried rice without a rice line: {RICE_BOWL_G} g x {mult} (owner's 150 g rice portion, SUPPLY-UR row 21)")
            comp["RIC"] = RICE_BOWL_G * mult
        elif re.search(SUSHI_CATS, cat) or re.search(SUSHI_NAMES, nm):
            if re.search(r"platter|tray", nm):
                continue                                 # multi-piece items: size unknown, left as is
            g = BURRITO_RICE_G if re.search(r"burrito|burito", nm) else (RICE_BOWL_G if "chirashi" in nm else SUSHI_RICE_G)
            put(item, "SUS", g, "B_sushi_rice", f"maki/sushi/burrito without sushi rice: {g} g (MENU2's standard maki line is SUS 100)")
            comp["SUS"] = g

    # rule C: miso soup with sets, tempura meals, value meals
    for item, comp in list(after.items()):
        nm, cat = names[item].lower(), str(cats[item]).upper()
        if re.search(SET_A, nm) or re.search(SET_B, nm) or cat in ("TEMPURA MEALS", "VALUE MEALS"):
            mult = 3 if "good for 3" in nm else (6 if "good for 6" in nm else 1)
            for c, q in MISO_SMALL.items():
                if c not in comp:
                    put(item, c, q * mult, "C_miso_soup_side",
                        "printed menu: SET A 'w/ miso', SET B 'w/miso, kani salad & Iced Tea', tempura/value meals "
                        f"'free miso soup' - small miso soup x {mult}")
                    comp[c] = q * mult

    # rule D: Set B completion (the generator's own SET_B_ADDONS rule, applied where missing)
    for item, comp in list(after.items()):
        if re.search(SET_B, names[item].lower()):
            for c, q in {"ICT": 1.0, "KNI": 0.25}.items():
                if c not in comp:
                    put(item, c, q, "D_set_b_addons", "Set B = Set A + iced tea + kani salad (printed menu; generator SET_B_ADDONS)")
                    comp[c] = q

    # rule E: named main ingredient missing from an existing recipe (only missing lines are added)
    E = {3: ({"CF": 30}, "chicken named in the dish; MENU2's own 'Baked Sushi Chicken 30 grams' = CF_060 x 0.5 = 30 g"),
         54: ({"CF": 30}, "chicken named in the dish; MENU2 'Baked Sushi Chicken 30 grams'"),
         55: ({"CF": 30}, "chicken named in the dish; MENU2 'Baked Sushi Chicken 30 grams'"),
         213: ({"CF": 30}, "chicken named in the dish; MENU2 'Baked Sushi Chicken 30 grams'"),
         40: ({"CF": 60}, "torikatsu named in the burrito: one 60 g chicken portion (CF_060)"),
         165: ({"CF": 60}, "torikatsu named in the burrito: one 60 g chicken portion (CF_060)"),
         397: ({"CF": 60}, "torikatsu named in the burrito: one 60 g chicken portion (CF_060)"),
         188: ({"SB": 100}, "beef named in the dish; Sharing = 2 x Regular's SB 50 (MENU2 line was 0)")}
    for n_pcs, item in [(48, 19), (40, 362), (64, 364), (96, 365)]:
        E[item] = ({c: q * n_pcs / 48 for c, q in lines[363].items()},
                   f"{n_pcs} pcs = {n_pcs}/48 of the full 48 pcs California Maki Platter recipe")
    for item, (comp_e, basis) in E.items():
        comp = after.setdefault(item, {})
        for c, q in comp_e.items():
            if c not in comp:
                put(item, c, q, "E_named_ingredient", basis)
                comp[c] = q

    add = pd.DataFrame(add)
    # item status table (every sold item)
    st = menu[["item_id", "item_name", "category"]].copy()
    st["before"] = np.where(st.item_id.isin(lines), "MENU2 / borrowed recipe", "NO RECIPE")
    st["after"] = [status.get(i, "MENU2 / borrowed recipe") for i in st.item_id]
    st["synthetic_lines_added"] = st.item_id.map(add.groupby("item_id").size()).fillna(0).astype(int)
    st["rules"] = st.item_id.map(add.groupby("item_id").rule.agg(lambda s: ",".join(sorted(set(s))))).fillna("")

    newi = pd.DataFrame([dict(ingredient_code=c, ingredient_name=v[0], category=v[1], storage_type=v[2], uom=v[3],
                              shelf_life_days=v[4], is_perishable=v[5], supply_ur_product=v[6], supplier_name=v[7],
                              order_unit=v[8], pack_size=v[9], pack_unit=v[10], pack_size_base=v[11],
                              min_order_packs=v[12], basis=v[13]) for c, v in NEW_INGREDIENTS.items()])
    add.to_csv(HERE / "recipe_additions.csv", index=False)
    st.to_csv(HERE / "item_bom_status.csv", index=False)
    newi.to_csv(HERE / "ingredient_additions.csv", index=False)
    print(f"recipe lines added: {len(add)}")
    print(add.rule.value_counts().to_string())
    print(st.after.value_counts().to_string())
    return add, st, newi


if __name__ == "__main__":
    build()
