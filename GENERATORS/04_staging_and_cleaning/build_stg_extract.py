"""Trims generated_v4 to the columns the dw needs: generated_v4_pre_stg_trim/*.csv (full) -> generated_v4/*.csv.

supabase_final/01_schema.sql (the ERD's dw schema) is the source of truth. This script keeps only
the generated_v4 columns that populate, look up or validate a dw column, renames them to the dw
names, and keeps rows in the study window. not loaded: the full files, with every provenance and lineage column, stay in generated_v4_pre_stg_trim/.

Writes generated_v4/<table>.csv (loaded by supabase_final/02_load_staging.psql) and
generated_v4/MANIFEST.csv (rows and columns kept / dropped per source file).
Sales is not written to generated_v4 here: it goes to cleaned/sales_staged.csv (window, new sale_id, SKU fixes) and
clean_sales.py then writes the final generated_v4/sales.csv (every validated line, revenue and non-revenue).
Also writes generated_v4_audit/sales_duplicates_removed.csv with the same sale_id numbering.
Run:  py build_stg_extract.py  then  py clean_sales.py   (after any rebuild of generated_v4)
"""
from pathlib import Path

import pandas as pd

import sku_fix

ROOT = Path(__file__).resolve().parent
SRC, OUT = ROOT / 'generated_v4_pre_stg_trim', ROOT / 'generated_v4'
# Five-year study window. The source data ends 2026-09-08, so the window ends there in practice;
# rows before WINDOW_START are counted in the manifest and not loaded.
WINDOW_START, WINDOW_END = '2021-09-01', '2026-09-30'

