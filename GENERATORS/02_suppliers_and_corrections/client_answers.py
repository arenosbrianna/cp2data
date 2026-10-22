"""The client's answers (Q&A 2026-10-05/06) and the owner's confirmed follow-up (2026-10-06), how
generated_v4 applies them, and the registers that document them. build_v4_supply_ur.py calls this
module before the simulation (ingredient updates, whole-fish and usable pack sizes, recipe lines) and
after it (derived columns, registers and checks).

Provenance classes (column `provenance` / `*_provenance` in every client-answer table):
  SOURCE_DERIVED        the owner's workbook (MENU2, SUPPLY-UR, COSTING, SALES'26, REFERENCES)
  CLIENT_PROVIDED       stated by the client / owner (Q&A, or the owner-confirmed follow-up); owner
                        estimates stay estimates, not measurements
  MODELLED_FROM_CLIENT  a modelling number standing for an approximate client statement
                        ("up to 4 weeks+" -> 28 days, "50-60%" -> 55%); the client did not give the number
  SYNTHETIC_ASSUMPTION  team / generator assumption with no client or source figure
  EXTERNAL_REFERENCE    published recipes or food-safety guidance
  DERIVED               calculated from other values
  SIMULATION            output of the inventory simulation

Simulation inputs: frozen / thawed life, mushroom life, ginger chilled, KAL = kalamansi, one whole
fish per salmon / tuna order at the owner's yield, usable units per pack (SUPPLY-UR Wastage/
Fluctuation is a yield loss), mango in California maki and kani salads (COSTING grams).
Recipes keep the workbook grams (MENU2, confirmed by SUM-SALES25; workbook_fixes.py for the cells the
generator misread); only explicit owner answers change a quantity.
Checks only (client_answer_checks.csv; nothing is tuned to them): weekly restock budget, the owner's weekly kg
baselines, mango and cucumber kg a week, salmon / tuna fish a month, days a tuna lasts, storage capacity.
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

import workbook_fixes as wf

SOURCE = 'client Q&A 2026-10-05/06'
OWNER = 'owner follow-up 2026-10-06 (confirmed by the owner)'
REAL_START = '2025-12-01'          # first day of SALES'26, the real POS window

# --- round 3: owner answers still pending, and analysis scenarios ----------------------------------
# owner_answers_pending.json holds one key per open owner question. A null owner_value means the
# generator keeps current_value with its current provenance; a set owner_value is used and recorded
# as CLIENT_PROVIDED. current_value is checked against the data at every build (build_v4_supply_ur).
OWNER_FILE = Path(__file__).resolve().parent / 'owner_answers_pending.json'
ROUND3 = 'owner round 3 (owner_answers_pending.json)'
ROUND4 = 'owner round 4, 2026-10-07 (owner_answers_pending.json)'
BUDGET_CALIBRATION_AT = 0.5   # where in the owner's weekly budget range the calibrated cost lands (0.5 = midpoint)
ROUND4_KEYS = ('tuna_grams_per_serving', 'tuna_use_outside_pos', 'salmon_whole_kg', 'sushi_rice_kg_per_week',
               'ground_beef_pack_g', 'mango_g_per_shake', 'salmon_mango_roll_has_mango', 'sashimi_trim_source',
               'chicken_storage_location', 'weekly_budget_php')
# Scenarios for analysis only (run_v4_scenarios.py); the dataset is always built with the defaults.
SCENARIOS = {'tuna_scenario': ('owner_split', 'recipe_only'),       # recipe_only = no tuna use outside the POS
             'salmon_weight_scenario': ('price_sheet', 'owner_example_10kg')}
SCENARIO = {'tuna_scenario': 'owner_split', 'salmon_weight_scenario': 'price_sheet'}


def owner_answers():
    """key -> dict(value, provenance, status, meta): owner_value when set (CLIENT_PROVIDED, or the answer's
    owner_value_provenance for a range midpoint or estimate), else current_value with its current provenance.
    An answer recorded with not_applied_because (owner_answer_given, owner_value null) is ANSWERED_NOT_APPLIED:
    the data keeps current_value."""
    raw = json.loads(OWNER_FILE.read_text(encoding='utf-8'))['answers']
    out = {}
    for k, a in raw.items():
        answered = a['owner_value'] is not None
        assert not (answered and 'not_applied_because' in a), f'{k}: an applied answer cannot be marked not applied'
        out[k] = dict(value=a['owner_value'] if answered else a['current_value'],
                      provenance=a.get('owner_value_provenance', 'CLIENT_PROVIDED') if answered else a['current_provenance'],
                      status='ANSWERED' if answered else
                      ('ANSWERED_NOT_APPLIED' if 'not_applied_because' in a else 'PENDING_OWNER'), meta=a)
    return out


def off_pos_use_ratio():
    """code -> tuna use outside the POS as a ratio to POS use (I07; owner round 3). Empty when not answered or
    when the recipe_only scenario is analysed."""
    a = owner_answers()['tuna_use_outside_pos']
    if a['status'] != 'ANSWERED' or SCENARIO['tuna_scenario'] == 'recipe_only':
        return {}
    split = dict(a['value'])
    pos = split.pop('pos_dishes')
    return {'TUN': round(sum(split.values()) / pos, 4)}


# I12, team decision 2026-10-07 (round 5): the owner's ~4 kg of ground beef a week (4 x 1 kg packs, as bought) is staff
# meals / off-menu food: no workbook recipe uses ground beef. Logged as use outside the POS (inventory.qty_off_pos_use),
# so menu food cost stays on the recipes while the stock leaving the freezer is accounted for.
GB_STAFF_MEALS_KG_BOUGHT_PER_WEEK = 4.0
GB_USABLE_FRACTION = 0.6       # SUPPLY-UR row 51 Ground Beef, Wastage/ Fluctuation 0.4 (checked in the build)


def off_pos_use_daily():
    """code -> fixed use outside the POS, usable base units per open day (I12)."""
    return {'GB': round(GB_STAFF_MEALS_KG_BOUGHT_PER_WEEK * 1000 * GB_USABLE_FRACTION / 7, 4)}


def off_pos_codes():
    return set(off_pos_use_ratio()) | set(off_pos_use_daily())


# --- gyoza made in-house (team decision 2026-10-07, round 5) -----------------------------------------------------
# makisushi_Jan_2026.xlsx REFERENCES rows 19-31, "GYOZA": one batch of filling = Cabbage 3 kgs, Baguio Pechay 3 kgs,
# White Onion 0.5 kgs, Carrots 1 kgs, Ginger 300 gms ("???" beside it), Garlic 0.5 kgs, Ground Pork 0.74 kgs,
# Oyster Sauce 1 bot; Kikkoman, Sesame, Hondashi and Salt with no amount. The sheet gives no pieces per batch. Round 6
# (team decision 2026-10-08) sets 450 pieces a batch, accepts the 300 g ginger, the seasoning grams below and wrappers at
# PHP 50 for 50. Every MENU2 gyoza piece (GZA) becomes one wrapper plus 1/450 of the batch. Labour is not modelled.
GYOZA_BATCH = {'CAB': 3000, 'PCH': 3000, 'ONI': 500, 'CAR': 1000, 'GIN': 300, 'GAR': 500, 'GP': 740, 'OYS': 1,
               # round 6 (team decision 2026-10-08): seasonings at "standard ratios for a batch that size" - 200 ml
               # Kikkoman (soy sauce SHO, 1.05 g/mL = 210 g), 50 ml sesame oil (0.92 g/mL = 46 g), 50 g hondashi, 20 g salt
               'SHO': 210, 'SES': 46, 'HON': 50, 'SLT': 20}
GYOZA_SEASONINGS = ('SHO', 'SES', 'HON', 'SLT')
# round 6 (team decision 2026-10-08): one batch makes 450 pieces ("about 6,740 g of filling / 15 g"). The listed solids
# total 9.04 kg (cabbage, pechay, onion, carrots, ginger, garlic, pork), so 450 pieces is ~20 g of filling a piece.
GYOZA_PIECES_PER_BATCH = 450
GYOZA_FILLING_G_PER_PIECE = round(sum(g for c, g in GYOZA_BATCH.items()
                                      if c not in ('OYS',) + GYOZA_SEASONINGS) / GYOZA_PIECES_PER_BATCH, 2)
GYOZA_WHY = ('in-house gyoza (team decisions 2026-10-07 / 08): makisushi_Jan_2026.xlsx REFERENCES rows 20-31 batch '
             f'(9.04 kg of filling, 1 bottle oyster sauce, team-set seasonings) / {GYOZA_PIECES_PER_BATCH} pieces a batch')
# new ingredients: code -> (name, category, storage_type, uom, shelf_life_days, unit_cost, cost provenance and basis,
#                            supplier product or name, order_unit, pack_size, pack_unit, pack_size_base)
NEW_INGREDIENTS = {
    'GZW': ('Gyoza Wrapper', 'dry goods', 'frozen', 'pc', 90, 1.00,
            'team decision 2026-10-08: packs of 50 for PHP 50 (PHP 1.00 a wrapper), a Manila wet-market / grocery rate; '
            'SUPPLY-UR row 9 (BANRI, "Gyoza Wrapper", 1 pk) records no price', 'Gyoza Wrapper', 'pack', 50, 'pc', 50),
    'PCH': ('Baguio Pechay', 'vegetable', 'chilled', 'g', 5, None, 'SUPPLY-UR row 69 usable rate',
            'Baguio Pechay', 'kg', 1, 'kg', 1000),
    'GAR': ('Garlic', 'vegetable', 'ambient', 'g', 60, None, 'SUPPLY-UR row 65 usable rate', 'Garlic', 'kg', 1, 'kg', 1000),
    'GIN': ('Ginger (fresh)', 'vegetable', 'chilled', 'g', 21, 0.20,
            'COSTING row 27 (ginger: PHP 2 for 10 g, i.e. PHP 50 a 250 g); pack size assumed 250 g', 'HI-TOP', 'pack',
            250, 'g', 250),
    'OYS': ('Oyster Sauce', 'sauce', 'ambient', 'pc', 180, 234.0,
            'COSTING row 19 (oyster, PHP 234 a bottle); REFERENCES uses "1 bot" a batch', 'SHOKURYOHIN', 'bottle', 1,
            'bottle', 1),
    'SES': ('Sesame Oil', 'sauce', 'ambient', 'g', 365, round(636 / 1000 / 0.92, 4),
            'COSTING row 39 (Sesame Oil PHP 636 a liter) at 0.92 g/mL (SAUCE_DENSITY); 1 L bottle assumed', 'SHOKURYOHIN',
            'bottle', 1, 'L', 1),
    'HON': ('Hondashi', 'dry goods', 'ambient', 'g', 365, None, 'SUPPLY-UR row 32 (Hondashi - Mrutomo) usable rate',
            'Hondashi - Mrutomo', 'kg', 1, 'kg', 1000),
    'SLT': ('Salt', 'dry goods', 'ambient', 'g', 730, 0.03,
            'SYNTHETIC_ASSUMPTION: no workbook price (COSTING books salt only as PHP 0.25 a serving); PHP 30 a kg assumed',
            'HI-TOP', 'kg', 1, 'kg', 1000),
}
NEW_PRICED = {'PCH': 'Baguio Pechay', 'GAR': 'Garlic', 'HON': 'Hondashi - Mrutomo'}        # unit_cost = this SUPPLY-UR row's usable rate


def new_ingredient_rows(ing, rates):
    """ingredients.csv rows for NEW_INGREDIENTS (ids after the current maximum)."""
    if set(NEW_INGREDIENTS) <= set(ing['ingredient_code']):
        return ing
    rate = rates[rates['is_chosen_supplier']].set_index('product')['unit_rate_per_gms']
    nid = int(ing['ingredient_id'].max()) + 1
    rows = []
    for k, (c, v) in enumerate(NEW_INGREDIENTS.items()):
        name, cat, store, uom, life, cost = v[:6]
        cost = round(float(rate[NEW_PRICED[c]]), 4) if c in NEW_PRICED else cost
        rows.append(dict(ingredient_id=nid + k, ingredient_code=c, ingredient_name=name, category=cat,
                         storage_type=store, uom=uom, shelf_life_days=life,
                         is_perishable=life <= 7 or cat == 'dairy', unit_cost=cost, catalog_unit_cost=np.nan,
                         menu2_codes='REFERENCES gyoza', cost_source=v[6], name_source='REFERENCES (round 5)'))
    return pd.concat([ing, pd.DataFrame(rows).reindex(columns=ing.columns)], ignore_index=True)


def new_terms(ing, terms_cols):
    """supplier_item_terms rows (supplier_id filled by the caller) for NEW_INGREDIENTS."""
    iid = ing.set_index('ingredient_code')['ingredient_id']
    rows = [dict(supplier_id=np.nan, ingredient_id=int(iid[c]), order_unit=v[8], pack_size=v[9], pack_unit=v[10],
                 pack_size_base=v[11], min_order_packs=1) for c, v in NEW_INGREDIENTS.items()]
    return pd.DataFrame(rows)[terms_cols]


GYOZA_REMOVED_WHY = ('team decision 2026-10-07: gyoza are made in-house (makisushi_Jan_2026.xlsx REFERENCES rows '
                     '19-31), so the ready-made GZA line is replaced by a wrapper and the filling ingredients '
                     '(recipe_source REFERENCES:gyoza)')


def gyoza_lines(df, qty, ing):
    """Every GZA line (gyoza pieces) -> one wrapper a piece + the batch share of each filling ingredient."""
    code_id = ing.set_index('ingredient_code')['ingredient_id']
    gz = df[df['ingredient_code'] == 'GZA']
    rows = []
    for r in gz.itertuples():
        pcs = getattr(r, qty)
        parts = {'GZW': 1.0, **{c: g / GYOZA_PIECES_PER_BATCH for c, g in GYOZA_BATCH.items()}}
        for c, per in parts.items():
            rows.append(dict(item_id=int(r.item_id), ingredient_id=int(code_id[c]), ingredient_code=c,
                             item_name=r.item_name if hasattr(r, 'item_name') else '', qty=round(pcs * per, 6),
                             recipe_source='REFERENCES:gyoza',
                             derivation=f'{GYOZA_WHY}; {pcs:g} gyoza x ' + ('1 wrapper' if c == 'GZW' else
                                        f'{GYOZA_BATCH[c]:g} / {GYOZA_PIECES_PER_BATCH:.1f}')))
    return df[df['ingredient_code'] != 'GZA'].copy(), gz, rows


# --- round 6 (team decision 2026-10-08): Hi-Top is a walk-in grocery -------------------------------------------------
# SUPPLY-UR names "HI-TOP" (and the mango, cucumber and other produce rows were filled from it). It is Hi-Top Supermart,
# Quezon Avenue, a few blocks from the restaurant on Panay Avenue, which also fits Q3 ("like at groceries"). Staff walk
# or take a tricycle there with petty cash when stock runs low: no delivery truck, lead time 0, always in stock. In the
# simulation's daily cycle (receive in the morning, use, review in the evening) an evening run is on the shelf the next
# morning, as before; a run during service is an emergency buy at the regular price (Config.walk_in_suppliers). The terms
# apply to every item bought there, not only mango and cucumber. Mango stays at SUPPLY-UR's PHP 300 a kg (accepted as a
# conservative ceiling).
WALK_IN = {'HI-TOP': 'Hi-Top Supermart, Quezon Avenue (walk-in grocery, petty cash; team decision 2026-10-08): bought '
                     'when stock runs low; lead time 0 (an evening run is on the shelf the next morning); a run during '
                     'service is an emergency buy at the regular price, no premium'}


def walk_in_terms(assume):
    """supplier_term_assumptions with the walk-in suppliers' terms (lead time 0, no variation, always in stock, any day)."""
    assume = assume.copy()
    for name, basis in WALK_IN.items():
        k = assume['supplier_name'] == name
        assert k.sum() == 1, name
        assume.loc[k, ['lead_time_days', 'lead_time_sd_days', 'fill_rate', 'delivery_interval_days']] = [0, 0.0, 1.0, 1]
        assume.loc[k, 'basis'] = basis
        assume.loc[k, 'terms_status'] = 'CLIENT_PROVIDED'
        assume.loc[k, 'terms_source'] = 'Q3 ("like at groceries"); team decision 2026-10-08'
    return assume


def owner(key):
    return owner_answers()[key]['value']

# --- the answers, verbatim --------------------------------------------------------------------------
ANSWERS = {
    'Q1': ('How long do you keep salmon and tuna or other frozen goods, or how many days do you keep salmon '
           'and tuna and perishable raw ingredients in general?',
           "Usually the shelf life is the same once frozen, because when frozen they can stay up to 4 weeks+. "
           "Salmon and tuna only differ from other meats/perishable goods once they're thawed. For fish meat, "
           "we only take out ready-made portions/pieces since it's not a fast-moving menu item. Essentially, "
           "once you take out the fish meat and it thaws, it shouldn't go back and forth in the freezer as much "
           "as possible to maintain freshness. For meats, they're also already portioned once put in the "
           "freezer and we'll only take out a few portions to thaw and use within the day."),
    'Q2': ('Are ground beef/pork or mushrooms frozen or do you just buy small amounts?',
           "Ground beef/pork - yes, we buy them while still frozen in bulk and portion them before putting in the "
           "refrigerator. For mushrooms and similar ingredients, we specifically buy small amounts to last us a "
           "couple of weeks or until supply runs out, then we restock. They're just stored in the chiller anyway."),
    'Q3': ('Do you buy cucumbers and mangoes per piece or by kilogram?',
           "We stock cucumbers and especially mangoes by kilogram since they spoil easily HAHA. Around 2-3kg per "
           "week is consumed. Same thing - until supply lasts and we restock once we run out (it's quick to buy "
           "mangoes compared to other ingredients since they're accessible like at groceries etc). Mangoes are "
           "mainly for California maki & kani salads."),
    'Q4': ('Average budget spent on ingredients per week',
           "The expense is around 5k to 15k — that's the average budget spent on weekly restock, depending on "
           "when they do the restocking. Then, when whole salmon and tuna arrive, it's 5k each, once or twice a "
           "month."),
    'Q5': ('Storage capacity - like how many kg can the fridge hold?',
           "For storage capacity, we only have 3 standard fridges & 1 chest freezer: Fridge 1 - drinks, sodas in "
           "cans/ice/pitchers/ (I don't know how much is in there on average but its storage capacity is supposedly "
           "250L) though it's always full anyway so yea. Fridge 2 - veggies & mangoes in the chiller only (the "
           "freezer part is only occupied with extra meats too). Chiller 1 - that's a Fujidenzo, like a full chiller "
           "fridge. All the ready-made portioned ingredients are stored here like sliced cucumbers, sliced mangoes, "
           "sliced crabsticks, tofus, gingers, wasabi, tempura pastes, etc. Chest Freezer 1 - all the uncut/"
           "unportioned meats are here, literally still wrapped in plastic. Tall Freezer 1 - all the portioned "
           "meats - fish & pork & beef that are frozen - are placed here. They're divided into sections."),
    'Q6': ('Ingredient naming', 'Rename squash at SQU.'),
    'O1': ('Does the PHP 5,000-15,000 weekly budget cover all ingredients?',
           "Yes, for normal weekly restocking, the PHP 5,000-15,000 budget generally covers the regular "
           "ingredients we need. However, it does not include the purchase of a whole salmon or whole tuna, "
           "which is a larger periodic purchase of around PHP 5,000 each and happens about once or twice a "
           "month. So the weekly budget should be treated as the regular restocking budget, while whole-fish "
           "purchases are separate periodic expenses."),
    'O2': ("Is the price sheet's Wastage/Fluctuation column trim loss or a price buffer? How many usable kg "
           "does a whole salmon give?",
           "The Wastage/Fluctuation percentage is better treated as an allowance for trim/yield loss, rather "
           "than a price buffer. When we buy a whole salmon, not all of its weight becomes usable meat because "
           "of the skin, bones, trimming, and other parts that cannot be used for the menu items. For planning "
           "purposes, around 50-60% of a whole salmon's weight can be treated as usable meat, depending on the "
           "size and how it is cut. For example, a 10 kg whole salmon would give roughly 5-6 kg of usable meat. "
           "This should be treated as an estimate for the model, not an exact measured yield."),
    'O3': ('Whole tuna: weight and how long one lasts.',
           "A whole tuna is usually purchased as a larger fish and its exact weight varies. For inventory "
           "planning, we can use around 20 kg per whole tuna as a reasonable working assumption. One whole tuna "
           "can last around 2-4 weeks, depending on sales volume and how much is portioned and frozen. We don't "
           "thaw the entire fish at once; it is processed into portions, and only the amount needed is taken "
           "out for use."),
    'O4': ('Is KAL squash or kalamansi?',
           "KAL refers to kalamansi. We should therefore standardize KAL as kalamansi across the ingredients, "
           "recipes, inventory, sales-related mappings, and supplier datasets. (The follow-up's summary table "
           "said 'Squash'; the team confirmed kalamansi.)"),
    'O5': ('Are portioned ground beef/pork kept in the freezer or the chiller?',
           "They are portioned and stored in the freezer. Ground beef and pork are bought frozen in bulk, "
           "divided into smaller portions, and kept frozen. Only the portions needed for near-term use are "
           "taken out to thaw."),
    'T1': ('Does tuna go anywhere that is not rung up at the till?',
           "Yes, in several places. Staff meals: the trimmings and the panga (collar) get grilled or made into kinilaw "
           "for the crew. Off-menu specials: a kinilaw or tuna belly special on slow days, often not entered at the till. "
           "Comps and tasting portions: sashimi for regulars, supplier or event guests, and bundle add-ons. Catering and "
           "party trays: Christmas orders sometimes go through a separate sheet. Cutting waste: blood line, skin, and the "
           "first slices that don't make the grade. Plausible split, kg a week: POS dishes ~1.0, staff meals and "
           "trimmings ~0.5, off-menu specials and kinilaw ~0.5, comps / tasting / catering ~0.5, cutting loss and "
           "unrecorded ~0.5; total ~3.0, so a fish lasts about 25 days."),
    'T2': ("About how many grams of tuna go into each dish? Is Pork Misono's 120 g of tuna a mistake?",
           "Maki and nigiri-style dishes: about 30-40 g of tuna. Sashimi: about 60-90 g. Pork Misono is a typo in my "
           "sheet. It should have 120 g of pork loin and no tuna, like Pork Teppanyaki."),
    'T3': ('How much of a whole tuna becomes usable meat?',
           "About 50-55% of the whole fish, not 65%. A 20 kg fish gives about 10-11 kg."),
    'D5': ('Team decisions on the open owner questions (2026-10-07, round 5)',
           "Budget: Set the system baseline to the ~PHP 23k/week recipe figure. The 5-15k was a fantasy, and the 49k means food is either spoiling, being stolen, or eaten by staff unrecorded. By setting it to 23k, the system will accurately reflect what your menu should cost. Salmon: Approve 3 fish per month and use the supplier's actual list price of ~PHP 3,000. The PHP 5,000 figure means they were either quoting a different premium grade, getting ripped off by a middleman, or just misremembering. Mango: Accept the 3.8 kg a week as reality. If shakes are taking up half of that because of a massive 180g portion, that explains the gap perfectly. For now, let the system use the 3.8 kg figure so you don't trigger stockouts. Next week, you can work with the bartenders to test a 120g or 150g shake portion to bring costs down. Ground beef: Log the 4 kg as Staff Meals / Off-Menu. If no workbook recipe uses it, the kitchen is almost certainly cooking it for their daily family meals. Categorizing it this way keeps your official food cost (menu profitability) accurate while still accounting for the inventory leaving the fridge. Storage litres: Approve the unconfirmed figures provisionally so the simulation can proceed. Fridge capacities won't drastically alter your immediate finances. MENU2 duplicates: Delete or hide two of each pair in the system. Gyoza filling: Model the in-house recipe from the REFERENCES tab. Since you are paying for the raw ingredients and the labor to make it, the system needs to track the individual components (pork, cabbage, wrappers) rather than treating it like a pre-bought frozen item. Pork belly yield: Use the conservative 55% yield from SUPPLY-UR. A 68% yield assumes perfect butchery with minimal fat trimming. Pork belly requires heavy trimming, and it shrinks significantly when cooked. Using 55% gives you a financial buffer; if the kitchen yields more, it's bonus profit."),
    'D6': ('Team decisions on the remaining open questions (2026-10-08, round 6; summary of the team message)',
           'Storage: chilled items (eggs, mayo, cheese, miso, noodles) are in Fridge 2; if Fridge 1 is for drinks / front-of-house, the kitchen staff need their mayo, miso and noodles on the line. Chicken is kept whole in the chest freezer when it arrives in bulk and moved to the tall freezer once portioned. Mangoes (and cucumbers): the supplier is Hi-Top Supermart (Quezon Avenue, a few blocks from the restaurant on Panay Ave); delivery schedule walk-in / petty cash, 0-day lead time; accept PHP 300/kg for mangoes as a conservative ceiling. Gyoza: one batch makes 450 pieces (about 6,740 g of filling / 15 g); wrappers in packs of 50 for PHP 50 (PHP 1.00 each); accept the 300 g of ginger; seasonings for a batch: 200 ml Kikkoman, 50 ml sesame oil, 50 g hondashi, 20 g salt (or a flat 5% cost buffer).'),
    'O6': ('Do shakes use fresh mango?',
           "Yes, shakes can use fresh mango. The mango is purchased fresh, stored in the chiller, and used for "
           "shakes as well as menu items such as California Maki and Kani Salad."),
}

