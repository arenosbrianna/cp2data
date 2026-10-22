"""Build data_dictionary.csv — one row per column across all eight exports.

Descriptions and source tags come from MAKISUSHI_SPEC.md §5; the profile columns
(dtype, fill rate, distinct count, range, example) are measured from the files,
so the dictionary cannot drift from the data it documents.

Source tags (spec §5):
  F  fixed from the owner's files      K  kept real (never resampled)
  G  generated backfill (< 2025-12-01) S  simulated across the full span
  D  derived at export time

  python make_data_dictionary.py
"""

from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "generated"
OUT = Path(__file__).parent / "data_dictionary.csv"

# (key, units, source, description) per table.column
SPEC: dict[str, dict[str, tuple]] = {
    "sales": {
        "sale_id": ("PK", "", "D", "Surrogate key, one row per item per day."),
        "date_id": ("FK", "yyyymmdd", "D", "Trading day; joins to calendar.date_id."),
        "item_id": ("FK", "", "F", "Menu item sold; joins to menu_items.item_id."),
        "sku": ("", "", "F", "Point-of-sale SKU as printed on the owner's export. "
                "Not a key — use item_id. 99% are clean 5-digit codes, but 13 items "
                "carry malformed repeated-digit values (e.g. 1064144444) and 6 are 0. "
                "Kept as-is: the owner's file is ground truth."),
        "category": ("", "", "F", "Menu section, e.g. MAKI ROLLS. Spelling varies by "
                     "row — inconsistent labelling is reproduced, not scrubbed."),
        "quantity_sold": ("", "units", "K/G", "Units of this item sold that day. "
                          "Mean 1.41, 75% are exactly 1, max 16; drawn from a "
                          "Negative-Binomial so the count is overdispersed."),
        "unit_price": ("", "PHP", "F", "Menu price per unit at time of sale."),
        "gross_sales": ("", "PHP", "K/G", "unit_price x quantity_sold, before discount."),
        "discount": ("", "PHP", "K/G", "Peso value discounted. Applied on ~26% of "
                     "lines at a median ~7% of gross (Bernoulli x Beta)."),
        "net_sales": ("", "PHP", "K/G", "gross_sales minus discount. Zero or negative "
                      "on management comps."),
        "cost_of_goods": ("", "PHP", "K", "EMPTY ON EVERY ROW. The owner's POS never "
                          "populated it, so gross profit cannot be derived from this "
                          "table. Kept empty deliberately."),
        "taxes": ("", "PHP", "K/G", "Tax charged; zero on all but ~0.4% of lines."),
        "channel": ("", "", "S", "dine-in or GrabFood. Delivery share was high in "
                    "2021 and decays toward a tenth of trade by 2026."),
        "is_comp": ("", "bool", "K/G", "True where the line was comped (MANAGEMENT "
                    "category, net <= 0). About 5% of rows."),
    },
    "inventory": {
        "inventory_id": ("PK", "", "D", "Surrogate key, one row per ingredient per day."),
        "date_id": ("FK", "yyyymmdd", "D", "Stock day; joins to calendar.date_id."),
        "ingredient_id": ("FK", "", "F", "Joins to ingredients.ingredient_id."),
        "supplier_id": ("FK", "", "S", "Supplier this line is normally bought from; "
                        "joins to suppliers.supplier_id."),
        "opening_stock": ("", "uom", "S", "On hand at the start of the day."),
        "qty_received": ("", "uom", "S", "Delivered that day, after the supplier's "
                         "lead time; short-shipped when the fill rate misses."),
        "qty_consumed": ("", "uom", "S", "Drawn by the dishes actually sold: the sum "
                         "over dishes of units sold x recipe quantity. Equals "
                         "recipe-implied demand exactly unless stock ran out."),
        "qty_wasted": ("", "uom", "S", "Total discarded that day; itemised in waste.csv."),
        "closing_stock": ("", "uom", "S", "On hand at end of day. The ledger balances: "
                          "closing = opening + received - consumed - wasted."),
        "reorder_level": ("", "uom", "S", "Reorder point s = mean lead-time demand + "
                          "z x sd, with z = 1.41 (~92% service level)."),
        "order_qty": ("", "uom", "S", "Placed that day, rounded up to a whole pack and "
                      "inflated by the manager's ordering bias. Zero on days with no "
                      "review or no trigger."),
        "on_order_qty": ("", "uom", "S", "Ordered but not yet delivered."),
        "stockout_flag": ("", "bool", "S", "True where demand could not be met in "
                          "full from stock — the shortfall is a lost sale."),
    },
    "waste": {
        "waste_id": ("PK", "", "D", "Surrogate key, one row per disposal event."),
        "date_id": ("FK", "yyyymmdd", "D", "Day of disposal; joins to calendar."),
        "ingredient_id": ("FK", "", "F", "Joins to ingredients.ingredient_id."),
        "supplier_id": ("FK", "", "S", "Who delivered the spoiled batch — spoilage "
                        "attributes back to a supplier and its lead time."),
        "batch_id": ("", "", "S", "Internal FEFO batch that spoiled. 0 for prep-trim, "
                     "which is not tied to a single batch."),
        "waste_quantity": ("", "uom", "S", "Quantity discarded, in the ingredient's uom."),
        "uom": ("", "", "F", "Unit of measure: g, ml or pc."),
        "waste_reason": ("", "", "S", "expiry (aged past its effective shelf life), "
                         "overstock (expired while holding well above normal usage), "
                         "or prep-trim (unavoidable kitchen loss, 4-6% of throughput)."),
        "unit_cost": ("", "PHP/uom", "F", "Cost of that batch, from the supplier's "
                      "real unit rate plus its fluctuation band."),
        "waste_value_php": ("", "PHP", "D", "waste_quantity x unit_cost — the capital "
                            "thrown away."),
        "received_date": ("", "date", "S", "When the spoiled batch was delivered."),
        "expiry_date": ("", "date", "S", "When it expired. Effective shelf life varies "
                        "with batch quality and weather, so it is not simply "
                        "received_date + shelf_life_days."),
        "days_held": ("", "days", "D", "Days between receipt and disposal."),
    },
    "suppliers": {
        "supplier_id": ("PK", "", "D", "Surrogate key."),
        "supplier_name": ("", "", "F", "Real supplier name from the owner's SUPPLY-UR sheet."),
        "category_served": ("", "", "F", "What they supply, e.g. seafood/frozen."),
        "lead_time_mean": ("", "days", "S", "Average days from order to delivery. "
                           "Inflated by bad weather; capped below a perishable's "
                           "shelf life, since it cannot outlive the trip."),
        "lead_time_sd": ("", "days", "S", "Day-to-day variability in that lead time."),
        "fill_rate": ("", "0-1", "S", "Share of orders delivered in full; the rest "
                      "arrive short."),
        "min_order_qty": ("", "packs", "S", "Minimum order the supplier accepts."),
        "delivery_cadence_days": ("", "days", "S", "How often they run a delivery route."),
    },
    "menu_items": {
        "item_id": ("PK", "", "D", "Surrogate key."),
        "sku": ("", "", "F", "Point-of-sale SKU. Not unique and not a key — 13 "
                "values are malformed and 6 items have 0. Join on item_id."),
        "item_name": ("", "", "F", "Dish name as printed on the menu. A few carry "
                      "encoding corruption from the source export (e.g. "
                      "'Lemonadeuecea') and some near-duplicates differ only by "
                      "spelling."),
        "category": ("", "", "F", "Menu section."),
        "price": ("", "PHP", "F", "Menu price, taken from the owner's sales export."),
        "is_promo": ("", "bool", "F", "Promotional item; year-stamped promos only sell "
                     "in their own year."),
        "is_comp": ("", "bool", "F", "Item used for management comps."),
        "is_active": ("", "bool", "F", "Currently on the menu."),
        "date_introduced": ("", "date", "F", "First day it could be sold. Delivery-only "
                            "items phase in during 2022."),
        "date_retired": ("", "date", "F", "Last day it could be sold. EMPTY ON EVERY "
                         "ROW — nothing has been withdrawn from the menu yet."),
    },
    "ingredients": {
        "ingredient_id": ("PK", "", "D", "Surrogate key."),
        "ingredient_code": ("", "", "F", "The owner's recipe code, e.g. TUN, CF_060."),
        "ingredient_name": ("", "", "F", "Product name cross-referenced from the "
                            "purchasing catalogue."),
        "category": ("", "", "F", "Ingredient family: seafood, pork, veg, sauce, ..."),
        "storage_type": ("", "", "F", "ambient, chilled or frozen."),
        "uom": ("", "", "F", "Unit of measure: g, ml or pc."),
        "portion_g": ("", "g", "F", "Grams in one portion, for portion-coded lines "
                      "such as CF_060 (60 g chicken fillet). Empty for bulk lines."),
        "pack_size": ("", "uom", "D", "Purchase pack, used to round orders up. Capped "
                      "so a short-life line is not bought in quantities it cannot use."),
        "shelf_life_days": ("", "days", "F", "Nominal shelf life (USDA FoodKeeper). "
                            "Fish 1-2 d, leafy veg 3-7 d, frozen 60-180 d."),
        "is_perishable": ("", "bool", "F", "Subject to spoilage."),
        "unit_cost": ("", "PHP/uom", "F", "Cost per unit, from the owner's supplier "
                      "rate sheet."),
        "name_inferred": ("", "bool", "F", "True where the code could not be matched "
                          "to the catalogue and the name is a best guess — BAR, KAL "
                          "and SAS only. Ask the owner before relying on these."),
    },
    "recipes": {
        "item_id": ("FK", "", "F", "Dish; joins to menu_items.item_id."),
        "ingredient_id": ("FK", "", "F", "Joins to ingredients.ingredient_id."),
        "ingredient_code": ("", "", "F", "The owner's recipe code, for readability."),
        "qty_per_unit": ("", "mixed", "F", "The owner's own recipe number, AS WRITTEN. "
                         "Units are inconsistent in the source: portion-coded lines "
                         "state portions, bulk lines state grams, though both are "
                         "labelled g. Use qty_base for arithmetic."),
        "qty_base": ("", "uom", "D", "qty_per_unit normalised to the ingredient's base "
                     "unit (portions multiplied out by portion_g). This is what "
                     "consumption is computed from."),
        "uom": ("", "", "F", "Base unit the normalised quantity is expressed in."),
    },
    "calendar": {
        "date": ("", "date", "D", "Calendar date, 2021-01-01 to 2026-09-08."),
        "date_id": ("PK", "yyyymmdd", "D", "Integer date key used by every fact table."),
        "day_of_week": ("", "", "D", "Day name, Monday to Sunday."),
        "dow": ("", "0-6", "D", "Day index, 0 = Monday. Wednesday (2) is the sales peak."),
        "week": ("", "1-53", "D", "ISO week number."),
        "month": ("", "1-12", "D", "Calendar month."),
        "quarter": ("", "1-4", "D", "Calendar quarter."),
        "year": ("", "", "D", "Calendar year."),
        "is_weekend": ("", "bool", "D", "Saturday or Sunday. Note the trade peak is "
                       "midweek, not at the weekend — this is an office district."),
        "is_holiday": ("", "bool", "D", "Philippine public holiday."),
        "is_payday": ("", "bool", "D", "15th or month end, when spending lifts 8-15%."),
        "is_ber_month": ("", "bool", "D", "September to December, the Philippine peak "
                         "retail season."),
    },
}


