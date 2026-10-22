"""Cleaning and standardisation of the POS sales table for forecasting and inventory optimisation.

Input : cleaned/sales_staged.csv, written by build_stg_extract.py (columns: sale_id, sale_date, item_id, channel,
        pos_sku, pos_category_raw, quantity_sold, unit_price, gross_sales, discount, net_sales, is_complimentary)
Output:
  generated_v4/sales.csv     THE sales dataset: every validated line, revenue and non-revenue, with an is_revenue
                             flag instead of is_complimentary (the comps are the is_revenue = False rows); loaded by supabase_final
  generated_v4/sales_dropped.csv  date, item and quantity of the lines rejected below: consumed stock still
                             needs them (used only by the consumption check in 03_transform.sql)
  cleaned/sales_cleaned.csv  paying-customer demand only (sales_revenue_clean): the forecast input
  cleaned/sales_rejected.csv every row removed by a validation rule, with the reason
Run:  py build_stg_extract.py  then  py clean_sales.py [--src cleaned/sales_staged.csv] [--out cleaned]
"""
import argparse
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
LOAD_DIR = ROOT / 'generated_v4'
MAX_IMPUTE_SHARE = 0.05          # a text column missing in more than 5% of rows is reported, not silently filled
KEY_COLS = ['sale_id', 'sale_date', 'item_id', 'quantity_sold', 'unit_price', 'gross_sales', 'discount',
            'net_sales', 'is_complimentary']
MONEY_COLS = ['unit_price', 'gross_sales', 'discount', 'net_sales']
TEXT_COLS = ['channel']
MENU_CSV = LOAD_DIR / 'menu_items.csv'     # written by build_stg_extract.py; the menu is the source of truth for category
NON_REVENUE_CATEGORY = 'Management'
_menu = pd.read_csv(MENU_CSV)
MENU_CATEGORY = dict(zip(_menu['item_id'], _menu['category']))
CHANNEL_LABELS = {'DINE-IN': 'Dine-In', 'GRABFOOD': 'GrabFood'}
# Whole days of the client's POS export (workbook SALES'26) that are line-for-line copies of an earlier day: same items,
# quantities, gross and discounts on every line (2026-04-04 = 2026-06-02 with 30 lines, 2026-07-23 = 2026-07-24 with 34).
# Team decision 2026-10-10: keep the FIRST day of each pair, remove the later copy. The removed lines go to
# sales_rejected.csv / sales_dropped.csv (their stock use was simulated, so the consumption check still counts them).
# Caveat: the later dates then have no sale line and look like closures; they are listed in dq_removed_duplicate_days.csv.
DUPLICATE_DAY_COPIES = {'2026-06-02': '2026-04-04', '2026-07-24': '2026-07-23'}   # removed day -> kept day


def normalise_text(value):
    """Strip hidden characters, collapse whitespace, upper-case.

    Principle: joins and group-bys compare strings exactly, so 'Maki ' and 'MAKI\\u200b' would silently become
    separate categories. NFKC folds look-alike forms; control/format characters (zero-width space, BOM) are
    removed; no-break spaces become normal spaces.
    """
    if pd.isna(value):
        return np.nan
    text = unicodedata.normalize('NFKC', str(value)).replace(' ', ' ')
    text = ''.join(ch for ch in text if unicodedata.category(ch) not in ('Cc', 'Cf') or ch in '\t\n')
    text = re.sub(r'\s+', ' ', text).strip().upper()
    return text or np.nan


def to_cents(series):
    """Money as integer cents so '=' means exactly equal to the cent, free of float noise (0.1 + 0.2 != 0.3)."""
    return (series * 100).round().astype('Int64')