# --- Q1 / Q2 / O5: shelf life and storage state --------------------------------------------------------
FROZEN_LIFE_DAYS = 28    # MODELLED_FROM_CLIENT: "up to 4 weeks+" -> the 4-week minimum
THAWED_USE_DAYS = 1      # Q1: portions are thawed and used within the day
MUSHROOM_LIFE_DAYS = 14  # MODELLED_FROM_CLIENT: "to last us a couple of weeks"
# Team decision 2026-10-09: mushroom (14 d) and egg (21 d) are perishable although their shelf life is over 7 days.
# is_perishable = (shelf life <= 7 d or dairy) or one of these codes; the schema CHECK only requires the flag for the first two.
PERISHABLE_OVERRIDE = ('MUS', 'EGG')
RAW_FISH = ('SAL', 'TUN', 'SAS', 'SQD', 'PDT')
RAW_MEAT = ('CF', 'CT', 'PB', 'PL', 'SB', 'GP', 'GB')
RAW_FROZEN = RAW_FISH + RAW_MEAT
MANUFACTURED_FROZEN = ('EBI', 'EBK', 'GZA', 'KNI')    # factory-frozen products; their generator life is kept

FROZEN_WHY = (f'Q1: frozen goods keep "up to 4 weeks+", salmon and tuna the same as other meats; '
              f'{FROZEN_LIFE_DAYS} d = the 4-week minimum, a modelling value (the client gave no exact number)')
KAL_WHY = ('O4: KAL is kalamansi (MENU2 labels it "KALAMANSI 10 gms each"); the generator had inferred "Kalabasa '
           '(Squash)". unit_cost PHP 0.10/g = COSTING PHP 1 per kalamansi / MENU2 10 g each')
# code: ({column: new value}, reason). is_perishable is re-derived with the generator's own rule.
INGREDIENT_UPDATES = {
    **{c: ({'storage_type': 'frozen', 'shelf_life_days': FROZEN_LIFE_DAYS}, FROZEN_WHY) for c in RAW_FROZEN},
    'MUS': ({'shelf_life_days': MUSHROOM_LIFE_DAYS},
            'Q2: mushrooms are bought in small amounts "to last us a couple of weeks", kept in the chiller; '
            f'{MUSHROOM_LIFE_DAYS} d = two weeks, a modelling value'),
    'BSG': ({'storage_type': 'chilled'}, 'Q5: ginger is kept in Chiller 1'),
    'KAL': ({'ingredient_name': 'Kalamansi', 'category': 'fruit'}, KAL_WHY),
}

# --- Q4 / O1-O3: whole salmon and tuna -------------------------------------------------------------------
# Team decision 2026-10-07 (round 5): salmon at the supplier's list price, INGREDIENTS.xlsx sheet "Squid" row 11
# "Salmon Whole Norweigian, 5-6kg /per pc, 590" -> 5 kg (the owner's weight) x PHP 590 a kg = PHP 2,950 (~PHP 3,000).
# The client's PHP 5,000 a fish (Q4) is kept as a recorded figure only. Tuna has no catalogue whole-fish price: PHP 5,000.
SALMON_LIST_PHP_PER_KG = 590
WHOLE_FISH_PHP = {'SAL': 2950, 'TUN': 5000}
WHOLE_FISH_PHP_CLIENT = {'SAL': 5000, 'TUN': 5000}            # Q4 "PHP 5,000 each"
WHOLE_FISH_PRICE_SOURCE = {
    'SAL': ('SOURCE_DERIVED', 'team decision 2026-10-07: INGREDIENTS.xlsx Squid C11 PHP 590 a kg (Salmon Whole '
                              'Norwegian, 5-6 kg a fish) x 5 kg; the client\'s PHP 5,000 (Q4) is not used'),
    'TUN': ('CLIENT_PROVIDED', 'Q4, O1: about PHP 5,000 each, a whole-unit price, not per kg')}
# fish a month: tuna the client's "once or twice a month"; salmon 3 a month approved (team decision 2026-10-07)
WHOLE_FISH_PER_MONTH = {'SAL': (1, 3), 'TUN': (1, 2)}
FISH_PRODUCT = {'SAL': 'Salmon', 'TUN': 'Tuna Steak'}          # their SUPPLY-UR rows
SALMON_USABLE, SALMON_USABLE_RANGE = 0.55, (0.50, 0.60)        # O2 "around 50-60%" -> the midpoint
TUNA_WHOLE_KG = 20.0                                           # O3 working assumption
TUNA_DAYS_PER_FISH = (14, 28)                                  # O3 "around 2-4 weeks"


SALMON_EXAMPLE_KG = 10.0                                       # O2's example ("a 10 kg whole salmon"); scenario only
# I14: when salmon / tuna run out, the emergency buy is whole fish too, at the regular price a fish
WHOLE_UNIT_EMERGENCY = tuple(WHOLE_FISH_PHP)
WHOLE_UNIT_EMERGENCY_PREMIUM = 0.0
# I20 (team decision 2026-10-06): one whole tuna outlasts its 28-day life, so the reorder trigger only reacted
# after it expired. Tuna is checked daily and its replacement is planned for the morning the old fish is binned.
# Salmon is left out: it reorders normally, and including it added overlap waste in the preview.
PLANNED_REPLACEMENT = ('TUN',)


def fish_basis(rates):
    """One row per whole fish: price, whole weight, usable fraction and grams, PHP per usable g, with provenance.
    Salmon: weight = the owner's answer if given (round 3), else PHP 5,000 / SUPPLY-UR PHP per kg (team choice);
    the salmon_weight_scenario 'owner_example_10kg' uses O2's 10 kg example for analysis only. Usable 55% (O2).
    Tuna: 20 kg (O3); usable = the owner's answer if given, else 1 - SUPPLY-UR tuna wastage."""
    ans = owner_answers()
    rows = []
    for code, product in FISH_PRODUCT.items():
        r = rates[(rates['product'] == product) & rates['is_chosen_supplier']].iloc[0]
        per_kg = r['unit_rate_php'] / r['detailed_quantity'] * 1000
        php = WHOLE_FISH_PHP[code]
        if code == 'SAL':
            a = ans['salmon_whole_kg']
            if a['status'] == 'ANSWERED':
                whole_g, wprov = round(a['value'] * 1000), 'CLIENT_PROVIDED'
            elif SCENARIO['salmon_weight_scenario'] == 'owner_example_10kg':
                whole_g, wprov = round(SALMON_EXAMPLE_KG * 1000), 'SIMULATION'
            else:
                whole_g, wprov = round(php / per_kg * 1000), 'DERIVED'
            usable, uprov = SALMON_USABLE, 'MODELLED_FROM_CLIENT'
        else:
            a = ans['tuna_usable_fraction']
            whole_g, wprov = round(TUNA_WHOLE_KG * 1000), 'CLIENT_PROVIDED'
            usable = a['value'] if a['status'] == 'ANSWERED' else 1 - r['wastage_fluctuation']
            uprov = a['provenance']
        usable_g = round(whole_g * usable, 2)          # = the pack the simulation receives
        rows.append(dict(ingredient_code=code, client_price_php_per_fish=php, supply_ur_row=int(r['source_row']),
                         supply_ur_product=product, supply_ur_price_php_per_kg=per_kg,
                         supply_ur_wastage_fluctuation=r['wastage_fluctuation'], whole_g_per_fish=whole_g,
                         whole_g_provenance=wprov, usable_fraction=usable, usable_fraction_provenance=uprov,
                         usable_g_per_fish=usable_g, usable_cost_php_per_g=round(php / usable_g, 4)))
    return pd.DataFrame(rows)


def whole_fish_terms(rates):
    """code -> supplier_item_terms values for one whole fish (pack_size_base = whole grams as bought)."""
    fb = fish_basis(rates).set_index('ingredient_code')
    return {c: {'order_unit': 'whole fish', 'pack_size': '1', 'pack_unit': 'fish',
                'pack_size_base': str(int(fb.loc[c, 'whole_g_per_fish']))} for c in fb.index}


# --- I18: sauces bought in litres, stocked in grams ------------------------------------------------------
# The owner's sheets measure these sauces in grams (SUPPLY-UR prices soy sauce "per gms"; COSTING has
# "Teppanyaki Sauce - Grams"), so recipes, unit costs and stock stay in grams and only the three litre
# packs (SYNTHETIC v1 supplier terms) are converted, with a sauce-specific density instead of 1 g/mL.
FSANZ = 'https://www.foodstandards.gov.au/sites/default/files/2023-12/npc-specific-gravities.pdf'
SAUCE_DENSITY = {  # code: (g per mL, provenance, basis)
    'SHO': (1.05, 'EXTERNAL_REFERENCE', f'FSANZ specific gravities, "Sauce, soy" 1.05 ({FSANZ}); USDA FoodData '
            'Central 174277 shoyu 255 g per cup = 1.08 g/mL (https://fdc.nal.usda.gov/food-details/174277/nutrients)'),
    'TEP': (1.082, 'EXTERNAL_REFERENCE', 'analogue: USDA FoodData Central 2707445 "Teriyaki sauce", 16 g per tablespoon '
            '(14.787 mL) = 1.082 g/mL (https://fdc.nal.usda.gov/food-details/2707445/nutrients); teppanyaki sauce is '
            'the same kind of sweet soy grill sauce'),
    'SES': (0.92, 'EXTERNAL_REFERENCE', 'USDA FoodData Central 171016 "Oil, sesame, salad or cooking", 13.6 g per '
            'tablespoon (14.787 mL) = 0.920 g/mL (https://fdc.nal.usda.gov/food-details/171016/nutrients); round 6 gyoza '
            'seasoning, bought as a 1 L bottle (COSTING row 39)'),
    'TSS': (1.05, 'DERIVED', 'tentsuyu = 3 parts dashi : 1 mirin : 1 soy sauce (https://en.wikipedia.org/wiki/Tentsuyu), '
            f'with FSANZ stock 1.02, soy 1.05 and mirin between sweet dessert wine 1.05 and 46%-sugar syrup 1.20 '
            f'({FSANZ}): 1.03-1.06, midpoint 1.05'),
}


def sauce_terms(terms):
    """code -> supplier_item_terms values: litre pack converted to grams at the sauce's density."""
    out = {}
    for code, (dens, _, _) in SAUCE_DENSITY.items():
        t = terms.loc[terms['code'] == code].iloc[0]
        assert t['pack_unit'] == 'L', code
        out[code] = {'pack_size_base': str(int(round(float(t['pack_size']) * 1000 * dens)))}
    return out


def usable_fractions(ing, isup, rates):
    """Per ingredient: the usable share of a purchased pack. O2: SUPPLY-UR Wastage/ Fluctuation is a trim /
    yield loss, and unit_cost (price / (1 - wastage)) is already per usable unit."""
    fb = fish_basis(rates).set_index('ingredient_code')
    w = rates.set_index('source_row')['wastage_fluctuation']
    s = isup.set_index('ingredient_id')
    rows = []
    for r in ing.itertuples():
        b = s.loc[r.ingredient_id]
        if r.ingredient_code in fb.index:
            f = fb.loc[r.ingredient_code]
            frac, prov = f.usable_fraction, f.usable_fraction_provenance
            basis = ('O2: about 50-60% of a whole salmon is usable; 55% midpoint' if r.ingredient_code == 'SAL' else
                     'owner round 3: about 50-55% of a whole tuna is usable; 52.5% midpoint'
                     if f.usable_fraction_provenance != 'SOURCE_DERIVED' else
                     f'SUPPLY-UR row {f.supply_ur_row} ({f.supply_ur_product}) wastage {f.supply_ur_wastage_fluctuation:g} '
                     'applied to the whole tuna; the owner gave no tuna yield')
        elif b['basis'].startswith('its unit_cost'):
            frac, prov = 1 - w[b['sheet_row']], 'SOURCE_DERIVED'
            basis = f'SUPPLY-UR row {int(b["sheet_row"])} Wastage/ Fluctuation {w[b["sheet_row"]]:g}, a trim / yield loss (O2)'
        else:
            frac, prov, basis = 1.0, 'SYNTHETIC_ASSUMPTION', 'not priced from SUPPLY-UR, no yield figure: pack fully usable'
        rows.append(dict(ingredient_id=r.ingredient_id, usable_fraction=round(float(frac), 4),
                         usable_fraction_provenance=prov, usable_fraction_basis=basis))
    return pd.DataFrame(rows)


# --- Q3 / O6: mango -------------------------------------------------------------------------------------
# Usable mango per kani stick, from the owner's COSTING sheet (makisushi_Jan_2026.xlsx), which prices mango
# at SUPPLY-UR's usable rate (PHP 0.60 a g = PHP 300 / 500 usable g), so its grams are usable grams:
#   row 655 "California Maki" (1 kani, 100 g rice, 20 g cucumber, sold at PHP 180, the dine-in roll): 20 g
#   row 590 "CALIFORNIA MAKI" (1 kani, sold at PHP 220 = the GrabFood "CALIFORNIA MAKI" listing):     30 g
# MENU2 has one kani stick per 8-piece California maki roll and 2 (regular) / 4 (sharing) per kani salad, so
# the rate scales every size. (Until 2026-10-07: 26 g from published recipes, cultures.ca / homefoodie.com.ph.)
MANGO_G_PER_KANI = 20.0
MANGO_G_PER_KANI_BY_ITEM = {'CALIFORNIA MAKI': 30.0}     # GrabFood listing, COSTING row 590
MANGO_COSTING_ROW = {20.0: 655, 30.0: 590}
MANGO_DISHES = re.compile(r'california maki|kani salad', re.I)   # not baked sushi / BSP California
MANGO_SOURCES = 'makisushi_Jan_2026.xlsx COSTING rows 590 (30 g) and 655 (20 g)'
MANGO_WASTAGE = 0.5


def _rows(df, rows, qty, ing):
    """New recipe rows in df's own layout (the simulation's bom, or recipes.csv)."""
    out = pd.DataFrame(rows)
    out[qty] = out.pop('qty')
    out['uom'] = out['ingredient_id'].map(ing.set_index('ingredient_id')['uom'])
    out['is_synthetic'] = True
    out['menu2_code'] = ''
    out['source_dish'] = out['item_name']
    out['qty_adjusted_by'] = ''
    return out[list(df.columns)]


def mango_lines(df, qty, menu, ing):
    """Rows adding mango to every California maki and kani salad, at the COSTING grams per kani stick."""
    kni = ing.loc[ing['ingredient_code'] == 'KNI', 'ingredient_id'].item()
    mng = ing.loc[ing['ingredient_code'] == 'MNG', 'ingredient_id'].item()
    names = menu.set_index('item_id')['item_name']
    sticks = df[df['ingredient_id'] == kni].groupby('item_id')[qty].sum()
    items = [i for i in sticks.index if MANGO_DISHES.search(names[i])]
    assert not set(df.loc[df['ingredient_id'] == mng, 'item_id']) & set(items), 'mango already in a recipe'
    assert set(MANGO_G_PER_KANI_BY_ITEM) <= {names[i] for i in items}
    rows = []
    for i in items:
        dish = 'kani salad' if 'salad' in names[i].lower() else 'California maki'
        g = MANGO_G_PER_KANI_BY_ITEM.get(names[i], MANGO_G_PER_KANI)
        rows.append(dict(item_id=int(i), ingredient_id=int(mng), ingredient_code='MNG', item_name=names[i],
                         qty=g * sticks[i], recipe_source='COSTING:client_mango',
                         derivation=f'client_mango: {SOURCE} Q3 says mangoes are mainly for California maki and kani '
                                    f'salads (line: CLIENT_PROVIDED); {g:g} g usable per kani stick x {sticks[i]:g} '
                                    f'sticks in this {dish} (quantity: SOURCE_DERIVED, makisushi_Jan_2026.xlsx COSTING '
                                    f'row {MANGO_COSTING_ROW[g]}, mango priced at the usable rate PHP 0.60 a g)'))
    return rows


# --- O4: recipe lines built on KAL = squash -------------------------------------------------------------
DROP_LINES = {(60, 'KAL'), (343, 'KAL'), (344, 'KAL')}     # the SYNTHETIC "Crunchy Veggie" rolls
DROP_WHY = ('O4: KAL is kalamansi. This SYNTHETIC (A_new_recipe) line added KAL as a crunchy vegetable when the '
            'generator read KAL as squash, so its basis no longer holds')


def drop_lines(bom):
    """(bom without DROP_LINES, the dropped rows)."""
    hit = pd.Series([(i, c) in DROP_LINES for i, c in zip(bom['item_id'], bom['ingredient_code'])], index=bom.index)
    assert hit.sum() == len(DROP_LINES), f'expected {len(DROP_LINES)} lines to drop, found {hit.sum()}'
    return bom[~hit].copy(), bom[hit].assign(removed_because=DROP_WHY)


# --- round 3: recipe lines and quantities behind owner keys ------------------------------------------------
SALMON_MANGO_ROLL = '[MR] Salmon Mango Roll'     # I09
SHAKE_ITEMS = ('[DS] Mango Shake', 'Upgrade to Mango Shake')
JUICE_ITEMS = ('[DS] Mango Juice',)
WEEKLY_USE_KEYS = {'sushi_rice_kg_per_week': 'SUS', 'chicken_fillet_kg_per_week': 'CF',
                   'pork_loin_kg_per_week': 'PL', 'sukiyaki_beef_kg_per_week': 'SB', 'ground_beef_kg_per_week': 'GB'}
TRIM_FISH = {'cut_from_salmon': 'SAL', 'cut_from_tuna': 'TUN'}
PORK_MISONO = r'(\[PR\] )?pork misono'                    # items 126, 128, 380
PORK_MISONO_WHY = ('owner round 3: Pork Misono is a typo in the owner\'s sheet (MENU2 rows 817 / 963 typed TUN 120); '
                   'it is 120 g of pork loin and no tuna')


