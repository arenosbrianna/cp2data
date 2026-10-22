# Makisushi DSS — Redesign Handoff

Source: CP-1 Final Revised Manuscript (Group 6) vs. the current web prototype (Dashboard, Inventory, Suppliers, Waste & Spoilage, Analytics, Insights, Reports).
Mockups: `mockups/*.dc.html` (reference only — layout, content and data, not production code).

## 0. Core problem

The manuscript describes a pipeline: **Loyverse CSV → ETL/PostgreSQL → forecast (SES/SARIMA/Holt-Winters/ML) → LP optimization (PuLP) → prescriptive alerts → tracking/feedback.**
The prototype only covers the alert step, and its numbers are hard-coded and contradict each other. The goal: every screen value must come from one dataset and be traceable to a forecast or LP run.

**Decide first:** Objective 4 and §3.4.2 say the dashboard is built in **Power BI** (DAX `TODAY()` alerts). The prototype is a custom web app. Either revise the manuscript to justify the web app (and move the DAX logic to server-side computation) or rebuild in Power BI. Each screen below maps to one Power BI report page.

---

## 1. Gap audit

### A. Missing or incomplete modules
| # | Issue | Manuscript ref | Fix | Screen |
|---|---|---|---|---|
| A1 | No demand forecasting screen | Obj 2, §3.3.3–3.3.5, §3.4.4 | Forecast chart with 80/95% intervals, model leaderboard (WMAPE, MASE), selected model per ingredient | Forecasts |
| A2 | No Supplier Purchasing List | §3.4.5 | Table: order-by, ingredient, supplier ID/name/contact, lead time, qty, delivery split, unit cost, line cost, "ordered" checkbox | Purchasing |
| A3 | Stockout Risk Warning not built | §3.4.2 | Projected stock vs forecast demand, reorder-level line, lead-time window, banner with exact order qty | Risk |
| A4 | Spoilage Alert Matrix is a text card | §3.4.2, §1.4c | Ingredient × days-to-expiry matrix; at-risk = on hand − forecast use before expiry; ₱ at risk; promo menu items via BOM | Risk |
| A5 | Excess Capital Gauge is a text card | §3.4.2 | Gauge of excess ₱ as share of inventory value; per-ingredient stock vs forecast bars; "freeze order" | Risk |
| A6 | LP constraints/alternatives invisible | §3.3.6, §3.3.7, Obj 3 | Editable budget / chiller / safety stock / shelf-life / lead-time; 3 scenarios; binding-constraint notes | Purchasing |
| A7 | No recommendation tracking | §3.3.6 | Log Apply/Modify/Dismiss with user, time, reason; outcome measured next ETL cycle | Tracking |
| A8 | Baseline KPIs not shown | §1.3 | Avg weekly waste, spoilage rate, stockout frequency, inventory turnover — baseline vs current | Overview, Tracking |
| A9 | No data freshness / ingest | §1.4, §3.2.1, §3.4.2 | "Data as of …" on every page; Upload Loyverse CSV; Refresh; Log waste | Overview (header) |
| A10 | Descriptive pages incomplete | §3.3.1, §3.4.3 | Reorder level + days of cover on inventory; ingredient × weekday waste heatmap; ingredient usage summary | Risk |

### B. Numbers that contradict each other (current prototype)
- B1 Top 3 dishes sum to ₱8,433 but "Total sales today" = ₱4,250.75.
- B2 Ranking wrong: Salmon Sashimi (₱3,072) ranked #3; California Maki = ₱8/piece.
- B3 ₱4,250.75 ÷ 128 orders = ₱33/order.
- B4 Alert counts: Dashboard "4", sidebar badge "2", chips Critical 2 + Low 5.
- B5 Waste: 149 kg/30 days ≈ 35 kg/week, above the 24.5 kg baseline, yet "current weekly waste" = 14.2 kg; "-4.4% spoilage rate" has no base.
- B6 ₱ too low: ₱2,612 for 149 kg (₱17.5/kg); "2.5 kg salmon protects ₱185".
- B7 Expiry dates (Sep 7–10 2026) are past but still "Critical" — status is hard-coded.
- B8 PuLP card: forecast 14.8 kg, order 5.0 kg, no ingredient named, no netting; inventory says 10 kg salmon; Tsukiji linked only to Hamachi.
- B9 Aged tamari soy sauce in Excess Capital — not a perishable raw material (out of scope §1.4).
- B10 "Order volume vs wait time" — wait time not in schema; y-axis in ₱.
- B11 "Revenue vs profit" — no cost field in schema.
- B12 Waste chart duplicated (Waste + Analytics); 6th bar unlabeled.
- B13 Suppliers: "Items with lead time 10" vs 5 linked ingredients; "Orders needing action 7" vs 6.