# staging table: (source CSV, {source column: staging column}, window date column or None)
# Column order here is the CSV column order and must match 02_load_staging.psql.
TABLES = {
    'calendar': ('calendar.csv', {
        'date': 'date', 'day_of_week': 'day_of_week', 'dow': 'dow', 'week': 'iso_week',
        'iso_year': 'iso_year', 'week_start_date': 'week_start_date', 'month': 'month',
        'quarter': 'quarter', 'year': 'year', 'is_weekend': 'is_weekend', 'is_holiday': 'is_holiday',
        'is_payday': 'is_payday', 'is_ber_month': 'is_ber_month'}, 'date'),
    'storage_locations': ('storage_locations.csv', {
        'storage_location_id': 'storage_location_id', 'temperature_state': 'temperature_state',
        'capacity_l': 'storage_in_liters',
        'counts_toward_raw_ingredient_capacity': 'counts_toward_raw_ingredient_capacity',
        'primary_function': 'primary_function'}, None),
    'menu_items': ('menu_items.csv', {
        'item_id': 'item_id', 'item_name': 'item_name', 'display_name': 'display_name',
        'category': 'category', 'price': 'list_price',
        'sku': 'pos_sku', 'is_complimentary': 'is_complimentary',
        'is_active': 'is_active'}, None),
    'ingredients': ('ingredients.csv', {
        'ingredient_id': 'ingredient_id', 'ingredient_code': 'ingredient_code',
        'ingredient_name': 'ingredient_name', 'category': 'category', 'storage_type': 'storage_type',
        'uom': 'base_uom', 'shelf_life_days': 'shelf_life_days', 'is_perishable': 'is_perishable',
        'unit_cost': 'standard_unit_cost'}, None),
    'suppliers': ('suppliers.csv', {
        'supplier_id': 'supplier_id', 'supplier_name': 'supplier_name',
        'delivery_lead_time_days': 'lead_time_days', 'lead_time_sd_days': 'lead_time_sd_days',
        'delivery_interval_days': 'delivery_interval_days'}, None),
    # pack_size_base <- usable_qty_per_pack: the simulation puts the usable quantity of a pack into
    # stock (receipts are whole multiples of it), and standard_unit_cost is per usable unit.
    'supplier_item_terms': ('supplier_catalog.csv', {
        'supplier_id': 'supplier_id', 'ingredient_id': 'ingredient_id', 'order_unit': 'order_unit',
        'pack_size': 'pack_size', 'pack_unit': 'pack_unit', 'usable_qty_per_pack': 'pack_size_base',
        'min_order_packs': 'min_order_packs'}, None),
    'recipes': ('recipes.csv', {
        'item_id': 'item_id', 'ingredient_id': 'ingredient_id', 'qty_per_item': 'qty_base',
        'uom': 'uom'}, None),
    'sales': ('sales.csv', {
        'sale_id': 'sale_id', 'sale_date': 'sale_date', 'item_id': 'item_id', 'channel': 'channel',
        'pos_sku': 'pos_sku', 'category': 'pos_category_raw', 'quantity_sold': 'quantity_sold',
        'unit_price': 'unit_price', 'gross_sales': 'gross_sales', 'discount': 'discount',
        'net_sales': 'net_sales', 'is_complimentary': 'is_complimentary'}, 'sale_date'),
    'sales_artifact_log': ('sales_artifact_log.csv', {
        'sale_date': 'sale_date', 'item_id': 'item_id', 'quantity_sold': 'quantity_sold',
        'in_pos_export': 'in_pos_export', 'in_consumption': 'in_consumption'}, 'sale_date'),
    'inventory': ('inventory.csv', {
        'inventory_date': 'snapshot_date', 'ingredient_id': 'ingredient_id', 'supplier_id': 'supplier_id',
        'opening_stock': 'opening_qty', 'qty_received': 'qty_received', 'qty_emergency': 'qty_emergency',
        'qty_consumed': 'qty_consumed', 'qty_off_pos_use': 'qty_off_pos_use',
        'closing_stock': 'closing_qty', 'reorder_level': 'reorder_point', 'order_qty': 'order_qty',
        'on_order_qty': 'on_order_qty', 'stockout_flag': 'stockout_flag',
        'emergency_cost_php': 'emergency_cost_php'}, 'inventory_date'),
    'inventory_batches': ('inventory_batches.csv', {
        'snapshot_date': 'snapshot_date', 'batch_id': 'batch_id', 'ingredient_id': 'ingredient_id',
        'supplier_id': 'supplier_id', 'received_date': 'received_date', 'expiry_date': 'expiry_date',
        'qty_on_hand': 'qty_on_hand', 'unit_cost': 'unit_cost', 'days_to_expiry': 'days_to_expiry'},
        'snapshot_date'),
    'waste': ('waste.csv', {
        'waste_id': 'waste_id', 'waste_date': 'waste_date', 'ingredient_id': 'ingredient_id',
        'supplier_id': 'supplier_id', 'batch_id': 'batch_id', 'waste_quantity': 'waste_qty',
        'waste_reason': 'waste_reason', 'unit_cost': 'unit_cost', 'waste_value_php': 'waste_value_php',
        'received_date': 'received_date', 'expiry_date': 'expiry_date',
        'expired_on_date': 'expired_on_date', 'days_held': 'days_held'}, 'waste_date'),
}


STAGED_SALES = ROOT / 'cleaned' / 'sales_staged.csv'     # input of clean_sales.py, which writes generated_v4/sales.csv
MENU_SKU = {}
SALE_ID_OFFSET = 0


def keep_sets():
    """Ingredients and suppliers the dw uses. An ingredient with no recipe line is never consumed; a supplier with no
    supplier_item_terms row supplies no ingredient. Both are left out of the load; the full files stay in SRC."""
    rec = pd.read_csv(SRC / 'recipes.csv', dtype=str, keep_default_na=False)
    terms = pd.read_csv(SRC / 'supplier_catalog.csv', dtype=str, keep_default_na=False)
    ing_ids = set(rec['ingredient_id'])
    terms = terms[terms['ingredient_id'].isin(ing_ids)]
    return {'ingredient_id': ing_ids, 'supplier_id': set(terms['supplier_id'])}