def real_use(df, qty, sales):
    """code -> usable g a day in the real POS window (recorded sales x these recipe lines)."""
    s = sales[pd.to_datetime(sales['sale_date']) >= REAL_START]
    days = (pd.to_datetime(s['sale_date']).max() - pd.Timestamp(REAL_START)).days + 1
    j = s[['item_id', 'quantity_sold']].merge(df[['item_id', 'ingredient_code', qty]], on='item_id')
    return (j['quantity_sold'] * j[qty]).groupby(j['ingredient_code']).sum() / days


def v4_recipe_lines(df, qty, menu, ing, sales, usable_by_code, tuna_usable_g, ctx=None):
    """generated_v3 recipe lines -> v4: O4 drops, Q3 mango, I09 Salmon Mango Roll, I11 sashimi trim, owner
    quantity answers (round 3) and the analysis scenario. Used for the simulation's bom (qty_base) and for
    recipes.csv (qty_per_item), so both get identical lines. Returns (lines, dropped, ctx); pass the ctx of
    the first call to the second so both scale by the same factors."""
    ans = owner_answers()
    names = menu.set_index('item_id')['item_name']
    code_id = ing.set_index('ingredient_code')['ingredient_id']
    df = df.assign(qty_adjusted_by='')
    df, dropped = drop_lines(df)
    # workbook audit 2026-10-07: MENU2 platter components summed, promo Katsudon from its own MENU2 row
    df, n = wf.apply_menu2_components(df, qty, names)
    assert n == sum(len(v) for v in wf.MENU2_COMPONENTS.values())
    # round 5: gyoza made in-house from the REFERENCES batch (the GZA lines are replaced by their components)
    df, gz, rows = gyoza_lines(df, qty, ing)
    for r in rows:
        r['item_name'] = names[r['item_id']]
    clash = {(r['item_id'], r['ingredient_code']) for r in rows} & set(zip(df['item_id'], df['ingredient_code']))
    assert not clash, f'gyoza components already in these recipes: {sorted(clash)}'
    dropped = pd.concat([dropped, gz.assign(removed_because=GYOZA_REMOVED_WHY)], ignore_index=True)
    df = pd.concat([df, _rows(df, rows, qty, ing)], ignore_index=True)
    df = pd.concat([df, _rows(df, mango_lines(df, qty, menu, ing), qty, ing)], ignore_index=True)
    # I09: [MR] Salmon Mango Roll names mango but MENU2 gives no mango line
    smr = int(names[names == SALMON_MANGO_ROLL].index.item())
    if ans['salmon_mango_roll_has_mango']['value'] and not ((df['item_id'] == smr) & (df['ingredient_code'] == 'MNG')).any():
        g, prov = ans['salmon_mango_roll_mango_g']['value'], ans['salmon_mango_roll_mango_g']['provenance']
        approved = ans['salmon_mango_roll_has_mango']['status'] == 'ANSWERED'
        df = pd.concat([df, _rows(df, [dict(
            item_id=smr, ingredient_id=int(code_id['MNG']), ingredient_code='MNG', item_name=SALMON_MANGO_ROLL, qty=g,
            recipe_source='OWNER:salmon_mango_roll' if approved else 'SYNTHETIC:salmon_mango_roll',
            derivation=(f'{ROUND4}: the owner approved the mango line, {g:g} g usable per 8-piece roll (assumed in round '
                        '3 on the cultures.ca basis of the California maki lines)') if approved else
                       f'SYNTHETIC (salmon_mango_roll): the dish is named for mango but MENU2 has no mango line (I09; '
                       f'line {ans["salmon_mango_roll_has_mango"]["provenance"]}, pending the owner); {g:g} g usable '
                       f'per 8-piece roll ({prov}: cultures.ca 0.2 mango per roll x 260 g x 0.5, the same basis as '
                       f'the California maki lines)')], qty, ing)], ignore_index=True)
    snap = {'current_tuna_g': df.loc[df['ingredient_code'] == 'TUN'].set_index('item_id')[qty].to_dict(),
            'current_mango_g': df.loc[df['ingredient_code'] == 'MNG'].assign(
                n=lambda d: d['item_id'].map(names)).set_index('n')[qty].to_dict()}
    # I07: Pork Misono carries TUN 120 g and no pork in MENU2; the owner confirmed it should be pork loin
    a = ans['pork_misono_pork_loin_g']
    if a['status'] == 'ANSWERED':
        pm = df['item_id'].map(names).str.fullmatch(PORK_MISONO, case=False)
        bad = pm & (df['ingredient_code'] == 'TUN')
        assert bad.sum() == 3 and not (pm & (df['ingredient_code'] == 'PL')).any(), 'Pork Misono lines changed'
        dropped = pd.concat([dropped, df[bad].assign(removed_because=PORK_MISONO_WHY)], ignore_index=True)
        items = df.loc[bad, 'item_id'].tolist()
        df = pd.concat([df[~bad], _rows(df, [dict(
            item_id=int(i), ingredient_id=int(code_id['PL']), ingredient_code='PL', item_name=names[i], qty=float(a['value']),
            recipe_source='OWNER:pork_misono',
            derivation=f'{ROUND3}: the owner says Pork Misono is pork loin {a["value"]:g} g and no tuna (MENU2 rows 817 / '
                       '963 typed TUN 120), like Pork Teppanyaki/Misono') for i in items], qty, ing)], ignore_index=True)
    # I11: sashimi trim bought as packs (current) or cut from a whole fish
    src = ans['sashimi_trim_source']['value']
    if src in TRIM_FISH:
        fish = TRIM_FISH[src]
        for i in df.index[df['ingredient_code'] == 'SAS']:
            same = df.index[(df['item_id'] == df.at[i, 'item_id']) & (df['ingredient_code'] == fish)]
            if len(same):
                df.loc[same[0], qty] += df.at[i, qty]
                df.loc[same[0], 'qty_adjusted_by'] = 'owner:sashimi_trim_source'
                df = df.drop(i)
            else:
                df.loc[i, ['ingredient_code', 'ingredient_id', 'qty_adjusted_by']] = \
                    [fish, int(code_id[fish]), 'owner:sashimi_trim_source']
        df = df.reset_index(drop=True)
    if ctx is None:
        ctx = {'use_g_day': real_use(df, qty, sales), 'tuna_usable_g': tuna_usable_g, **snap}
    # owner quantity answers
    a = ans['tuna_grams_per_serving']
    if a['status'] == 'ANSWERED':
        for item, g in a['value'].items():
            k = (df['item_id'] == int(item)) & (df['ingredient_code'] == 'TUN')
            assert k.sum() == 1, f'tuna_grams_per_serving: item {item} has no tuna line'
            df.loc[k, [qty, 'qty_adjusted_by']] = [float(g), 'owner:tuna_grams_per_serving']
    for key, items in (('mango_g_per_shake', SHAKE_ITEMS), ('mango_g_per_juice', JUICE_ITEMS)):
        if ans[key]['status'] == 'ANSWERED':
            k = df['item_id'].map(names).isin(items) & (df['ingredient_code'] == 'MNG')
            df.loc[k, [qty, 'qty_adjusted_by']] = [float(ans[key]['value']), f'owner:{key}']
    if 'factors' not in ctx:
        ctx['factors'] = {}
        for key, code in WEEKLY_USE_KEYS.items():
            a = ans[key]
            if a['status'] == 'ANSWERED':
                used = a['value'] * (usable_by_code[code] if a['meta'].get('owner_value_basis') == 'bought' else 1)
                ctx['factors'][code] = (used * 1000 / 7 / ctx['use_g_day'][code], f'owner:{key}')
    for code, (f, why) in ctx['factors'].items():
        k = df['ingredient_code'] == code
        df.loc[k, qty] *= f
        df.loc[k, 'qty_adjusted_by'] = why
    # I05 round 4: the owner's weekly budget is a calibration target. Every regular-ingredient quantity the owner
    # has not stated is scaled by one factor so the ingredient cost of real POS sales lands in the budget range.
    if 'budget_factor' not in ctx:
        ctx['budget_factor'] = budget_factor(df, qty, sales, ing)
    if ctx['budget_factor'] is not None:
        k = budget_scaled(df)
        df.loc[k, qty] *= ctx['budget_factor']
        df.loc[k, 'qty_adjusted_by'] = 'calibrated:weekly_budget_php'
    ctx.setdefault('use_g_day_final', real_use(df, qty, sales))
    return df.reset_index(drop=True), dropped, ctx


def budget_target():
    """PHP a week the calibrated ingredient cost lands on, or None when the budget is not a calibration target."""
    ans = owner_answers()
    if ans['weekly_budget_reading']['value'] != 'calibration_target':
        return None
    lo, hi = ans['weekly_budget_php']['value']
    return lo + BUDGET_CALIBRATION_AT * (hi - lo)


def budget_scaled(df):
    """recipe lines the budget calibration scales: regular ingredients whose quantity no owner answer set."""
    return (~df['ingredient_code'].isin(list(WHOLE_FISH_PHP)) & ~df['qty_adjusted_by'].str.startswith('owner:')
            & ~df['recipe_source'].str.startswith('OWNER:'))


def budget_factor(df, qty, sales, ing):
    """factor on the scaled lines so that real POS sales x recipes x unit_cost of regular ingredients = target."""
    target = budget_target()
    if target is None:
        return None
    s = sales[pd.to_datetime(sales['sale_date']) >= REAL_START]
    days = (pd.to_datetime(s['sale_date']).max() - pd.Timestamp(REAL_START)).days + 1
    lines = df.assign(scaled=budget_scaled(df))
    lines = lines[~lines['ingredient_code'].isin(list(WHOLE_FISH_PHP))]
    j = s[['item_id', 'quantity_sold']].merge(lines[['item_id', 'ingredient_code', qty, 'scaled']], on='item_id')
    j['php'] = j['quantity_sold'] * j[qty] * j['ingredient_code'].map(ing.set_index('ingredient_code')['unit_cost'])
    assert j['php'].notna().all()
    week = j.groupby('scaled')['php'].sum() / days * 7
    fixed, scaled = week.get(False, 0.0), week[True]
    assert target > fixed, f'owner-stated quantities alone cost PHP {fixed:,.0f} a week, above the target {target:,.0f}'
    return (target - fixed) / scaled


def owner_current_drift(ctx, rates, terms_gb_pack_g):
    """Pending (or answered but not applied) keys whose current_value in owner_answers_pending.json no longer
    matches the data."""
    ans, bad = owner_answers(), []
    tun = rates[(rates['product'] == FISH_PRODUCT['TUN']) & rates['is_chosen_supplier']].iloc[0]
    sal = rates[(rates['product'] == FISH_PRODUCT['SAL']) & rates['is_chosen_supplier']].iloc[0]
    data = {
        'tuna_grams_per_serving': {str(int(i)): float(g) for i, g in ctx['current_tuna_g'].items()},
        'tuna_usable_fraction': round(1 - tun['wastage_fluctuation'], 4),
        'salmon_whole_kg': round(WHOLE_FISH_PHP['SAL'] / (sal['unit_rate_php'] / sal['detailed_quantity'] * 1000), 3),
        **{k: round(ctx['use_g_day_final'][c] * 7 / 1000, 3) for k, c in WEEKLY_USE_KEYS.items()},
        'ground_beef_pack_g': terms_gb_pack_g,
        'mango_g_per_shake': ctx['current_mango_g'][SHAKE_ITEMS[0]], 'mango_g_per_juice': ctx['current_mango_g'][JUICE_ITEMS[0]],
        'salmon_mango_roll_mango_g': 26.0,          # the round-3 provisional line (cultures.ca basis)
        'chicken_storage_location': INGREDIENT_STORAGE['CF'][3], 'onion_storage_location': INGREDIENT_STORAGE['ONI'][3],
    }
    for k, v in data.items():
        a = ans[k]
        if a['status'] == 'ANSWERED':
            continue
        cur = a['meta']['current_value']
        if k == 'tuna_grams_per_serving':
            cur = {i: e['g'] for i, e in cur.items()}
        if (cur != v) if isinstance(v, (str, dict)) else abs(float(cur) - float(v)) > 1e-6:
            bad.append(f'{k}: json {cur!r} vs data {v!r}')
    return bad


# recipe_source -> (line_provenance, qty_provenance)
RECIPE_PROVENANCE = {'MENU2': ('SOURCE_DERIVED', 'SOURCE_DERIVED'),
                     'NAME_MATCH': ('SOURCE_DERIVED', 'SOURCE_DERIVED'),
                     'NAME_MATCH+SET_B': ('SOURCE_DERIVED', 'SOURCE_DERIVED'),
                     'COSTING:client_mango': ('CLIENT_PROVIDED', 'SOURCE_DERIVED'),
                     'SYNTHETIC:salmon_mango_roll': ('SYNTHETIC_ASSUMPTION', 'EXTERNAL_REFERENCE'),
                     'OWNER:pork_misono': ('CLIENT_PROVIDED', 'CLIENT_PROVIDED'),
                     'OWNER:salmon_mango_roll': ('CLIENT_PROVIDED', 'CLIENT_PROVIDED')}


def recipe_provenance(rec):
    p = rec['recipe_source'].map(RECIPE_PROVENANCE)
    p = p.where(p.notna(), pd.Series([('SYNTHETIC_ASSUMPTION', 'SYNTHETIC_ASSUMPTION')] * len(rec), index=rec.index))
    line, qty = p.str[0].copy(), p.str[1].copy()
    # O6: shakes use fresh mango, so the mango shake / juice lines exist; their grams stay assumed
    line[(rec['ingredient_code'] == 'MNG') & (rec['recipe_source'] == 'SYNTHETIC:A_new_recipe')] = 'CLIENT_PROVIDED'
    trim = rec['qty_adjusted_by'] == 'owner:sashimi_trim_source'      # owner moved the line; grams stay MENU2's
    owner_set = rec['qty_adjusted_by'].str.startswith('owner:') & ~trim
    qty[owner_set] = 'CLIENT_PROVIDED'
    line[trim] = 'CLIENT_PROVIDED'
    qty[rec['qty_adjusted_by'].str.startswith('scenario:')] = 'SIMULATION'
    # I05 round 4: source / team grams scaled to the owner's weekly budget (one factor, client_parameters)
    qty[rec['qty_adjusted_by'] == 'calibrated:weekly_budget_php'] = 'MODELLED_FROM_CLIENT'
    # I23: a MENU2 blank filled with the median of the same code is not a workbook quantity
    imputed = rec['derivation'].str.contains('imputed: blank in MENU2', regex=False, na=False) & (rec['qty_adjusted_by'] == '')
    qty[imputed] = 'SYNTHETIC_ASSUMPTION'
    qty[rec['qty_adjusted_by'] == wf.ADJUSTED_BY] = 'SOURCE_DERIVED'
    # round 5 gyoza: the component is in REFERENCES; its share a piece rests on the assumed pieces per batch;
    # the wrapper is one a piece
    gy = rec['recipe_source'] == 'REFERENCES:gyoza'
    line[gy] = 'SOURCE_DERIVED'
    qty[gy] = np.where(rec.loc[gy, 'ingredient_code'] == 'GZW', 'DERIVED', 'SYNTHETIC_ASSUMPTION')
    unadjusted = (rec['qty_adjusted_by'] == '') & ~imputed & ~gy
    assert rec.loc[unadjusted, 'recipe_source'].str.startswith('SYNTHETIC').eq(
        qty[unadjusted].isin(['SYNTHETIC_ASSUMPTION', 'EXTERNAL_REFERENCE'])).all()
    synthetic = line.eq('SYNTHETIC_ASSUMPTION') | qty.isin(['SYNTHETIC_ASSUMPTION', 'EXTERNAL_REFERENCE', 'SIMULATION'])
    return rec.assign(line_provenance=line, qty_provenance=qty, is_synthetic=synthetic)


# --- Q5: storage ----------------------------------------------------------------------------------------
STORAGE_LOCATIONS = [  # id, location, unit type, state, holds (client), capacity_l, counts toward raw, compartments, reference
    ('FR1', 'Fridge 1', 'standard refrigerator', 'chilled',
     'drinks: canned drinks / sodas, ice, pitchers; usually full', 250, False, 'single unit', '',
     'previous team research: 8.8-11.0 cu ft; e.g. 2-door household unit or beverage showcase chiller'),
    ('FR2', 'Fridge 2', 'standard refrigerator with freezer section', 'chilled + frozen',
     'chiller: vegetables, mangoes; freezer section: supplemental / extra meat', 225, True,
     'chiller compartment + freezer section', 'UNKNOWN (client gave the unit total only)',
     'previous team research, not measured: about 160-230 L chiller and 65-80 L freezer for 2-door top-freezer '
     'units of this size (e.g. Condura, Panasonic)'),
    ('CH1', 'Chiller 1', 'Fujidenzo upright full chiller', 'chilled',
     'ready-made / portioned ingredients: sliced cucumber, sliced mango, sliced crabsticks, tofu, ginger, '
     'wasabi, tempura pastes', 240, True, 'shelves', '',
     'previous team research: 8.5-14.0 cu ft; e.g. Fujidenzo ISUP-110H'),
    ('CF1', 'Chest Freezer 1', 'chest freezer', 'frozen',
     'uncut / unportioned raw meats, still wrapped in their original plastic', 250, True, 'single open bin', '',
     'previous team research: 9.0-15.0 cu ft; e.g. Fujidenzo IFC-110GDF'),
    ('TF1', 'Tall Freezer 1', 'upright drawer freezer', 'frozen',
     'portioned fish, pork, beef in separate sections / drawers', 198, True, 'drawers per protein (fish / pork / beef)',
     '', 'previous team research: 7.0-11.0 cu ft; e.g. Fujidenzo IUF-70S 198 L'),
    ('DRY', 'Dry storage', 'shelving (not described by the client)', 'ambient',
     'ambient dry goods, sauces, rice, packaging', None, True, '', '', 'not part of the client\'s storage answer'),
]

# ingredient code -> (receipt form, receipt location, stored form, stored location id, ready-to-use location,
#                     provenance of the stored location, basis)
_FISH = ('whole fish, frozen', 'CF1', 'ready-made portions, frozen', 'TF1', 'thawed on the day of use',
         'CLIENT_PROVIDED', 'Q4 whole salmon / tuna arrive; Q1 / O3 processed into portions, only the amount needed '
         'is taken out; Q5 Tall Freezer 1 holds portioned fish. Whole fish before portioning in Chest Freezer 1: '
         'SYNTHETIC_ASSUMPTION')
_PORK_BEEF = ('bulk, frozen, original plastic', 'CF1', 'portions, frozen', 'TF1', 'thawed on the day of use',
              'CLIENT_PROVIDED', 'Q1 meats are portioned once put in the freezer; Q5 Chest Freezer 1 holds unportioned '
              'meat, Tall Freezer 1 portioned pork / beef')
_GROUND = ('bulk, frozen', 'CF1', 'portions, frozen', 'TF1', 'thawed on the day of use', 'CLIENT_PROVIDED',
           'Q2 / O5 bought frozen in bulk, divided into portions and kept frozen; only near-term portions are thawed. '
           'Tall Freezer 1 holds portioned pork / beef (Q5)')
_CHICKEN = ('bulk, frozen, original plastic', 'CF1', 'portions, frozen', 'TF1', 'thawed on the day of use',
            'SYNTHETIC_ASSUMPTION', 'Q1 meats are portioned once put in the freezer; the client names fish / pork / beef '
                                    'drawers only, so the chicken location is assumed')
_PACKED_FROZEN = ('frozen pack', 'CF1', 'frozen pack', 'CF1', 'drawn frozen on the day of use',
                  'SYNTHETIC_ASSUMPTION', 'frozen in its packaging; location not named by the client')
_VEG = ('whole, chilled', 'FR2', 'whole, chilled', 'FR2', 'prepared on the day', 'CLIENT_PROVIDED',
        'Q5 Fridge 2 holds vegetables (item matched by category)')
_CHILLED_UNNAMED = ('chilled', '', 'chilled', '', 'used from the chiller', 'UNKNOWN',
                    'chilled item not named by the client; unit not assigned')
_DRY = ('ambient', 'DRY', 'ambient', 'DRY', 'used from dry storage', 'SYNTHETIC_ASSUMPTION',
        'ambient item; dry storage is not part of the client\'s storage answer')