### C. Wording / framing
- C1 Remove "AI decision support", "AI-driven", "Smart actions" → "Recommendations — from forecasts and order optimization".
- C2 Replace sidebar "DSR & CRISP-DM · PuLP Active" with data-pipeline freshness.
- C3 "Sales velocity" → "Daily revenue, last 7 days" with dates + forecast overlay.
- C4 Every recommendation = trigger → evidence → action → ₱ impact → what Apply does.
- C5 Never color-only status: pair with icon + text; amber for warning, red for critical.

### D. Data-model gaps (revise Table 3.1 / Chapter 3)
- D1 Add `unit_cost` to `dim_ingredient`.
- D2 Add batch / `received_date` to inventory (spoilage scoring uses receipt date).
- D3 Add BOM bridge table (needed for disaggregation + promo suggestions).
- D4 Remove `ingredient_id` from `fact_sales` (item grain; ingredients via BOM) — avoids double-counting revenue.
- D5 Add `fact_forecast` and `fact_recommendation`.
- D6 Add storage zone / capacity; log stockout events.
- D7 MAPE is rejected in §3.3.2 but used in §3.3.5.2 and §3.4.7 → use WMAPE + MASE (+ RMSE) consistently.
- D8 ML regression listed in §3.3.3 but missing from §3.4.4 → list all four models everywhere.

---

## 2. Schema changes (PostgreSQL)

```sql
ALTER TABLE dim_ingredient
  ADD COLUMN unit_cost      NUMERIC(10,2) NOT NULL,
  ADD COLUMN storage_zone   VARCHAR(20)   NOT NULL DEFAULT 'chiller', -- chiller | freezer | dry
  ADD COLUMN reorder_level  NUMERIC(10,2),
  ADD COLUMN is_perishable  BOOLEAN       NOT NULL DEFAULT TRUE;

CREATE TABLE dim_storage_zone (
  storage_zone VARCHAR(20) PRIMARY KEY,
  capacity_kg  NUMERIC(10,2) NOT NULL          -- chiller = 150
);

CREATE TABLE bridge_bom (
  item_id          INT REFERENCES dim_menu_item(item_id),
  ingredient_id    INT REFERENCES dim_ingredient(ingredient_id),
  qty_per_serving  NUMERIC(10,4) NOT NULL,
  PRIMARY KEY (item_id, ingredient_id)
);

-- fact_sales: drop ingredient_id (item grain)
ALTER TABLE fact_sales DROP COLUMN ingredient_id;

CREATE TABLE fact_inventory_batch (
  batch_id       BIGSERIAL PRIMARY KEY,
  ingredient_id  INT REFERENCES dim_ingredient(ingredient_id),
  supplier_id    INT REFERENCES dim_supplier(supplier_id),
  received_date  DATE NOT NULL,
  expiry_date    DATE NOT NULL,                -- received_date + shelf_life_days
  qty_received   NUMERIC(10,2) NOT NULL,
  qty_remaining  NUMERIC(10,2) NOT NULL
);

CREATE TABLE fact_forecast (
  run_id         INT,
  date_id        INT REFERENCES dim_date(date_id),
  ingredient_id  INT REFERENCES dim_ingredient(ingredient_id),
  model          VARCHAR(30),                  -- SES | SARIMA | HW | ML
  yhat           NUMERIC(10,3),
  lo80 NUMERIC(10,3), hi80 NUMERIC(10,3),
  lo95 NUMERIC(10,3), hi95 NUMERIC(10,3),
  is_selected    BOOLEAN,
  PRIMARY KEY (run_id, date_id, ingredient_id, model)
);

CREATE TABLE fact_model_score (
  run_id INT, ingredient_id INT, model VARCHAR(30),
  wmape NUMERIC(6,3), mase NUMERIC(6,3), rmse NUMERIC(10,3),
  holdout_start DATE, holdout_end DATE,
  PRIMARY KEY (run_id, ingredient_id, model)
);

CREATE TABLE fact_purchase_plan (
  run_id INT, scenario VARCHAR(20),             -- min_spoilage | balanced | max_availability
  ingredient_id INT, supplier_id INT,
  order_qty NUMERIC(10,2), delivery_date DATE, order_by TIMESTAMP,
  line_cost NUMERIC(12,2), ordered BOOLEAN DEFAULT FALSE
);

CREATE TABLE fact_recommendation (
  rec_id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMP, type VARCHAR(20),      -- stockout | spoilage | excess | weekly_order
  ingredient_id INT, recommended_qty NUMERIC(10,2), peso_impact NUMERIC(12,2),
  status VARCHAR(12),                           -- open | applied | modified | dismissed
  decided_by VARCHAR(60), decided_at TIMESTAMP, reason TEXT,
  outcome_text TEXT, outcome_waste_kg NUMERIC(10,2)
);

CREATE TABLE fact_stockout_event (
  date_id INT, ingredient_id INT, service_period VARCHAR(10), note TEXT
);

CREATE TABLE etl_run (
  run_id SERIAL PRIMARY KEY, started_at TIMESTAMP, finished_at TIMESTAMP,
  source_file TEXT, status VARCHAR(12), rows_loaded INT
);
```