def main(src, out_dir):
    log = {}
    df = pd.read_csv(src, dtype=str, keep_default_na=True)   # read as text: nothing is coerced before we look at it
    log['rows read'] = len(df)
    rejected = []

    def reject(mask, reason):
        """Move rows out of the working frame, never delete silently (audit trail)."""
        nonlocal df
        if mask.any():
            rejected.append(df[mask].assign(reject_reason=reason))
            log[f'rejected: {reason}'] = int(mask.sum())
        df = df[~mask]

    # ------------------------------------------------------------------ 3a. types, then missing values
    # Principle: parse first so that unparseable text becomes a visible NaN instead of a hidden string.
    for c in ['sale_id', 'item_id', 'quantity_sold', 'pos_sku']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    for c in MONEY_COLS:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['is_complimentary'] = df['is_complimentary'].str.strip().str.lower().map(
        {'true': True, 'false': False, '1': True, '0': False})
    # 5. strict datetime64[ns]; anything that is not an ISO date is rejected, not guessed (day/month ambiguity)
    df['sale_date'] = pd.to_datetime(df['sale_date'], format='%Y-%m-%d', errors='coerce').astype('datetime64[ns]')

    # Invalid POS SKUs (not 5 digits) -> the assigned codes in sku_corrections.csv (see sku_fix.py); a no-op when
    # the input already carries them (generated_v4/sales.csv does) and when the mapping file is absent.
    if (ROOT / 'sku_corrections.csv').exists():
        mp = pd.read_csv(ROOT / 'sku_corrections.csv').set_index('old_sku')['new_sku'].to_dict()
        fixed = df['pos_sku'].isin(mp)
        df['pos_sku'] = df['pos_sku'].replace(mp)
        log['SKUs replaced by assigned 5-digit codes'] = int(fixed.sum())

    # Text columns: normalise first (Task 2), then treat empty as missing.
    for c in TEXT_COLS:
        df[c] = df[c].map(normalise_text)
    # Principle: one label per category, so counts, forecasts and joins are not split across spellings.

    miss = df.isna().mean()
    log['missing share per column (before handling)'] = {c: round(float(v), 4) for c, v in miss.items() if v > 0} or 'none'

    # Money, quantity, ids and dates are never imputed: a made-up price or quantity would be fabricated demand,
    # and these fields drive both the forecast target and the inventory draw-down. Those rows are rejected.
    reject(df[KEY_COLS].isna().any(axis=1), 'missing key field (id/date/quantity/money/comp flag)')
    # Descriptive text may be filled with an explicit UNKNOWN only while it is rare (<= threshold);
    # pos_sku is not a key in the source (not unique), so it stays null when missing.
    for c in TEXT_COLS:
        share = df[c].isna().mean()
        if share > MAX_IMPUTE_SHARE:
            print(f'WARNING: {c} is missing in {share:.1%} of rows (> {MAX_IMPUTE_SHARE:.0%}); filled with UNKNOWN, review the source')
        log[f'{c} filled with UNKNOWN'] = int(df[c].isna().sum())
        df[c] = df[c].fillna('UNKNOWN')

    # Lines with pos_sku = 0: the POS never gave these (hand-keyed) items a SKU, and the source has no real one.
    # Team decision 2026-10-09: drop them from the cleaned sales files (kept in sales_rejected.csv).
    # The warehouse load is NOT affected: these lines still feed the ingredient consumption reconciliation there.
    reject(df['pos_sku'] == 0, 'no POS SKU (pos_sku = 0)')

    # ------------------------------------------------------------------ 3b. exact duplicates
    # Principle: a repeated POS record double-counts demand and inflates the forecast level.
    dup = df.duplicated(keep='first')
    reject(dup, 'exact duplicate record')
    # Same sale ignoring the surrogate sale_id is only flagged: two identical lines can be two real customers.
    log['flagged (kept): identical except sale_id'] = int(df.duplicated(subset=[c for c in df.columns if c != 'sale_id']).sum())

    # Whole-day copies from the source export: keep the first day, remove the later one (see DUPLICATE_DAY_COPIES).
    # Guard: a removed day is only dropped if it really equals its kept day on item, quantity, gross and discount.
    cols_eq = ['item_id', 'quantity_sold', 'gross_sales', 'discount']
    for gone, kept in DUPLICATE_DAY_COPIES.items():
        a = df[df['sale_date'] == pd.Timestamp(gone)].sort_values(['item_id', 'quantity_sold', 'gross_sales'])[cols_eq].reset_index(drop=True)
        k = df[df['sale_date'] == pd.Timestamp(kept)].sort_values(['item_id', 'quantity_sold', 'gross_sales'])[cols_eq].reset_index(drop=True)
        assert len(a) and a.equals(k), f'{gone} is not an exact copy of {kept}: not removed'
    reject(df['sale_date'].isin([pd.Timestamp(d) for d in DUPLICATE_DAY_COPIES]),
           'whole-day copy of an earlier day in the source export (kept: first day)')
    pd.DataFrame([dict(removed_day=g, kept_day=k, note='line-for-line copy in workbook sheet SALES26; later copy removed 2026-10-10; no sale line on removed_day (not a closure)')
                  for g, k in DUPLICATE_DAY_COPIES.items()]).to_csv(LOAD_DIR.parent / 'dq_removed_duplicate_days.csv', index=False)

    # ------------------------------------------------------------------ 3c. numeric integrity
    # Principle: the table has no refund/void flag, so a negative quantity or amount is a logical impossibility,
    # not a return. Quantity must be a positive whole number.
    reject((df['quantity_sold'] <= 0) | (df['quantity_sold'] % 1 != 0), 'quantity_sold not a positive integer')
    reject((df[MONEY_COLS] < 0).any(axis=1), 'negative money value with no refund/void flag')
    reject(df['discount'] > df['gross_sales'], 'discount exceeds gross_sales')

    # ------------------------------------------------------------------ 4. accounting identities
    # Principle: gross = quantity x unit price and net = gross - discount must hold to the cent, otherwise
    # revenue totals and price elasticity (forecast features) are wrong.
    # gross is checked against the unrounded unit price: the POS stores some unit prices as gross / quantity
    # (5,080.00 / 9 = 564.4444...), so rounding the price to cents first would reject genuine sales. The gross
    # amount must still be reproduced to within half a cent.
    gross_ok = (df['gross_sales'] - df['quantity_sold'] * df['unit_price']).abs() < 0.005
    reject(~gross_ok, 'gross_sales != quantity_sold x unit_price')
    net_ok = to_cents(df['net_sales']) == (to_cents(df['gross_sales']) - to_cents(df['discount']))
    reject(~net_ok, 'net_sales != gross_sales - discount')

    # ------------------------------------------------------------------ 2. category from the menu (source of truth)
    # The sales category is the menu item's category, looked up by item_id; the POS label is not used.
    df['category'] = df['item_id'].map(MENU_CATEGORY)
    unmapped = df['category'].isna()
    if unmapped.any():
        print('ITEMS NOT IN MENU:', sorted(df.loc[unmapped, 'item_id'].unique()))
    log['rows with item not in menu'] = int(unmapped.sum())
    df = df[~unmapped]

    # Promotions carry no label here: fact_sales has no promotion column (team decision 2026-10-10). A campaign sale is
    # recognised by its date, item and quantity (anniversary_promo_rules.py) and listed in anniversary_promo_schedule.md.

    # ------------------------------------------------------------------ 1. split revenue demand from consumption
    # Principle: a forecast of paying demand must not include staff meals or comps, but the inventory
    # optimiser must still stock for them: ingredients are consumed either way. So both are kept, separately.
    is_comp = df['is_complimentary'] | (df['category'] == NON_REVENUE_CATEGORY)
    sales_inventory_comps = df[is_comp].copy()
    sales_revenue_clean = df[~is_comp].copy()
    log['complimentary/management lines moved to comps'] = len(sales_inventory_comps)
    log['  of which flagged complimentary outside Management'] = int(
        (sales_inventory_comps['is_complimentary'] & (sales_inventory_comps['category'] != NON_REVENUE_CATEGORY)).sum())
    log['  gross_sales excluded from revenue by that split (PHP)'] = round(float(sales_inventory_comps['gross_sales'].sum()), 2)
    # Zero-price lines that are not comps would be free add-ons; they stay in demand and are only reported.
    log['zero-price paying lines kept (free add-ons)'] = int((sales_revenue_clean['unit_price'] == 0).sum())

    # ------------------------------------------------------------------ 5. analytics readiness
    # Principle: time-series models need a monotonic datetime index; a stable sort keeps same-day order.
    for frame in (sales_revenue_clean, sales_inventory_comps):
        frame.sort_values(['sale_date', 'sale_id'], kind='stable', inplace=True)
        frame.reset_index(drop=True, inplace=True)
        for c in ['sale_id', 'item_id', 'quantity_sold']:
            frame[c] = frame[c].astype('int64')
        frame['pos_sku'] = frame['pos_sku'].astype('Int64')
        frame['is_complimentary'] = frame['is_complimentary'].astype(bool)
    for frame in (sales_revenue_clean, sales_inventory_comps):
        frame['channel'] = frame['channel'].map(CHANNEL_LABELS).fillna(frame['channel'].str.title())
    # The output carries the menu category in place of the raw POS label, which is dropped.
    def group_in_place(frame):
        cols = [c for c in frame.columns if c not in ('pos_category_raw', 'is_complimentary', 'category')]   # is_revenue replaces the comp flag
        cols.insert(cols.index('channel'), 'category')
        return frame[cols]
    sales_revenue_clean = group_in_place(sales_revenue_clean)
    sales_inventory_comps = group_in_place(sales_inventory_comps)
    assert sales_revenue_clean['sale_date'].dtype == 'datetime64[ns]'
    assert sales_revenue_clean['sale_date'].is_monotonic_increasing

    out_dir.mkdir(exist_ok=True)
    sales_revenue_clean.assign(is_revenue=True).to_csv(out_dir / 'sales_cleaned.csv', index=False, date_format='%Y-%m-%d')
    # Principle: stock leaves for staff meals and comps as well as for sales, so inventory work needs every line.
    # One table with an explicit flag keeps a single source of truth; revenue work filters is_revenue.
    sales_all_consumption = pd.concat([sales_revenue_clean.assign(is_revenue=True),
                                       sales_inventory_comps.assign(is_revenue=False)])
    sales_all_consumption = sales_all_consumption.sort_values(['sale_date', 'sale_id'], kind='stable', ignore_index=True)
    assert sales_all_consumption['sale_id'].is_unique
    load_cols = ['sale_id', 'sale_date', 'item_id', 'category', 'channel', 'pos_sku', 'quantity_sold', 'unit_price',
                 'gross_sales', 'discount', 'net_sales', 'is_revenue']
    sales_all_consumption[load_cols].to_csv(LOAD_DIR / 'sales.csv', index=False, date_format='%Y-%m-%d')
    all_rejected = pd.concat(rejected) if rejected else pd.DataFrame(columns=list(df.columns) + ['reject_reason'])
    all_rejected.to_csv(out_dir / 'sales_rejected.csv', index=False)
    # Sold-but-not-loaded lines still drew stock down, so the warehouse's consumption check needs their size
    # (a line without a date, item or quantity cannot be attributed to a day and an ingredient: left out).
    dropped = all_rejected[['sale_date', 'item_id', 'quantity_sold']].dropna()
    dropped.astype({'item_id': 'int64', 'quantity_sold': 'int64'}).to_csv(
        LOAD_DIR / 'sales_dropped.csv', index=False, date_format='%Y-%m-%d')

    log['rows in sales_cleaned.csv (sales_revenue_clean)'] = len(sales_revenue_clean)
    log['rows in generated_v4/sales.csv (revenue + non-revenue)'] = len(sales_all_consumption)
    log['revenue date range'] = f"{sales_revenue_clean['sale_date'].min():%Y-%m-%d} .. {sales_revenue_clean['sale_date'].max():%Y-%m-%d}"
    log['net sales in sales_cleaned (PHP)'] = round(float(sales_revenue_clean['net_sales'].sum()), 2)
    print('\nSUMMARY OF TRANSFORMATIONS')
    for k, v in log.items():
        print(f'  {k}: {v}')
    assert log['rows read'] == (len(sales_revenue_clean) + len(sales_inventory_comps)
                                + sum(len(r) for r in rejected)), 'row accounting does not balance'
    return sales_revenue_clean, sales_inventory_comps


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=str(ROOT / 'cleaned' / 'sales_staged.csv'))
    ap.add_argument('--out', default=str(ROOT / 'cleaned'))
    a = ap.parse_args()
    sales_revenue_clean, sales_inventory_comps = main(Path(a.src), Path(a.out))