INGREDIENT_STORAGE = {
    'SAL': _FISH, 'TUN': _FISH,
    'SAS': ('not bought: cut from the whole salmon in-house', 'TF1', 'portions, frozen, with the salmon', 'TF1',
            'thawed on the day of use', 'CLIENT_PROVIDED',
            'owner round 4 (I11): trim is cut from the whole fish; Q5 Tall Freezer 1 holds the portioned fish'),
    'PB': _PORK_BEEF, 'PL': _PORK_BEEF, 'SB': _PORK_BEEF, 'GP': _GROUND, 'GB': _GROUND,
    'CF': _CHICKEN, 'CT': _CHICKEN,
    'SQD': _PACKED_FROZEN[:4] + ('thawed on the day of use',) + _PACKED_FROZEN[5:],
    'PDT': _PACKED_FROZEN[:4] + ('thawed on the day of use',) + _PACKED_FROZEN[5:],
    'EBI': _PACKED_FROZEN, 'EBK': _PACKED_FROZEN, 'GZA': _PACKED_FROZEN,
    'KNI': ('boxed, frozen', 'CF1', 'boxed, frozen', 'CF1', 'sliced crabsticks in Chiller 1', 'CLIENT_PROVIDED',
            'Q5 Chiller 1 holds sliced crabsticks (ready-to-use); boxed frozen stock location assumed (Chest Freezer 1)'),
    'CUC': ('whole, by the kg', 'FR2', 'whole, chilled', 'FR2', 'sliced cucumber in Chiller 1', 'CLIENT_PROVIDED',
            'Q3 bought by the kg; Q5 vegetables in Fridge 2, sliced cucumber in Chiller 1'),
    'MNG': ('whole, by the kg', 'FR2', 'whole, chilled', 'FR2', 'sliced mango in Chiller 1', 'CLIENT_PROVIDED',
            'Q3 bought by the kg; O6 fresh, in the chiller; Q5 mangoes in Fridge 2, sliced mango in Chiller 1'),
    'BEL': _VEG, 'CAB': _VEG, 'CAR': _VEG, 'TOG': _VEG,
    'KAL': ('by the kg, chilled', 'FR2', 'whole fruit, chilled', 'FR2', 'used whole as a garnish', 'SYNTHETIC_ASSUMPTION',
            'produce kept with the vegetables and mangoes (Fridge 2); kalamansi is not named in the storage answer'),
    'MUS': ('small packs, chilled', 'FR2', 'chilled', 'FR2', 'used from the chiller', 'CLIENT_PROVIDED',
            'Q2 "stored in the chiller"; the unit is not named, Fridge 2 (vegetables) assumed'),
    'VMO': ('portion, chilled', 'CH1', 'portion, chilled', 'CH1', 'ready-made portion', 'SYNTHETIC_ASSUMPTION',
            'a ready-made bean-sprout portion; Chiller 1 holds ready-made portions'),
    'TUF': ('block, chilled', 'CH1', 'chilled', 'CH1', 'ready-to-use', 'CLIENT_PROVIDED', 'Q5 Chiller 1 holds tofu'),
    'BSG': ('tub, chilled', 'CH1', 'chilled', 'CH1', 'ready-to-use', 'CLIENT_PROVIDED', 'Q5 Chiller 1 holds ginger'),
    'WAS': ('pack, chilled', 'CH1', 'chilled', 'CH1', 'ready-to-use', 'CLIENT_PROVIDED', 'Q5 Chiller 1 holds wasabi'),
    'B+B': ('dry mix, ambient', 'DRY', 'dry mix, ambient', 'DRY', 'tempura paste in Chiller 1', 'CLIENT_PROVIDED',
            'the dry mix is ambient; Q5 Chiller 1 holds the prepared tempura pastes'),
    'ONI': _DRY[:6] + ('generator keeps onions ambient; the client\'s "vegetables" in Fridge 2 may include them '
                       '(unconfirmed)',),
    'ICT': ('case, ambient', 'DRY', 'bottles, chilled for sale', 'FR1', 'served chilled', 'CLIENT_PROVIDED',
            'Q5 Fridge 1 holds drinks; not a raw ingredient, excluded from ingredient capacity'),
    **{c: _CHILLED_UNNAMED for c in ('EGG', 'TAM', 'CHE', 'MAY', 'MSO', 'NOD', 'ENOD')},
    # round 5: in-house gyoza components
    'GZW': ('frozen pack', 'CF1', 'frozen pack', 'CF1', 'thawed for wrapping', 'SYNTHETIC_ASSUMPTION',
            'wrappers kept frozen in their packs; location not named by the client'),
    'PCH': _VEG, 'GIN': _VEG,
    'GAR': _DRY, 'OYS': _DRY, 'SES': _DRY, 'HON': _DRY, 'SLT': _DRY,
    **{c: _DRY for c in ('NOR', 'SUS', 'RIC', 'SHO', 'OKO', 'TEP', 'TER', 'TSS', 'MZN', 'SOT', 'BAR')},
}
CHILLED_UNNAMED = ('EGG', 'TAM', 'CHE', 'MAY', 'MSO', 'NOD', 'ENOD')


def storage_map():
    """INGREDIENT_STORAGE with the I13 owner keys applied (chicken, unnamed chilled items, onions)."""
    ans = owner_answers()
    m = dict(INGREDIENT_STORAGE)

    def put(code, loc, a, why):
        v = list(m[code])
        v[3], v[5] = loc, a['provenance']
        v[1] = v[1] or loc                  # an item with no receiving location is received where it is stored
        why = a['meta'].get('decision', f'{ROUND3}: {why}')
        v[6] = f'{v[6]}; {why}' if a['status'] == 'ANSWERED' else v[6]
        m[code] = tuple(v)
    for c in ('CF', 'CT'):
        put(c, ans['chicken_storage_location']['value'], ans['chicken_storage_location'], 'owner named the chicken location')
    a = ans['chilled_items_storage_location']
    for c in CHILLED_UNNAMED:
        loc = a['value'].get(c) if isinstance(a['value'], dict) else a['value']
        if loc:
            put(c, loc, a, 'owner named the chiller')
    put('ONI', ans['onion_storage_location']['value'], ans['onion_storage_location'], 'owner named where onions are kept')
    return m

# --- registers --------------------------------------------------------------------------------------------
LOG = [  # id, status, interpretation, applied_to
    ('Q1', 'APPLIED',
     f'Frozen raw fish and meat ({", ".join(RAW_FROZEN)}): frozen, {FROZEN_LIFE_DAYS}-day life '
     '(MODELLED_FROM_CLIENT: the 4-week minimum of "up to 4 weeks+"; not a client number). Thawed portions: '
     f'used within {THAWED_USE_DAYS} day and not refrozen; the kitchen thaws the portions it uses that day, so no '
     'thawed stock is carried overnight. The old 2-day chilled life of salmon / tuna (v1-v3) is withdrawn.',
     'ingredients (storage_type, shelf_life_days, thawed_use_within_days, thaw_policy, shelf_life_provenance); '
     'inventory, inventory_batches, waste regenerated; inventory.qty_thawed; batches / waste storage_state'),
    ('Q2', 'APPLIED',
     'Ground beef / pork: bulk frozen receipt (Chest Freezer 1) -> portioned -> portions kept frozen (Tall Freezer 1) '
     '-> thawed and used within the day; the owner confirmed the freezer (O5). '
     f'Mushrooms: chilled, small packs, {MUSHROOM_LIFE_DAYS}-day life (MODELLED_FROM_CLIENT: "a couple of weeks"). '
     '"Similar ingredients" are not named, so only mushroom changes.',
     'ingredients MUS shelf_life_days; ingredient_storage GP / GB flow; packs unchanged ("bulk" gives no size)'),
    ('Q3', 'APPLIED',
     'Cucumber and mango bought by the kg (order unit kg, base unit g; 1 kg = 1,000 g as bought, 500 usable g at '
     'SUPPLY-UR\'s 50% yield). Mango added to every California maki and kani salad at the owner\'s COSTING grams: '
     f'{MANGO_G_PER_KANI:g} g usable per kani stick (row 655), 30 g on the GrabFood "CALIFORNIA MAKI" (row 590). '
     '2-3 kg a week is a validation signal, not a target. "Until supply lasts and we restock once we run out" and '
     '"quick to buy ... like at groceries": the simulation keeps its reorder-point policy with the SUPPLY-UR supplier '
     '(HI-TOP, filled from the nearest named row); the grocery source and the run-out restock are not modelled (I25).',
     'supplier_item_terms CUC / MNG; recipes (MNG lines, line_provenance, qty_provenance); client_answer_checks'),
    ('Q4', 'RECORDED + CHECK',
     'Weekly restock budget is a range, PHP 5,000-15,000, "depending on when they do the restocking" (restated '
     '2026-10-07; supersedes round 4\'s PHP 25,000 and the interim PHP 10,000-15,000). It is a validation signal: '
     'recipes keep the workbook grams, and the gap is reported (I05). Whole salmon and tuna: PHP 5,000 per fish (a '
     'whole-unit price, not per kg), 1-2 arrivals a month each, outside the weekly budget (O1). Salmon / tuna orders '
     'are one whole fish. No purchase transactions are created from these figures.',
     'supplier_item_terms SAL / TUN; client_parameters; client_answer_checks'),
    ('Q5', 'RECORDED + CHECK',
     'Five units ("3 standard fridges & 1 chest freezer" plus the Tall Freezer the answer goes on to describe), used as '
     'segmented capacity, never one pool. Fridge 1 (drinks, "supposedly 250L", always full) is excluded from '
     'ingredient capacity. Fridge 2: chiller = vegetables and mangoes only, freezer section = extra meat; its split '
     'is UNKNOWN. Chiller 1 = ready-made portioned ingredients; Chest Freezer 1 = uncut meat in its plastic; Tall '
     'Freezer 1 = portioned fish / pork / beef. The other four litre figures come from the follow-up, not the Q5 '
     'text (I22). Round-4 storage answers that contradict this are not applied (I21). Capacities are litres and '
     'stock is grams; no kg-per-litre figure is assumed: the check reports the packing density at which stock would '
     'no longer fit.',
     'storage_locations; ingredient_storage; ingredients.storage_type BSG; client_parameters; client_answer_checks'),
    ('Q6', 'SUPERSEDED (O4)',
     'The client asked to rename squash to SQU, and SQU was applied on 2026-10-06. The owner then confirmed that KAL '
     'is kalamansi (O4): no squash exists in the source, so SQU is retired and ingredient 18 keeps code KAL.',
     'ingredients, recipes, ingredient_suppliers, suppliers.ingredient_codes, supplier_pack_size_check, storage tables'),
    ('O1', 'APPLIED',
     'The PHP 5,000-15,000 is the regular weekly restock budget for all regular ingredients; whole salmon and tuna '
     '(PHP 5,000 each, 1-2 a month) are separate periodic purchases.',
     'client_parameters (budget scope); client_answer_checks C01 / C02 exclude whole fish'),
    ('O2', 'APPLIED',
     'SUPPLY-UR Wastage/ Fluctuation is a trim / yield-loss allowance: stock is held in usable units, a purchased pack '
     'delivers pack x (1 - wastage) usable units, and unit_cost = price / (1 - wastage) (unchanged). Salmon: 55% usable '
     '(MODELLED_FROM_CLIENT, midpoint of "around 50-60%") replaces the sheet\'s 35%. A whole salmon is 5 kg (owner '
     'round 4, I19; was 4.17 kg = PHP 5,000 / SUPPLY-UR PHP 1,200 a kg), so 2,750 usable g a fish at PHP 1.82 a usable '
     'g (COSTING prices salmon at the SUPPLY-UR PHP 3.43; the owner\'s whole-fish answers are used, I25). Yield is an '
     'owner estimate, not a measurement.',
     'supplier_item_terms (usable_fraction, usable_qty_per_pack: the simulation\'s pack); ingredients.unit_cost SAL; '
     'inventory, batches, waste regenerated'),
    ('O3', 'APPLIED',
     'Whole tuna 20 kg (owner working assumption). Usable share: 65% from SUPPLY-UR\'s tuna row at first, replaced '
     'by the owner\'s 50-55% (T3). "Lasts 2-4 weeks" is a validation check, not a target. Only portions are thawed '
     '(thaw rule unchanged).',
     'ingredients.unit_cost TUN; supplier_item_terms TUN; client_answer_checks C19'),
    ('O4', 'APPLIED',
     'KAL is kalamansi: ingredient 18 is "Kalamansi", code KAL (the v1-v3 code). SQU is retired; no squash exists in '
     'any source. 13 recipe lines (MENU2 lines and copies of MENU2 California recipes) stay as kalamansi; the 3 '
     'SYNTHETIC "Crunchy Veggie" lines that used KAL as a squash vegetable are removed (recipe_lines_removed.csv). '
     'Cost PHP 0.10 a g = COSTING PHP 1 per kalamansi / MENU2 "10 gms each".',
     'ingredients; recipes; ingredient_suppliers basis; storage tables; inventory / batches / waste regenerated'),
    ('O5', 'APPLIED', 'Portioned ground beef / pork are kept frozen; this settles the Q2 "refrigerator" wording (I03). '
     'No data change: already modelled frozen.', 'ingredient_storage GP / GB basis; client_answer_issues I03'),
    ('T1', 'APPLIED', "Tuna use outside the POS is modelled at the owner's split: 2.0 kg outside the POS for every 1.0 kg "
     "in POS dishes, applied as that ratio x the month's POS tuna use on open days (MODELLED_FROM_CLIENT: an estimate). "
     'Kept in inventory.qty_off_pos_use, never counted as sales. The cutting-loss part may overlap the 50-55% yield.',
     'simulation; inventory.qty_off_pos_use; client_answer_checks C06 / C07 / C19'),
    ('T2', 'APPLIED', 'Pork Misono (items 126, 128, 380): the TUN 120 g line is removed and pork loin 120 g added '
     '(CLIENT_PROVIDED). Grams per dish were answered by category (30-40 g maki / nigiri, 60-90 g sashimi): MENU2 '
     'grams are kept and compared with the ranges.',
     'recipes; recipe_lines_removed.csv; audit/output_v4/tuna_grams_by_category.csv'),
    ('T3', 'APPLIED', "Tuna usable 52.5% (MODELLED_FROM_CLIENT, midpoint of 50-55%) replaces SUPPLY-UR's 65%: 10,500 "
     'usable g a fish, PHP 0.48 a usable g.', 'supplier_item_terms TUN; ingredients.unit_cost TUN'),
    ('O6', 'APPLIED', 'Shakes use fresh mango: the mango shake / juice lines are confirmed (line_provenance '
     'CLIENT_PROVIDED); round 4 set their grams (180 g shake, 130 g juice, CLIENT_PROVIDED).',
     'recipes line_provenance; client_answer_checks C13'),
    ('R4', 'PARTLY APPLIED',
     'Applied: Tuna Sashimi 100 g (MENU2 row 986 says 120 g; the owner overrides it); cutting loss inside the 50-55% '
     'yield; salmon 5 kg a fish; ground beef 1 kg packs; mango 180 g a shake / 130 g a juice; Salmon Mango Roll 26 g '
     'mango; sashimi trim cut from the whole salmon; onions in dry storage; budget PHP 5,000-15,000 (restated). Not '
     'applied: the weekly kg baselines and the budget calibration (they would replace the workbook\'s MENU2 grams; '
     'checks C23 / I05); chicken in the Chest Freezer, chilled items in Fridge 1 and the 50/50 Fridge 2 split (they '
     'contradict Q5; I21).', 'owner_answers_pending.json; client_parameters owner_*; recipes; storage tables'),
    ('D5', 'APPLIED',
     'Budget baseline PHP 23,000 a week (the recipe figure; checks +/- 10%); 5k-15k recorded, ~49k read as loss. Salmon: '
     '3 a month approved, PHP 2,950 a fish (5 kg x PHP 590, INGREDIENTS.xlsx). Mango: 3.8 kg a week accepted. Ground beef: '
     '4 kg a week as bought logged as staff meals (qty_off_pos_use). Storage litres approved provisionally. MENU2 '
     'duplicate pairs: one row kept, the other hidden. Gyoza: made in-house from REFERENCES (wrapper + filling; pieces a '
     'batch assumed, I27). Pork belly: SUPPLY-UR 55% kept. "Delete or hide two of each pair" is read as hiding the extra '
     'row of each pair: deleting both rows would remove the chicken from Torikatsudon.',
     'client_parameters; client_answer_checks; recipes; ingredients; supplier_item_terms; inventory / batches / waste'),
    ('D6', 'APPLIED',
     'Eggs, tamago, mayo, cheese, miso and fresh noodles stored in Fridge 2 (kitchen side); chicken received whole in Chest '
     'Freezer 1, portions in Tall Freezer 1. HI-TOP is Hi-Top Supermart, a walk-in grocery: lead time 0, always in stock, '
     'emergency runs at the regular price; these terms cover everything bought there. Mango PHP 300 a kg kept. Gyoza: 450 '
     'pieces a batch (~20 g of filling a piece over all listed solids; the team 15 g figure counted cabbage, pechay and pork '
     'only), wrappers PHP 1.00 (50 for PHP 50), ginger 300 g accepted, seasonings as grams (soy sauce 210 g, sesame oil 46 g, '
     'hondashi 50 g, salt 20 g a batch) rather than the 5% buffer, so they are tracked as stock.',
     'ingredient_storage; storage_locations; supplier_term_assumptions; recipes; ingredients; inventory / batches / waste'),
]