---

## 3. Business rules (single source of truth)

- **Today** = server date at query time; every status recomputes on refresh.
- **Days left** = `expiry_date − today`. Expired < 0; Critical ≤ 1; Warning 2–3; OK > 3.
- **Use before expiry** = Σ forecast demand from today to expiry date.
- **At risk** = max(0, batch qty remaining − use before expiry). **₱ at risk** = at risk × unit_cost. Spoilage alert if at risk > 0.
- **Stockout warning** if projected stock (no new order) < reorder_level within supplier lead time.
- **Excess** if on hand > 1.5 × 7-day forecast. **Excess ₱** = (on hand − 7-day forecast) × unit_cost. Gauge = excess ₱ ÷ total inventory value; zones <10% ok, 10–20% review, >20% act.
- **LP input order** = 7-day forecast − usable on hand before expiry + safety stock (from 80% interval).
- **Model selection**: lowest WMAPE on 2-month holdout among models with MASE < 1.
- **Spoilage rate** = waste qty ÷ received qty. **Turnover** = COGS ÷ avg inventory value (monthly).
- **Alert badge** = count of open spoilage + stockout + excess alerts; same number everywhere.
- Scope: perishable raw materials only (`is_perishable = TRUE`).

---

## 4. Screens

Shared shell: top bar (logo, "Data as of <last etl_run.finished_at> · Loyverse export", user) + sidebar (Overview, Demand forecasts, Risk alerts [badge], Purchasing, Tracking) + pipeline status card. Sidebar stacks above content on mobile.

### 4.1 Overview — "Today's decisions"
- Actions: Upload Loyverse CSV · Log waste · Refresh data.
- KPI row (vs baseline Jun–Aug 2026): weekly food waste, spoilage rate, stockouts this week, inventory turnover.
- Decision queue (priority order, critical → routine). Each item: severity chip, type, title, evidence, ₱ impact, source (model/LP), buttons Apply / Modify / Dismiss… → writes `fact_recommendation`.
- Yesterday card: revenue, receipts, avg ticket, top 3 items **by revenue** (from same query).
- This week's order plan: spend vs budget bar → link to Purchasing.
- Daily revenue chart: last 7 days actual + next 7 days forecast.

### 4.2 Demand forecasts
- Ingredient tabs. Chart: 21 days actual (BOM-derived) + 14-day forecast, 80/95% bands, today marker, holiday flag marker (dim_date.is_holiday).
- Stats: next-7-day total + 80% interval, WMAPE, MASE.
- Model comparison: SES, SARIMA, Holt-Winters, ML regression — WMAPE bar, MASE, "fails MASE < 1" note, SELECTED tag.
- "How this feeds the order": forecast − usable on hand + safety = LP input.
- Table: all ingredients — selected model, next 7 days, interval, WMAPE, MASE, last retrained. Button: Retrain models.

### 4.3 Risk alerts
- Summary tiles: spoilage alerts (₱ at risk), stockout warning, excess (₱ tied up).
- Spoilage alert matrix: rows = batches; columns = next 7 days + ">7 d"; expiry cell red/amber/neutral with text; on hand, use before expiry, at risk (+₱), action (promo items from BOM + button) or "no risk" note.
- Stockout section: alert banner with exact qty/supplier/delivery split; chart of forecast demand bars, stock with LP order (solid), stock without order (dashed red), reorder line, shaded lead-time window.
- Excess capital gauge + per-ingredient stock vs forecast bars + "Freeze next order".
- Waste heatmap: ingredient × weekday, avg kg last 8 weeks, single-hue ramp, with one-line pattern insight.

