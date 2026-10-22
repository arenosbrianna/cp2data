# REBUILT_SCOPE20 - 20-ingredient scope, flat yearly level, realistic noise

NOTE (2026-10-23): UPDATED FILES, v14 and the older working folders now live in `../OTHER_PROJECT_FILES/`.

Built 2026-10-22. `datasets/` = 16 CSVs in the layout of `UPDATED FILES/datasets/`. `supabase_final/` = the `UPDATED FILES` schema / load / transform SQL (unchanged) plus the landing, staging and mart SQL. `audit_consistency.py` = independent audit of sales, stock and waste. `sales_trend_eda.ipynb` = sales trend EDA of this data. `external_factors.md` = the Philippine factors used and their sources.

## Load order (landing -> staging -> warehouse -> marts)
1. `supabase_final/00_landing_and_staging.sql` - schemas `landing`, `stg`, `mart`; 14 all-text landing tables; 14 typed staging tables; `stg.promote_from_landing()`.
2. `supabase_final/01_schema.sql` - the `dw` schema.
3. Upload the 14 CSVs from `datasets/` into `landing.<name>` (MANIFEST.csv and storage_locations.csv are reference files, not loaded); `supabase_final/test_landing_load.psql` does it with psql `\copy`.
4. `select stg.promote_from_landing();`
5. `supabase_final/03_transform.sql` - staging to `dw`, with the load assertions. (Do not run `02_load_staging.psql` in this route.)
6. `supabase_final/04_marts.sql` - the `mart` views for forecasting and optimization; more marts = more views, re-runnable.

## What was asked and what was done (2026-10-22)
| Requirement | Result |
|---|---|
| 20-ingredient scope of Oct 19 | ingredients, recipes, volumes, suppliers, calendar, menu items identical to `UPDATED FILES`; supplier terms identical except the two small-pack rows (tamago, bean sprouts) |
| More noise | day-to-day and month-to-month noise raised (below) |
| No yearly upward trend ("flatten it") | same-months level of 2023, 2024, 2025 within 1.3 % of the real 2026 level, slope -0.2 % a year |
| 2021: GrabFood greater than dine-in | 2021 GrabFood PHP 112.4k vs Dine-In 79.2k (58.7 %), every month 56-60 % |
| 2021 total sales PHP 180-200k | PHP 191,537 for Sep-Dec 2021 (the data starts 2021-09-01) |
| More GrabFood in 2022, then subtly lower, then steady | 27 % of 2022 sales (PHP 1.07M), 40 % in Jan 2022, 29 % Jul 2022, 15 % Jan 2023, 7 % Jan 2024, steady 4-6 % from mid-2024 (real 2026: 3.3 %) |
| Philippine external factors | inflation, COVID reopening, typhoons - see `external_factors.md` |
| Waste, sales, inventory consistent | `audit_consistency.py`: 30 PASS, 0 FAIL |
| No duplicate sale lines | none; see "Duplicates" |
| Lower waste on tamago and bean sprouts, bought only in small packs | tamago waste 70.5 % -> 53.0 % of what is bought, bean sprouts 57.9 % -> 34.9 %, all waste PHP 293k -> 262k; packs of 50 g (usable), at most 4 per purchase; see "Waste" |
| Staff meals in the optimizer | `dw.v_lp_ingredient_week_input` (in `supabase_final/01_schema.sql` of this package, not in `UPDATED FILES`) adds `staff_weekly_baseline` (trailing 28-day recipe use of the non-paying staff / management / complimentary sale lines) to `total_requirement`, like the existing off-POS baseline for ground beef and tuna; the demand forecast stays on paying sales only. Tested against an independent calculation. Staff lines are 3.2 % of tracked demand (chicken thigh 10 %, bean sprouts 9 %) |
| Staff meals similar to the real data | staff and complimentary lines now match the real months: 1.7-1.8 units a day (real 1.72), 1.4-1.5 lines a day (real 1.41), weekday shape within 0.05 of the real index, same top dishes (9 of 10); 2021 scaled to the tiny business; see "Staff meals" |
| Noise across the datasets, no under- or over-fitting | `noise_audit.py`: every table carries realistic noise and the forecasting behaviour matches the real months; see "Noise audit" |
| Ingredient prices, shelf life, deliveries, stock counts, sales extras | supply-side noise added, sales extras checked against the real data; see "Supply-side noise" |
| Prices follow the real POS and the menu table | `price_sources.py`: 100 % of generated paying lines priced from the sources (was 57 %); see "Sales shape" |
| Dish mix follows the real POS | the generated Dine-In dish mix is within 0.08-0.10 of the real mix (the two halves of the real period differ by 0.18 from each other); the real top dish, California Maki, is 8.3-8.5 % of Dine-In units (real 8.25 %, was 6.6-7.0 %): whole lines moved from the other maki rolls, category total unchanged |
| Every value rounded to 4 decimals | `round_datasets.py`: 181 cells in `recipes`, `sales` and `ingredient_volume` (0 cells above 4 decimals left in 181,198 rows) |
| Fix ING01 | `validation/post_load_validation.sql` tests the current rule (shelf life <= 5 days => perishable); 65 PASS, 0 FAIL |

