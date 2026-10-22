# Makisushi Synthetic Dataset Generator — Master Specification (LOCKED)

> **Handoff doc for Claude Code.** The single source of truth: goal, output files, schema, the data-generating chain, formulas, locked parameters, constraints, decisions, and current build progress. Pairs with the code module `makisushi_generator.py` (Section 1 = dimensions/recipes, already built & verified). **Status: plan finalized; Sections 2–6 not yet coded.**

---

## 0. Orientation (read first)

- **What this is:** a formula-driven synthetic data generator for a capstone DSS on *perishable raw-material inventory & food-waste reduction* for **Makisushi** (Japanese restaurant, Panay Ave × EDSA, Quezon City).
- **Core rule of this project:** *everything the owner uploaded is the baseline / ground truth. We keep it exactly, and only generate what is missing.* (See §1–2.)
- **Golden rule:** numeric data is generated from **math**, never from an LLM (one narrow exception: free-text fields, budget ₱250 — §11).
- **Status:** Section 1 (dimensions + recipes) DONE & verified in `makisushi_generator.py`. Plan fully finalized (this doc). **Next task: Section 2 — generate `sales.csv`.**
- **Today:** 2026-09-21. Real data runs through 2026-09-08.

**Terminology note:** "**recipes**" = the bill of materials (BOM) = the owner's `MENU2` sheet mapping each dish to its ingredient quantities. Earlier drafts called this "BOM"; the file is `recipes.csv`.

---

## 1. Context & goal

Makisushi buys perishables daily and estimates demand by hand → over-ordering (spoilage, tied-up cash) and under-ordering (stockouts, lost sales). The capstone builds a decision-support layer (forecasting → linear-program replenishment → Power BI dashboard) and needs ~5 years of Sales, Inventory, Waste, and Supplier data.

The owner provided **fake but authoritative** data for a recent window only, plus the menu/ingredients/recipes. We **keep all of it** and **generate the missing pieces** so the combined dataset behaves like 5 real years. The generator is also a reusable **Eskwelabs teaching dataset**. Because the data is fake, **no de-identification is needed** — the files are used as ground truth.

---

## 2. The reframe — keep everything real, generate only what's missing

**What we KEEP exactly (baseline / ground truth, from the uploads):**
- Menu, prices, categories (`SALES'26`, `MAKISUSHI-MENU.xlsx`)
- Ingredients, pack sizes, product names, some prices (`INGREDIENTS.xlsx`, `EGG+VEG`)
- Recipes (`MENU2`)
- Supplier names + unit rates + fluctuation % (`SUPPLY-UR`)
- **Real sales for 2025-12-01 → 2026-09-08** (kept unchanged)

**What we GENERATE (the missing data):**
1. **Sales history 2021-01-01 → 2025-11-30** — the years the owner didn't have.
2. **Inventory, Waste, and Supplier-order records for the FULL span 2021-01-01 → 2026-09-08** — these were **never logged for any period**, so there is no real version to keep; they are generated from scratch, *driven by* the real + synthetic sales through the recipes.

**Seam** `t* = 2025-12-01`. Backfill sales = `t < t*`; real sales kept for `t ≥ t*`. The backfill must be **statistically continuous at the seam** (same Wednesday-peak weekly shape, item mix, price points, discount/comp rates, volume level) so the stitched 2021→2026 series looks like one dataset.

---

## 3. Output — 8 files

### The 4 generated datasets (what the capstone asked for)

| # | File | Table | Grain | Real / Synthetic |
|---|---|---|---|---|
| 1 | `sales.csv` | `fact_sales` | item × day | real Dec'25–Sep'26 **+** synthetic 2021→Nov'25 |
| 2 | `inventory.csv` | `fact_inventory` | ingredient × day (full daily panel) | 100% simulated |
| 3 | `waste.csv` | `fact_waste` | **waste event** (standalone log) | 100% simulated |
| 4 | `suppliers.csv` | `dim_supplier` | supplier | 9 real names + synthetic dynamics |

### The 4 reference tables (real anchors — exported so foreign keys resolve)

| # | File | Table | Rows |
|---|---|---|---|
| 5 | `menu_items.csv` | `dim_menu_item` | 446 |
| 6 | `ingredients.csv` | `dim_ingredient` | 54 |
| 7 | `recipes.csv` | `bom` | 828 lines |
| 8 | `calendar.csv` | `dim_date` | 2,077 |

