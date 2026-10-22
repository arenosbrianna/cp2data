"""Assigned replacement codes for POS SKUs that are not valid 5-digit codes.

The POS export (SALES'26 / MENU) carries 21 distinct SKU values that cannot be POS codes: 4 to 14 digits, padded
with repeated digits ('1064111111', '10641122222') or cut short ('1066', '1070'). Every real POS SKU has 5
digits. No source holds the true code for these items, so the true code cannot be recovered.
Team decision 2026-10-09: replace each invalid value with an ASSIGNED 5-digit code, the same code wherever the
old value appears (menu and sales stay in step; sharing between items that already shared a value is kept).
Assigned codes are NOT POS-issued: they start above the highest real SKU, so they cannot collide with one.
The mapping is written to sku_corrections.csv; replace its new_sku with real POS codes if the owner supplies them.
Valid codes and the 0 placeholder are left alone (0 is handled separately: no SKU).
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
MAPPING_CSV = ROOT / 'sku_corrections.csv'
FULL_MENU = ROOT / 'generated_v4_pre_stg_trim' / 'menu_items.csv'    # untrimmed original, old SKU values
FULL_SALES = ROOT / 'generated_v4_pre_stg_trim' / 'sales.csv'


def is_valid(sku):
    return (sku >= 10000) & (sku <= 99999)


def build_mapping():
    """Deterministic old SKU -> assigned SKU, ordered by the first item_id that carries the old value."""
    menu = pd.read_csv(FULL_MENU, usecols=['item_id', 'sku'])
    sales = pd.read_csv(FULL_SALES, usecols=['item_id', 'pos_sku'])
    seen = pd.concat([menu.rename(columns={'sku': 'old_sku'}), sales.rename(columns={'pos_sku': 'old_sku'})])
    bad = seen[(seen['old_sku'] != 0) & ~is_valid(seen['old_sku'])]
    first = bad.groupby('old_sku').item_id.min().sort_values(kind='stable')
    last_real = int(max(menu.loc[is_valid(menu['sku']), 'sku'].max(), sales.loc[is_valid(sales['pos_sku']), 'pos_sku'].max()))
    rows = [dict(old_sku=int(old), new_sku=last_real + i, first_item_id=int(item),
                 basis='ASSIGNED: old value is not a 5-digit POS code and no source has the real one')
            for i, (old, item) in enumerate(first.items(), start=1)]
    out = pd.DataFrame(rows)
    assert is_valid(out['new_sku']).all() and out['new_sku'].is_unique
    out.to_csv(MAPPING_CSV, index=False)
    return dict(zip(out['old_sku'], out['new_sku']))


def apply(series, mapping):
    """Replace invalid SKUs by their assigned code; everything else is returned unchanged."""
    s = pd.to_numeric(series)
    return s.map(lambda v: mapping.get(int(v), v) if pd.notna(v) else v).astype(s.dtype)


if __name__ == '__main__':
    m = build_mapping()
    print(f'{len(m)} invalid SKU values mapped; written to {MAPPING_CSV.name}')