## Sales shape
- **Flat level.** Jan-Aug mean net per open day (same months every year, so seasonality cannot hide a trend): 2023 10.98k, 2024 11.07k, 2025 10.95k, real 2026 10.93k (+0.4 %, +1.3 %, +0.1 % against the real level; spread 1.2 %; slope -0.2 % a year; the changes go +0.8 % then -1.2 %). 2022 is the reopening year (Jan-Aug 8.7k). Seasonally adjusted yearly levels: 2022 10.8k, 2023 12.0k, 2024 12.5k, 2025 12.3k, 2026 12.3k.
- **How the level is held:** each generated year's Jan-Aug mean is set to the real Jan-Aug 2026 level +- a few percent (random, must go up AND down); the seasonal shape, noise, Nov / Dec peaks and storm days inside the year are kept. Inflation and typhoon effects therefore show as dips inside a year, not as a level shift between years.
- **2021 to 2022:** 2021 is a depressed COVID year (PHP 41k, 44k, 53k, 54k a month). 2022 ramps from PHP 86k in January (Alert Level 3) to 263k in March (full capacity from 1 March) and 370k in June, then stays at the normal level.
- **Noise:** monthly noise x2.0 (`NOISE_MULT`), day-to-day spread 0.44-0.46 (log SD within month; real months 0.39), month-to-month change SD 0.132 (real 0.129). 29 random storm / outage days (30-65 % of the day's sales, at least 6 lines kept) and 12 busy days (+25-55 %), logged in `noise_events.json`; three documented storm days (Carina 24-25 Jul 2024, Kristine 23 Oct 2024). Paydays, Dec 24 / 31 and the real months are not touched.
- **Prices follow the original sources** (user, 2026-10-22; `price_sources.py`): every generated paying line is priced from the real POS (most common real price of that dish and channel, at least 5 real lines) or else the menu table (list price; GrabFood x 1.25). 100 % of the generated paying lines (41,236 of 41,237) now carry such a price; before, 43 % did not (mostly 4-16 % below list, the generator's own older price history), which also gave the generated years a hidden price rise of 1-7 %. The monthly plan keeps the sales level, so the higher prices mean slightly fewer units (69,045 paying units). One dish has one price per channel at any time: no same-day price conflicts remain. Inflation acts on volume only.
- 2021 days have about 4 lines on average, so the day-to-day spread in 2021 (0.74) is high; this is small-count noise.

## GrabFood
Follows the real POS and the menu table (2026-10-22). The real POS has 85 % of its GrabFood lines on the dedicated GrabFood-category listings (price = list price) and 15 % on regular dishes (price x 1.25); the generated years now match: 85 % on listings in 2022-2025 (was 46 %), 56 % in 2021 (was 2 %; the rest of 2021 is limited because the post-build step may only move a line to a same-name listing with an IDENTICAL recipe, so ingredient use stays consistent). Generated GrabFood lines move to the same-name listing, else to a listing drawn with the real listing mix (`gf_listings.py`; days, quantities and discount rates unchanged, price = the listing's source price).
2021: locked file converted to a GrabFood-led mix, enforced again after the stock build (`enforce_covid_channel_mix.py`, targets 63/63/62/60 %). 2022 onwards: `gf_rebalance.decay_targets()` converts Dine-In lines before the stock build so that the monthly GrabFood share follows 4 % + 46 % x exp(-months since Jan 2022 / 9). GrabFood share of paid net by year: 2021 63.0 %, 2022 29 %, 2023 11 %, 2024 6 %, 2025 5 %, real 2026 3 %. 2021 total paid net PHP 181,698 (GrabFood 113,696 vs Dine-In 68,002).
Payday and holiday effects (vs other days of the same month and weekday, Dec 24/31 excluded): payday +7.5 % (was +16 %, real +5 to +10 %), holiday -7.8 % (was about -4 %; real -20 to -37 % on only 11 days, so only the direction is used). Whole lines move between days of the same month and weekday; month totals do not change. SYNTHETIC_ASSUMPTION.

## Duplicates
`dedupe_sales_lines.py` merges every pair of lines with the same date, dish, channel and revenue flag in the generated years into one line at one price (48 groups; they were price-history overlaps such as 180 and 190 PHP on one day). Quantities are summed, so stock and waste are unchanged. The raw locked 2021 file had 26 lines sharing a date, dish, channel and price; they no longer exist. A paid line and a complimentary line of the same dish and day are different lines and stay apart. Real POS lines are never touched. Audit checks S1 and S2 test this.

## How it was made (scripts in `GENERATORS/`)
1. `08_scope_rebuild/apply_scope20_inputs.py` (VMO merged into Togue, 20 perishables set).
2. `07_sales_shaping/gen_lock2021.py` + `gf_rebalance.py`: the shipped 2021 lines get the GrabFood-led mix and the PHP 190k level (`aim2021.json`, calibrated per month because the stock build adds lines).
3. `07_sales_shaping/shape_monthly_trend_noisy.py` with `LEVEL_FLAT=1 EXTERNAL=1 LOCK_2021=1 LOCK_FILE=locked_2021_gf.csv GF_COVID=1 SHOCKS=1 NOISE_MULT=2.0 DAY_SD=0.45` (see `run_chain.sh`). The yearly level is held by `FLAT_YEARS` (default on); an open day that ends empty is refilled by the floor step.
4. `07_sales_shaping/calib_loop.sh` runs the chain and corrects the monthly ratios against the plan (`update_ratios_plan.py`) and the 2021 aim until final = plan (final within 0-1 % of plan per year; final ratios in `ratios_final.json`).
5. `06_scoped_inventory_model/scope20_salmon_patch/build_v11.py` + `full_sim10.py` + `opt_policy.py` with `EXTRA_PORTIONS=CHE:2,EBK:100,PDT:5,TAM:50,TOG:50 NO_STAPLE=TAM,TOG PAR_ALPHA_ITEM=TAM:0.5,TOG:0.5 GF_NORM=0 SEEDX=20261010 SAL_DEMAND_LOT=0 SAL_MONTH_CAP=1 SAL_P_CURE=1.0 SAL_BUSY_MONTHS=2,9,10,11,12 SAL_CAP_SCALE=1` (the user's `full_sim10_salcap.diff` plus the demand-scaled cap for the generated years).
6. `07_sales_shaping/finalize.sh` runs `08_scope_rebuild/port_scope_rebuild.py`, `renumber_ingredient_ids_scope20.py`, `enforce_covid_channel_mix.py`, `dedupe_sales_lines.py`, then the audit.
`menu_items.csv` (26 dish-name changes), `MANIFEST.csv`, `storage_locations.csv` come from `UPDATED FILES`.

## Supply-side noise (2026-10-22, user: "fix all of these")
| Area | What was added | Result |
|---|---|---|
| Ingredient prices | each ingredient's daily price index = month-of-year seasonality (produce 7 %, others 2 %) x a slow drift (AR(1), spells of months) x short spikes after typhoons (produce +20 %, seafood +6 %, about two weeks) x 2 % daily noise, normalised to mean 1 (no long-run trend); used for scheduled and emergency purchases | lag-1 autocorrelation of delivery prices 0.75 (was -0.02), CV 4.4 %, average price = standard cost |
| Shelf life | each batch: nominal -1 / 0 / +1 day (15 / 70 / 15 %) | 0.16 / 0.70 / 0.15 measured; load rule relaxed to "within one day of received + shelf life - 1" (`03_transform.sql`, validation BAT01) |
| Stock counts | losses inside the shelf life, recorded as waste: `spoilage` (part of a batch goes bad, 0.8 % per batch-day for short-life items) and `shrinkage` (2 % of ingredient-days lose 2-10 % of the stock on hand: miscounts, unexplained losses) | waste reasons now expiry 58 %, shrinkage 18 %, over_ordering 13 %, spoilage 11 % of waste value; total waste PHP 371k = 7.4 % of purchases (was 5.1 %) |
| Deliveries | 1-2 days late (3 % walk-in, 8 % other suppliers); short or partly rejected (50-90 % of the order; 3 % walk-in, 7 % other) | receipts / orders 98.6 % (by ingredient 96.6-100 %); stockout events 476 (was 400), lost-sale events 42 (was 24) |
| Sales extras | not added, checked against the real data instead | price changes already exist (42 % of dishes with 20+ lines show more than one price within the 9 real months, 73 % over the generated years; this corrects the earlier "one price per dish"); dish launches exist (75 dishes with 50+ lines first sold in 2022-2025); retirements cannot be added (every dish sold earlier also sells in the real months); voids / refunds are not added because the real export has none (0 of 392 real non-paying lines have a price above zero, 0 lines are 100 % discounted) |
**Schema effect (no new table or column):** `dw.fact_waste.batch_id` is no longer unique (a batch can have a loss inside the shelf life and a later expiry row); `waste_reason` allows `spoilage` and `shrinkage`; the date rule is "after expiry" for expiry rows and "inside the batch's life" for the two loss types; the ledger view books a loss on its own day. Updated in `01_schema.sql`, `03_transform.sql`, `02_load_staging.psql`, `00_landing_and_staging.sql` and `validation/post_load_validation.sql` (new checks WST13-WST15).

## Noise audit (`noise_audit.py`, 2026-10-22)
| Dataset | Noise measured | Result |
|---|---|---|
| Sales (daily) | log SD of daily net sales within a month | 0.44-0.46 (real 0.39) |
| Sales (months) | month-to-month change SD | 0.132 (real 0.129) |
| Dish demand | dish-day variance / mean (1 = Poisson), top-20 dishes | 1.48-1.57 (real 1.44) |
| Stock use | recorded use / (sales x recipes) per ingredient-day | mean 1.041, SD **0.088**, 5th-95th pct 0.92-1.16 (before: SD 0.023, too clean; now `LOSS_NOISE=0.07 VARF_FLOOR=0.85`, same 3.6 % average loss) |
| Purchases | unit cost per delivery | CV 4 %, lag-1 autocorrelation 0.75 (drifting, no long-run trend) |
| Deliveries | gap between deliveries | CV 0.44 per ingredient |
| Storm / busy days, staff meals, off-POS use | random days; real-day copies; weekly 0.85-1.15 draws | see the sections above |
**Forecasting behaviour (weighted MAPE of the test period):**
| | Generated (2023-2025) | Real (Dec 2025 - Sep 2026) |
|---|---|---|
| Daily, plain mean | 39 % | 33 % |
| Daily, same weekday last week | 53 % | 44 % |
| Daily, Holt-Winters | 44 % | 31 % |
| Weekly, plain mean | 24 % | 17 % |
| Weekly, rolling mean of the last 4 weeks | 16 % | 11 % |
- **Not too clean:** no method gets daily error below about 35 %, and last week's value is worse than a plain average in both the generated and the real data. A gradient-boosting model on calendar and lag features beats the plain mean by only 11 % (real: 4 %) and shows a train / test gap, so models do not fit it perfectly.
- **Not signal-free (no underfitting by construction):** at weekly level a 4-week rolling mean clearly beats the plain mean in both. Seasonality (Nov / Dec peaks, weekday shape, payday) and the level are recoverable, with noise about 1.4 times the real weekly noise, as asked ("more noise").
- Consumption stays tied to sales (monthly correlation 0.998, kitchen variance 3.4-4.3 % a year), so ingredient forecasts built from dish forecasts remain valid.

## Staff meals (non-paying lines)
Compared with the real months (Dec 2025 - Sep 2026), user request 2026-10-22:
| | Real | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| lines per open day | 1.41 | 1.40 | 1.54 | 1.48 | 1.46 |
| units per open day | 1.72 | 1.72 | 1.84 | 1.81 | 1.80 |
| share of open days with any | 50 % | 55 % | 57 % | 55 % | 56 % |
| distinct dishes | 106 | 88 | 90 | 87 | 77 |
- **Weekday index of units (Mon..Sun):** real 0.52 1.09 1.27 1.21 0.55 1.47 0.89; generated 2022-07..2025-11 0.57 1.11 1.23 1.17 0.59 1.49 0.85. Same top dishes (Crazy Kani Burrito, California Maki, Karaagedon).
- **What was fixed:** (1) lines of dishes that did not exist in the generated years were dropped, losing 6-9 % of the units, mostly on Mondays and Tuesdays: they are now re-assigned to an available dish drawn in proportion to the real staff-meal frequency; (2) the complimentary lines of ordinary dishes (real 0.24 units a day, generated 0.06) are copied from the real days too; (3) real days are drawn in shuffled rounds, so each weekday averages the real average; (4) a staff dish joins from the first paying sale of the same-named dish (6 of the 19 real-only dishes join from their own date; 13 never sold before the real months, so variety stays below the real 106).
- **2021 and the 2022 ramp:** staff meals scale with the business: 0.49 units a day in 2021 (9 units per 100 paying units, was 26) and the first months of 2022 are thinned in proportion to the level (4.6 per 100 in 2022 against 4.3 real).
- Generated years run about 6 % above the real unit volume (the stock build also restores a few staff units); the real Dec 2025 was busy (2.5 units a day) and is part of the real average.
- Ground beef and tuna off-POS use (staff meals / bulk prep in the inventory) has no real record to compare with; it is the client's rule.

## Waste
- **Total** PHP 262k = 5.1 % of purchases (about 4,038 expired batches); 83 % expiry, 17 % over-ordering. By year (share of that year's purchases): 2021 about 33 % (tiny volume), 2022-2025 about 4-5 %, 2026 about 6 %.
- **Concentrated:** tuna 23 % of waste value, mango 22 %, cucumber 20 %, salmon 8 %, tamago 5 %, tofu 5 %, ground pork 4 %. Beef and chicken are almost never wasted.
- **Tamago and bean sprouts** (3-day shelf life, lumpy use) were the worst: the old rule kept two 100 g portions of every item on the shelf, so 70 % of the tamago and 58 % of the bean sprouts bought expired. Now (user decision 2026-10-22) they are **bought only in small packs, as needed** at the walk-in market: 50 g portions (`EXTRA_PORTIONS=...,TAM:50,TOG:50`), never more than 4 packs in one purchase (`MAX_PACKS_ITEM=TAM:4,TOG:4`; largest purchase in the data 200 g), no stock floor (`NO_STAPLE=TAM,TOG`) and a 50 % service level instead of 95 % (`PAR_ALPHA_ITEM=TAM:0.5,TOG:0.5`). `supplier_item_terms.csv` carries the small pack for these two (`08_scope_rebuild/set_small_packs.py`: order unit portion, 50 g usable, 83.33 g gross for bean sprouts at their 60 % yield, min order 1 pack; an assumption, the client packs were 250 g and 0.25 kg). Result: 53.0 % of the tamago and 34.9 % of the bean sprouts bought is wasted.
- **Cost of the change:** more same-day market purchases (tamago 142 and bean sprout 131 stockout events), so total stockout events rise from 184 to 400 and lost-sale events from 21 to 24 (the walk-in same-day success rate of 95 % is unchanged, as decided). Going below 50 g portions or a lower service level gains almost nothing more: the rest comes from lumpy demand (tamago is used on about 30 % of days) against a 3-day life.

## Salmon (2026-10-19 rules)
Cost 1.8182 PHP/g, one whole fish per delivery, at most 2 deliveries a month (3 in Feb, Sep, Oct, Nov, Dec), same-day whole-fish purchase when it runs out, salmon not a staple. `SAL_CAP_SCALE=1` lets the cap grow with demand in the generated years (before 2025-12-01); the real months keep the client's cap.

## Checks (local PostgreSQL 17; nothing was applied to Supabase)
- `audit_consistency.py datasets`: **30 PASS, 0 FAIL** - no duplicate lines; gross - discount = net; the kitchen variance between sales x recipes and stock use is 3.6-3.7 % in every year (range 2.9-5.0 % by ingredient), monthly correlation 0.998; daily flow opening + received + emergency - consumed - wasted = closing; batches add up to closing stock; expiry rule; every waste row is a real expired batch with its leftover quantity and cost; stockout events consistent; purchases follow sales (about 25 % of net sales in 2022-2026) and the waste share stays at 3.9-6.1 % of purchases in the full years.
- Load: `03_transform.sql` assertions pass (ledger, batch stock, expiry, sales-to-consumption, stockouts, open days: only the two real POS gap days 2026-06-02 and 2026-07-24 have no sale line).
- `validation/post_load_validation.sql`: **65 PASS, 45 INFO, 0 FAIL**.
- Marts: all 9 views return rows on temporary forecast / optimizer rows (rolled back).

| | UPDATED FILES | REBUILT_SCOPE20 |
|---|---|---|
| sale lines | 41,163 | 51,126 |
| net sales PHP M | 15.21 | 19.98 |
| waste PHP k | 272 | 371 |
| stockout events (lost sales) | 185 (26) | 476 (42) |

## Caveats
- `dw.v_lp_ingredient_week_input` now lists every in-scope (perishable) ingredient for every forecast week (2026-10-23): an ingredient no forecast dish uses (ground beef, mostly off-POS) still gets a row with forecast_requirement 0 plus its off-POS and staff baselines. It was missing from the optimiser input before. Rehearsal: a 3-week naive forecast fed the view (20 ingredients x 3 weeks, no nulls) and a HiGHS MILP solved to optimality.
- 2021 waste (fixed 2026-10-23, user): it was PHP 44.6k, 38 % of that year's purchases, because the first months have only about 5 paying units a day while the stock rules were built for the later volume. Before 2022 (env LOWVOL_END) the stock build now (a) buys whole salmon and tuna as cut portions (500 g / 3.5 kg, `LOWVOL_PORTIONS`; whole fish from 2022, as the client practice), (b) has no staple floor, a use-sized opening stock and no start-up demand proxy after day 28, (c) buys same-day walk-in items for the median cover demand only. Result: 2021 waste PHP 17.4k = 18 % of purchases (stockouts 13 -> 35, lost sales 2 -> 4). Still above 2022+ (6-8 %); the rest is salmon/tuna/cucumber/mango minimums at a tiny volume. SYNTHETIC_ASSUMPTION; 2021 receipts of salmon/tuna are therefore not whole fish.
- **Client budget (validation finding, not tuned):** the client's general weekly budget is PHP 5,000-15,000 (walk-in or delivery). Total weekly purchases of the 20 tracked perishables, all suppliers, average PHP 21.0k in 2022-2025 (real months Dec 2025 - Aug 2026: 19.0k); 21 % of weeks are inside the range, 78 % above, none below. This is the known gap behind the earlier budget-gap analysis (levers to reach PHP 15,000); the 34 shelf-stable ingredients are not in these totals.
- **Prices above 1.3 x list price (checked against the sources):** the 17 items besides Red Iced Tea are all GrabFood lines and 34 of their 35 lines are real POS data (e.g. Katsudon 400 against list 159 on three real days), untouched. Red Iced Tea (item 290) sold at 210 in the generated years but at 145 in the real POS and the menu table; it is now 145 (181.25 on GrabFood) throughout. One generated Gyoza line is at half the list price (89.5 against 179).
- **Tamago stock cover:** average stock at end of day is 125 g against an average use of 32 g a day (no use on 72 % of days), i.e. 3.9 days of cover against a 3-day shelf life; it is the lumpy-demand effect behind the 53 % tamago waste.
- 2021 volume is so small (about 4 lines a day) that the minimum pack sizes dominate: purchases are 64 % of 2021 net sales and waste is 35 % of 2021 purchases. That follows from the PHP 190k year, not from a bug.
- The 2021 to 2022 recovery is steep by design (see above) because 2021 is only PHP 190k for the year.
- Total net sales rose against the Oct 19 file (15.2M to 20.1M) because the generated years are now held at the real 2026 level instead of below it.
- Monthly values sit within about 0-3 % of the plan; individual months can differ more because of the noise.
- `MANIFEST_final.csv` and the prose in `DATA_NOTES.md` still describe the Oct 19 numbers.