ISSUES = [  # id, type, topic, detail, resolution, needs_client, blocking, status, evidence
    ('I01', 'CONTRADICTION', 'frozen shelf life',
     'Previous v4 gave raw frozen fish / meat 30 days ("the life the other meats had"); v1-v3 gave salmon / tuna / '
     'sashimi trim a 2-day chilled life.',
     f'{FROZEN_LIFE_DAYS} days for all 12 raw frozen fish / meat, MODELLED_FROM_CLIENT; expiry, waste and stock '
     'regenerated.', False, False, 'CORRECTED', 'validator SHL-1, SHL-6'),
    ('I02', 'CONTRADICTION', 'thawed state',
     'No thawed state: frozen life applied up to the moment of use.',
     f'thawed_use_within_days = {THAWED_USE_DAYS} and thaw_policy on the 12 items; inventory.qty_thawed = frozen '
     'stock thawed that day; batches / waste carry storage_state. O3 / O5: only the portions needed are thawed.',
     False, False, 'CORRECTED', 'validator INV-2'),
    ('I03', 'CONTRADICTION', 'ground beef / pork storage',
     'Q2 said portions go "in the refrigerator"; Q1 and Q5 put portioned meat in the freezer.',
     'Owner O5: portions are kept frozen. Modelled that way since the first pass; no data change.', False, False,
     'RESOLVED', 'owner O5; validator STO-3'),
    ('I04', 'CONTRADICTION', 'KAL identity',
     'MENU2 labels every KAL line "KALAMANSI 10 gms each (avg)"; makisushi_generator named KAL "Kalabasa (Squash)" by '
     'inference, and Q6 asked to rename squash to SQU. No source mentions squash.',
     'Owner O4: KAL is kalamansi. Ingredient 18 = "Kalamansi", code KAL; SQU retired; 3 SYNTHETIC lines that used it '
     'as a vegetable removed.', False, False, 'RESOLVED', 'owner O4; validator ING-2, REC-5'),
    ('I05', 'VALIDATION_SIGNAL', 'weekly budget',
     'Modelled consumption cost of regular ingredients (real sales x recipes) is ~PHP 23.2k a week (lines from the '
     'owner\'s workbook alone ~18.5k; simulated purchases ~25.3k) against the client\'s PHP 5,000-15,000 (restated '
     '2026-10-07). Duplicate sales, synthetic sales, double-counted ingredients, whole fish and an unusual period are '
     'ruled out (audit/output_v4/budget_trace.csv); regular ingredients cost ~30% of net sales, inside the 28-33% '
     'casual-dining benchmark. The owner\'s own figures disagree with each other: the MENU2 grams (confirmed by the '
     'SUM-SALES25 calculator) cost more than PHP 15,000 a week, while the round-4 weekly baselines (30 kg rice, 18 kg '
     'chicken, ...) would cost ~PHP 49k.',
     'Team decisions 2026-10-07: recipes keep the workbook grams; neither the budget calibration nor the weekly '
     'baselines are applied (owner_answers_pending.json not_applied_because). PHP 5,000-15,000 is a validation signal '
     '(BUD-2 WARN, never forced down; a soft target for the optimization); the baselines are checks C23. To raise with '
     'the owner: which of the three figures describes a normal week.', True, False,
     'OPEN - OWNER FIGURES DISAGREE', 'validator BUD-2 WARN; budget_trace.csv; client_answer_checks C01, C02, C20, C21, '
                                      'C23'),
    ('I06', 'CONTRADICTION', 'Wastage/ Fluctuation semantics; salmon yield',
     'SUPPLY-UR Wastage/ Fluctuation had no stated meaning; at the sheet\'s 35% usable a salmon gave 1,458 usable g.',
     'Owner O2: a trim / yield loss; salmon 50-60% usable (55% used).', False, False, 'RESOLVED',
     'owner O2; validator UNI-3, CST-1'),
    ('I07', 'CONTRADICTION', "tuna use vs the owner's tuna",
     'A 20 kg tuna was taken as 13,000 usable g and recipes use ~150 g a day, so one fish lasted ~87 days against the '
     "owner's 2-4 weeks and ~75% of tuna expired. MENU2 also gave Pork Misono 120 g of tuna and no pork.",
     'Owner round 3 (T1-T3): tuna also goes to staff meals, off-menu specials, comps / catering and cutting loss, about '
     '2.0 kg a week against ~1.0 in POS dishes (modelled as a ratio, kept apart from sales in inventory.qty_off_pos_use); '
     'usable yield 50-55% (52.5% used); Pork Misono is pork loin 120 g. Round 4: the cutting loss is inside the yield, '
     'so the owner\'s last ~0.5 kg is unrecorded use; Tuna Sashimi 100 g. One fish lasts ~26 days, within 2-4 weeks '
     '(TUN-1). Estimates, not measurements.', False, False, 'RESOLVED',
     'owner T1-T3, round 4; validator TUN-1, OFF-1, REC-6'),
    ('I08', 'VALIDATION_SIGNAL', 'mango quantity',
     'All mango is ~3.8 kg a week as bought against Q3\'s 2-3 kg: California maki + kani salad ~1.7 kg at the COSTING '
     'grams (20 g a kani stick, 30 g on the GrabFood roll); shakes / juice at the owner\'s round-4 180 g / 130 g ~2.0 '
     'kg; mango rolls ~0.1 kg. Simulated purchases ~5.3 kg (incl. stock that spoils).',
     'Not tuned. The owner set the shake / juice grams to test whether the high use is over-portioning or spoilage; '
     'the maki and salad lines alone sit below 2 kg. Q3 says mango is "mainly for California maki & kani salads", '
     'which the data does not show while shakes sell at their current rate: raise with the owner.', True, False,
     'OPEN - VALIDATION GAP', 'client_answer_checks C12-C14'),
    ('I09', 'CONTRADICTION', 'Salmon Mango Roll',
     '[MR] Salmon Mango Roll (MENU2) had no mango line, while its SYNTHETIC copy [MR] Tuna Mango Roll has 30 g.',
     'Owner round 4 approved the provisional line: 26 g usable mango per roll (CLIENT_PROVIDED).', False, False,
     'RESOLVED', 'owner round 4; validator REC-4'),
    ('I10', 'CONTRADICTION', 'pack quantity basis',
     'Packs other than salmon / tuna were counted as fully usable.',
     'O2: supplier_item_terms keeps the pack as bought and adds usable_fraction and usable_qty_per_pack, which the '
     'simulation receives.', False, False, 'RESOLVED', 'owner O2; validator UNI-3'),
    ('I11', 'OPEN_QUESTION', 'sashimi trim',
     'SAS was bought as a 250 g pack from FRANCESCO, but ingredient_suppliers said it is cut from salmon and tuna.',
     'Owner round 4: cut from the whole fish in-house, never bought; the 3 SAS lines (MENU2 Super supreme / [PL] Super '
     'Supreme rows 646 / 890, SALMON SKIN) draw on salmon. SAS stays in the ingredient master with no use.', False,
     False, 'RESOLVED', 'owner round 4; validator OWN-1'),
    ('I12', 'OPEN_QUESTION', 'ground beef waste',
     'Ground beef (SYNTHETIC ingredient: no MENU2 line uses GB) is used at ~35 g a week against a 1 kg bulk pack (600 '
     'usable g), so most of each pack expires. The owner says ~4 kg a week (4 packs).',
     'Pack confirmed 1 kg (CLIENT_PROVIDED). The 4 kg a week is not applied: no workbook recipe uses ground beef, so '
     'there is no dish to scale (check C23-GB). Raise with the owner: which dishes use ground beef.', True, False,
     'OPEN - NO RECIPE FOR THE OWNER\'S USE', 'validator OWN-1; client_answer_checks C18, C23-GB'),
    ('I13', 'OPEN_QUESTION', 'storage not named by the client',
     'Chicken location, the chiller for EGG, TAM, CHE, MAY, MSO, NOD, ENOD, onions and Fridge 2\'s split are not named '
     'in Q5.', 'Onions: dry storage (round 4, CLIENT_PROVIDED). The round-4 answers for chicken, the chilled items and '
     'Fridge 2 contradict Q5 and are not applied (I21): chicken TF1 (SYNTHETIC_ASSUMPTION), chilled items unassigned, '
     'Fridge 2 split UNKNOWN.', True, False, 'OPEN (see I21)', 'validator OWN-1, STO-2'),
    ('I14', 'CONTRADICTION', 'emergency buys of whole-fish items',
     'When frozen salmon / tuna ran out the simulation bought the missing grams at once (+25%); the client buys only '
     'whole fish.',
     'Emergency buys of salmon / tuna are whole fish at PHP 5,000 (Config.whole_unit_emergency); what the day does not '
     'use is stocked like a delivery. With I20 fixed, tuna is restocked by planned orders and emergency buys are '
     'genuinely unplanned.', False, False, 'CORRECTED',
     'validator INV-3'),
    ('I15', 'LEGACY', 'v1 documents outside generated_v4',
     'source_to_target_mapping.csv, data_dictionary.csv, run_supplier_scenarios.py / supplier_scenarios.csv and generator '
     'comments describe v1-v3 rules (2-day fish, 30-day frozen, squash, 1 g/mL sauces).',
     'Superseded notes on every old-rule line; LEGACY_SUPERSEDED_BY_V4.md lists what changed.', False, False,
     'LEGACY-CLOSED', 'validator LEG-1'),
    ('I16', 'LEGACY', 'SQL schema',
     'supabase_v3 has one capacity per storage_type and one budget_php.',
     'supabase_v4/ generated from the v4 CSVs by build_v4_sql.py: every column, dim_storage_location, budget_min_php / '
     'budget_max_php, KAL / no SQU, qty_thawed, storage_state and provenance constraints. Not executed (no PostgreSQL '
     'here); staging types checked against every value.', False, False, 'LEGACY-CLOSED', 'validator LEG-1'),
    ('I17', 'CONTRADICTION', 'previous client-answer log',
     'The previous log paraphrased Q2, called the rename a team decision, put onions in Fridge 2 and kept Fridge 2\'s '
     'split as a fit note.', 'Answers quoted verbatim; split UNKNOWN; onions in dry storage; Fridge 1 excluded.', False,
     False, 'CORRECTED', 'client_answers_applied.csv'),
    ('I18', 'CONTRADICTION', 'litre-to-gram packs',
     'SHO, TEP and TSS were stocked in grams but bought in litre bottles at an undocumented 1 g/mL.',
     'Recipes, costs and stock stay in grams (the owner\'s unit); the three litre packs convert at cited densities: soy '
     '1.05 (FSANZ), teppanyaki 1.082 (USDA teriyaki analogue), tempura sauce 1.05 (derived, 3:1:1 tentsuyu).', False,
     False, 'CORRECTED', 'validator UNI-2; client_parameters density_g_per_ml_*'),
    ('I19', 'VALIDATION_SIGNAL', 'salmon whole weight',
     'Whole salmon was taken as 4.17 kg (PHP 5,000 / PHP 1,200 a kg): recipes needed ~3 fish a month vs the owner\'s '
     '1-2.', 'Owner round 4: ~5 kg a fish (CLIENT_PROVIDED; INGREDIENTS.xlsx also lists whole salmon at 5-6 kg). At 55% '
     'usable, the MENU2 salmon lines plus the sashimi trim now cut from salmon still need ~2.7 fish a month (~2.9 '
     'bought) against "once or twice a month". Not tuned; raise with the owner.', True, False,
     'OPEN - VALIDATION GAP', 'client_answer_checks C04, C06, C10'),
    ('I20', 'POLICY_DEFECT', 'reorder trigger ignores expiry',
     'The (R,s,S) trigger compared closing stock + on order with the reorder point, counting stock that expires before '
     'any order could arrive. A 13 kg tuna never fell below the 1.4 kg reorder point by use: 1 planned tuna order in 5.7 '
     'years, and 66 of 72 tuna emergencies on the morning a fish expired. Across all items 80% of emergency spend '
     '(PHP 452k of 568k) followed a known expiry (audit/output_v4/emergency_split.csv).',
     'Team decision 2026-10-06: fix A for tuna only (Config.planned_replacement = TUN): on the last order day whose '
     'delivery arrives by the morning after a fish\'s last usable day, the replacement fish is planned. That last chance '
     'comes earlier before a closure (no orders or deliveries on closed days); the first version missed this and left '
     '2 emergency fish after the Christmas 2021 and Holy Week 2024 closures. A general expiry-aware trigger was rejected '
     '(waste PHP 894k -> 1.52M); fix A with salmon added ~PHP 27k of salmon waste. The remaining expiry-linked '
     'emergencies of other items are small packs and stay as simulated behaviour.', False, False, 'CORRECTED',
     'validator POL-1 (80 planned tuna orders, 0 emergency fish); reorder_fix_preview.csv; reorder_fix_preview_A.csv'),
    ('I21', 'CONTRADICTION', 'round-4 storage answers vs Q5',
     'Round 4 put portioned chicken in the Chest Freezer, eggs / tamago / cheese / mayo / miso / noodles in Fridge 1 '
     'and split Fridge 2 50/50 between bar prep and the sushi line\'s prepped vegetables. Q5: Chest Freezer 1 holds '
     'only uncut meat still in its plastic, portioned meat is in Tall Freezer 1, Fridge 1 holds drinks and is always '
     'full, Fridge 2\'s chiller holds vegetables and mangoes only, prepped ingredients are in Chiller 1.',
     'Team decision 2026-10-07: Q5 wins. The three round-4 answers are recorded as given but not applied '
     '(owner_answers_pending.json not_applied_because): chicken received in Chest Freezer 1, portions in Tall Freezer 1 '
     '(SYNTHETIC_ASSUMPTION); chilled items unassigned; Fridge 1 excluded from ingredient capacity. Raise with the owner.',
     True, False, 'OPEN - OWNER ANSWERS DISAGREE', 'owner_answers_pending.json; ingredient_storage; storage_locations'),
    ('I22', 'OPEN_QUESTION', 'storage litres',
     'Q5 gives a capacity for Fridge 1 only ("supposedly 250L"); Fridge 2 225 L, Chiller 1 240 L, Chest Freezer 1 250 L '
     'and Tall Freezer 1 198 L come from the follow-up (the reference notes show the team\'s model research, e.g. '
     'Fujidenzo IUF-70S 198 L). Q5 also says "3 standard fridges & 1 chest freezer" but describes five units.',
     'Kept as CLIENT_PROVIDED (feasible capacity, follow-up; not stated in Q5) and never enforced; five units modelled '
     'as described. Confirm the four figures with the owner.', True, False, 'OPEN', 'storage_locations.capacity_provenance'),
    ('I23', 'WORKBOOK', 'MENU2 recipe lines',
     'Row-by-row comparison of generated_v4/recipes.csv with makisushi_Jan_2026.xlsx MENU2 (and SUM-SALES25, the '
     'owner\'s calculator for 2026-08-31, which matches the MENU2 grams line for line). The generator kept the last of '
     'two MENU2 rows with the same dish and code, so platters whose column F names separate components lost all but '
     'one; promo Katsudon took the MANAGEMENT pork line; 22 lines filled from a median of blank MENU2 cells were '
     'labelled SOURCE_DERIVED. MENU2 notes with no code or quantity are not modelled: MANGO in (HS) Mixed Sushi & '
     'Sashimi (rows 607 / 613), Onigiri mango (row 981, no POS item), CAMOTE / BEANS / EGGPLANT in Mixed Tempura '
     '(rows 539-541).',
     '12 lines corrected from the workbook (workbook_fixes.MENU2_COMPONENTS; qty_adjusted_by = '
     'workbook:menu2_components): Medium Party Tray kani 5, Seafood Platter salmon 80, Super supreme / supreme / [PL] '
     'Super Supreme kani 3, Mixed Maki Rolls kani 0.75, Special Mixed kani 9, Small Party Tray kani 4, Mixed Sushi & '
     'Sashimi kani 1.5 (2 items), promo Katsudon pork 60 g (2 items). Imputed lines now qty_provenance '
     'SYNTHETIC_ASSUMPTION. Still open with the owner: Torikatsudon CF_060 1 vs 2 (rows 447 / 811), Yakisoba w/ gyoza '
     'GZA 3 vs 1 (rows 455 / 459), Mixed Tempura Regular TSS 60 marked CARROTS vs 30 (rows 536 / 537); the blank '
     'quantities (recipe_review.csv v4_status).', True, False, 'CORRECTED (3 ROW PAIRS OPEN)',
     'recipe_review.csv v4_status; recipes.qty_adjusted_by'),
    ('I24', 'WORKBOOK', 'printed menu prices',
     'menu_items.printed_menu_price came from a parser that missed slash prices (ICED TEA 88/150, SPECIAL KANI SALAD '
     '275/390, VALUE MEALS 695/715), the SMALL / LARGE baked sushi columns, the Mix & Match KANI / EBI TEMPURA columns '
     'and the sashimi, ramen, starters, house specialty and tempura sections, and gave [ST] Gyoza (8pcs) the 4-piece '
     'price 238 and Tonkatsu ala carte the TONKATSU don price.',
     'Rebuilt from an explicit map of every price cell in MAKISUSHI-MENU.xlsx (workbook_fixes.PRINTED; each item '
     'carries its cell in printed_menu_cell): 317 items. Row 108 repeats the EBI TEMPURA label with the kani tempura '
     'prices 210 / 370 / 720 and is read as kani tempura. 12 price cells have no POS item (Chashu don A / B, '
     'Okonomiyaki garlic & cheese sharing, the unnamed row 102, the five SMALL baked sushi, Croffle, Fruity Soda).',
     False, False, 'CORRECTED', 'menu_items.printed_menu_cell'),
    ('I25', 'WORKBOOK', 'owner answers vs the workbooks',
     'Where the owner\'s answers and the workbooks disagree: COSTING / SUPPLY-UR price usable salmon at PHP 3.43 a g and '
     'tuna at PHP 0.80 (v4: PHP 5,000 a whole fish, PHP 1.82 / 0.48 a usable g); INGREDIENTS.xlsx lists whole salmon '
     '(5-6 kg) at PHP 450-590 a kg, i.e. PHP 2,250-3,540 a fish, not PHP 5,000; MENU2 gives Tuna Sashimi 120 g (owner: '
     '100 g) and Pork Misono 120 g of tuna (owner: pork loin); REFERENCES weighs 2.65 kg of frozen pork belly into '
     '1.8 kg of portions (68% usable; SUPPLY-UR wastage 0.45 gives 55%); REFERENCES has an in-house gyoza filling '
     'batch (cabbage, pechay, onion, carrots, ginger, garlic, 0.74 kg ground pork) while v4 buys gyoza (GZA) ready '
     'made; Q3 buys mangoes "like at groceries" while SUPPLY-UR\'s mango row has no supplier (HI-TOP filled from the '
     'nearest row).',
     'The owner\'s explicit answers are applied and the workbook figure is kept beside them (client_parameters, '
     'supply_unit_rates, this register). Tamago now uses COSTING\'s PHP 0.2308 a g (row 610) instead of an assumed '
     '50 g per egg. The gyoza filling, the pork belly yield and the mango source are open with the owner.', True, False,
     'DOCUMENTED (3 OPEN)', 'client_parameters; supply_unit_rates; ingredients.unit_cost TAM'),
    ('I26', 'WORKBOOK', 'sales and payment sheets',
     'All 8,305 SALES\'26 rows are in sales.csv with identical names, quantities, gross, discount, net, category and '
     'date (116,270 cells); none was removed as a duplicate or closure line. clean_sales_v4 had replaced 146 real SKUs '
     'with the item\'s menu SKU and dropped taxes (3 real lines carry tax: rows 1630, 7382, 7693). The export wrote the '
     'lemon emoji as "Lemonadeüçã" (row 4138). PMTT SUM\'s daily sales column equals v4 daily net sales on all 83 days; '
     'its payment columns have the owner\'s own gaps (2026-07-23 PHP 752 short; 2026-08-04 repeats 2026-08-03). '
     'PMNTS BRKDWN has 23 days of 2025 payments: the synthetic history totals PHP 230k on those days against PHP 218k '
     '(within 6%) but is not matched day by day. SUM-SALES25 is the 2026-08-31 pivot (14 items, PHP 4,323).',
     'sales.pos_sku (SALES\'26 column B) and sales.taxes (column M) restored next to the menu SKU; the emoji decoded '
     '("Lemonade🍋"). The backfill is a modelled history and is not tuned to the 23 payment days.', False, False,
     'CORRECTED', 'sales.pos_sku, sales.taxes; audit/audit_sources_v4.py'),
]