### 4.4 Purchasing (LP)
- Constraints panel: budget, chiller capacity, safety stock (80%/95%/none), enforce shelf life, respect lead times, Re-run optimizer; objective shown.
- Scenario cards (radio): Minimize spoilage / Balanced (recommended) / Maximize availability — cost, projected waste, service level, over-budget or stockout warnings.
- Binding constraints + budget-used bar for the selected scenario.
- Supplier purchasing list (sorted by order-by): ordered checkbox, order by, ingredient, supplier name + ID, phone + contact person, lead time, qty + delivery split, unit cost, line cost, total.
- "Not ordered this cycle" note (covered stock / frozen excess). Print/PDF, Approve plan.

### 4.5 Tracking
- Baseline vs post-DSS KPI cards (4 metrics).
- Weekly food waste chart (12 weeks) with baseline line + go-live marker.
- Adoption: applied / modified / dismissed split + top dismissal reasons.
- Recommendation log: date, type, recommendation, decision (+reason), by, measured outcome.
- Forecast accuracy (weighted WMAPE) per week since go-live. Export comparison (PDF).

---

## 5. Sample dataset (internally consistent — replace with real data)

Today = Mon 19 Oct 2026. Last ETL = Sun 18 Oct 11:30 PM. Budget ₱45,000/week. Chiller 150 kg.

**Suppliers**
| ID | Name | Contact | Lead |
|---|---|---|---|
| SUP-01 | Tsukiji Fresh Marine Phils | +63 917 555 4281 (Mr. Bryan Tan) | 1 day |
| SUP-02 | Niigata Grain Alliance Inc. | +63 918 882 1940 (Sales Desk) | 2 days |
| SUP-03 | Ariake Nori Imports Corp | +63 922 419 7733 (Order Desk) | 2 days |
| SUP-04 | Valley Organic Produce Direct | +63 908 333 1120 (Aling Teresa) | 1 day |
| SUP-05 | Yamashiro Shoyu Foodservice | +63 917 220 8891 (Office) | 3 days |

**Ingredients**
| Ingredient | Supplier | Unit cost | On hand | Received | Shelf life | Expires | 7-day forecast | Model | WMAPE | MASE |
|---|---|---|---|---|---|---|---|---|---|---|
| Fresh salmon | SUP-01 | ₱1,150/kg | 6.0 kg | Sat 17 Oct | 3 d | Tue 20 Oct | 21.0 kg | SARIMA(1,0,1)(1,1,1)7 | 11.9% | 0.57 |
| Tuna loin | SUP-01 | ₱1,400/kg | 2.0 kg | Sun 18 Oct | 3 d | Wed 21 Oct | 11.2 kg | Holt-Winters add. | 14.2% | 0.62 |
| Hamachi | SUP-01 | ₱1,250/kg | 2.4 kg | Sun 18 Oct | 4 d | Thu 22 Oct | 4.2 kg | Holt-Winters add. | 19.8% | 0.79 |
| Koshihikari rice | SUP-02 | ₱140/kg | 45 kg | — | 180 d | — | 38.5 kg | SES α=0.32 | 6.3% | 0.48 |
| Nori sheets (50/pack) | SUP-03 | ₱420/pack | 6 packs | — | long | — | 9 packs | SES α=0.21 | 9.1% | 0.55 |
| Hass avocado | SUP-04 | ₱65/pc | 30 pcs | Sat 17 Oct | 4 d | Wed 21 Oct | 42 pcs | ML regression (GBM) | 17.5% | 0.70 |
| Japanese cucumber | SUP-04 | ₱180/kg | 4.0 kg | Fri 16 Oct | 7 d | Fri 23 Oct | 5.6 kg | SES α=0.28 | 12.4% | 0.61 |
| Ebi (frozen) | SUP-01 | ₱620/kg | 9.0 kg | Thu 1 Oct | 90 d | — | 3.5 kg | — | — | — |
| Cream cheese | SUP-05 | ₱480/kg | 5.0 kg | Mon 12 Oct | 21 d | Mon 2 Nov | 1.8 kg | — | — | — |

Total on-hand value = ₱32,170.