def build() -> pd.DataFrame:
    rows = []
    for table, cols in SPEC.items():
        df = pd.read_csv(DATA / f"{table}.csv")

        missing = set(df.columns) - set(cols)
        extra = set(cols) - set(df.columns)
        if missing or extra:
            raise SystemExit(
                f"{table}.csv does not match the dictionary — "
                f"undocumented: {sorted(missing) or 'none'}; "
                f"documented but absent: {sorted(extra) or 'none'}"
            )

        for col in df.columns:                       # file order, not dict order
            key, units, source, desc = cols[col]
            s = df[col]
            if pd.api.types.is_bool_dtype(s):
                rng = f"{s.mean()*100:.1f}% true"
            elif units == "yyyymmdd":
                rng = f"{int(s.min())} to {int(s.max())}"
            elif pd.api.types.is_numeric_dtype(s) and s.notna().any():
                whole = float(s.dropna().mod(1).max()) == 0
                fmt = ",.0f" if whole else ",.2f"
                rng = f"{s.min():{fmt}} to {s.max():{fmt}}"
            elif s.notna().any():
                rng = f"{s.nunique():,} distinct"
            else:
                rng = "always empty"
            rows.append({
                "table": table,
                "column": col,
                "key": key,
                "dtype": str(s.dtype),
                "units": units,
                "source": source,
                "description": desc,
                "non_null_pct": round(s.notna().mean() * 100, 1),
                "distinct": s.nunique(dropna=True),
                "range_or_values": rng,
                "example": s.dropna().iloc[0] if s.notna().any() else "",
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    dd = build()
    dd.to_csv(OUT, index=False, encoding="utf-8-sig")   # utf-8-sig so Excel is happy
    print(f"wrote {OUT.name} — {len(dd)} columns across {dd.table.nunique()} tables")
    print(dd.groupby("table", sort=False).size().to_string())
    print("\nsource tags: F fixed from the owner's files · K kept real · "
          "G generated backfill · S simulated · D derived")