IMPACT = [  # answer, file, column / table, before (generated_v4_pre_client_audit), after, applied
    ('Q1', 'ingredients.csv', 'storage_type, shelf_life_days (SAL, TUN, SAS)', 'frozen, 30 d (v1-v3: chilled, 2 d)',
     f'frozen, {FROZEN_LIFE_DAYS} d', 'APPLIED'),
    ('Q1', 'ingredients.csv', 'shelf_life_days (CF, CT, PB, PL, SB, GP, GB, SQD, PDT)', '30 d',
     f'{FROZEN_LIFE_DAYS} d', 'APPLIED'),
    ('Q1', 'ingredients.csv', 'shelf_life_days (EBI, EBK, GZA, KNI)', '90 / 30 / 30 / 30 d', 'unchanged (>= 4 weeks)',
     'NO_CHANGE_NEEDED'),
    ('Q1', 'ingredients.csv', 'thawed_use_within_days, thaw_policy, shelf_life_provenance, shelf_life_basis', '(absent)',
     'new columns', 'APPLIED'),
    ('Q1', 'inventory.csv', 'all quantities; qty_thawed (new)', '30-day expiry',
     'regenerated; qty_thawed = qty_consumed - qty_emergency for the 12 items, else 0', 'REGENERATED'),
    ('Q1', 'inventory_batches.csv', 'expiry_date, days_to_expiry; storage_state (new)', 'received + 29 d',
     f'received + {FROZEN_LIFE_DAYS - 1} d; storage_state from the ingredient', 'REGENERATED'),
    ('Q1', 'waste.csv', 'rows, expiry_date, waste_reason; storage_state (new)', '30-day expiry',
     f'{FROZEN_LIFE_DAYS}-day expiry', 'REGENERATED'),
    ('Q2 / O5', 'ingredients.csv', 'shelf_life_days (MUS)', '14 d (v1-v3: 5 d)', '14 d, MODELLED_FROM_CLIENT', 'APPLIED'),
    ('Q2 / O5', 'ingredient_storage.csv', 'GP, GB flow', '(absent)', 'bulk frozen CF1 -> portions TF1 -> thawed same day',
     'APPLIED'),
    ('Q3', 'supplier_item_terms.csv', 'CUC, MNG order_unit / pack_unit', 'kg / kg', 'kg / kg (500 usable g a kg)',
     'APPLIED'),
    ('Q3', 'recipes.csv', 'MNG lines in 12 California maki + 4 kani salads', '26 g usable per kani stick',
     'same quantity; derivation cites references; provenance columns', 'APPLIED'),
    ('Q3 / O6', 'recipes.csv', 'line_provenance, qty_provenance', '(absent)',
     'on every line; mango shake / juice lines CLIENT_PROVIDED (grams SYNTHETIC)', 'APPLIED'),
    ('Q4 / O1', 'client_parameters.csv', 'budget range and scope, whole-fish price / frequency', '(absent)', 'recorded',
     'RECORDED'),
    ('Q4 / O2', 'supplier_item_terms.csv', 'SAL pack', 'whole fish = 1,458 usable g', 'whole fish = 4,167 g as bought, '
     '55% usable = 2,291.85 g', 'APPLIED'),
    ('Q4 / O3', 'supplier_item_terms.csv', 'TUN pack', 'whole fish = 6,250 usable g', 'whole fish = 20,000 g as bought, '
     '65% usable = 13,000 g', 'APPLIED'),
    ('O2 / O3', 'ingredients.csv', 'unit_cost SAL, TUN', 'PHP 3.4286 / 0.8000 per usable g',
     'PHP 2.1816 / 0.3846 per usable g (PHP 5,000 / usable g a fish)', 'APPLIED'),
    ('O2', 'supplier_item_terms.csv', 'usable_fraction, usable_fraction_provenance, usable_qty_per_pack (new)',
     '(absent; packs counted fully usable)', 'pack x (1 - SUPPLY-UR wastage) for every SUPPLY-UR-priced item',
     'APPLIED'),
    ('O2', 'inventory / inventory_batches / waste', 'all', 'packs counted fully usable', 'regenerated with usable packs',
     'REGENERATED'),
    ('Q4 / O1', 'client_answer_checks.csv, client_budget_diagnosis.csv', 'budget and fish checks', 'spend vs range',
     'recipe-cost view, fish per month, days a tuna lasts', 'CHECK_ONLY'),
    ('Q5', 'storage_locations.csv', 'all', '5 rows; Fridge 2 split as a fit note; Fridge 1 counted',
     '6 rows; split UNKNOWN; counts_toward_raw_ingredient_capacity', 'APPLIED'),
    ('Q5', 'ingredient_storage.csv', 'per-ingredient storage flow', '(absent)', 'new table', 'APPLIED'),
    ('Q5', 'ingredients.csv', 'storage_type (BSG); primary_storage_location (new)', 'chilled (v1-v3: ambient)',
     'chilled; location id', 'APPLIED'),
    ('Q5', 'supabase_v3/01_schema.sql', 'dw.dim_storage, optimization_run.budget_php', 'per storage_type; one budget',
     'unchanged (v3 schema)', 'FLAGGED'),
    ('Q6 / O4', 'ingredients, recipes, ingredient_suppliers, suppliers, supplier_pack_size_check, storage tables',
     'ingredient_code, ingredient_name, category (id 18)', 'SQU "Kalabasa (Squash)" vegetable (v1-v3: KAL)',
     'KAL "Kalamansi" fruit', 'APPLIED'),
    ('O4', 'recipes.csv; recipe_lines_removed.csv (new)', 'KAL lines in items 60, 343, 344', '3 lines, 10 g each',
     'removed and logged', 'APPLIED'),
    # round 3 (before = generated_v4_pre_resolution)
    ('R3 / I18', 'supplier_item_terms.csv', 'pack_size_base; density_g_per_ml, density_provenance (new) for SHO, TEP, TSS',
     '1,800 / 1,000 / 1,800 g (1 g/mL)', '1,890 / 1,082 / 1,890 g (cited densities)', 'APPLIED'),
    ('R3 / I09', 'recipes.csv', 'MNG line on [MR] Salmon Mango Roll', '(absent)', '26 g usable, behind an owner key',
     'PROVISIONAL'),
    ('R3 / I14', 'inventory / inventory_batches / waste', 'emergency buys of SAL, TUN', 'missing grams at +25%',
     'whole fish at PHP 5,000; the rest stocked as a batch', 'REGENERATED'),
    ('R3', 'recipes.csv', 'qty_adjusted_by (new); is_synthetic from provenance', '(absent)',
     'owner:<key> when an owner answer sets a quantity (none yet)', 'APPLIED'),
    ('R3', 'client_parameters.csv', 'owner_answer_status (new); owner_* rows, densities, emergency, scenarios, budget '
     'reading and figures', '(absent)', '19 pending owner keys and their current values', 'APPLIED'),
    ('R3 / I05', 'client_answer_checks.csv', 'C01 / C02 wording; C20 weekly purchase spread; C21 food cost share',
     'spend vs range', 'validation signal with a cited benchmark', 'CHECK_ONLY'),
    ('R3 / I15-I16', 'supabase_v4/ (new); legacy documents', 'schema; superseded notes', 'v3 schema; old rules stated',
     'v4 schema generated from the CSVs; notes on every old-rule line', 'APPLIED'),
    ('T1 / I07', 'inventory.csv', 'qty_off_pos_use (new); tuna qty_consumed includes it', '(absent)',
     'tuna used outside the POS, 2.0 x POS tuna use by month', 'REGENERATED'),
    ('T2 / I07', 'recipes.csv; recipe_lines_removed.csv', 'Pork Misono (126, 128, 380)', 'TUN 120 g', 'PL 120 g',
     'APPLIED'),
    ('T3 / I07', 'supplier_item_terms.csv; ingredients.csv', 'TUN usable_fraction, unit_cost', '0.65; PHP 0.3846 a g',
     '0.525; PHP 0.4762 a g', 'APPLIED'),
    ('R4 / I20', 'inventory / inventory_batches / waste', 'tuna reorder timing (Config.planned_replacement)',
     '1 planned tuna order, 72 emergency fish', 'replacement fish planned at the last order chance before the old one '
     'expires, closures included', 'REGENERATED'),
    # round 4 and the workbook audit (before = generated_v4_pre_round4)
    ('R4 / I19', 'supplier_item_terms.csv; ingredients.csv', 'SAL pack, unit_cost', '4,167 g whole; PHP 2.1816 a g',
     '5,000 g whole, 2,750 usable g; PHP 1.8182 a g', 'APPLIED'),
    ('R4 / I11', 'recipes.csv', 'SAS lines (3)', 'sashimi trim pack', 'moved onto SAL (cut in-house)', 'APPLIED'),
    ('R4 / I08', 'recipes.csv', 'mango shake / juice grams', '150 / 120 g (SYNTHETIC)', '180 / 130 g (CLIENT_PROVIDED)',
     'APPLIED'),
    ('R4 / I07', 'recipes.csv; inventory.csv', 'Tuna Sashimi; tuna use outside the POS', '120 g; cutting loss counted',
     '100 g; cutting loss inside the yield', 'APPLIED'),
    ('R4 / I05', 'recipes.csv', 'weekly baselines, budget calibration', '(none)', 'not applied: workbook grams kept',
     'NOT_APPLIED'),
    ('R4 / I21', 'ingredient_storage.csv; storage_locations.csv', 'chicken, chilled items, Fridge 2 split', 'TF1; '
     'unassigned; UNKNOWN', 'unchanged: the round-4 answers contradict Q5', 'NOT_APPLIED'),
    ('Q4 (2026-10-07)', 'client_parameters.csv', 'weekly_restock_budget_php', 'PHP 5,000-15,000',
     'PHP 5,000-15,000 (restated; round 4 PHP 25,000 and the interim PHP 10,000-15,000 superseded)', 'RECORDED'),
    ('W / I23', 'recipes.csv; recipe_review.csv', '12 MENU2 lines; imputed-line provenance; v4_status',
     'last duplicate row kept; imputed = SOURCE_DERIVED', 'components summed; imputed = SYNTHETIC_ASSUMPTION',
     'APPLIED'),
    ('W / Q3', 'recipes.csv', 'MNG lines in California maki + kani salads', '26 g a kani stick (EXTERNAL_REFERENCE)',
     '20 g a kani stick, 30 g on the GrabFood roll (COSTING rows 655 / 590, SOURCE_DERIVED)', 'APPLIED'),
    ('W / I24', 'menu_items.csv', 'printed_menu_price; printed_menu_cell (new)', '142 items, parser misreads',
     '317 items from an explicit cell map', 'APPLIED'),
    ('W / I26', 'sales.csv; menu_items.csv; item_name_split_review.csv', 'pos_sku, taxes (new); Lemonade name',
     'menu SKU only; no taxes; mis-decoded emoji', 'SALES\'26 SKU and taxes kept; emoji decoded', 'APPLIED'),
    ('W / I25', 'ingredients.csv', 'unit_cost TAM', 'PHP 0.2267 a g (50 g per egg)', 'PHP 0.2308 a g (COSTING row 610)',
     'APPLIED'),
    ('R4 + W', 'inventory / inventory_batches / waste', 'all', 'round-3 recipes and packs', 'regenerated', 'REGENERATED'),
    # round 5 (before = the workbook-audit build of 2026-10-07)
    ('D5 / I05', 'client_parameters.csv; client_answer_checks.csv', 'weekly_restock_budget_php; C01 / C02 / C20',
     'PHP 5,000-15,000 (validation signal)', 'baseline PHP 23,000 +/- 10%; C02 = menu food cost, C02b staff meals', 'APPLIED'),
    ('D5 / I19', 'ingredients.csv; client_parameters.csv', 'SAL unit_cost; salmon price and fish a month',
     'PHP 5,000 a fish (PHP 1.8182 a usable g); 1-2 a month', 'PHP 2,950 (PHP 1.0727 a usable g); up to 3 a month', 'APPLIED'),
    ('D5 / I08', 'client_answer_checks.csv', 'C12-C14 mango', '2-3 kg a week', '3.8 kg a week +/- 10%', 'APPLIED'),
    ('D5 / I12', 'inventory.csv', 'GB qty_off_pos_use', '0', '2.4 kg usable a week (staff meals)', 'REGENERATED'),
    ('D5 / I27', 'ingredients, recipes, supplier_item_terms, ingredient_suppliers, ingredient_storage',
     'GZA lines; GZW, PCH, GAR, GIN, OYS (new)', 'ready-made gyoza GZA', 'wrapper + REFERENCES filling per piece', 'APPLIED'),
    ('D5 / I22', 'storage_locations.csv', 'capacity_provenance', 'follow-up; not stated in Q5', 'approved provisionally',
     'APPLIED'),
    ('D5 / I23', 'recipe_review.csv', 'v4_status of the 3 open duplicate pairs', 'open', 'one row kept, other hidden',
     'APPLIED'),
    ('D5', 'inventory / inventory_batches / waste', 'all', 'workbook-audit build', 'regenerated', 'REGENERATED'),
    # round 6 (before = generated_v4_pre_round6)
    ('D6 / I21', 'ingredient_storage.csv; storage_locations.csv', 'EGG, TAM, CHE, MAY, MSO, NOD, ENOD; CF, CT; FR2 holds',
     'unassigned; TF1 (assumed)', 'FR2; CF1 bulk -> TF1 portions (team decision)', 'APPLIED'),
    ('D6 / I25', 'supplier_term_assumptions.csv', 'HI-TOP terms', 'lead 1 d, fill 0.96, delivery every day',
     'walk-in: lead 0, fill 1.0, no emergency premium', 'APPLIED'),
    ('D6 / I27', 'recipes.csv; ingredients.csv; supplier_item_terms.csv', 'gyoza lines; GZW cost; SES, HON, SLT (new)',
     '~603 pieces a batch, wrapper PHP 1.50, no seasonings', '450 pieces, PHP 1.00, seasonings tracked', 'APPLIED'),
    ('D6', 'inventory / inventory_batches / waste', 'all', 'round-5 build', 'regenerated', 'REGENERATED'),
]


# --- ingredient table ---------------------------------------------------------------------------------
TAMAGO_COSTING_PHP_PER_G = 0.2308      # makisushi_Jan_2026.xlsx COSTING E610 (0.230769...)


def v4_ingredients(ing, rates):
    """ingredients with INGREDIENT_UPDATES and the whole-fish unit costs applied; is_perishable re-derived as the
    generator does."""
    ing = new_ingredient_rows(ing.copy(), rates)          # round 5: in-house gyoza components
    for code, (vals, _) in INGREDIENT_UPDATES.items():
        m = ing['ingredient_code'] == code
        assert m.sum() == 1, code
        for col, v in vals.items():
            ing.loc[m, col] = v
        ing.loc[m, 'is_perishable'] = (ing.loc[m, 'shelf_life_days'] <= 7) | (ing.loc[m, 'category'] == 'dairy')
    for r in fish_basis(rates).itertuples():
        ing.loc[ing['ingredient_code'] == r.ingredient_code, 'unit_cost'] = r.usable_cost_php_per_g
    # workbook audit: COSTING row 610 prices tamago at PHP 0.2308 a g ("6 eggs can produce 390 grams tamago");
    # the generator had assumed 50 g of tamago per egg (PHP 0.2267 a g)
    ing.loc[ing['ingredient_code'] == 'TAM', 'unit_cost'] = TAMAGO_COSTING_PHP_PER_G
    ing.loc[ing['ingredient_code'].isin(PERISHABLE_OVERRIDE), 'is_perishable'] = True
    if owner('onion_storage_location') == 'FR2':          # I13: onions kept in Fridge 2 are chilled stock
        ing.loc[ing['ingredient_code'] == 'ONI', 'storage_type'] = 'chilled'
    return ing


def ingredient_columns(ing):
    """client_answer note, shelf-life provenance, thaw rule and primary storage location per ingredient."""
    code = ing['ingredient_code']
    note = {c: f'{SOURCE}: {why}' for c, (_, why) in INGREDIENT_UPDATES.items()}
    for c in MANUFACTURED_FROZEN:
        note[c] = f'{SOURCE} (no change): Q1 "4 weeks+" is a minimum; this factory-frozen product keeps its longer life'
    note['CUC'] = f'{SOURCE} (no change): Q3 bought by the kilogram; order unit kg already'
    note['MNG'] = (f'{SOURCE}: Q3 bought by the kilogram; added to California maki and kani salads '
                   f'({MANGO_G_PER_KANI:g} g usable per kani stick); {OWNER}: O6 shakes use fresh mango')
    note['KAL'] = f'{OWNER}: {KAL_WHY} (Q6 rename to SQU superseded)'
    note['MUS'] += '; team decision 2026-10-09: perishable although 14 d (flag set by PERISHABLE_OVERRIDE)'
    note['EGG'] = f'{SOURCE} (no change): team decision 2026-10-09: perishable although 21 d (flag set by PERISHABLE_OVERRIDE)'
    for c in ('GP', 'GB'):
        note[c] += f'; Q2 bought frozen in bulk and portioned; {OWNER}: O5 portions kept frozen'
    sal = owner_answers()['salmon_whole_kg']
    sal_g = round(sal['value'] * 1000)
    note['SAL'] += (f'; Q4 bought whole at PHP 5,000 a fish; {OWNER}: O2 about 50-60% usable (55% used); whole fish '
                    + (f'{sal["value"]:g} kg ({ROUND4}: owner standardized the weight)' if sal['status'] == 'ANSWERED'
                       else f'{sal["value"]:.2f} kg from the SUPPLY-UR price')
                    + f'; unit_cost = PHP 5,000 / {round(sal_g * SALMON_USABLE, 2):,} usable g')
    tuna_u = owner_answers()['tuna_usable_fraction']['value']
    note['TUN'] += (f'; Q4 bought whole at PHP 5,000 a fish; {OWNER}: O3 about 20 kg a fish, lasts 2-4 weeks; '
                    f'{ROUND3}: {tuna_u:.1%} usable (owner: 50-55%), unit_cost = PHP 5,000 / {20000 * tuna_u:,.0f} usable g; '
                    'tuna is also used outside the POS (inventory.qty_off_pos_use)')
    prov = pd.Series('SYNTHETIC_ASSUMPTION', index=ing.index)
    basis = pd.Series('generator value (makisushi_generator / synthetic_recipes); no client or source figure',
                      index=ing.index)
    prov[code.isin(RAW_FROZEN + ('MUS',))] = 'MODELLED_FROM_CLIENT'
    basis[code.isin(RAW_FROZEN)] = FROZEN_WHY
    basis[code == 'MUS'] = INGREDIENT_UPDATES['MUS'][1]
    basis[code.isin(MANUFACTURED_FROZEN)] = 'generator value for a factory-frozen product; >= 4 weeks, so ' \
                                           'consistent with Q1 "4 weeks+"'
    basis[code.isin(['CUC', 'MNG'])] += '; consistent with Q3 "spoil easily"'
    basis[code == 'KAL'] = 'generator value (set when KAL was read as squash); plausible for chilled kalamansi'
    thaw = code.isin(RAW_FROZEN)
    loc = code.map({c: v[3] for c, v in storage_map().items()})
    assert loc.notna().all(), f'no storage mapping for {sorted(code[loc.isna()])}'
    return ing.assign(
        shelf_life_provenance=prov, shelf_life_basis=basis,
        thawed_use_within_days=pd.array(np.where(thaw, THAWED_USE_DAYS, pd.NA), dtype='Int64'),
        thaw_policy=np.where(thaw, 'portions thawed on the day of use, in the number used; not refrozen (Q1)', ''),
        primary_storage_location=loc.replace('', pd.NA),
        client_answer=code.map(note))


def off_pos_column(inv, use, ing):
    """inventory.qty_off_pos_use: what the simulation consumed beyond recorded sales x recipes (I07: staff meals,
    specials, comps, trimming). qty_consumed stays total use; POS use = qty_consumed - qty_off_pos_use."""
    pos = use.groupby(['date', 'ingredient_id'])['qty'].sum()
    key = pd.MultiIndex.from_arrays([pd.to_datetime(inv['inventory_date']), inv['ingredient_id']])
    off = (inv['qty_consumed'].to_numpy() - pos.reindex(key).fillna(0).to_numpy()).round(4)
    ids = set(ing.loc[ing['ingredient_code'].isin(list(off_pos_codes())), 'ingredient_id'])
    assert (np.abs(off[~inv['ingredient_id'].isin(ids).to_numpy()]) < 1e-3).all(), 'off-POS use outside the configured items'
    inv = inv.copy()
    inv.insert(inv.columns.get_loc('qty_consumed') + 1, 'qty_off_pos_use',
               np.where(inv['ingredient_id'].isin(ids), np.maximum(off, 0.0), 0.0))
    return inv


def thaw_columns(inv, batches, waste, ing):
    """inventory.qty_thawed (frozen stock drawn and thawed that day); storage_state on batches and waste.
    Gram emergency buys are used at once (not thawed); a whole-fish emergency buy (I14) is stocked like a
    delivery and its portions are thawed, so for salmon / tuna everything consumed was thawed."""
    thaw_ids = set(ing.loc[ing['ingredient_code'].isin(RAW_FROZEN), 'ingredient_id'])
    whole_ids = set(ing.loc[ing['ingredient_code'].isin(WHOLE_UNIT_EMERGENCY), 'ingredient_id'])
    t = inv['ingredient_id'].isin(thaw_ids)
    direct = np.where(inv['ingredient_id'].isin(whole_ids), 0.0, inv['qty_emergency'])
    inv = inv.copy()
    inv.insert(inv.columns.get_loc('qty_consumed') + 1, 'qty_thawed',
               np.where(t, (inv['qty_consumed'] - direct).round(4), 0.0))
    state = ing.set_index('ingredient_id')['storage_type']
    batches = batches.copy()
    batches.insert(batches.columns.get_loc('days_to_expiry') + 1, 'storage_state', batches['ingredient_id'].map(state))
    waste = waste.copy()
    waste.insert(waste.columns.get_loc('waste_reason') + 1, 'storage_state', waste['ingredient_id'].map(state))
    return inv, batches, waste


# --- tables -----------------------------------------------------------------------------------------------
def log_table():
    answers, ans = dict(ANSWERS), owner_answers()
    verb = dict.fromkeys(ans[k]['meta']['owner_answer_verbatim'] for k in ROUND4_KEYS)
    answers['R4'] = ('Owner round 4 follow-ups, 2026-10-07 (one answer per key in owner_answers_pending.json)',
                     ' | '.join(verb))
    src = {'Q': SOURCE, 'T': ROUND3, 'R': ROUND4, 'D5': 'team decision 2026-10-07 (round 5)',
           'D6': 'team decision 2026-10-08 (round 6)'}
    rows = [dict(answer_id=a, question=answers[a][0], client_answer_verbatim=answers[a][1], status=s,
                 interpretation=i, applied_to=t, source=src.get(a, src.get(a[0], OWNER))) for a, s, i, t in LOG]
    return pd.DataFrame(rows)


# Round 5 (team decisions 2026-10-07, after the workbook audit): issue -> (resolution added, needs_client, status)
ROUND5_ISSUES = {
    'I05': ('Round 5 (team decision 2026-10-07): the weekly baseline is the recipe figure, PHP 23,000 (checks read +/- '
            '10% as normal). The client\'s PHP 5,000-15,000 is recorded, not used. The ~PHP 49k implied by the round-4 '
            'weekly kg is read as food leaving beyond the recipes (spoilage, theft or unrecorded staff food): checks C23.',
            False, 'RESOLVED (TEAM BASELINE)'),
    'I08': ('Round 5: ~3.8 kg a week as bought is the accepted level (check C13), with the owner\'s 180 g shakes; the '
            'bar will test a 120-150 g shake. Simulated purchases are higher (~5.3 kg: mango spoils in 5 days, C14).',
            False, 'RESOLVED (TEAM BASELINE)'),
    'I12': ('Round 5: the owner\'s 4 kg a week (as bought) is staff meals / off-menu food, logged as '
            'inventory.qty_off_pos_use (2.4 kg usable a week, Config.off_pos_use_daily) and kept out of menu food cost '
            '(C02; shown in C02b).', False, 'RESOLVED'),
    'I19': ('Round 5: 3 salmon a month approved; a fish costs PHP 2,950 = 5 kg x the supplier list price PHP 590 a kg '
            '(INGREDIENTS.xlsx Squid C11), not the client\'s PHP 5,000 (a different grade, a middleman or misremembered).',
            False, 'RESOLVED (TEAM DECISION)'),
    'I22': ('Round 5: the four figures are approved provisionally so the simulation proceeds; capacity is never '
            'enforced.', False, 'PROVISIONAL'),
    'I23': ('Round 5 (team decision): in each of the three open pairs one row is kept and the other hidden: Torikatsudon '
            'CF_060 x 2 (row 811, as [PR] row 814; row 447 hidden), Yakisoba w/ gyoza GZA 1 (row 459; row 455 hidden), '
            'Mixed Tempura Regular TSS 30 (row 537; row 536, TSS 60 marked CARROTS, hidden).', False, 'CORRECTED'),
    'I25': ('Round 5: gyoza are modelled in-house from REFERENCES (I27); pork belly keeps SUPPLY-UR\'s conservative 55% '
            '(heavy trimming, cooking shrink; a higher kitchen yield is margin); salmon priced from INGREDIENTS.xlsx (I19). '
            'Open: the mango source (Q3 groceries vs the HI-TOP fill).', True, 'DOCUMENTED (1 OPEN)'),
}
ROUND5_NEW = [
    ('I27', 'MODEL_ASSUMPTION', 'in-house gyoza',
     'Round 5 models gyoza as made in-house from makisushi_Jan_2026.xlsx REFERENCES rows 19-31: each piece is one wrapper '
     'plus 1/n of the batch (cabbage 3 kg, Baguio pechay 3 kg, white onion 0.5 kg, carrots 1 kg, ginger 300 g, garlic '
     '0.5 kg, ground pork 0.74 kg, 1 bottle oyster sauce). The sheet does not say how many pieces a batch makes, the '
     'ginger is marked "???", and kikkoman, sesame, hondashi and salt have no amount. SUPPLY-UR\'s Gyoza Wrapper row has '
     'no price or pack size. Labour is not modelled.',
     f'n = 9.04 kg / {GYOZA_FILLING_G_PER_PIECE:g} g of filling a piece = {GYOZA_PIECES_PER_BATCH:.1f} pieces '
     '(SYNTHETIC_ASSUMPTION); wrapper PHP 1.50, 50 a pack (SYNTHETIC_ASSUMPTION); pechay and garlic at their SUPPLY-UR '
     'usable rates, ginger and oyster sauce from COSTING rows 27 / 19; the 4 seasonings left out. New ingredients GZW, '
     'PCH, GAR, GIN, OYS; the ready-made GZA lines are logged in recipe_lines_removed.csv. Confirm pieces a batch and the '
     'wrapper price with the kitchen.', True, False, 'OPEN - KITCHEN FIGURES', 'client_parameters gyoza_*; recipes '
                                                                               'REFERENCES:gyoza'),
]


ROUND6_ISSUES = {
    'I13': ('Round 6 (team decision 2026-10-08): chilled items in Fridge 2; chicken whole in Chest Freezer 1, portions '
            'in Tall Freezer 1.', False, 'RESOLVED (TEAM DECISION)'),
    'I21': ('Round 6 (team decision 2026-10-08): Fridge 1 stays drinks / front of house; the chilled items go to Fridge 2 '
            '(the kitchen side); chicken is received whole in Chest Freezer 1 and portioned into Tall Freezer 1, which '
            'reads the round-4 "chest freezer" as the bulk stage. The 50/50 Fridge 2 split stays unrecorded (no capacity '
            'effect: capacity is not enforced).', False, 'RESOLVED (TEAM DECISION)'),
    'I25': ('Round 6: mango and cucumber come from Hi-Top Supermart, a walk-in grocery a few blocks away, so Q3 ("like '
            'at groceries") and the HI-TOP fill agree; PHP 300 a kg kept.', False, 'DOCUMENTED'),
    'I27': ('Round 6 (team decision 2026-10-08): 450 pieces a batch, wrappers PHP 1.00 (50 for PHP 50), the 300 g ginger '
            'accepted, seasonings 200 ml soy sauce, 50 ml sesame oil, 50 g hondashi, 20 g salt a batch (new SES, HON, SLT; '
            'salt priced at an assumed PHP 30 a kg). These are team figures, not a kitchen count; 450 pieces over 9.04 kg '
            'of listed solids is ~20 g a piece.', False, 'RESOLVED (TEAM FIGURES)'),
}