def prune(table, df, keep):
    """Drops rows of an unused ingredient / supplier. Inventory rows of a dropped ingredient must all be zero and it
    must have no batch or waste row, so nothing that was consumed, bought or wasted is lost."""
    if table in ('suppliers',):
        out = df[df['supplier_id'].isin(keep['supplier_id'])]
    elif table in ('ingredients', 'supplier_item_terms', 'inventory', 'inventory_batches', 'waste'):
        gone = ~df['ingredient_id'].isin(keep['ingredient_id'])
        if table in ('inventory_batches', 'waste'):
            assert not gone.any(), f'{table}: rows for an ingredient without a recipe'
        if table == 'inventory':
            num = [c for c in TABLES['inventory'][1] if c not in ('inventory_date', 'ingredient_id', 'supplier_id', 'stockout_flag')]
            assert (df.loc[gone, num].apply(pd.to_numeric) == 0).all().all(), 'inventory: activity for an unused ingredient'
        out = df[~gone]
    else:
        return df
    if len(out) != len(df):
        print(f'  {table}: {len(df) - len(out)} rows of unused ingredients / suppliers left out')
    return out


def main():
    global SKU_MAP, SALE_ID_OFFSET
    SKU_MAP = sku_fix.build_mapping()
    keep = keep_sets()
    OUT.mkdir(exist_ok=True)
    manifest, used = [], set()
    for table, (src, cols, date_col) in TABLES.items():
        df = pd.read_csv(SRC / src, low_memory=False, keep_default_na=False, dtype=str)
        missing = set(cols) - set(df.columns)
        if missing:
            raise SystemExit(f'{src}: missing source columns {sorted(missing)}')
        n_in = len(df)
        if table in ('menu_items', 'sales'):    # invalid POS SKUs -> assigned 5-digit codes (see sku_fix.py)
            col = 'sku' if table == 'menu_items' else 'pos_sku'
            df[col] = sku_fix.apply(df[col].astype('int64'), SKU_MAP).astype('int64').astype(str)
        if table == 'menu_items':
            # Filter out synthetic items (documentation only, not loaded to dw)
            if 'is_synthetic' in df.columns:
                df = df[df['is_synthetic'] != 'True'].copy()
            MENU_SKU.update(dict(zip(df['item_id'].astype(int), df['sku'].astype('int64'))))
        if table == 'recipes':
            # Filter out synthetic items (documentation only, not loaded to dw)
            df['item_id'] = df['item_id'].astype(int)
            df = df[df['item_id'].isin(MENU_SKU.keys())].copy()
        if table == 'sales':
            # sale_id restarts at 1 for the study window (team decision 2026-10-09). Ids run without a gap from the
            # first in-window line, so new id = old id - SALE_ID_OFFSET (4023 on the current data).
            old_id = df['sale_id'].astype('int64')
            SALE_ID_OFFSET = int(old_id[df['sale_date'] >= WINDOW_START].min()) - 1
            df['sale_id'] = (old_id - SALE_ID_OFFSET).astype(str)
            # The menu's SKU wins (team decision 2026-10-09): a sale line carries its menu item's SKU, so menu and
            # sales agree in every dataset. The lines whose own POS SKU differed are listed in sku_line_overrides.csv.
            menu_sku = df['item_id'].astype(int).map(MENU_SKU)
            line_sku = df['pos_sku'].astype('int64')
            diff = menu_sku.notna() & (line_sku != menu_sku)
            df.loc[diff, ['sale_id', 'sale_date', 'item_id', 'pos_sku']].assign(menu_sku=menu_sku[diff].astype('int64'))                 .rename(columns={'pos_sku': 'line_sku_before'}).to_csv(ROOT / 'sku_line_overrides.csv', index=False)
            df.loc[diff, 'pos_sku'] = menu_sku[diff].astype('int64').astype(str)
        pre = post = 0
        if date_col:
            pre = int((df[date_col] < WINDOW_START).sum())
            post = int((df[date_col] > WINDOW_END).sum())
            df = df[(df[date_col] >= WINDOW_START) & (df[date_col] <= WINDOW_END)]
        df = prune(table, df, keep)          # ingredients / suppliers that nothing in the dw uses (team decision 2026-10-09)
        if table == 'waste':                 # label wording of fact_waste's check constraint (01_schema.sql); the source files spell it differently
            df['waste_reason'] = df['waste_reason'].replace({'EXPIRED_DURING_CLOSURE': 'Expired during closure',
                                                             'expired during closure': 'Expired during closure'})
        if table == 'waste':                 # waste_id restarts at 1 for the study window (team decision 2026-10-09)
            old_id = df['waste_id'].astype('int64')
            waste_id_offset = int(old_id.min()) - 1
            df['waste_id'] = (old_id - waste_id_offset).astype(str)
        text = df[list(cols)].rename(columns=cols).to_csv(index=False, lineterminator='\n')
        target = STAGED_SALES if table == 'sales' else OUT / f'{table}.csv'   # sales is finished by clean_sales.py
        if not target.exists() or target.read_bytes() != text.encode('utf-8'):   # unchanged files stay untouched
            target.write_bytes(text.encode('utf-8'))
        used.add(src)
        manifest.append(dict(source_file=src, staging_table=f'stg.{table}', rows_in=n_in,
                             rows_before_window=pre, rows_after_window=post, rows_out=len(df),
                             columns_in=len(df.columns), columns_kept=len(cols),
                             columns_dropped=';'.join(c for c in df.columns if c not in cols)))
    # Register of POS double-logs removed upstream: it shares the sales id space (ids sit in the gaps of sales),
    # so it moves with it. Lines before the window drop out of the register, as they do from sales (full copy in SRC).
    AUDIT = ROOT / 'generated_v4_audit'
    dups = pd.read_csv(SRC / 'sales_duplicates_removed.csv', low_memory=False)
    dups = dups[(dups['sale_date'] >= WINDOW_START) & (dups['sale_date'] <= WINDOW_END)].copy()
    dups['sale_id'] -= SALE_ID_OFFSET
    dups['duplicate_of_sale_id'] = (dups['duplicate_of_sale_id'] - SALE_ID_OFFSET).astype('Int64')
    kept_ids = set(pd.read_csv(STAGED_SALES, usecols=['sale_id'])['sale_id'])
    assert dups['sale_id'].min() >= 1 and not set(dups['sale_id']) & kept_ids, 'duplicate ids collide with sales'
    assert dups['duplicate_of_sale_id'].isin(kept_ids).all(), 'a removed copy points at a line outside sales'
    AUDIT.mkdir(exist_ok=True)
    dups.to_csv(AUDIT / 'sales_duplicates_removed.csv', index=False)
    print(f'sale_id: new = old - {SALE_ID_OFFSET}; duplicates register {len(dups)} rows renumbered')
    for f in sorted(SRC.glob('*.csv')):          # audit / lineage registers: not part of the dw load
        if f.name not in used:
            df = pd.read_csv(f, low_memory=False)
            cols = df.columns
            manifest.append(dict(source_file=f.name, staging_table='(not loaded)', rows_in=len(df),
                                 rows_before_window=0, rows_after_window=0, rows_out=0,
                                 columns_in=len(cols), columns_kept=0, columns_dropped=';'.join(cols)))
    pd.DataFrame(manifest).to_csv(OUT / 'MANIFEST.csv', index=False)
    for m in manifest:
        print(f"{m['source_file']:32} -> {m['staging_table']:26} rows {m['rows_in']:>7} -> {m['rows_out']:>7}"
              f"  (pre-window {m['rows_before_window']}), cols {m['columns_in']} -> {m['columns_kept']}")


if __name__ == '__main__':
    main()
