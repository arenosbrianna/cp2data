"""
Makisushi dataset v3 = v2 + the SYNTHETIC recipe supplement (synthetic_recipes/).

Everything in v2 is reused unchanged (same seed, same sales, same simulation code).
The only difference is the recipe input: before the simulation runs, v3 adds
  * 4 ingredients (Japanese rice, miso paste, mango, ground beef), priced from the
    owner's SUPPLY-UR sheet like every other ingredient, with SYNTHETIC supplier terms;
  * the recipe lines in synthetic_recipes/recipe_additions.csv (recipes for items that
    had none, rice in rice dishes, miso soup with sets, Set B add-ons).
Every added recipe line is marked in generated_v3/recipes.csv:
    recipe_source = 'SYNTHETIC:<rule>', is_synthetic = True
MENU2-derived lines keep recipe_source MENU2 / NAME_MATCH / NAME_MATCH+SET_B.

generated/ and generated_v2/ are never written. Output: generated_v3/.
Run:  py synthetic_recipes/build_synthetic_recipes.py   (if the rules changed)
      py makisushi_datagen_v3.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

import makisushi_datagen_v2 as v2

SUPP = Path(__file__).resolve().parent / "synthetic_recipes"
_v2_load_dimensions = v2.load_dimensions
_DIMS = {}


def load_dimensions(cfg) -> dict:
    dims = _v2_load_dimensions(cfg)
    ing, terms, bom, sup = dims["ingredients"], dims["terms"], dims["bom"], dims["suppliers"]
    add_i = pd.read_csv(SUPP / "ingredient_additions.csv")
    add_r = pd.read_csv(SUPP / "recipe_additions.csv")
    rate = dims["supply_ref"].set_index("product")["rate_per_base"]
    sid = dict(zip(sup["supplier_name"], sup["supplier_id"]))

    next_id = int(ing["ingredient_id"].max()) + 1
    new_rows, new_terms = [], []
    for k, r in enumerate(add_i.itertuples()):
        iid = next_id + k
        cost = float(rate[r.supply_ur_product])
        new_rows.append(dict(ingredient_id=iid, ingredient_code=r.ingredient_code, ingredient_name=r.ingredient_name,
                             category=r.category, storage_type=r.storage_type, uom=r.uom,
                             shelf_life_days=int(r.shelf_life_days), is_perishable=bool(r.is_perishable),
                             unit_cost=round(cost, 4), cost_source=f"SUPPLY-UR: {r.supply_ur_product}",
                             catalog_unit_cost=float("nan"), name_source="SYNTHETIC supplement",
                             menu2_codes="SYNTHETIC"))
        new_terms.append(dict(supplier_id=sid[r.supplier_name], ingredient_id=iid, order_unit=r.order_unit,
                              pack_size=r.pack_size, pack_unit=r.pack_unit, pack_size_base=r.pack_size_base,
                              min_order_packs=int(r.min_order_packs)))
    ing = pd.concat([ing, pd.DataFrame(new_rows)[ing.columns]], ignore_index=True)
    terms = pd.concat([terms, pd.DataFrame(new_terms)[terms.columns]], ignore_index=True)
    code_id = dict(zip(ing["ingredient_code"], ing["ingredient_id"]))

    add = pd.DataFrame(dict(
        item_name=add_r["item_name"], ingredient_code=add_r["ingredient_code"], qty_base=add_r["qty_per_item"],
        menu2_code="", derivation="SYNTHETIC (" + add_r["rule"] + "): " + add_r["basis"],
        item_id=add_r["item_id"].astype(int), recipe_source="SYNTHETIC:" + add_r["rule"],
        source_dish=add_r["item_name"], ingredient_id=add_r["ingredient_code"].map(code_id).astype(int)))
    clash = add.merge(bom[["item_id", "ingredient_id"]], on=["item_id", "ingredient_id"])
    if len(clash):
        raise ValueError(f"synthetic lines would overwrite {len(clash)} existing recipe lines")
    bom = pd.concat([bom, add[bom.columns]], ignore_index=True)
    dims.update(ingredients=ing, terms=terms, bom=bom)
    _DIMS.update(dims)
    return dims


def run() -> dict:
    v2.load_dimensions = load_dimensions          # v2.run() resolves it at call time
    cfg = v2.Config(out_dir=Path("generated_v3"), remove_closure_days=True)
    tables = v2.run(cfg)
    # provenance on every recipe line (v2's export drops it)
    bom = _DIMS["bom"][["item_id", "ingredient_id", "recipe_source"]]
    rec = tables["recipes"].merge(bom, on=["item_id", "ingredient_id"], how="left")
    rec["is_synthetic"] = rec["recipe_source"].str.startswith("SYNTHETIC")
    rec.to_csv(cfg.out_dir / "recipes.csv", index=False)
    rec.to_parquet(cfg.out_dir / "recipes.parquet", index=False)
    print(f"recipes.csv: {len(rec)} lines, {int(rec.is_synthetic.sum())} SYNTHETIC")
    return tables


if __name__ == "__main__":
    run()