def issues_table():
    rows = []
    for r in ISSUES + ROUND5_NEW:
        r = list(r)
        for upd in (ROUND5_ISSUES, ROUND6_ISSUES):
            if r[0] in upd:
                add, needs, status = upd[r[0]]
                r[4], r[5], r[7] = f'{r[4]} {add}', needs, status
        rows.append(r)
    return pd.DataFrame(rows, columns=['issue_id', 'type', 'topic', 'detail', 'resolution', 'needs_client',
                                       'blocking', 'status', 'evidence'])


def impact_table():
    return pd.DataFrame(IMPACT, columns=['answer_id', 'file', 'column_or_table', 'before', 'after', 'applied'])


def removed_lines_table(dropped):
    return dropped.assign(source=np.select([dropped['removed_because'] == DROP_WHY,
                                            dropped['removed_because'] == GYOZA_REMOVED_WHY],
                                           [OWNER, 'team decision 2026-10-07 (round 5)'], ROUND3))


def storage_table():
    t = pd.DataFrame(STORAGE_LOCATIONS, columns=[
        'storage_location_id', 'location', 'unit_type', 'temperature_state', 'holds', 'capacity_l',
        'counts_toward_raw_ingredient_capacity', 'compartments', 'compartment_capacity_l', 'reference_note'])
    t['capacity_l'] = t['capacity_l'].astype('Int64')
    # Q5 states a capacity for Fridge 1 only ("supposedly 250L"); the other litres are the feasible capacities from the
    # follow-up, not in the Q5 text (I22)
    t['capacity_provenance'] = np.select(
        [t['storage_location_id'].eq('FR1'), t['capacity_l'].notna()],
        ['CLIENT_PROVIDED (Q5: "supposedly 250L")', 'CLIENT_PROVIDED (feasible capacity, follow-up; not stated in Q5; approved provisionally, team decision 2026-10-07)'],
        'UNKNOWN')
    t['reference_note'] = np.where(t['reference_note'].str.startswith('previous team research'),
                                   'EXTERNAL_REFERENCE, not measured: ' + t['reference_note'], t['reference_note'])
    t['capacity_enforced_in_simulation'] = False
    ans = owner_answers()
    a = ans['fridge2_compartments_l']
    if a['status'] == 'ANSWERED':               # I13: owner gives Fridge 2's chiller / freezer litres
        t.loc[t['storage_location_id'] == 'FR2', 'compartment_capacity_l'] = \
            f'chiller {a["value"]["chiller"]} L, freezer {a["value"]["freezer"]} L (CLIENT_PROVIDED, {ROUND3})'
    a = ans['fridge2_use_split']
    if a['status'] == 'ANSWERED':               # I13 round 4: the owner splits Fridge 2 by use, not by compartment
        fr2 = t['storage_location_id'] == 'FR2'
        t.loc[fr2, 'compartments'] = t.loc[fr2, 'compartments'] + '; shared by use: ' + ', '.join(
            f'{k.replace("_", " ")} {v:.0%}' for k, v in a['value'].items()) + f' (CLIENT_PROVIDED, {ROUND4})'
    a = ans['chilled_items_storage_location']
    if a['status'] == 'ANSWERED' and 'FR1' in (a['value'].values() if isinstance(a['value'], dict) else [a['value']]):
        fr1 = t['storage_location_id'] == 'FR1'     # I13 round 4: chilled ingredients share Fridge 1 with the drinks
        t.loc[fr1, 'holds'] = (t.loc[fr1, 'holds'] + '; chilled ingredients (dairy: eggs, tamago, mayo, cheese; miso; '
                               f'fresh noodles) per the owner ({ROUND4})')
        t.loc[fr1, 'counts_toward_raw_ingredient_capacity'] = True
    if a['status'] == 'ANSWERED' and 'FR2' in (a['value'].values() if isinstance(a['value'], dict) else [a['value']]):
        fr2 = t['storage_location_id'] == 'FR2'     # round 6: the line's chilled ingredients are in Fridge 2's chiller
        t.loc[fr2, 'holds'] = (t.loc[fr2, 'holds'] + '; chiller also: eggs, tamago, mayo, cheese, miso, fresh noodles '
                               '(team decision 2026-10-08: kept on the kitchen side, Fridge 1 is drinks / front of house)')
    assert t['capacity_l'].sum() == 1163
    return t


def ingredient_storage_table(ing):
    rows = []
    smap = storage_map()
    for r in ing.itertuples():
        recv_form, recv_loc, form, loc, ready, prov, basis = smap[r.ingredient_code]
        rows.append(dict(ingredient_id=r.ingredient_id, ingredient_code=r.ingredient_code,
                         ingredient_name=r.ingredient_name, storage_type=r.storage_type,
                         receipt_form=recv_form, receipt_location=recv_loc or pd.NA, stored_form=form,
                         stored_location=loc or pd.NA, ready_to_use=ready,
                         thawed_use_within_days=r.thawed_use_within_days, location_provenance=prov, basis=basis))
    out = pd.DataFrame(rows)
    # Fridge 1's drinks are not raw ingredients; chilled ingredients the owner placed there (round 4) are
    out['counts_toward_raw_ingredient_capacity'] = out['stored_location'].ne('FR1') | (
        out['location_provenance'].eq('CLIENT_PROVIDED') & out['ingredient_code'].isin(CHILLED_UNNAMED))
    return out


FOOD_COST_BENCHMARK = (0.28, 0.33, 'https://kitchensync.us/blog/restaurant-finance/restaurant-food-cost')


# Team decision 2026-10-07 (round 5): the weekly baseline is the recipe figure, ~PHP 23k (C02 on the workbook grams).
# The client's PHP 5,000-15,000 is recorded but not the baseline; the round-4 ~PHP 49k (weekly kg baselines) is read as
# loss beyond the recipes (spoilage, theft or unrecorded staff food). Checks compare against baseline +/- tolerance.
BUDGET_BASELINE_PHP, BUDGET_TOLERANCE = 23000, 0.10
# Team decision 2026-10-07: mango ~3.8 kg a week as bought is the accepted level (owner's 180 g shakes), not Q3's 2-3 kg
MANGO_BASELINE_KG, MANGO_TOLERANCE = 3.8, 0.10


def budget_range():
    """(min, max) PHP a week the checks read as normal: the team baseline +/- the tolerance."""
    return (round(BUDGET_BASELINE_PHP * (1 - BUDGET_TOLERANCE), 2), round(BUDGET_BASELINE_PHP * (1 + BUDGET_TOLERANCE), 2))


def client_budget_range():
    """(min, max) PHP a week the client stated (Q4, restated 2026-10-07)."""
    return tuple(owner_answers()['weekly_budget_php']['value'])


def parameters_table(fish, storage, budget=None, calibration=None):
    """Every client figure and modelling value, with provenance: the optimization's input register.
    budget: {'consumption', 'purchases'} PHP a week (real POS window, regular ingredients) from the checks;
    calibration: the budget calibration factor on recipe quantities (None when not calibrated)."""
    P = []

    def add(name, value, vmin, vmax, unit, prov, src, interp, used, enforced, status=''):
        P.append(dict(parameter=name, value=value, value_min=vmin, value_max=vmax, unit=unit, provenance=prov,
                      source=src, interpretation=interp, used_in=used, enforced_in_simulation=enforced,
                      owner_answer_status=status))
    add('frozen_shelf_life_days', FROZEN_LIFE_DAYS, None, None, 'days', 'MODELLED_FROM_CLIENT', 'Q1',
        '"up to 4 weeks+"; the 4-week minimum. The client gave no exact number', f'ingredients ({len(RAW_FROZEN)} raw '
        'frozen fish / meat); batch expiry; waste', True)
    add('thawed_use_within_days', THAWED_USE_DAYS, None, None, 'days', 'MODELLED_FROM_CLIENT', 'Q1, O3, O5',
        'meat: stated ("take out a few portions to thaw and use within the day"); fish: thawed portions should not go '
        'back in the freezer, same-day use assumed (USDA FSIS: 1-2 days after refrigerator thawing)',
        'ingredients.thawed_use_within_days; inventory.qty_thawed', True)
    add('mushroom_shelf_life_days', MUSHROOM_LIFE_DAYS, None, None, 'days', 'MODELLED_FROM_CLIENT', 'Q2',
        '"to last us a couple of weeks"', 'ingredients MUS', True)
    add('cucumber_mango_order_unit', 'kg', None, None, '', 'CLIENT_PROVIDED', 'Q3', 'base unit g; 1 kg = 1,000 g',
        'supplier_item_terms CUC, MNG', True)
    add('cucumber_mango_kg_per_week', None, 2, 3, 'kg / week', 'CLIENT_PROVIDED', 'Q3, O6',
        '"around 2-3 kg per week is consumed"; mango is used in maki, kani salad and shakes (O6)',
        'client_answer_checks (validation)', False)
    add('mango_usable_g_per_kani_stick', MANGO_G_PER_KANI, 20.0, 30.0, 'g usable', 'SOURCE_DERIVED', MANGO_SOURCES,
        'COSTING prices mango at the usable rate, so its grams are usable: 20 g on the dine-in California Maki (row '
        '655), 30 g on the GrabFood CALIFORNIA MAKI (row 590, used for that listing)', 'recipes (MNG lines)', True)
    lo, hi = budget_range()
    clo, chi = client_budget_range()
    reading = owner_answers()['weekly_budget_reading']
    calibrated = reading['value'] == 'calibration_target'
    assert not calibrated, 'the budget calibration was withdrawn 2026-10-07'
    add('weekly_restock_budget_php', BUDGET_BASELINE_PHP, lo, hi, 'PHP / week', 'DERIVED',
        'team decision 2026-10-07 (round 5): the recipe figure, modelled consumption cost on the workbook grams (C02)',
        f'the weekly baseline for regular ingredients (whole salmon / tuna excluded): what the menu should cost; checks '
        f'read +/- {BUDGET_TOLERANCE:.0%} as normal. Not a cap', 'client_answer_checks C01, C02, C20; validator BUD-2; '
        'optimization: the weekly budget', False)
    add('weekly_restock_budget_php_client_stated', None, clo, chi, 'PHP / week', 'CLIENT_PROVIDED',
        'Q4, O1 (restated 2026-10-07)', '"around 5k to 15k ... depending on when they do the restocking"; not the '
        'baseline (team decision 2026-10-07: below what the recipes cost)', 'documentation', False)
    add('weekly_cost_implied_by_owner_kg_baselines_php', 49000, None, None, 'PHP / week', 'DERIVED',
        'owner round 4 weekly kg (30 kg rice, 18 kg chicken, 12 kg pork, 8 kg beef, 4 kg ground beef) x unit_cost',
        'about twice the recipe figure: read as food leaving beyond the recipes (spoilage, theft or unrecorded staff '
        'food), not as a budget (team decision 2026-10-07); checks C23', 'documentation; client_answer_checks C23', False)
    add('weekly_restock_budget_reading', 'baseline', None, None, 'ceiling | validation_signal | baseline',
        'SYNTHETIC_ASSUMPTION', 'team decision 2026-10-07 (round 5)',
        'cost outside the baseline band is a WARN to investigate, never forced down; recipes keep the workbook grams',
        'validator BUD-2; optimization_run.budget_reading', False)
    add('mango_kg_per_week_baseline', MANGO_BASELINE_KG, round(MANGO_BASELINE_KG * (1 - MANGO_TOLERANCE), 2),
        round(MANGO_BASELINE_KG * (1 + MANGO_TOLERANCE), 2), 'kg / week as bought', 'DERIVED',
        'team decision 2026-10-07 (round 5): accept the modelled ~3.8 kg (check C13)',
        'all mango lines, with the owner\'s 180 g shake / 130 g juice; Q3\'s 2-3 kg is not the baseline. A 120-150 g '
        'shake test with the bar is planned; until then the simulation orders for this level',
        'client_answer_checks C13, C14', False)
    if calibration is not None:
        add('budget_calibration_factor', round(calibration, 6), None, None, 'x recipe quantity', 'MODELLED_FROM_CLIENT',
            f'{ROUND4}; I05', f'one factor on every regular-ingredient recipe quantity no owner answer set (MENU2, '
            f'name-matched, team and reference grams), so real POS sales x recipes x unit_cost = PHP '
            f'{budget_target():,.0f} a week ({BUDGET_CALIBRATION_AT:.0%} of the way through the owner\'s range); whole '
            'salmon / tuna and owner-stated grams are not scaled',
            'recipes (qty_adjusted_by = calibrated:weekly_budget_php)', True)
    if budget:
        add('modelled_consumption_cost_php_per_week', round(budget['consumption']), None, None, 'PHP / week', 'DERIVED',
            'inventory.qty_consumed x unit_cost, real POS window, regular ingredients',
            'ingredient cost of what real sales used (sales x recipes); not cash purchases: purchase timing and stock '
            'carried between weeks differ', 'client_answer_checks C02', False)
        add('simulated_purchases_php_per_week', round(budget['purchases']), None, None, 'PHP / week', 'SIMULATION',
            'inventory.qty_received x unit_cost + emergency buys, real POS window, regular ingredients',
            'what the simulated kitchen bought, including stock later wasted', 'client_answer_checks C01', False)
    add('food_cost_benchmark_share', None, FOOD_COST_BENCHMARK[0], FOOD_COST_BENCHMARK[1], 'share of net sales',
        'EXTERNAL_REFERENCE', FOOD_COST_BENCHMARK[2], 'typical food cost for full-service casual dining; a benchmark, '
        'not a Makisushi figure', 'client_answer_checks C21', False)
    add('supply_ur_wastage_fluctuation_meaning', 'trim / yield loss', None, None, '', 'CLIENT_PROVIDED', 'O2',
        'an allowance for trim / yield loss, not a price buffer: usable = bought x (1 - wastage)',
        'supplier_item_terms.usable_fraction; ingredients.unit_cost', True)
    for r in fish.itertuples():
        name = 'salmon' if r.ingredient_code == 'SAL' else 'tuna'
        c = r.ingredient_code
        prov, why = WHOLE_FISH_PRICE_SOURCE[c]
        lo, hi = WHOLE_FISH_PER_MONTH[c]
        add(f'whole_{name}_price_php_per_fish', int(r.client_price_php_per_fish), None, None, 'PHP / fish', prov,
            why, 'a whole-unit price, not per kg', 'ingredients.unit_cost; emergency whole-fish buys', True)
        if WHOLE_FISH_PHP[c] != WHOLE_FISH_PHP_CLIENT[c]:
            add(f'whole_{name}_price_php_per_fish_client_stated', WHOLE_FISH_PHP_CLIENT[c], None, None, 'PHP / fish',
                'CLIENT_PROVIDED', 'Q4, O1', 'the client\'s "5k each"; not used (team decision 2026-10-07: a different '
                'grade, a middleman or misremembered)', 'documentation', False)
        add(f'whole_{name}_arrivals_per_month', None, lo, hi, 'fish / month',
            'CLIENT_PROVIDED' if c == 'TUN' else 'SYNTHETIC_ASSUMPTION',
            'Q4' if c == 'TUN' else 'team decision 2026-10-07 (Q4 said once or twice a month)',
            '"once or twice a month"' if c == 'TUN' else 'up to 3 a month approved: the MENU2 salmon lines need ~2.7',
            'client_answer_checks (validation)', False)
        add(f'whole_{name}_spend_php_per_month', None, lo * WHOLE_FISH_PHP[c], hi * WHOLE_FISH_PHP[c], 'PHP / month',
            'DERIVED', 'price x fish a month', f'PHP {WHOLE_FISH_PHP[c]:,} x {lo}-{hi} fish',
            'client_answer_checks (validation)', False)
        add(f'{name}_supply_ur_price_php_per_kg', round(r.supply_ur_price_php_per_kg, 2), None, None, 'PHP / kg',
            'SOURCE_DERIVED', f'SUPPLY-UR row {r.supply_ur_row} ({r.supply_ur_product})', 'owner\'s price list',
            'salmon whole weight' if name == 'salmon' else 'documentation (cost comes from the whole-fish price)',
            name == 'salmon')
        sal_owner = name == 'salmon' and r.whole_g_provenance == 'CLIENT_PROVIDED'
        add(f'{name}_whole_g_per_fish', int(r.whole_g_per_fish), None, None, 'g', r.whole_g_provenance,
            (f'{ROUND4}; I19' if sal_owner else 'Q4 + SUPPLY-UR') if name == 'salmon' else 'O3',
            ('owner: whole salmon average 4.5-5 kg a fish, standardized at 5 kg (the earlier 10 kg was a two-fish order); '
             'at PHP 5,000 a fish this implies PHP 1,000 a kg, not the price sheet\'s PHP 1,200' if sal_owner else
             'PHP 5,000 / SUPPLY-UR price per kg (team choice; the owner\'s 10 kg was an example)') if name == 'salmon'
            else '"around 20 kg per whole tuna as a reasonable working assumption"; an estimate',
            'supplier_item_terms.pack_size_base', True)
        tuna_owner = name == 'tuna' and r.usable_fraction_provenance != 'SOURCE_DERIVED'
        add(f'{name}_usable_fraction', r.usable_fraction,
            SALMON_USABLE_RANGE[0] if name == 'salmon' else (0.50 if tuna_owner else None),
            SALMON_USABLE_RANGE[1] if name == 'salmon' else (0.55 if tuna_owner else None),
            'fraction', r.usable_fraction_provenance,
            'O2' if name == 'salmon' else (f'T3, {ROUND3}' if tuna_owner else f'SUPPLY-UR row {r.supply_ur_row}'),
            '"around 50-60%"; the midpoint; an estimate, not a measured yield' if name == 'salmon' else
            ('"about 50-55% of the whole fish, not 65%"; the midpoint; an estimate, not a measured yield' if tuna_owner
             else f'1 - wastage {r.supply_ur_wastage_fluctuation:g} of SUPPLY-UR "{r.supply_ur_product}"; no owner figure'),
            'supplier_item_terms.usable_fraction', True)
        add(f'{name}_usable_g_per_fish', r.usable_g_per_fish, None, None, 'g', 'DERIVED', 'whole g x usable fraction',
            '', 'supplier_item_terms.usable_qty_per_pack (the simulation\'s pack)', True)
        add(f'{name}_usable_cost_php_per_g', r.usable_cost_php_per_g, None, None, 'PHP / usable g', 'DERIVED',
            'PHP 5,000 / usable g a fish', '', 'ingredients.unit_cost', True)
    add('tuna_days_per_fish', None, *TUNA_DAYS_PER_FISH, 'days', 'CLIENT_PROVIDED', 'O3',
        '"around 2-4 weeks, depending on sales volume"', 'client_answer_checks C19 (validation)', False)
    for r in storage.itertuples():
        if pd.notna(r.capacity_l):
            add(f'capacity_l_{r.storage_location_id}', int(r.capacity_l), None, None, 'L', 'CLIENT_PROVIDED',
                'Q5' if r.storage_location_id == 'FR1' else 'follow-up (Q5 names the unit, not its litres; I22)',
                f'{r.location}: {r.holds}' + ('' if r.counts_toward_raw_ingredient_capacity
                                               else '; EXCLUDED from ingredient capacity'),
                'storage_locations; optimization storage constraint (per location)', False)
    add('capacity_l_FR2_chiller_vs_freezer', 'UNKNOWN', None, None, 'L', 'UNKNOWN', 'Q5',
        'Q5: chiller = vegetables and mangoes only, freezer section = extra meat; only the 225 L unit total is known; '
        '160-230 / 65-80 L is reference, not measured', 'storage_locations', False)
    add('capacity_l_total_physical', int(storage['capacity_l'].sum()), None, None, 'L', 'DERIVED', 'Q5',
        'sum of the five units; NOT one interchangeable constraint', 'documentation', False)
    raw = storage.loc[storage['counts_toward_raw_ingredient_capacity'] & storage['capacity_l'].notna(), 'capacity_l']
    add('capacity_l_cold_ingredient_units', int(raw.sum()), None, None, 'L', 'DERIVED', 'Q5',
        'Fridge 2 + Chiller 1 + Chest Freezer 1 + Tall Freezer 1 (Fridge 1 excluded); use per location, not pooled',
        'documentation', False)
    add('packing_density_kg_per_l', 'UNKNOWN', None, None, 'kg / L', 'UNKNOWN', '',
        'no litres-per-gram data; not assumed. client_answer_checks reports the break-even density per location',
        'storage capacity check', False)
    # round 3
    for code, (dens, prov, basis) in SAUCE_DENSITY.items():
        add(f'density_g_per_ml_{code}', dens, None, None, 'g / mL', prov, basis,
            'converts the litre bottle (SYNTHETIC v1 pack) to grams; recipes, costs and stock stay in grams (I18)',
            'supplier_item_terms.pack_size_base', True)
    add('whole_fish_emergency_unit', 'whole fish', None, None, '', 'CLIENT_PROVIDED', 'Q4, O2, O3',
        'salmon / tuna are bought only as whole fish, so an emergency buy is whole fish too; the rest is stocked (I14)',
        'simulation (Config.whole_unit_emergency); inventory.qty_emergency', True)
    add('whole_fish_emergency_premium', WHOLE_UNIT_EMERGENCY_PREMIUM, None, None, 'fraction', 'SYNTHETIC_ASSUMPTION',
        'Q4 "PHP 5,000 each"', 'an emergency fish costs the regular PHP 5,000; other emergency buys keep the '
        'SYNTHETIC 25% premium', 'inventory.emergency_cost_php', True)
    r_off = off_pos_use_ratio().get('TUN')
    a_off = owner_answers()['tuna_use_outside_pos']
    add('tuna_off_pos_use_ratio', r_off, None, None, 'kg outside the POS per kg in POS dishes', a_off['provenance'],
        f'{ROUND3}, {ROUND4}; I07', 'owner split, kg a week: POS dishes ~1.0; staff meals and trimmings, off-menu '
        'specials, comps / tasting / catering, unrecorded use ~0.5 each. Applied as ratio x POS tuna use in the same '
        'month, on open days. Round 4: the cutting loss (bloodline / skin) is inside the 50-55% yield, not counted '
        'again; the owner\'s "cutting loss and unrecorded" ~0.5 is kept as unrecorded use, the reading that matches '
        '"a fish lasts about 25 days"', 'simulation (Config.off_pos_use_ratio); inventory.qty_off_pos_use', True)
    add('ground_beef_staff_meals_kg_per_week', GB_STAFF_MEALS_KG_BOUGHT_PER_WEEK, None, None, 'kg / week as bought',
        'MODELLED_FROM_CLIENT', 'owner round 4 (I12) "4 packs (4 kg) per week"; team decision 2026-10-07 (round 5)',
        f'staff meals / off-menu: no workbook recipe uses ground beef. {off_pos_use_daily()["GB"]:g} usable g per open '
        f'day (x {GB_USABLE_FRACTION:g} usable, SUPPLY-UR row 51); kept out of menu food cost (C02), shown in C02b',
        'simulation (Config.off_pos_use_daily); inventory.qty_off_pos_use', True)
    add('gyoza_pieces_per_batch', GYOZA_PIECES_PER_BATCH, None, None, 'pieces a batch', 'SYNTHETIC_ASSUMPTION',
        'team decision 2026-10-08 (round 6)', 'set as "about 6,740 g of filling / 15 g" (cabbage, pechay and pork only); '
        f'over all the listed solids (9.04 kg) that is {GYOZA_FILLING_G_PER_PIECE:g} g of filling a piece. Not a kitchen '
        'count', 'recipes (REFERENCES:gyoza lines)', True)
    add('gyoza_filling_g_per_piece', GYOZA_FILLING_G_PER_PIECE, None, None, 'g filling a piece', 'DERIVED',
        'listed solids / gyoza_pieces_per_batch', '', 'documentation', False)
    add('gyoza_batch', json.dumps(GYOZA_BATCH), None, None, 'g (OYS: bottles) a batch', 'SOURCE_DERIVED',
        'makisushi_Jan_2026.xlsx REFERENCES rows 20-31; seasoning grams: team decision 2026-10-08',
        'vegetables, ginger (300 g accepted though marked "???"), garlic, pork, oyster sauce from the sheet; SHO 210 g '
        '(200 ml Kikkoman), SES 46 g (50 ml sesame oil), HON 50 g, SLT 20 g are team-set standard ratios '
        '(SYNTHETIC_ASSUMPTION)', 'recipes (REFERENCES:gyoza lines)', True)
    add('pork_belly_usable_fraction', 0.55, None, None, 'fraction', 'SOURCE_DERIVED',
        'SUPPLY-UR row 42 (Wastage/ Fluctuation 0.45); team decision 2026-10-07 (round 5)',
        'the conservative yield is kept: REFERENCES rows 3-15 weigh 2.65 kg frozen into 1.8 kg of portions (68%), but '
        'pork belly needs heavy trimming and shrinks when cooked; a higher kitchen yield is a margin buffer',
        'supplier_item_terms.usable_fraction PB; ingredients.unit_cost PB', True)
    add('planned_replacement_items', ', '.join(PLANNED_REPLACEMENT), None, None, 'ingredient codes', 'SYNTHETIC_ASSUMPTION',
        'team decision 2026-10-06 (I20)', 'on the last order day whose delivery still arrives by the morning after a '
        'pack\'s last usable day (earlier before a closure), a replacement is planned instead of an emergency buy '
        'after it expires', 'simulation (Config.planned_replacement)', True)
    for k, choices in SCENARIOS.items():
        add(k, SCENARIO[k], None, None, ' | '.join(choices), 'SIMULATION', 'run_v4_scenarios.py',
            'analysis switch; the dataset is always built with the first choice', 'scenario runs only', False)
    for k, a in owner_answers().items():
        v = a['value']
        add(f'owner_{k}', json.dumps(v) if isinstance(v, (dict, list)) else v, None, None, a['meta']['unit'],
            a['provenance'], f'owner rounds 3-4 (owner_answers_pending.json); {a["meta"]["issue"]}',
            a['meta']['question'] + (f' NOT APPLIED: {a["meta"]["not_applied_because"]}'
                                     if a['status'] == 'ANSWERED_NOT_APPLIED' else ''), a['meta']['applies_to'],
            k not in ('weekly_budget_reading', 'tuna_use_outside_pos', 'fridge2_use_split')
            and a['status'] != 'ANSWERED_NOT_APPLIED', a['status'])
    return pd.DataFrame(P)


