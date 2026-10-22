"""Anniversary promotion rules: the single source of truth for the campaign calendar, the eligible menu items
and the discount arithmetic. Used by reorganize_anniversary_promos.py (builds the sales), the validation and
build_promo_schedule.py (documents the campaigns). Nothing here is loaded into the warehouse: fact_sales carries no
promotion column (team decision 2026-10-10); a promotional sale is recognised by these rules, never by a label.

Provenance (see the strict provenance rules): the windows, items, offers and the 10 % / 25 % rates are the team's
campaign plan of 2026-10-10 (CLIENT/TEAM_PROVIDED instruction). The 2026 rate (10 %) is a design assumption, not
verified history. Everything below the plan (volumes, dates, quantities, channels of ADDED lines) is
SYNTHETIC_ASSUMPTION.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
import calendar

import pandas as pd

# ---------------------------------------------------------------------------------------------- study period
STUDY_START, STUDY_END = date(2021, 10, 1), date(2026, 9, 30)
# first date of SALES'26 (the client's real POS export). From here on every sale line is a client record: the
# reorganisation never changes it and never adds a line on or after this date.
REAL_POS_START = date(2025, 12, 1)
WINDOW_FIRST_DAY = 8          # "second week to the last week" = the 8th through the final calendar day, inclusive
WINDOW_MONTHS = {'Jun': 6, 'Nov': 11}

GRABFOOD_PRICE_FACTOR = 1.25  # observed on every item in the dataset (GrabFood unit price = Dine-In price x 1.25)


@dataclass(frozen=True)
class Offer:
    key: str                       # stable id used in the register and the schedule
    label: str
    kind: str                      # 'percent_off' | 'pair_percent_off' | 'pair_free_item'
    rate: float = 0.0              # discount rate (percent_off kinds)
    item_ids: tuple = ()           # qualifying menu item ids (resolved from the catalogue for category-based offers)
    min_qty: int = 1               # quantity on one sale line needed to qualify
    free_item_id: int = 0          # pair_free_item: the complimentary item
    uplift: float = 1.0            # synthetic volume multiplier applied to the observed baseline (design assumption)
    mechanics: str = ''


# item ids checked against the catalogue by verify_catalogue(): id -> (display_name, pos_sku)
EXPECTED_ITEMS = {
    22: ('Gyoza (4 pcs)', 10749),
    23: ('Tofu (4 pcs)', 10925),
    42: ('Chicken Misono', 10923),
    126: ('Pork Misono', 10924),
    109: ('Okonomiyaki', 10634),
    115: ('Okonomiyaki Garlic & Cheese', 10754),
    118: ('Okonomiyaki Promo Buttered Chicken', 10746),
    120: ('Okonomiyaki Cheesy Mushroom', 10638),
    146: ('Shoyu Seafood Ramen', 10875),
    85: ('Katsudon', 10633),
    170: ('Torikatsudon', 10632),
    343: ('Crunchy Veggie Salad Roll', 10369),
}
# same-named dishes that are NOT part of any campaign (regular menu / delivery listings / staff comps)
SAME_NAME_EXCLUDED = {
    'Gyoza (4 pcs)': (6, 418, 420),
    'Chicken Misono': (43, 44, 45, 47),
    'Pork Misono': (128,),
    'Katsudon': (257, 258, 259),
    'Torikatsudon': (171, 172, 282, 283),
    'Shoyu Seafood Ramen': (144, 388),
    'Okonomiyaki Cheesy Beef (Regular)': (114,),
}

BAKED_SUSHI_CATEGORY = 'Baked Sushi'     # the whole-tray Baked Sushi line; 'Baked Sushi Pie' is a different product
MAKI_CATEGORY = 'Maki Rolls'
FREE_ROLL_ITEM = 343                     # Crunchy Veggie Salad Roll (the only Veggie Salad Roll on the menu)

# design assumptions for synthetic volume (documented in the schedule):
MIN_SPAN_DAYS = 30                       # a promo dish seen for < 30 days in the real export is rated over 30 days
BAKED_PAIR_UPLIFT = 2.0                  # a 25 % pair discount is assumed to double natural pair purchases

CAMPAIGNS = {
    2021: ('Starter Specials', (Offer('2021-starters', 'Starter Specials: 10% off Gyoza (4 pcs) and Tofu (4 pcs)',
                                      'percent_off', 0.10, (22, 23),
                                      mechanics='10% off each qualifying line'),)),
    2022: ('Misono Specials', (Offer('2022-misono', 'Misono Specials: 10% off Chicken Misono and Pork Misono',
                                     'percent_off', 0.10, (42, 126),
                                     mechanics='10% off each qualifying line'),)),
    2023: ('Japanese Comfort Food Specials',
           (Offer('2023-comfort', 'Comfort Food Specials: 10% off Okonomiyaki and Shoyu Seafood Ramen',
                  'percent_off', 0.10, (109, 115, 118, 120, 146),
                  mechanics='10% off each qualifying line'),)),
    2024: ('Baked Sushi and Maki Offers',
           (Offer('2024-baked', 'Offer A: 25% off Baked Sushi when two or more are bought',
                  'pair_percent_off', 0.25, (), min_qty=2, uplift=BAKED_PAIR_UPLIFT,
                  mechanics='25% off a Baked Sushi line with quantity >= 2; a line with quantity 1 stays regular'),
            Offer('2024-maki', 'Offer B: buy two Maki Rolls, get one Veggie Salad Roll free',
                  'pair_free_item', 0.0, (), min_qty=2, free_item_id=FREE_ROLL_ITEM,
                  mechanics='a paid Maki Rolls line with quantity >= 2 earns floor(quantity / 2) complimentary '
                            'Crunchy Veggie Salad Roll(s) on the same date and channel'))),
    2025: ('Katsudon Specials', (Offer('2025-katsudon', 'Katsudon Specials: 10% off Torikatsudon and Katsudon',
                                       'percent_off', 0.10, (170, 85),
                                       mechanics='10% off each qualifying line'),)),
    2026: ('Anniversary Specials',
           (Offer('2026-anniversary', 'Anniversary Specials: 10% off Torikatsudon, Katsudon, Gyoza (4 pcs), '
                                      'Chicken Misono and Pork Misono',
                  'percent_off', 0.10, (170, 85, 22, 42, 126),
                  mechanics='10% off each qualifying line (assumed: the 2025 rate; no 2026 rate is established)'),)),
}
# the 2026 items the plan names as NOT part of the campaign (they stay regular sales)
EXCLUDED_2026 = {23: 'Tofu (4 pcs)', 109: 'Okonomiyaki', 115: 'Okonomiyaki Garlic & Cheese',
                 118: 'Okonomiyaki Promo Buttered Chicken', 120: 'Okonomiyaki Cheesy Mushroom',
                 71: 'Free 4 pcs California Maki', 72: 'Free Sola'}


# ---------------------------------------------------------------------------------------------- calendar
def window_dates(year):
    """{'Jun': (start, end), 'Nov': (start, end)} for the windows that lie wholly inside the study period."""
    out = {}
    for label, month in WINDOW_MONTHS.items():
        start, end = date(year, month, WINDOW_FIRST_DAY), date(year, month, calendar.monthrange(year, month)[1])
        if start >= STUDY_START and end <= STUDY_END:
            out[label] = (start, end)
    return out


def all_windows():
    """[(year, label, start, end)] in date order, 2021 .. 2026."""
    return [(y, lab, s, e) for y in sorted(CAMPAIGNS) for lab, (s, e) in sorted(window_dates(y).items(), key=lambda kv: kv[1][0])]


def window_of(day):
    """(year, label) of the campaign window containing `day`, else None."""
    for y, lab, s, e in all_windows():
        if s <= day <= e:
            return y, lab
    return None


# ---------------------------------------------------------------------------------------------- catalogue
def verify_catalogue(menu, name_col='display_name', sku_col='sku', price_col='price'):
    """Every item id the plan names must exist with the expected name and POS SKU, and the free roll must carry a price."""
    problems = []
    m = menu.set_index('item_id')
    for iid, (name, sku) in EXPECTED_ITEMS.items():
        if iid not in m.index:
            problems.append(f'item {iid} ({name}) missing from the menu')
        elif m.at[iid, name_col] != name or int(m.at[iid, sku_col]) != sku:
            problems.append(f'item {iid}: menu says {m.at[iid, name_col]!r} / {m.at[iid, sku_col]}, plan says {name!r} / {sku}')
    for name, ids in SAME_NAME_EXCLUDED.items():
        for iid in ids:
            if iid not in m.index:
                problems.append(f'excluded same-name item {iid} ({name}) not in the menu')
    if problems:
        raise SystemExit('catalogue check failed:\n  ' + '\n  '.join(problems))


def resolved_items(offer, menu, category_col='category', price_col='price'):
    """Qualifying item ids of an offer. Category-based offers are resolved from the catalogue: paying items only."""
    if offer.key == '2024-baked':
        sel = menu[(menu[category_col] == BAKED_SUSHI_CATEGORY) & (menu[price_col] > 0)]
        return tuple(sorted(sel['item_id']))
    if offer.key == '2024-maki':
        sel = menu[(menu[category_col] == MAKI_CATEGORY) & (menu[price_col] > 0)]
        return tuple(sorted(sel['item_id']))
    return tuple(offer.item_ids)


def offer_table(menu, **kw):
    """[(year, campaign_name, Offer, resolved item ids)] for every offer."""
    return [(y, name, o, resolved_items(o, menu, **kw)) for y in sorted(CAMPAIGNS) for name, offers in [CAMPAIGNS[y]] for o in offers]


# ---------------------------------------------------------------------------------------------- arithmetic
def promo_discount(gross, rate):
    """Discount in pesos, rounded half-up to the centavo (net = gross - discount then holds exactly)."""
    return float((Decimal(str(round(float(gross), 2))) * Decimal(str(rate))).quantize(Decimal('0.01'), ROUND_HALF_UP))


def money(x):
    return float(Decimal(str(x)).quantize(Decimal('0.01'), ROUND_HALF_UP))


def grab_price(dine_in_price):
    return money(Decimal(str(dine_in_price)) * Decimal(str(GRABFOOD_PRICE_FACTOR)))


# ---------------------------------------------------------------------------------------------- classification
def classify(df, menu, paying, date_col='sale_date', qty_col='quantity_sold', category_col='category',
             price_col='price'):
    """Adds campaign columns to a sales frame by rule, never by label:
    cp_year, cp_window, cp_offer (None when the line is not a campaign sale), cp_rate (the offer's discount rate).
    A line qualifies when `paying` is True for it (a paying, non-complimentary line: the caller decides how its frame
    says so), it is dated inside a study-period campaign window of a year whose offer lists its item, and its quantity
    reaches the offer's minimum. Lines that fail any test stay regular sales."""
    out = df.copy()
    days = pd.to_datetime(out[date_col]).dt.date
    wins = [window_of(d) for d in days]
    out['cp_year'] = pd.array([w[0] if w else pd.NA for w in wins], dtype='Int64')
    out['cp_window'] = [w[1] if w else None for w in wins]
    out['cp_offer'] = None
    out['cp_rate'] = 0.0
    paying = pd.Series(paying, index=out.index).astype(bool)
    for y, _name, o, ids in offer_table(menu, category_col=category_col, price_col=price_col):
        hit = (paying & (out['cp_year'] == y).fillna(False).astype(bool) & out['item_id'].isin(ids)
               & (out[qty_col] >= o.min_qty))
        out.loc[hit, 'cp_offer'] = o.key
        out.loc[hit, 'cp_rate'] = o.rate
    out['cp_year'] = out['cp_year'].where(out['cp_offer'].notna(), pd.NA)
    out['cp_window'] = out['cp_window'].where(out['cp_offer'].notna(), None)
    return out