**Output format:** CSV **+** Parquet (decision E1). **Latent variables are stripped from every file** (§9).

---

## 4. Source files (real inputs) — `/mnt/project/` (repoint `Config.src_dir` as needed)

**`makisushi_Jan_2026.xlsx`** (multi-sheet, the main source):
- `SALES'26` — **calibration anchor.** 8,305 rows, **2025-12-01 → 2026-09-08**, 278 trading days, 446 items, 29 categories. Grain ≈ item × day.
- `MENU2` — **the recipes** (long: code · dish · qty). 829 lines, 304 dishes, 54 ingredient codes.
- `SUM-SALES25` — pivot; used only for ingredient portion names (e.g. `CF_060 = Chicken Fillet 60 g`).
- `SUPPLY-UR` — 9 suppliers, product unit rates (₱), Wastage/Fluctuation %.
- `EGG+VEG` — vegetable sub-recipes (fresh produce grams: cabbage/carrot/togue/onion/bell pepper).
- `COSTING`, `PMTT SUM`, `PMNTS BRKDWN` — costs & daily totals (secondary).

**`INGREDIENTS.xlsx`** — purchasing catalog by **brand + product name + packaging**, 6 sheets (Dry ~240, Frozen, Shrimp, Squid/Fishes, Beef, Sake). **No code column** — cross-referenced to recipe codes by name (see §12 / Appendix B). Source of **real ingredient names, pack sizes, and some prices** (e.g. Tuna Loin ₱560/kg, Tuna Belly ₱380, Cream Dory ₱130).

**`MAKISUSHI-MENU.xlsx`** — printed menu (messy; prices better taken from `SALES'26`).