# --- checks -----------------------------------------------------------------------------------------------
def _periods(dates):
    end = dates.max()
    return {'all years': dates >= dates.min(), 'last 52 weeks': dates > end - pd.Timedelta(days=364),
            'real POS window': dates >= pd.Timestamp(REAL_START)}


def _status(v, lo, hi):
    if lo is None or pd.isna(v):
        return 'INFO'
    return 'WITHIN' if lo <= v <= hi else ('ABOVE' if v > hi else 'BELOW')


def usage_by_line(sales, log, bom):
    """usable quantity per day x ingredient x recipe_source: recorded sales + lost POS lines (as the simulation)."""
    s = sales[['sale_date', 'item_id', 'quantity_sold']]
    lost = log.loc[log['in_consumption'] & (log['artifact_type'] == 'dropped_pos_line'),
                   ['sale_date', 'item_id', 'quantity_sold']]
    j = pd.concat([s, lost]).merge(bom[['item_id', 'ingredient_id', 'qty_per_item', 'recipe_source']], on='item_id')
    j['qty'] = j['quantity_sold'] * j['qty_per_item']
    j['date'] = pd.to_datetime(j['sale_date'])
    return j.groupby(['date', 'ingredient_id', 'recipe_source'], as_index=False)['qty'].sum()


def checks(inv, ing, fish, use, istore, storage, terms, sales):
    """Client figures next to the simulation's. Nothing is tuned to them."""
    inv = inv.assign(inventory_date=pd.to_datetime(inv['inventory_date']))
    by_id = ing.set_index('ingredient_id')
    inv['code'] = inv['ingredient_id'].map(by_id['ingredient_code'])
    inv['cost'] = inv['ingredient_id'].map(by_id['unit_cost'])
    inv['buy_php'] = inv['qty_received'] * inv['cost'] + inv['emergency_cost_php']
    inv['use_php'] = inv['qty_consumed'] * inv['cost']
    inv['pos_php'] = (inv['qty_consumed'] - inv['qty_off_pos_use']) * inv['cost']      # menu food cost (I12)
    dates = inv['inventory_date']
    per = _periods(dates)
    out = []

    def add(cid, name, client, lo, hi, unit, series_fn, basis, note=''):
        for p, m in per.items():
            days = dates[m].nunique()
            v = series_fn(m, days)
            out.append(dict(check_id=cid, check=name, client_value=client, client_min=lo, client_max=hi, period=p,
                            simulated_value=round(float(v), 2), unit=unit, status=_status(round(float(v), 2), lo, hi), basis=basis,
                            note=note))
    nf = ~inv['code'].isin(list(WHOLE_FISH_PHP))
    blo, bhi = budget_range()
    btxt = f'baseline PHP {BUDGET_BASELINE_PHP:,} +/- {BUDGET_TOLERANCE:.0%} (team decision 2026-10-07; client said 5k-15k)'
    calibrated = budget_target() is not None
    add('C01', 'weekly restock spend, excl. whole salmon / tuna', btxt, blo, bhi, 'PHP / week',
        lambda m, d: inv.loc[m & nf, 'buy_php'].sum() / d * 7, 'SIMULATION',
        'simulated purchases: qty_received x unit_cost + emergency buys (25% premium; whole fish at PHP 5,000). '
        + ('Follows from the budget calibration of C02; not independent validation' if calibrated
           else 'Validation signal, not a cap'))
    add('C02', 'weekly menu food cost (sales x recipes), excl. whole salmon / tuna', btxt, blo, bhi,
        'PHP / week', lambda m, d: inv.loc[m & nf, 'pos_php'].sum() / d * 7, 'DERIVED',
        '(qty_consumed - qty_off_pos_use) x unit_cost = sales x BOM; staff meals are C02b; not cash purchases (timing '
        'and stock carry-over differ)'
        + (f'; CALIBRATED: recipe quantities are scaled so this is PHP {budget_target():,.0f} on recorded sales'
           if calibrated else ''))
    add('C02b', 'weekly staff meals / off-menu cost, excl. whole salmon / tuna', 'information (I12: ground beef)', None,
        None, 'PHP / week', lambda m, d: inv.loc[m & nf, 'use_php'].sum() / d * 7 - inv.loc[m & nf, 'pos_php'].sum() / d * 7,
        'DERIVED', 'qty_off_pos_use x unit_cost: stock that leaves the freezer outside the menu; not menu food cost')
    weekly = inv[nf].set_index('inventory_date')['buy_php'].resample('W-SUN').sum().iloc[1:-1]
    for cid, q, lab in (('C20a', .25, 'P25'), ('C20b', .5, 'median'), ('C20c', .75, 'P75')):
        add(cid, f'weekly purchases, excl. whole fish: {lab} week', f'{btxt} (depends on when they restock)',
            blo, bhi, 'PHP / week', lambda m, d, q=q: weekly[weekly.index >= dates[m].min()].quantile(q),
            'SIMULATION', 'spread of whole Mon-Sun weeks of simulated purchases')
    s = sales.assign(sale_date=pd.to_datetime(sales['sale_date']))
    lo, hi, url = FOOD_COST_BENCHMARK
    add('C21', 'modelled food cost of regular ingredients, share of net sales', f'benchmark {lo:.0%}-{hi:.0%} ({url})',
        lo * 100, hi * 100, '% of net sales',
        lambda m, d: 100 * inv.loc[m & nf, 'pos_php'].sum() / s.loc[s['sale_date'] >= dates[m].min(), 'net_sales'].sum(),
        'DERIVED', 'C02 cost / recorded net sales; EXTERNAL_REFERENCE benchmark, not a Makisushi figure')
    for r in fish.itertuples():
        name, g, upf = ('salmon', 'C04', 'C06') if r.ingredient_code == 'SAL' else ('tuna', 'C05', 'C07')
        k = inv['code'] == r.ingredient_code
        flo, fhi = WHOLE_FISH_PER_MONTH[r.ingredient_code]
        ftxt = f'{flo}-{fhi}' + (' (3 approved, team decision 2026-10-07)' if r.ingredient_code == 'SAL' else '')
        p_ = WHOLE_FISH_PHP[r.ingredient_code]
        add(g, f'{name}: whole fish bought per month (planned + emergency)', ftxt, flo, fhi, 'fish / month',
            lambda m, d, k=k, u=r.usable_g_per_fish: (inv.loc[m & k, 'qty_received'].sum()
                                                       + inv.loc[m & k, 'qty_emergency'].sum()) / u / d * 30.44,
            'SIMULATION', f'(qty_received + qty_emergency) / {r.usable_g_per_fish} usable g a fish; emergency buys are '
                          'whole fish too (I14)')
        add(upf, f'{name}: whole fish needed per month by use (POS dishes + use outside the POS)', ftxt, flo, fhi,
            'fish / month',
            lambda m, d, k=k, u=r.usable_g_per_fish: inv.loc[m & k, 'qty_consumed'].sum() / u / d * 30.44, 'DERIVED',
            f'qty_consumed / {r.usable_g_per_fish} usable g a fish ({r.usable_fraction:g} of {r.whole_g_per_fish} g)')
        add('C10' if name == 'salmon' else 'C11', f'{name}: spend per month', f'PHP {flo * p_:,}-{fhi * p_:,}',
            flo * p_, fhi * p_,
            'PHP / month', lambda m, d, k=k: inv.loc[m & k, 'buy_php'].sum() / d * 30.44, 'SIMULATION',
            'qty_received x unit_cost + emergency buys')
        if name == 'tuna':
            add('C19', 'tuna: days one whole fish lasts at total use (POS dishes + use outside the POS)', '2-4 weeks',
                *TUNA_DAYS_PER_FISH, 'days',
                lambda m, d, k=k, u=r.usable_g_per_fish: u / max(inv.loc[m & k, 'qty_consumed'].sum() / d, 1e-9),
                'DERIVED', f'{r.usable_g_per_fish} usable g / daily use (O3; issue I07)')
            add('C19a', 'tuna: days one whole fish would last on POS dishes alone', '2-4 weeks', *TUNA_DAYS_PER_FISH,
                'days', lambda m, d, k=k, u=r.usable_g_per_fish: u / max(
                    (inv.loc[m & k, 'qty_consumed'] - inv.loc[m & k, 'qty_off_pos_use']).sum() / d, 1e-9),
                'DERIVED', 'shows why the use outside the POS matters (I07)')
    mng = int(ing.loc[ing['ingredient_code'] == 'MNG', 'ingredient_id'].item())
    cuc = int(ing.loc[ing['ingredient_code'] == 'CUC', 'ingredient_id'].item())

    def use_kg(iid, sources=None):
        def f(m, d):
            x = use[(use['ingredient_id'] == iid) & (use['date'] >= dates[m].min())]
            if sources:
                x = x[x['recipe_source'].isin(sources)]
            return x['qty'].sum() / (1 - MANGO_WASTAGE) / 1000 / d * 7
        return f
    mlo, mhi = MANGO_BASELINE_KG * (1 - MANGO_TOLERANCE), MANGO_BASELINE_KG * (1 + MANGO_TOLERANCE)
    mtxt = f'{MANGO_BASELINE_KG:g} kg / week +/- {MANGO_TOLERANCE:.0%} (team decision 2026-10-07; Q3 said 2-3)'
    add('C12', 'mango as bought, California maki + kani salad lines', 'Q3: 2-3 kg / week ("mainly" these dishes)', None,
        None, 'kg / week', use_kg(mng, ['COSTING:client_mango']), 'DERIVED',
        'sales x BOM usable g / (1 - 0.5 SUPPLY-UR wastage); information: the baseline is all mango (C13)')
    add('C13', 'mango as bought, all mango lines (incl. shakes / juice)', mtxt, mlo, mhi, 'kg / week',
        use_kg(mng), 'DERIVED', 'as C12, every MNG line; shake / juice grams are the owner\'s round-4 180 / 130 g')
    add('C14', 'mango purchased (simulated)', mtxt, mlo, mhi, 'kg / week',
        lambda m, d: inv.loc[m & (inv['ingredient_id'] == mng), 'qty_received'].sum() / (1 - MANGO_WASTAGE) / 1000 / d * 7,
        'SIMULATION', 'qty_received usable g / (1 - 0.5); includes stock later wasted')
    add('C15', 'cucumber as bought, all lines', '2-3 kg / week', 2, 3, 'kg / week', use_kg(cuc), 'DERIVED',
        'sales x BOM usable g / (1 - 0.5 SUPPLY-UR wastage)')
    # the owner's round-4 weekly baselines: answered but not applied (recipes keep the workbook grams)
    ans = owner_answers()
    for key, code in WEEKLY_USE_KEYS.items():
        given = ans[key]['meta'].get('owner_answer_given')
        if given is None:
            continue
        k = inv['code'] == code
        bought = ans[key]['meta'].get('owner_value_basis') == 'bought'
        assert not bought or code == 'GB', 'only the ground beef baseline is read as bought'
        f = GB_USABLE_FRACTION if bought else 1.0
        add(f'C23-{code}', f'{code}: kg {"bought" if bought else "used"} a week vs the owner\'s weekly baseline ({key})',
            f'{given:g} kg / week', float(given), float(given), 'kg / week',
            lambda m, d, k=k, f=f: inv.loc[m & k, 'qty_consumed'].sum() / f / 1000 / d * 7, 'DERIVED',
            ('qty_consumed incl. staff meals / usable fraction 0.6, i.e. as bought' if bought else
             'qty_consumed (sales x MENU2 grams) / 1000') + '; validation only (issue I05)')
    tp = terms.assign(code=terms['ingredient_id'].map(by_id['ingredient_code'])).set_index('code')['usable_qty_per_pack']
    for cid, code, unit, life, note in (
            ('C16', 'MUS', 'weeks per pack', 'a couple of weeks', 'usable g per pack / weekly use; Q2 "to last us a '
                                                                  'couple of weeks"'),
            ('C17', 'GP', 'days per pack', 'thawed ground meat: 1-2 days (USDA FSIS)', 'usable g per bulk pack / daily '
                                                                                        'use; portions kept frozen (O5)'),
            ('C18', 'GB', 'days per pack', 'thawed ground meat: 1-2 days (USDA FSIS)', 'usable g per bulk pack / daily '
                                                                                        'use (issue I12)')):
        g = inv['code'] == code
        scale = 7 if unit.startswith('weeks') else 1
        add(cid, f'{code}: how long one pack ({tp[code]:g} usable g) lasts at recipe use', life, None, None, unit,
            lambda m, d, g=g, code=code, scale=scale: tp[code] / max(inv.loc[m & g, 'qty_consumed'].sum() / d * scale, 1e-9),
            'DERIVED', note)
    # storage: start-of-day stock after receipts, by stored location, grams only
    loc = istore.set_index('ingredient_id')['stored_location']
    uom = by_id['uom']
    inv['loc'] = inv['ingredient_id'].map(loc)
    inv['peak'] = inv['opening_stock'] + inv['qty_received']
    gram = inv['ingredient_id'].map(uom).eq('g')
    cap = storage.set_index('storage_location_id')['capacity_l']
    for lid in ('FR2', 'CH1', 'CF1', 'TF1'):
        k = inv['loc'].eq(lid)
        daily_kg = inv[k & gram].groupby('inventory_date')['peak'].sum() / 1000
        other = sorted(set(inv.loc[k & ~gram, 'code']))
        for p, m in _periods(daily_kg.index.to_series()).items():
            v = daily_kg[m.values].max()
            out.append(dict(check_id=f'S-{lid}', check=f'storage {lid}: peak stock of gram-unit items and break-even '
                            'density', client_value=f'{int(cap[lid])} L', client_min=None, client_max=None, period=p,
                            simulated_value=round(v, 2), unit='kg usable (peak, start of day)', status='INFO',
                            basis='SIMULATION',
                            note=f'stock fits unless fewer than {v / cap[lid]:.3f} kg can be packed per litre; '
                                 f'piece / serving items not converted: {", ".join(other) or "none"}'
                                 + ('; compartments share 225 L (split UNKNOWN)' if lid == 'FR2' else '')))
    frozen = inv['ingredient_id'].isin(set(ing.loc[ing['ingredient_code'].isin(RAW_FROZEN), 'ingredient_id'])) & gram
    daily = inv[frozen].groupby('inventory_date')['peak'].sum() / 1000
    for p, m in _periods(daily.index.to_series()).items():
        v = daily[m.values].max()
        out.append(dict(check_id='S-RAWFROZEN', check='storage: all raw frozen fish / meat if held in Tall Freezer 1 '
                        'alone', client_value='198 L', client_min=None, client_max=None, period=p,
                        simulated_value=round(v, 2), unit='kg usable (peak, start of day)', status='INFO',
                        basis='SIMULATION',
                        note=f'worst case (nothing in Chest Freezer 1): fits unless fewer than {v / 198:.3f} kg per litre'))
    return pd.DataFrame(out).assign(source=f'{SOURCE}; {OWNER}')


def budget_diagnosis(inv, ing, rates, isup, use):
    """Per ingredient, real POS window: weekly use and cost, and how much of the use comes from SYNTHETIC lines."""
    inv = inv.assign(inventory_date=pd.to_datetime(inv['inventory_date']))
    real = inv[inv['inventory_date'] >= REAL_START]
    weeks = real['inventory_date'].nunique() / 7
    d = ing.set_index('ingredient_id')[['ingredient_code', 'ingredient_name', 'uom', 'unit_cost']].copy()
    d['use_per_week'] = real.groupby('ingredient_id')['qty_consumed'].sum() / weeks
    r = rates.set_index('source_row')
    s = isup.set_index('ingredient_id').reindex(d.index)
    priced = s['basis'].str.startswith('its unit_cost')
    d['cost_source'] = np.where(priced, 'SUPPLY-UR row ' + s['sheet_row'].astype('Int64').astype(str),
                                'COSTING / team estimate')
    d.loc[d['ingredient_code'].isin(list(WHOLE_FISH_PHP)), 'cost_source'] = 'PHP 5,000 a whole fish (Q4, O2, O3)'
    d['supply_ur_wastage_fluctuation'] = s['sheet_row'].map(r['wastage_fluctuation']).where(priced)
    d['php_per_week'] = d['use_per_week'] * d['unit_cost']
    u = use[use['date'] >= REAL_START]
    syn = u[u['recipe_source'].str.startswith('SYNTHETIC')].groupby('ingredient_id')['qty'].sum()
    d['share_of_use_from_synthetic_lines'] = (syn / u.groupby('ingredient_id')['qty'].sum()).reindex(d.index).fillna(0)
    d['php_per_week_source_lines_only'] = d['php_per_week'] * (1 - d['share_of_use_from_synthetic_lines'])
    d['in_weekly_budget'] = ~d['ingredient_code'].isin(list(WHOLE_FISH_PHP))
    d['share_of_cost'] = d['php_per_week'] / d['php_per_week'].sum()
    d = d.sort_values('php_per_week', ascending=False).reset_index()
    return d.round({'use_per_week': 1, 'php_per_week': 0, 'php_per_week_source_lines_only': 0,
                    'share_of_use_from_synthetic_lines': 3, 'share_of_cost': 3})
