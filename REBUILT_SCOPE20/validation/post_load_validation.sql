-- =====================================================================
-- Makisushi dw - POST-LOAD VALIDATION (read-only: SELECT only, no DDL/DML)
-- Run in the Supabase SQL editor (or psql -f) after 01_schema.sql, 02_load_staging.psql, 03_transform.sql.
-- Every check returns one row: check_id, area, description, violations, expected, status, known_exception.
--   status PASS  : violations = expected
--   status KNOWN : violations = the count of a documented, accepted exception (see known_exception and
--                  reports/AUDIT_REPORT.md); NOT a clean pass - it needs a decision, it does not need a reload
--   status FAIL  : anything else - investigate before using the data
--   status INFO  : informational figure (expected is NULL)
-- Only the dw schema is read (stg.* is not needed, so it still works after stg is dropped).
-- =====================================================================
with
-- ---------- reference constants ----------
p as (select date '2021-09-01' as load_start, date '2026-09-30' as study_end),
-- ---------- sales line arithmetic ----------
s as (select f.*, c.category_name as category, m.pos_sku   -- category and SKU are the menu item's (not stored on the fact)
      from dw.fact_sales f join dw.dim_menu_item m using (item_id) join dw.dim_menu_category c using (category_id)),
chk(check_id, area, description, violations, expected) as (
  -- ===== ROW COUNTS =====
  select 'CNT01', 'rowcount', 'dim_date rows', (select count(*) from dw.dim_date), null::bigint
  union all select 'CNT02','rowcount','dim_menu_item rows',(select count(*) from dw.dim_menu_item),null
  union all select 'CNT03','rowcount','dim_menu_category rows',(select count(*) from dw.dim_menu_category),null
  union all select 'CNT04','rowcount','dim_ingredient rows',(select count(*) from dw.dim_ingredient),null
  union all select 'CNT05','rowcount','dim_supplier rows',(select count(*) from dw.dim_supplier),null
  union all select 'CNT06','rowcount','bridge_recipe_bom rows',(select count(*) from dw.bridge_recipe_bom),null
  union all select 'CNT07','rowcount','supplier_item_terms rows',(select count(*) from dw.supplier_item_terms),null
  union all select 'CNT08','rowcount','fact_sales rows',(select count(*) from dw.fact_sales),null
  union all select 'CNT09','rowcount','fact_inventory_snapshot rows',(select count(*) from dw.fact_inventory_snapshot),null
  union all select 'CNT10','rowcount','fact_inventory_batch_snapshot rows',(select count(*) from dw.fact_inventory_batch_snapshot),null
  union all select 'CNT11','rowcount','fact_inventory_transaction rows',(select count(*) from dw.fact_inventory_transaction),null
  union all select 'CNT12','rowcount','fact_waste rows',(select count(*) from dw.fact_waste),null
  union all select 'CNT13','rowcount','forecast / optimization output tables (empty before the engines run)',
         (select (select count(*) from dw.forecast_run)+(select count(*) from dw.fact_demand_forecast)+(select count(*) from dw.optimization_run)
                 +(select count(*) from dw.fact_replenishment_plan)),null
  -- ===== dim_date =====
  union all select 'DAT01','dim_date','calendar gaps inside [min,max]',
     (select (max(date)-min(date)+1) - count(*) from dw.dim_date), 0
  union all select 'DAT02','dim_date','day_of_week text <> Monday..Sunday from date',
     (select count(*) from dw.dim_date where day_of_week <> trim(to_char(date,'Day'))), 0
  union all select 'DAT03','dim_date','dow <> isodow-1',(select count(*) from dw.dim_date where dow <> extract(isodow from date)-1),0
  union all select 'DAT04','dim_date','iso_week / iso_year <> ISO calendar',
     (select count(*) from dw.dim_date where iso_week <> extract(week from date) or iso_year <> extract(isoyear from date)),0
  union all select 'DAT05','dim_date','week_start_date is not the Monday of the date',
     (select count(*) from dw.dim_date where week_start_date <> date_trunc('week', date)::date),0
  union all select 'DAT06','dim_date','month / quarter / year wrong',
     (select count(*) from dw.dim_date where month <> extract(month from date) or quarter <> extract(quarter from date) or year <> extract(year from date)),0
  union all select 'DAT07','dim_date','is_weekend <> (Sat or Sun)',(select count(*) from dw.dim_date where is_weekend <> (extract(isodow from date) >= 6)),0
  union all select 'DAT10','dim_date','is_ber_month <> (month in Sep..Dec)',(select count(*) from dw.dim_date where is_ber_month <> (month >= 9)),0
  union all select 'DAT12','dim_date','calendar starts before the stated study start 2021-10-01 (days of pre-study history loaded)',
     (select (select date '2021-10-01') - min(date) from dw.dim_date),null
  -- ===== orphans / FK resolution (declared FKs prevent these; re-tested independently) =====
  union all select 'FK01','orphan','fact_sales.item_id not in dim_menu_item',(select count(*) from dw.fact_sales f left join dw.dim_menu_item m using(item_id) where m.item_id is null),0
  union all select 'FK02','orphan','fact_sales.sale_date not in dim_date',(select count(*) from dw.fact_sales f left join dw.dim_date d on d.date=f.sale_date where d.date is null),0
  union all select 'FK03','orphan','bridge_recipe_bom item/ingredient not in dims',
     (select count(*) from dw.bridge_recipe_bom b left join dw.dim_menu_item m using(item_id) left join dw.dim_ingredient i using(ingredient_id) where m.item_id is null or i.ingredient_id is null),0
  union all select 'FK04','orphan','fact_inventory_* ingredient not in dim_ingredient',
     (select (select count(*) from dw.fact_inventory_snapshot x left join dw.dim_ingredient i using(ingredient_id) where i.ingredient_id is null)
           + (select count(*) from dw.fact_inventory_batch_snapshot x left join dw.dim_ingredient i using(ingredient_id) where i.ingredient_id is null)
           + (select count(*) from dw.fact_inventory_transaction x left join dw.dim_ingredient i using(ingredient_id) where i.ingredient_id is null)
           + (select count(*) from dw.fact_waste x left join dw.dim_ingredient i using(ingredient_id) where i.ingredient_id is null)),0
  union all select 'FK05','orphan','batch / waste supplier not in dim_supplier',
     (select (select count(*) from dw.fact_inventory_batch_snapshot x left join dw.dim_supplier i using(supplier_id) where i.supplier_id is null)
           + (select count(*) from dw.fact_waste x left join dw.dim_supplier i using(supplier_id) where i.supplier_id is null)),0
  union all select 'FK06','orphan','fact_waste.batch_id not in any batch snapshot',
     (select count(*) from dw.fact_waste w where not exists (select 1 from dw.fact_inventory_batch_snapshot b where b.batch_id=w.batch_id)),0
  union all select 'FK07','orphan','supplier_item_terms / dim_ingredient.storage_type orphans',
     (select (select count(*) from dw.supplier_item_terms t left join dw.dim_supplier s using(supplier_id) left join dw.dim_ingredient i using(ingredient_id) where s.supplier_id is null or i.ingredient_id is null)
           + (select count(*) from dw.dim_ingredient i left join dw.dim_storage st using(storage_type) where st.storage_type is null)),0
  union all select 'FK08','orphan','dim_menu_item.category_id orphans',
     (select count(*) from dw.dim_menu_item m left join dw.dim_menu_category c using(category_id) where c.category_id is null),0
  -- ===== sales =====
  union all select 'SAL01','sales','gross_sales <> quantity_sold * unit_price beyond the cent rounding of unit_price (0.005 x quantity)',(select count(*) from s where abs(gross_sales - quantity_sold*unit_price) > 0.005*quantity_sold + 0.00001),0
  union all select 'SAL01b','sales','lines where gross_sales <> quantity_sold * unit_price at all (POS stores unit_price = gross / quantity, rounded to cents; info)',(select count(*) from s where abs(gross_sales - quantity_sold*unit_price) > 0.005),null
  union all select 'SAL02','sales','net_sales <> gross_sales - discount (>0.005)',(select count(*) from s where abs(net_sales-(gross_sales-discount)) > 0.005),0
  union all select 'SAL03','sales','discount > gross_sales',(select count(*) from s where discount > gross_sales),0
  union all select 'SAL04','sales','channel outside Dine-In/GrabFood',(select count(*) from s where channel not in ('Dine-In','GrabFood')),0
  union all select 'SAL05','sales','Management-category line on GrabFood (prohibited combination)',(select count(*) from s where category='Management' and channel='GrabFood'),0
  union all select 'SAL08','sales','is_revenue=false line with net_sales > 0',(select count(*) from s where not is_revenue and net_sales > 0),0
  union all select 'SAL09','sales','is_revenue=true line with net_sales = 0',(select count(*) from s where is_revenue and net_sales = 0),null
  union all select 'SAL10','sales','Management/COMP category line flagged is_revenue',
     (select count(*) from s where category='Management' and is_revenue),0
  union all select 'SAL11','sales','unit_price <> menu list_price (ungrouped; GrabFood uplift expected) lines',
     (select count(*) from s join dw.dim_menu_item m using(item_id) where s.unit_price <> m.list_price and s.unit_price > 0),null
  union all select 'SAL12','sales','groups of lines identical except sale_id (possible double-logged lines)',
     (select count(*) from (select 1 from s group by sale_date,item_id,channel,quantity_sold,unit_price,gross_sales,discount,net_sales,is_revenue having count(*)>1) g),null
  union all select 'SAL13','sales','sales on inactive menu items',(select count(*) from s join dw.dim_menu_item m using(item_id) where not m.is_active),null
  union all select 'SAL14','sales','sale_id gaps (max - count)',(select max(sale_id)-count(*) from s),null
  union all select 'SAL15','sales','lines dated before 2021-10-01 (outside stated study period, kept)',(select count(*) from s where sale_date < date '2021-10-01'),null
  union all select 'SAL16','sales','menu items with no sale line at all',(select count(*) from dw.dim_menu_item m where not exists (select 1 from s where s.item_id=m.item_id)),null
  union all select 'SAL17','sales','promo_name / promo_year columns present in fact_sales',
     (select count(*) from information_schema.columns where table_schema='dw' and table_name='fact_sales' and column_name in ('promo_name','promo_year')),0
  -- ===== menu / BOM =====
  union all select 'BOM01','bom','qty_base <= 0',(select count(*) from dw.bridge_recipe_bom where qty_base<=0),0
  union all select 'BOM03','bom','BOM ingredients whose base_uom is not g/ml/pc/serving',(select count(*) from dw.bridge_recipe_bom b join dw.dim_ingredient i using(ingredient_id) where i.base_uom not in ('g','ml','pc','serving')),0
  union all select 'BOM04','bom','sold items with no recipe (distinct items)',
     (select count(distinct s.item_id) from s where not exists (select 1 from dw.bridge_recipe_bom b where b.item_id=s.item_id)),null
  union all select 'BOM05','bom','net sales of sold items with no recipe (PHP)',
     (select round(coalesce(sum(net_sales),0)) from s where not exists (select 1 from dw.bridge_recipe_bom b where b.item_id=s.item_id)),null
  union all select 'BOM06','bom','ingredients used by no recipe',(select count(*) from dw.dim_ingredient i where not exists (select 1 from dw.bridge_recipe_bom b where b.ingredient_id=i.ingredient_id)),null
  union all select 'BOM07','bom','recipe items that are never sold',(select count(distinct b.item_id) from dw.bridge_recipe_bom b where not exists (select 1 from s where s.item_id=b.item_id)),null
  union all select 'BOM09','bom','v_theoretical_consumption rows exceeding distinct (date,ingredient) (join multiplication)',
     (select count(*) - (select count(*) from (select distinct sale_date,ingredient_id from dw.v_theoretical_consumption) q) from dw.v_theoretical_consumption),0
  -- ===== inventory snapshot =====
  union all select 'INV01','inventory','ingredient x day grain incomplete (expected perishable-scope ingredients x calendar days - actual)',
     (select (select count(*) from dw.dim_ingredient where is_perishable)*(select count(*) from dw.dim_date where date <= (select max(snapshot_date) from dw.fact_inventory_snapshot)) - count(*) from dw.fact_inventory_snapshot),0
  union all select 'INV02','inventory','ledger imbalance > 0.01 (open+recv+emerg-consumed-waste-close)',(select count(*) from dw.v_inventory_ledger_check where abs(imbalance)>0.01),0
  union all select 'INV03','inventory','opening_qty <> previous day closing_qty',
     (select count(*) from (select snapshot_date, opening_qty, lag(closing_qty) over (partition by ingredient_id order by snapshot_date) pc from dw.fact_inventory_snapshot) x where pc is not null and abs(opening_qty-pc)>0.01),0
  union all select 'INV06','inventory','days with closing_qty = 0 (valid zero stock, informational)',(select count(*) from dw.fact_inventory_snapshot where closing_qty=0),null
  union all select 'INV07','inventory','batch quantity <> closing quantity (v_batch_snapshot_check)',(select count(*) from dw.v_batch_snapshot_check where abs(difference)>0.01),0
  union all select 'INV08','inventory','on_order_qty > 0 on a day with no PURCHASE_ORDER/pending order (info: days with on_order>0)',(select count(*) from dw.fact_inventory_snapshot where on_order_qty>0),null
  -- ===== batches =====
  union all select 'BAT01','batch','expiry_date more than one day away from received_date + shelf_life - 1 (batch shelf life varies by one day)',
     (select count(*) from (select distinct batch_id, ingredient_id, received_date, expiry_date from dw.fact_inventory_batch_snapshot) b join dw.dim_ingredient i using(ingredient_id)
        where abs(b.expiry_date - (b.received_date + (i.shelf_life_days-1))) > 1 or b.expiry_date < b.received_date),0
  union all select 'BAT02','batch','batch attributes (ingredient/supplier/received/expiry/unit_cost) vary between snapshot days',
     (select count(*) from (select batch_id from dw.fact_inventory_batch_snapshot group by batch_id having count(distinct (ingredient_id,supplier_id,received_date,expiry_date,unit_cost))>1) q),0
  union all select 'BAT03','batch','batch supplier <> the ingredient primary supplier',
     (select count(*) from (select distinct batch_id, ingredient_id, supplier_id from dw.fact_inventory_batch_snapshot) b
        left join dw.supplier_item_terms t on t.ingredient_id=b.ingredient_id and t.supplier_id=b.supplier_id where t.ingredient_id is null),0
  union all select 'BAT04','batch','batch qty_on_hand increases from one day to the next',
     (select count(*) from (select qty_on_hand, lag(qty_on_hand) over (partition by batch_id order by snapshot_date) pq from dw.fact_inventory_batch_snapshot) x where pq is not null and qty_on_hand > pq + 0.0001),0
  union all select 'BAT05','batch','batch snapshot day gap (non-consecutive days for one batch)',
     (select count(*) from (select snapshot_date, lag(snapshot_date) over (partition by batch_id order by snapshot_date) pd from dw.fact_inventory_batch_snapshot) x where pd is not null and snapshot_date - pd <> 1),null
  union all select 'BAT06','batch','batch used after expiry (v_expired_batch_use_check)',(select count(*) from dw.v_expired_batch_use_check where abs(used_after_expiry)>0.01),0
  union all select 'BAT07','batch','batches RECEIVED before first snapshot date (opening stock, info)',
     (select count(distinct batch_id) from dw.fact_inventory_batch_snapshot where received_date < (select min(date) from dw.dim_date)),null
  -- ===== transactions =====
  union all select 'TXN01','txn','RECEIPT quantity <> snapshot receipts / CONSUMPTION <> consumed (ledger-implied)',
     (select count(*) from dw.v_inventory_ledger_check where abs(imbalance)>0.01),0
  union all select 'TXN02','txn','extended_cost <> quantity x unit_cost',(select count(*) from dw.fact_inventory_transaction where abs(extended_cost-round(quantity*unit_cost,2))>0.01),0
  union all select 'TXN03','txn','stock_effect sign wrong',(select count(*) from dw.fact_inventory_transaction where (txn_type in ('RECEIPT','EMERGENCY_PURCHASE') and stock_effect<=0) or (txn_type='CONSUMPTION' and stock_effect>=0) or (txn_type='PURCHASE_ORDER' and stock_effect<>0)),0
  union all select 'TXN04','txn','RECEIPT without supplier / PURCHASE_ORDER without supplier',(select count(*) from dw.fact_inventory_transaction where txn_type in ('RECEIPT','PURCHASE_ORDER') and supplier_id is null),0
  union all select 'TXN05','txn','receipts with no earlier-or-same-day purchase order for the ingredient (receipts without a PO in last 30d)',
     (select count(*) from dw.fact_inventory_transaction r where r.txn_type='RECEIPT'
        and not exists (select 1 from dw.fact_inventory_transaction o where o.txn_type='PURCHASE_ORDER' and o.ingredient_id=r.ingredient_id and o.txn_date<=r.txn_date and o.txn_date>=r.txn_date-30)),null
  union all select 'TXN06','txn','transaction counts: PO / RECEIPT / EMERGENCY / CONSUMPTION (info, PO total)',(select count(*) from dw.fact_inventory_transaction where txn_type='PURCHASE_ORDER'),null
  union all select 'TXN07','txn','PURCHASE_ORDER quantity counted into stock_effect',(select coalesce(sum(stock_effect),0) from dw.fact_inventory_transaction where txn_type='PURCHASE_ORDER'),0
  -- ===== waste =====
  union all select 'WST01','waste','expiry waste_qty <> batch qty_on_hand on its last usable day',
     (select count(*) from dw.fact_waste w join dw.fact_inventory_batch_snapshot b on b.batch_id=w.batch_id and b.snapshot_date=w.expiry_date where w.waste_reason in ('over_ordering','expiry') and abs(b.qty_on_hand-w.waste_qty)>0.0001),0
  union all select 'WST02','waste','expiry waste rows whose batch has no snapshot on its expiry date',
     (select count(*) from dw.fact_waste w where w.waste_reason in ('over_ordering','expiry') and not exists (select 1 from dw.fact_inventory_batch_snapshot b where b.batch_id=w.batch_id and b.snapshot_date=w.expiry_date)),null
  union all select 'WST03','waste','waste header (ingredient/supplier/received/expiry/unit_cost) differs from batch snapshot',
     (select count(*) from dw.fact_waste w join (select distinct batch_id,ingredient_id,supplier_id,received_date,expiry_date,unit_cost from dw.fact_inventory_batch_snapshot) b using(batch_id)
        where w.ingredient_id<>b.ingredient_id or w.supplier_id<>b.supplier_id or w.received_date<>b.received_date or w.expiry_date<>b.expiry_date or abs(w.unit_cost-b.unit_cost)>0.00005),0
  union all select 'WST04','waste','expired batches (last day < max date) with no waste row (undisposed)',
     (select count(*) from (select distinct batch_id, expiry_date from dw.fact_inventory_batch_snapshot where expiry_date < (select max(date) from dw.dim_date where date <= (select max(snapshot_date) from dw.fact_inventory_snapshot))) b
        where not exists (select 1 from dw.fact_waste w where w.batch_id=b.batch_id and w.waste_reason in ('over_ordering','expiry'))
          and exists (select 1 from dw.fact_inventory_batch_snapshot x where x.batch_id=b.batch_id and x.snapshot_date=b.expiry_date)),0
  union all select 'WST05','waste','batch still on snapshot after its expiry date',(select count(*) from dw.fact_inventory_batch_snapshot where snapshot_date>expiry_date),0
  union all select 'WST06','waste','waste_date later than the day after expiry_date (expired during a closure, binned on reopening; info)',
     (select count(*) from dw.fact_waste where waste_reason in ('over_ordering','expiry') and waste_date>expiry_date+1),null
  union all select 'WST11','waste','waste rows per reason: over_ordering (batch larger than normal demand over its shelf life; info)',(select count(*) from dw.fact_waste where waste_reason='over_ordering'),null
  union all select 'WST12','waste','waste rows per reason: expiry (info)',(select count(*) from dw.fact_waste where waste_reason='expiry'),null
  union all select 'WST13','waste','waste rows per reason: spoilage (part of a batch lost inside its shelf life; info)',(select count(*) from dw.fact_waste where waste_reason='spoilage'),null
  union all select 'WST14','waste','waste rows per reason: shrinkage (small unexplained losses / miscounts; info)',(select count(*) from dw.fact_waste where waste_reason='shrinkage'),null
  union all select 'WST15','waste','losses inside the shelf life dated outside the life of their batch',(select count(*) from dw.fact_waste where waste_reason in ('spoilage','shrinkage') and (waste_date<received_date or waste_date>expiry_date)),0
  union all select 'WST08','waste','waste_value_php <> waste_qty x unit_cost (>0.01)',(select count(*) from dw.fact_waste where abs(waste_value_php-round(waste_qty*unit_cost,2))>0.01),0
  union all select 'WST10','waste','whole-batch disposal: waste rows whose waste_date has no matching ledger day',
     (select count(*) from dw.fact_waste w where not exists (select 1 from dw.fact_inventory_snapshot s where s.snapshot_date=(case when w.waste_reason in ('spoilage','shrinkage') then w.waste_date else w.expiry_date+1 end) and s.ingredient_id=w.ingredient_id)),0
  -- ===== supplier / replenishment =====
  union all select 'SUP01','supplier','ingredients with no primary supplier term',(select count(*) from dw.dim_ingredient i where not exists (select 1 from dw.supplier_item_terms t where t.ingredient_id=i.ingredient_id)),0
  union all select 'SUP02','supplier','ingredients with more than one supplier term',(select count(*) from (select ingredient_id from dw.supplier_item_terms group by 1 having count(*)>1) q),null
  union all select 'SUP03','supplier','suppliers with no term',(select count(*) from dw.dim_supplier s where not exists (select 1 from dw.supplier_item_terms t where t.supplier_id=s.supplier_id)),0
  union all select 'SUP07','supplier','dim_storage rows with NULL capacity_qty_l (LP storage constraint inputs missing)',(select count(*) from dw.dim_storage where capacity_qty_l is null),0
  union all select 'SUP08','supplier','ingredients whose inventory snapshot supplier is not primary (n/a: snapshot has no supplier col) - ingredients with batches from >1 supplier',
     (select count(*) from (select ingredient_id from dw.fact_inventory_batch_snapshot group by 1 having count(distinct supplier_id)>1) q),0
  union all select 'SUP09','supplier','lead_time_days < 1 or delivery_interval_days < 1',(select count(*) from dw.dim_supplier where lead_time_days<1 or delivery_interval_days<1),0
  -- ===== ingredient dimension =====
  union all select 'ING01','ingredient','perishable rule (scope of 2026-10-19, same as the dim_ingredient check): shelf life <= 5 days => is_perishable',(select count(*) from dw.dim_ingredient where not is_perishable and shelf_life_days<=5),0
  union all select 'SCP01','scope','ingredients with inventory snapshot rows that are outside the perishable scope',(select count(distinct s.ingredient_id) from dw.fact_inventory_snapshot s join dw.dim_ingredient i using (ingredient_id) where not i.is_perishable),0
  union all select 'SCP02','scope','batch, waste, transaction or shortage rows of ingredients outside the perishable scope',
     (select (select count(*) from dw.fact_inventory_batch_snapshot b join dw.dim_ingredient i using (ingredient_id) where not i.is_perishable)
           + (select count(*) from dw.fact_waste w join dw.dim_ingredient i using (ingredient_id) where not i.is_perishable)
           + (select count(*) from dw.fact_inventory_transaction t join dw.dim_ingredient i using (ingredient_id) where not i.is_perishable)
           + (select count(*) from dw.fact_stockout_event e join dw.dim_ingredient i using (ingredient_id) where not i.is_perishable)),0
  union all select 'SCP03','scope','perishable-scope ingredients with no inventory snapshot rows',(select count(*) from dw.dim_ingredient i where i.is_perishable and not exists (select 1 from dw.fact_inventory_snapshot s where s.ingredient_id=i.ingredient_id)),0
  union all select 'SCP04','scope','out-of-scope ingredients missing from the recipe BOM (they must stay available for recipe costing)',(select count(*) from dw.dim_ingredient i where not i.is_perishable and not exists (select 1 from dw.bridge_recipe_bom b where b.ingredient_id=i.ingredient_id)),0
  union all select 'SCP05','scope','v_menu_item_standard_cost lines <> BOM lines (recipe costing must include every ingredient)',(select (select sum(ingredient_lines) from dw.v_menu_item_standard_cost) - (select count(*) from dw.bridge_recipe_bom)),0
  union all select 'SCP06','scope','v_lp_ingredient_week_input or v_ingredient_shortage_penalty rows for out-of-scope ingredients',
     (select (select count(*) from dw.v_lp_ingredient_week_input v join dw.dim_ingredient i using (ingredient_id) where not i.is_perishable) + (select count(*) from dw.v_ingredient_shortage_penalty p join dw.dim_ingredient i using (ingredient_id) where not i.is_perishable)),0
  union all select 'ING02','ingredient','standard_unit_cost = 0',(select count(*) from dw.dim_ingredient where standard_unit_cost=0),0
  union all select 'ING03','ingredient','batch unit_cost differs from standard_unit_cost by more than 25% (info)',
     (select count(*) from (select distinct b.batch_id, b.unit_cost, i.standard_unit_cost from dw.fact_inventory_batch_snapshot b join dw.dim_ingredient i using(ingredient_id)) q where abs(unit_cost/standard_unit_cost-1)>0.25),null
  -- ===== views run =====
  union all select 'VW01','view','v_theoretical_consumption rows',(select count(*) from dw.v_theoretical_consumption),null
  union all select 'VW02','view','v_consumption_variance rows',(select count(*) from dw.v_consumption_variance),null
  union all select 'VW03','view','v_menu_item_standard_cost rows / items with a recipe (must be equal)',
     (select (select count(*) from dw.v_menu_item_standard_cost) - (select count(distinct item_id) from dw.bridge_recipe_bom)),0
  union all select 'VW04','view','v_inventory_ledger_check rows - fact_inventory_snapshot rows (join multiplication)',
     (select (select count(*) from dw.v_inventory_ledger_check) - (select count(*) from dw.fact_inventory_snapshot)),0
  union all select 'VW05','view','v_batch_snapshot_check rows - fact_inventory_snapshot rows',
     (select (select count(*) from dw.v_batch_snapshot_check) - (select count(*) from dw.fact_inventory_snapshot)),0
  union all select 'VW06','view','v_waste_by_context sum(events) - fact_waste rows',
     (select (select sum(events) from dw.v_waste_by_context) - (select count(*) from dw.fact_waste)),0
  union all select 'VW07','view','v_expired_batch_use_check rows',(select count(*) from dw.v_expired_batch_use_check),null
  union all select 'VW08','view','v_near_expiry_promotion rows (latest snapshot, days_to_expiry<=2)',(select count(*) from dw.v_near_expiry_promotion),null
  union all select 'VW09','view','v_lp_ingredient_week_input rows (0 until a champion forecast exists)',(select count(*) from dw.v_lp_ingredient_week_input),null
  union all select 'CLS01','forecast','observed days with no sale line (closures + the 2 removed duplicate days; dim_date.is_open tells closures apart)',
     (select count(*) from dw.dim_date d where d.date <= (select max(snapshot_date) from dw.fact_inventory_snapshot) and not exists (select 1 from dw.fact_sales f where f.sale_date=d.date)),null
  union all select 'CLS02','forecast','closed days (is_open = false) that are not flagged is_holiday (the two removed duplicate days are open but have no sale line)',
     (select count(*) from dw.dim_date d where d.date <= (select max(snapshot_date) from dw.fact_inventory_snapshot) and not d.is_open and d.is_holiday = false),0
  union all select 'VW10','view','v_consumption_variance: |variance| > 0.01 (unexplained by sales x BOM; includes off-POS use and lost lines)',
     (select count(*) from dw.v_consumption_variance where abs(variance_qty)>0.01),null
)
select c.check_id, c.area, c.description, c.violations::numeric as violations, c.expected::numeric as expected,
       case when c.expected is null then 'INFO'
            when c.violations = c.expected then 'PASS'
            when k.known_count is not null and c.violations = k.known_count then 'KNOWN'
            else 'FAIL' end as status,
       k.why as known_exception
from chk c
left join (values
    ('SUP07', 3, 'storage capacities are litres per unit and no site survey exists; LP storage constraint input is missing')
) k(check_id, known_count, why) on k.check_id = c.check_id
order by c.check_id;