**Alerts (badge = 5)**
- Spoilage: salmon 2.8 kg at risk (use before expiry 3.2) = ₱3,220; avocado 12 pcs (use 18) = ₱780.
- Stockout: tuna below reorder level 3.2 kg, runs out Tue 20 Oct; order 9.5 kg (3.5 Tue · 3.0 Thu · 3.0 Sat). Daily tuna forecast Mon–Sun: 1.23, 1.15, 1.30, 1.38, 1.99, 2.30, 1.84.
- Excess: ebi 5.5 kg = ₱3,410; cream cheese 3.2 kg = ₱1,536; total ₱4,946 = 15.4% of inventory value.

**Purchase plan (Balanced)**
| Ingredient | Qty | Deliveries | Order by | Line cost |
|---|---|---|---|---|
| Fresh salmon | 18.0 kg | 6.0 Tue · 6.0 Thu · 6.0 Sat | Today 3 PM | ₱20,700 |
| Tuna loin | 9.5 kg | 3.5 Tue · 3.0 Thu · 3.0 Sat | Today 3 PM | ₱13,300 |
| Hamachi | 2.0 kg | Thu | Today 3 PM | ₱2,500 |
| Nori | 5 packs | Wed | Today 5 PM | ₱2,100 |
| Hass avocado | 24 pcs | 12 Thu · 12 Sat | Wed 21 Oct | ₱1,560 |
| Japanese cucumber | 2.0 kg | Fri | Thu 22 Oct | ₱360 |
| **Total** | | | | **₱40,520** (90% of budget) |

Not ordered: rice (covered), ebi + cream cheese (frozen as excess).

**Scenarios**
| Scenario | Cost | Waste | Service | Note |
|---|---|---|---|---|
| Minimize spoilage | ₱36,393 | 3.9 kg | 95.1% | 2 stockout-risk days (tuna Sat) |
| Balanced ★ | ₱40,520 | 5.2 kg | 98.6% | Shelf life binds salmon/tuna; ₱4,480 budget slack; chiller peak 38/150 kg |
| Maximize availability | ₱46,883 | 9.4 kg | 99.7% | Over budget by ₱1,883 |

**KPIs**
| Metric | Baseline (Jun–Aug) | Post-DSS 4-wk avg | This week |
|---|---|---|---|
| Weekly food waste | 24.5 kg | 19.4 kg | 17.9 kg |
| Spoilage rate | 8.2% | 6.6% | 6.0% |
| Stockout frequency | 3.1/wk | 1.5/wk | 1 |
| Inventory turnover | 4.2×/mo | 4.9×/mo | 5.1× |

Weekly waste (wk of): 27 Jul 25.1 · 3 Aug 23.8 · 10 Aug 24.9 · 17 Aug 24.2 · 24 Aug 25.6 · 31 Aug 23.9 · 7 Sep 24.4 · 14 Sep 24.0 · **go-live** 21 Sep 21.8 · 28 Sep 19.6 · 5 Oct 18.4 · 12 Oct 17.9.
Weighted WMAPE since go-live: 15.8% → 14.9% → 14.1% → 13.6%.

**Sales**: Sun 18 Oct revenue ₱48,600, 96 receipts, avg ₱506. Top by revenue: Salmon Sashimi 5pc 38 × ₱290 = ₱11,020; California Maki 52 × ₱190 = ₱9,880; Spicy Tuna Roll 34 × ₱230 = ₱7,820.
Daily revenue Mon 12–Sun 18: 31,200 · 29,800 · 33,400 · 36,100 · 52,300 · 61,800 · 48,600. Forecast Mon 19–Sun 25: 32,000 · 30,500 · 34,200 · 37,000 · 53,900 · 63,500 · 50,100.

---

## 6. Acceptance checklist
- [ ] No hard-coded numbers in UI; all from PostgreSQL views.
- [ ] Same alert count on Overview, sidebar badge, and Risk page.
- [ ] Top items ⊂ daily revenue; totals reconcile.
- [ ] Expiry status recomputes against today; "Expired" state exists.
- [ ] Every recommendation shows evidence, ₱ impact, and source run; Apply/Modify/Dismiss write to `fact_recommendation`.
- [ ] Purchasing list = LP output joined to `dim_supplier`; totals match budget bar.
- [ ] Forecast page shows all 4 models with WMAPE + MASE (no MAPE).
- [ ] "Data as of" shown on every page; CSV upload + refresh + waste log work.
- [ ] No "AI" wording; no methodology badges in the UI.
- [ ] Status never color-only; text contrast ≥ 4.5:1; works at phone width.
- [ ] Manuscript Chapter 3 updated for schema changes, metric consistency, and Power BI vs web app decision.