### Key empirical findings (calibration targets)
- **Wednesday peak confirmed & measured:** Wed ≈ 48 items / ₱13.5k/day; Sun & Mon ≈ 35 / ₱9.0k. Midweek-lunch (office district). Kills the "weekends busiest" assumption.
- **Volume:** ~42 items and ~₱11.1k net/day; rare blow-out days (max ₱55k = catering).
- **Monthly totals flat** in-window (~₱286k–416k net) → trend is imposed (§8).
- **Item concentration:** top 10% of items = 59% of units; California Maki = 910 units. Long sparse tail.
- **Quantity/row:** mean 1.41, max 16, 75% == 1.
- **Real messiness (reproduce, don't scrub):** COGS empty on 100% of rows (Margin bogus = 1.0); ~5% of lines ₱0/negative (comps → `MANAGEMENT`, 393 rows); 26% of lines discounted (~7% median of gross); inconsistent category labels.

---

## 5. Schema + data dictionary

```
calendar ─┐                        ┌─ menu_items ─┐
          ├─< sales >──────────────┤              ├─< recipes >─┐
          │      (item × day)      │              │            │
          ├─< inventory >── ingredients ───────────┘            │
          │      (ingredient × day)        recipes bridge dish→ingredient
          └─< waste >──── ingredients / suppliers   (event log)
                          suppliers
```

**Grain fix (resolves the capstone's flagged issue):** `sales` is item-grain (no ingredient_id); the dish→ingredient mapping lives in `recipes`; ingredient-level stock/consumption lives in `inventory`; disposals live in `waste`.

### `sales.csv` — `fact_sales` — grain item × day — `K` real + `G` backfill (columns mirror `SALES'26`)
| feature | type | notes |
|---|---|---|
| sale_id (PK) / date_id (FK) / item_id (FK) / sku | int | |
| category | str | |
| quantity_sold | int | mostly 1 (75%), max 16 → Negative-Binomial |
| unit_price / gross_sales | float | gross = price × qty |
| discount / net_sales | float | net = gross − discount |
| cost_of_goods | null | **left empty (real artifact)** |
| taxes | float | mostly 0, rare nonzero |
| channel | str | dine-in / GrabFood (latent-driven, time-varying) |
| is_comp | bool | MANAGEMENT, net ≤ 0 |

### `inventory.csv` — `fact_inventory` — grain ingredient × day (full daily panel) — `S`
| feature | type | notes |
|---|---|---|
| inventory_id (PK) / date_id (FK) / ingredient_id (FK) / supplier_id (FK) | int | |
| opening_stock / qty_received / qty_consumed / qty_wasted / closing_stock | float | **closing = opening + received − consumed − wasted** (ledger balances) |
| reorder_level / order_qty / on_order_qty | float | ordering policy; order_qty ceil-to-pack; PO folded in (no PO file) |
| stockout_flag | bool | demand unmet within lead time |

`qty_wasted` here is the **daily total**; the itemized breakdown lives in `waste.csv`.

### `waste.csv` — `fact_waste` — grain waste event (standalone log) — `S`
| feature | type | notes |
|---|---|---|
| waste_id (PK) | int | |
| date_id (FK) | int | day of disposal |
| ingredient_id (FK) / supplier_id (FK) | int | supplier = the spoiled batch's source |
| batch_id | int | the spoiled batch (FEFO internal) |
| waste_quantity / uom | float/str | |
| waste_reason | str | **expiry · overstock · prep-trim** |
| unit_cost / waste_value_php | float | qty × cost → "excess capital tied up" |
| received_date / expiry_date / days_held | date/int | how long it sat before disposal |

### `suppliers.csv` — `dim_supplier` — names `F`, dynamics `S`
| feature | type | notes |
|---|---|---|
| supplier_id (PK) / supplier_name | int/str | 9 real names |
| category_served | str | |
| lead_time_mean / lead_time_sd | float | `S` (weather inflates actual lead time) |
| fill_rate | float | `S` |
| min_order_qty / delivery_cadence_days | int | `S` |

### `menu_items.csv` — `dim_menu_item` — `F`
`item_id (PK) · sku · item_name · category · price · est_unit_cost · is_promo · is_comp · is_active · date_introduced · date_retired`
(A+ menu evolution: year-stamped promos fire in their year; delivery phases in 2022 — §12.)

### `ingredients.csv` — `dim_ingredient` — `F` (names/packs/prices from `INGREDIENTS.xlsx`+`EGG+VEG`; shelf life from literature)
`ingredient_id (PK) · ingredient_code · ingredient_name · category · storage_type · uom · portion_g · pack_size · shelf_life_days · is_perishable · unit_cost · name_inferred`

### `recipes.csv` — `bom` — `F` (from `MENU2`)
`item_id (FK) · ingredient_id (FK) · ingredient_code · qty_per_unit · uom`

### `calendar.csv` — `dim_date` — `F`
`date_id (PK) · date · day_of_week · dow(0=Mon) · week · month · quarter · year · is_weekend · is_holiday(PH) · is_payday(15th & month-end) · is_ber_month(Sep–Dec)`

**Source tags:** `F` fixed-from-files · `K` kept-real · `G` generated-backfill · `S` simulated-full-span · `L` latent (**stripped**).

---

## 6. The data-generating chain (how the 4 datasets stay connected)

Every generated number flows through one chain, so sales, inventory, suppliers, and waste are linked on every day for all 5+ years — not four unrelated random tables:

```
 a dish is sold           →  recipes tell us its ingredients  →  ingredients drawn from stock
 (sales.csv)                 (recipes.csv)                        (inventory: qty_consumed)
        │                                                                   │
        │                                              stock low? reorder from supplier
        │                                              (inventory: order_qty ← suppliers.csv)
        │                                                                   │
        └───────────── stock expires before use? it's thrown out ──────────┘
                        (waste.csv event  +  inventory: qty_wasted)
```

Formally: `qty_consumed[g,t] = Σ_dishes  quantity_sold[dish,t] × recipe_qty[dish,g]`. Inventory is a running ledger drawn down by consumption and replenished by supplier orders; waste is what the ledger loses to spoilage. **This is why sales and inventory are connected throughout the dataset.**

---

## 7. Formal model

### 7.1 Modeling style
Hybrid: latent daily states → probabilistic time-series demand per item×day (multiplicative decomposition × Negative-Binomial) → deterministic recipe disaggregation → recursive discrete-time inventory/ordering sim with (R,s,S) policy + manager-bias distortion → per-batch FEFO spoilage → observation layer (artifacts + **drop latents**).

### 7.2 Sampling order (topological)
```
1  Reference tables: calendar · menu_items(+intro/retire) · ingredients(+shelf_life+cost)
                     · suppliers(+lead/reliability) · recipes                 [SECTION 1 ✅ + cost merge]
2  Latent daily series (full span): u_t (area activity) · w_t (weather) · m_t (mgr bias)
3  Demand quantity_sold[i,t]:  synthesize backfill (t < t*),  KEEP real (t ≥ t*)     → sales.csv
4  Sales financials + discount/comp/tax + logging artifacts                          → sales.csv
5  Consumption qty_consumed[g,t] = Σ_i sold[i,t]·recipe[i,g]                (deterministic)
6  Inventory recursion (orders, receipts, stock, stockouts)                          → inventory.csv
7  Spoilage per batch (FEFO)                                                          → waste.csv (+ qty_wasted)
8  DROP latents u,w,m,batch_quality · apply artifacts · export 8 files
```

### 7.3 Latent state processes (sampled first, **never exported**)
```
Area activity (common demand factor):  u_t = ρ_u·u_{t-1} + η^u ,  η^u~N(0,σ_u²)   ρ_u≈0.7
Weather severity (higher PH wet season): w_t = seasonal_w(t) + ρ_w·(w_{t-1}-seasonal) + η^w  (standardized)
Manager ordering bias (slow drift + learning): m_t = m_{t-1} + η^m ,  E[m_t]=m_0·e^{-t/τ}  τ≈3yr
Batch quality (per delivery k):  b_k ~ LogNormal(0,σ_b²),  E[b_k]=1
```

### 7.4 Demand (item × day)
```
log λ[i,t] = log base_i + log T(t) + log Yr(t) + log Wk(dow) + log Cal(t)
             + γ_i·u_t − δ_i·w_t + ε_early(t)
quantity_sold[i,t] ~ NegBinomial(mean=λ·1{i active at t}, size=r_i)   Var=λ+λ²/r_i
Channel:  P(delivery|t) = logistic(α + β·w_t + s_deliv(t))     (rain ⇒ more GrabFood)
Catering outlier: w.p. p_cat/day add a large platter draw (heavy tail → ₱55k days)
```
- `base_i` calibrated to the real slice; `ε_early` wider in early years; `s_deliv(t)` high in 2021 → decays to today's low GrabFood share by ~2023.

### 7.5 Seam-matching (invisible join)
Calibrate `base_i, Wk, Yr, r_i` to the real slice; fix `T(t*)=1`; `T(t)` for `t<t*` scales volumes down smoothly. **Validation gate (E3):** synthetic Nov-2025 daily mean, DOW profile, item mix must be KS-close to real Dec-2025. Real slice never resampled.

### 7.6 Consumption (deterministic) — §6.
Beverages have no perishable recipe → excluded from inventory/waste (still in sales).

### 7.7 Inventory & ordering (recursive, per ingredient, FEFO)
```
Review on schedule (fresh daily; dry/frozen weekly). Position P = on_hand + on_order.
  s_g = μ_LTD + z·σ_LTD                (reorder point, z≈1.41 → 92% service)
  S_g = s_g + μ_review_demand          (order-up-to)
  if P ≤ s_g:  order_qty = ceil_to_pack( (S_g − P)·(1 + m_t) )     ← manager bias distorts
Receipt after lead time:  L[s,t] = round( L_s^base·(1 + κ·w_t) + noise )   ← weather delay
Draw consumption FEFO; unmet ⇒ stockout_flag=1, lost sale
```

### 7.8 Spoilage & waste (per batch)
```
effective_shelf_life = round( shelf_life_g · b_k · (1 − φ·w_t) )
  expiry_waste : batch age > effective_shelf_life ⇒ remainder wasted (reason=expiry)
  prep_waste[g,t] = ω_g · qty_consumed[g,t]                (trim/overproduction)
  waste event → waste.csv ;  daily total → inventory.qty_wasted
```

### 7.9 Financials & logging artifacts (`sales.csv`)
```
gross = price·qty ; disc = 1{Bern(p_d)}·Beta(a,b)·gross ; net = gross − disc
comp rows (MANAGEMENT): p_comp≈0.05 ⇒ net ≤ 0 ; taxes mostly 0 ; cost_of_goods := NULL
label noise: rare category spelling variant ; ~0.3% duplicate (item,date) ; small missing-row rate
```

---

## 8. Parameters (locked values + provenance)

### 8.1 Trend `T(t)` — LOCKED: monotonic growth, **no COVID dip**
```
T(t) = trend_2021 ^ ( (t* − t) / (t* − start) )     # start=2021-01-01, t*=2025-12-01
trend_2021 = 0.48    # ⇒ CAGR ≈ 15.9%/yr, normalized to 1.0 at the seam
```
| year | 2021 | 2022 | 2023 | 2024 | 2025 | seam |
|---|---|---|---|---|---|---|
| T ≈ | 0.48 | 0.56 | 0.64 | 0.74 | 0.86 | 1.00 |

### 8.2 ⚠ Profit vs. Sales — critical
Owner's reference **₱190k (2021) → ₱317k (2026)** are **PROFIT** (~10% margin), **not** the sales the dataset stores. `sales.csv` holds **net revenue ≈ 10× larger**.
- Real Dec'25–Sep'26 **sales ≈ ₱3.1M**; the ₱317k profit sits on top.
- **2026 is partial** (~9.3 mo); annualized ≈ ₱400k profit / ≈ ₱4.0M sales — that's what makes T land at 1.0.
- **Assumption:** margin ≈ constant 10% (sales grow at same rate as profit). If margin widened as they scaled, nudge `trend_2021` up toward ~0.60.
- Profit is **not a column** (COGS empty); these figures only set the slope.

### 8.3 Weekly `Wk(dow)` (Mon→Sun) — from real data
`0.81 / 1.00 / 1.13 / 1.11 / 1.09 / 1.05 / 0.83` (Wed peak, Sun/Mon trough). Generator recomputes from the real slice; values are the target.

### 8.4 Annual & calendar — literature
Ber-month (Sep–Dec) **+10–20%**, Dec peak; Q3 (Jun–Aug) dip **−8–12%** (school start + rainy season). Payday (15th/EOM) **+8–15%**; December extra (13th-month pay).

### 8.5 Shelf lives (USDA FoodKeeper): fish/seafood 1–2 d · shrimp/squid 2–3 d · leafy veg 3–7 d · cooked rice ~1 d · egg 21–35 d · frozen 60–180 d · sauces/dry weeks–months.

### 8.6 Waste `ω_g` (foodservice lit): 4–10% of purchases pre-service; default 5–8%, higher for trim-heavy proteins & leafy veg.

### 8.7 Other: lead time fresh 1–3 d / dry-frozen 5–14 d ×(1+κ·w_t) · service `z`=1.41 (~92%) · discount `p_d`=0.26 / ~7% · comp `p_comp`≈0.05 · `ρ_u`≈0.7 · `ε_early` σ 0.25(2021)→0.10(2025) · catering `p_cat` small.

### 8.8 Scale: base ≈ 30 line-items/day × 2,077 days ≈ 60k+ sales rows; inventory full panel ≈ 112k rows. Scale to **millions** via `Config` knobs (horizon / volume / `branch_id`). Vectorized NumPy/pandas; inventory recursion vectorized across ingredients, iterated across days.

---

## 9. Omitted / latent variables (generated then STRIPPED)

| latent | drives (observed) | confounding created |
|---|---|---|
| `area_activity` u_t | demand scale (all items), dine-in share | items co-move beyond seasonality |
| `weather_severity` w_t | dine-in ↓, delivery ↑, lead time ↑, spoilage ↑ | low-sales days coincide with stockouts & waste → spurious causation; hidden common cause sales↔inventory |
| `manager_ordering_bias` m_t | order_qty deviation from optimal | **generates the core over/under-ordering problem**; waste correlates with manager-state, not just demand |
| `batch_quality` b_k | effective shelf life | waste variance unexplained by shelf_life_days |

Must **not** appear in any exported file or the EDA notebook — only their fingerprints (correlations) remain discoverable.

---

## 10. Realism artifacts (mapped to evidence)
overdispersed mostly-1 counts (qty mean 1.41) → per-item NB · zero-sales sparsity (top 10% = 59% units) → low-λ tail zeros · heavy-tail days (max ₱55k) → catering mixture · discounts (26%, ~7%) → Bernoulli×Beta · comps (MANAGEMENT ~5%, net≤0) · empty COGS (100%) · category label noise · pack rounding (order_qty ceil-to-pack) · logging gaps/dupes (24 dup item×date) · payday/holiday/ber-month multipliers.

---

## 11. Constraints (Eskwelabs brief)
1. **Formulae, not GenAI** for numbers. Exception: free-text fields via LLM API; **budget ₱250** → batch/template/recombine.
2. **Omitted variables required**, then **removed**; EDA must not show them.
3. **Scalable** hundreds → millions; vectorized.
4. **Reproducible:** single `seed`/`Config`.
5. **Realism required:** outliers, noise/rounding, class imbalance, logging artifacts.
6. **Three deliverables:** Word doc (formulae, ≥3 tables & 20+ features, APA lit, schema, data dictionary), Notebook 1 (generator), Notebook 2 (EDA + stretch).

---

## 12. Decisions log (LOCKED)

**Framing**
- Data is fake → used as ground truth; no de-identification.
- Keep everything uploaded; generate only the missing 2021→Nov'25 sales + full-span inventory/waste/supplier records (§2).
- Span 2021-01-01 → 2026-09-08; seam 2025-12-01.
- Trend: monotonic growth, no COVID dip, `trend_2021=0.48`, ~16%/yr (§8.1).
- ₱190k/₱317k are **PROFIT** (~10% margin); dataset stores sales (~10× larger); margin assumed ~constant (§8.2).
- Menu evolution **A+**: keep every item/price/recipe; year-stamped promos fire in their year; delivery (`GRAB FOOD`) phases in 2022; via `date_introduced`/`date_retired`.
- Channel mix time-varying (high delivery 2021 → low today); early-year noise wider.

**Finalized checklist**
| id | decision | locked to |
|---|---|---|
| A1 | Waste grain | **event log** → standalone `waste.csv` |
| A2 | Inventory rows | **full daily panel** (every ingredient × every day, ~112k) |
| A3 | Purchase orders | **folded** into inventory (`order_qty`/`qty_received`); no PO file |
| A4 | Batch tracking | **internal FEFO**; surfaced via waste log + `batch_id`; no per-batch panel |
| B1 | Ingredients in inventory | **all 54** (incl. dry/sauce) |
| B2 | Beverages | **excluded** from inventory/waste; still in sales |
| B3 | Branches | **single**; `branch_id` knob reserved for teaching-scale |
| C1 | Ordering policy | **(R,s,S)** + manager-bias distortion (internal engine) |
| D1 | Costs/packs | **merge** real `SUPPLY-UR` rates + `INGREDIENTS.xlsx` packs/prices **before** waste sim (so `waste_value_php` uses real ₱) |
| D2 | Ingredient names | **from `INGREDIENTS.xlsx` + `EGG+VEG`** (Appendix B); `name_inferred=True` only for **BAR, KAL, SAS** |
| E1 | Output format | **CSV + Parquet** |
| E2 | Scale | **real volumes + millions** via config |
| E3 | Seam validation | **hard KS gate** Nov→Dec before sales accepted |

**User skill calibration** (drives Notebook 2 stretch): prob/dist 8 · Python 9 · TS/ML 7 · restaurant ops 5 → go deep; **Notebook 2 stretch = SES / SARIMA / Holt-Winters with WMAPE & MASE + a PuLP replenishment LP** on the generated data (mirrors the capstone).

---

## 13. Progress / status

### ✅ Section 1 — reference tables (DONE, verified) — `makisushi_generator.py`
| table | rows | notes |
|---|---|---|
| calendar | 2,077 | 115 PH holidays, 136 paydays |
| menu_items | 446 | delivery items → 2022 intro, promos → 2025 |
| ingredients | 54 | 36 perishable; names being upgraded from `INGREDIENTS.xlsx` (D2) |
| suppliers | 9 | real names + simulated dynamics |
| recipes | 828 | 304 dishes, links complete, 77% volume-weighted coverage (rest = drinks) |
| supply_ref | 74 | real rates + fluctuation %, for the D1 cost merge |

API: `build_dimensions(cfg, rng) -> dict` (returns all). See Appendix A.

### ⬜ Remaining build plan
- **§1.5 cost/name merge** — fold `INGREDIENTS.xlsx` names/packs/prices + `SUPPLY-UR` rates into `ingredients`; drop `name_inferred` to BAR/KAL/SAS.
- **§2 latents + demand + seam** → `sales.csv`; emit seam plot + **pass KS gate (E3)**. ← *next build*
- **§3 sales financials + artifacts** → `sales.csv`.
- **§4 consumption + inventory sim** → `inventory.csv`.
- **§5 spoilage** → `waste.csv` (+ `qty_wasted`).
- **§6 export** — drop latents; write 8 files (CSV+Parquet); validation report (seam, DOW, concentration, waste% ∈ 4–10%, stockout frequency).
- **Notebook 2** — EDA + stretch (forecast bake-off + PuLP LP).

---

## 14. Deliverables (final)
1. **Word doc** — Model Research & Specs (this doc is its backbone): formulae (§7), ≥3 tables & 20+ features (§5), APA literature (§16), schema (§5), data dictionary (§5).
2. **Notebook 1** — imports `makisushi_generator.py`, runs the pipeline, exports the 8 files (latents stripped).
3. **Notebook 2** — EDA on a freshly generated dataset + stretch analysis.

---

## 15. (reserved)

## 16. Literature & citations
**Verified:** USDA FSIS *FoodKeeper* / foodsafety.gov (shelf lives) · LeanPath / National Restaurant Association; U. of Arizona (2005) foodservice waste (9.55% QSR / 3.11% FSR) · Filimonau et al. (2019), *Sustainability, 11*(21), 6016 · Oxford Business Group (2012) *The Report: Philippines* (Q4 spike, Q3 slow) · PH Labor Code (13th-month pay).
**Standard (format in APA yourself):** Croston (1972); Syntetos & Boylan (2005); Kolassa (2016, *IJF*); Cameron & Trivedi (2013); Winters (1960)/Holt (1957); Hyndman & Koehler (2006); Hyndman & Athanasopoulos (*FPP*); Scarf (1960); Silver, Pyke & Peterson (1998); Arrow, Harris & Marschak (1951).

---

## Appendix A — Section 1 API (`makisushi_generator.py`)
```python
@dataclass
class Config:
    seed=42; start="2021-01-01"; seam="2025-12-01"; end="2026-09-08"
    src_dir=Path("/mnt/project"); sales_file="makisushi_Jan_2026.xlsx"
    trend_2021=0.48; annual_growth=0.16; service_level_z=1.41

build_dim_date(cfg) · build_dim_menu_item(cfg) · build_bom_and_ingredients(cfg)
build_supply_ref(cfg) · build_dim_supplier(cfg,rng) · build_dimensions(cfg,rng)  # returns all
# constants: ING_RULES (code→category/storage/shelf_life/uom) · DEFAULT_COST · INFERRED · SUPPLIER_MAP
```
Prereq (Jupyter): `%pip install holidays pandas numpy openpyxl --break-system-packages`.

## Appendix B — ingredient code → real name (from `INGREDIENTS.xlsx` + `EGG+VEG`)
The catalog has **no code column**; codes are cross-referenced to product names. Previously-inferred 13:

| code | real name | source | confidence |
|---|---|---|---|
| MAY | Mayonnaise (Pure Select / Kewpie-style) | Dry | high |
| WAS | Wasabi paste (Premium Wasabi Paste) | Dry | high |
| NOR | Nori (seaweed sheet) | Dry | high |
| EBK | Ebiko (flying-fish roe) | Frozen | high |
| TEM | Tempura Ko (tempura flour/batter) | Dry | high |
| GP_050 | Ground Pork | Beef | high |
| CAR | Carrot | EGG+VEG | high |
| CHE | Cheese (cream cheese) | Frozen | likely |
| TAM | Tamago (egg omelette, in-house) | — | likely |
| SOT | glass/sotanghon noodle | — | uncertain |
| BAR | — unknown — | — | **ask owner** |
| KAL | — unknown (squash?) — | — | **ask owner** |
| SAS | — unknown — | — | **ask owner** |

The other 41 codes are also confirmed by the catalog (Tuna Loin/Belly, Salmon Fillet, Squid Tube, Beef Sukiyaki Cut, Pork Belly/Loin, Chicken Breast/Thigh, Shrimp PDTO/Nobashi, Japanese Rice, sauces). `ingredients.csv` stays keyed to the **54 recipe codes**, enriched with catalog names/packs/prices — the full ~350-SKU catalog is **not** dumped as ingredients (unused SKUs can't drive consumption).

## Appendix C — immediate next actions for Claude Code
1. **§1.5 merge:** upgrade `ingredients` names/packs/prices from `INGREDIENTS.xlsx`+`EGG+VEG`+`SUPPLY-UR`; set `name_inferred` only for BAR/KAL/SAS.
2. **§2:** `draw_latents(cfg,rng)`, `build_demand(...)` (backfill only), `stitch_real_slice(...)`, `seam_report(...)`; enforce the KS gate before proceeding.
3. Then §3–6 → the 8 files. Keep everything **seeded & vectorized**; never introduce an LLM call for numeric data.
