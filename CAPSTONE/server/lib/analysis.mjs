// Business rules of the DSS (docs/DSS_REDESIGN.md section 3) applied to warehouse data.
// Every number the screens show is computed here from dw.* rows; nothing is hard-coded except the rules below.
import * as L from './load.mjs';
import { currentModel } from './modelcontext.mjs';
import { addDays, diffDays, dow, mondayOf, days, label } from './dates.mjs';

export const RULES = {
  budgetExempt: new Set(['SAL', 'TUN']),   // whole salmon / tuna are outside the weekly budget (engines/optimize_engine.py BUDGET_EXEMPT)
  excessFactor: 1.5,                        // excess if on hand > 1.5 x 7-day forecast
  gaugeScale: 0.4,                          // gauge shows 0-40 %
  criticalDays: 1, warningDays: 3,          // days left: critical <= 1, warning 2-3, ok > 3
  chartActualDays: 21, chartForecastDays: 14,
  recommendedScenario: 'balanced',
  // 'runout'  : a stockout warning counts when projected stock (no new order, open orders included) runs out before a new order can arrive.
  // 'reorder' : also counts every ingredient whose inventory position (on hand + on order) is under its reorder level.
  stockoutMode: 'runout',
};

export const MODEL_LABEL = { SES: 'SES', SARIMA: 'SARIMA', HOLT_LINEAR: 'Holt linear', HOLT_WINTERS: 'Holt-Winters', ML_REGRESSION: 'ML regression', NAIVE: 'Naive baseline' };
export const MODEL_NOTE = {
  SES: 'no trend or seasonality', SARIMA: 'weekly seasonality, s = 7', HOLT_WINTERS: 'trend + weekly seasonality',
  HOLT_LINEAR: 'trend, no seasonality', ML_REGRESSION: 'adds weekday + holiday features', NAIVE: 'repeats the last observed week',
};
export const MODEL_ORDER = ['SES', 'SARIMA', 'HOLT_LINEAR', 'HOLT_WINTERS', 'ML_REGRESSION'];
export const modelsLabel = (st) => (st.productionModels.length ? st.productionModels.map((m) => MODEL_LABEL[m] ?? m).join(' + ') : 'none');

export const num = (v) => (v === null || v === undefined ? 0 : Number(v));
const sum = (a) => a.reduce((x, y) => x + y, 0);
export const quantile = (sorted, p) => {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * p;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
};

// ---- units --------------------------------------------------------------------------------------------------
export const unitMeta = (ing, weeklyBase = 0) => {
  if (ing.uom === 'g') {
    const weekly = weeklyBase / 1000;
    return { unit: 'kg', scale: 1000, dp: weekly >= 5 ? 1 : 2, per: 'kg' };
  }
  const weekly = weeklyBase;
  return { unit: ing.uom === 'pc' ? 'pcs' : 'servings', scale: 1, dp: weekly >= 20 ? 0 : 1, per: ing.uom === 'pc' ? 'pc' : 'serving' };
};
export const pesoFmt = (v) => `₱${Math.round(v).toLocaleString('en-US')}`;
export const fmtNum = (v, dp) => Number(v).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
export const qtyText = (ing, base, weeklyBase) => {
  if (ing.uom === 'g' && Math.abs(base) < 100) return `${fmtNum(base, 0)} g`;
  const m = unitMeta(ing, weeklyBase ?? Math.abs(base));
  return `${fmtNum(base / m.scale, m.dp)} ${m.unit}`;
};
export const unitCostText = (ing) => {
  const m = unitMeta(ing);
  return `${pesoFmt(ing.unitCost * m.scale)}/${m.per}`;
};

// ---- state --------------------------------------------------------------------------------------------------
let caches = new Map();                    // requested model ('' = the champion) -> { at, promise }
export const getState = (force = false) => {
  const key = currentModel() ?? '';
  const hit = caches.get(key);
  if (!force && hit?.promise && Date.now() - hit.at < 15000) return hit.promise;
  const entry = { at: Date.now(), promise: compute(key || null).catch((e) => { caches.delete(key); throw e; }) };
  caches.set(key, entry);
  return entry.promise;
};
export const resetState = () => { caches = new Map(); };

const compute = async (model) => {
  const meta = await L.loadMeta();
  const { asOf } = meta;
  const today = addDays(asOf, 1);
  const [ings, storage, snap, offBase, runs, bom, prices, dishes, recentRevenue] = await Promise.all([
    L.loadIngredients(), L.loadStorage(), L.loadSnapshot(asOf), L.loadOffPosBaseline(asOf), L.loadForecastRuns(),
    L.loadBom(), L.loadItemPrices(asOf), L.loadDishesByIngredient(asOf), L.loadTotalRecentRevenue(asOf),
  ]);
  const ingById = new Map(ings.map((i) => [i.id, i]));
  // production set: the CHAMPION is the is_selected run. The user may choose another model: its production forecast is the newest run of that model whose train end is the
  // last warehouse day (the engine stores it with is_selected = false, next to the champion's).
  const championRuns = runs.filter((r) => r.is_selected);
  const championModel = championRuns[0]?.model_name ?? null;
  const productionRuns = runs.filter((r) => r.train_end >= asOf);                       // runs arrive newest first
  const latestByModel = new Map();
  for (const r of productionRuns) if (!latestByModel.has(r.model_name)) latestByModel.set(r.model_name, r);
  const chosen = model && model !== championModel ? latestByModel.get(model) ?? null : null;
  const prodRuns = chosen ? [chosen] : championRuns;
  const selectedModel = chosen ? chosen.model_name : championModel;
  const run = prodRuns[0] || null;
  const productionModels = [...new Set(prodRuns.map((r) => r.model_name))];
  const availableModels = [...latestByModel.values()]
    .map((r) => ({ model: r.model_name, runId: r.run_id, isChampion: r.model_name === championModel, wmape: r.wmape === null ? null : Number(r.wmape), mase: r.mase === null ? null : Number(r.mase) }))
    .sort((a, b) => MODEL_ORDER.indexOf(a.model) - MODEL_ORDER.indexOf(b.model));

  const fc = new Map();                // `${ingredient}|${date}` -> {q, lo, hi}  (recipe-driven forecast of the production run)
  const horizonSet = new Set();
  let itemFc = new Map();              // item -> Map(date -> units)
  const modelShare = new Map();        // ingredient -> Map(model -> forecast quantity), to name the model that drives each ingredient
  const modelOfRun = new Map(prodRuns.map((r) => [r.run_id, r.model_name]));
  if (run) {
    const rows = await L.loadIngredientForecast(prodRuns.map((r) => r.run_id));
    for (const r of rows) {
      const k = `${r.ingredient_id}|${r.d}`;
      const prev = fc.get(k);
      fc.set(k, { q: (prev?.q ?? 0) + num(r.q), lo: r.lo === null ? prev?.lo ?? null : (prev?.lo ?? 0) + num(r.lo), hi: r.hi === null ? prev?.hi ?? null : (prev?.hi ?? 0) + num(r.hi) });
      horizonSet.add(r.d);
      if (!modelShare.has(r.ingredient_id)) modelShare.set(r.ingredient_id, new Map());
      const m = modelShare.get(r.ingredient_id), name = modelOfRun.get(r.run_id);
      m.set(name, (m.get(name) ?? 0) + num(r.q));
    }
    const items = await L.loadItemForecast(prodRuns.map((r) => r.run_id), today, addDays(today, 20));
    for (const r of items) { if (!itemFc.has(r.item_id)) itemFc.set(r.item_id, new Map()); itemFc.get(r.item_id).set(r.d, num(r.q)); }
  }
  const horizon = [...horizonSet].filter((d) => d >= today).sort();
  // keep the forecast calendar continuous from today (a missing day inside the run is a day with no recipe demand)
  const horizonDays = horizon.length ? days(today, diffDays(horizon[horizon.length - 1], today) + 1) : [];

  const stockById = new Map(snap.stock.map((s) => [s.id, s]));
  const batchesBy = new Map();
  for (const b of snap.batches) { if (!batchesBy.has(b.ingredient_id)) batchesBy.set(b.ingredient_id, []); batchesBy.get(b.ingredient_id).push({ ...b, qty: num(b.qty), unit_cost: num(b.unit_cost) }); }
  const arrivalsBy = new Map();
  for (const o of snap.openOrders) {
    const arrives = addDays(o.ordered, num(o.lead));
    if (arrives <= asOf) continue;
    const ing = ingById.get(o.ingredient_id);
    if (!ing) continue;
    if (!arrivalsBy.has(o.ingredient_id)) arrivalsBy.set(o.ingredient_id, []);
    arrivalsBy.get(o.ingredient_id).push({ id: `po-${o.ingredient_id}-${o.ordered}`, qty: num(o.qty), received: arrives, expiry: addDays(arrives, ing.shelfLife - 1), incoming: true });
  }
  const bomByIng = new Map(), minPortion = new Map();
  for (const r of bom) {
    if (!bomByIng.has(r.ingredient_id)) bomByIng.set(r.ingredient_id, []);
    bomByIng.get(r.ingredient_id).push(r.item_id);
    minPortion.set(r.ingredient_id, Math.min(minPortion.get(r.ingredient_id) ?? Infinity, num(r.qty_base)));
  }
  const dishesBy = new Map();
  for (const r of dishes) { if (!dishesBy.has(r.ingredient_id)) dishesBy.set(r.ingredient_id, []); dishesBy.get(r.ingredient_id).push({ name: r.dish, units: num(r.units) }); }

  const st = {
    meta, asOf, today, ings, ingById, storage, run, prodRuns, productionModels, championModel, selectedModel, isChampion: !chosen, availableModels, runs, fc, horizon: horizonDays, itemFc, stockById, batchesBy, arrivalsBy,
    offBase, bomByIng, minPortion, dishesBy, prices, recentRevenue,
    offPerDay: (id) => offBase.get(id) ?? 0,
  };
  // demand per day = recipe-driven forecast + the staff / prep baseline (same rule as dw.v_lp_ingredient_week_input)
  st.demand = (id, date) => (st.fc.get(`${id}|${date}`)?.q ?? 0) + st.offPerDay(id);
  st.dominantModel = (id) => {
    const m = modelShare.get(id);
    if (!m || !m.size) return productionModels[0] ?? null;
    return [...m.entries()].sort((a, b) => b[1] - a[1])[0][0];
  };
  st.weekly = (id) => sum(st.horizon.slice(0, 7).map((d) => st.demand(id, d)));
  return st;
};

// ---- stock simulation -----------------------------------------------------------------------------------------
// Consumes demand earliest-expiry-first. Returns end-of-day stock, unmet demand per day and what is left of each batch when it expires.
export const simulate = (batches, arrivals, dates, demand) => {
  const lots = [...batches, ...arrivals].map((b) => ({ ...b, rem: b.qty, lost: 0, lostOn: null, used: 0 }));
  lots.sort((a, b) => (a.expiry < b.expiry ? -1 : a.expiry > b.expiry ? 1 : String(a.id).localeCompare(String(b.id))));
  const end = [], unmet = [];
  dates.forEach((date, t) => {
    for (const l of lots) {
      if (l.rem > 1e-9 && l.expiry < date && l.lostOn === null) { l.lost = l.rem; l.lostOn = date; l.rem = 0; }
    }
    let need = demand[t];
    for (const l of lots) {
      if (need <= 1e-12) break;
      if (l.rem <= 1e-9 || l.received > date || l.expiry < date) continue;
      const take = Math.min(l.rem, need);
      l.rem -= take; l.used += take; need -= take;
    }
    unmet.push(Math.max(need, 0));
    end.push(sum(lots.filter((l) => l.received <= date && l.expiry >= date).map((l) => l.rem)));
  });
  return { end, unmet, lots };
};

const stateOf = (daysLeft) => (daysLeft < 0 ? 'expired' : daysLeft <= RULES.criticalDays ? 'critical' : daysLeft <= RULES.warningDays ? 'warning' : 'ok');

export const exposurePerDay = (st, ing) => {
  const date = st.horizon[0];
  if (!date) return 0;
  let total = 0;
  for (const item of st.bomByIng.get(ing.id) ?? []) {
    const units = st.itemFc.get(item)?.get(date) ?? 0;
    const price = st.prices.recent.get(item)?.price ?? st.prices.list.get(item) ?? 0;
    total += units * price;
  }
  return total;
};

// ---- risk -------------------------------------------------------------------------------------------------------
export const computeRisk = (st) => {
  const { today, horizon } = st;
  const H = horizon.length;
  const batchRows = [], spoilage = [], stockouts = [], excess = [], coverage = [];
  const horizonEnd = H ? horizon[H - 1] : today;
  let totalValue = 0;

  for (const ing of st.ings) {
    const stock = st.stockById.get(ing.id);
    if (!stock) continue;
    const onHandBatches = (st.batchesBy.get(ing.id) ?? []);
    const arrivals = st.arrivalsBy.get(ing.id) ?? [];
    const onHand = stock.closing;
    totalValue += onHand * ing.unitCost;
    const dem = horizon.map((d) => st.demand(ing.id, d));
    const sim = simulate(onHandBatches, arrivals, horizon, dem);
    const weekly = H ? sum(dem.slice(0, Math.min(7, H))) : 0;

    // batches
    const lotsById = new Map(sim.lots.map((l) => [l.id, l]));
    let dayEnd = null;
    for (const b of onHandBatches) {
      const l = lotsById.get(b.id);
      const daysLeft = diffDays(b.expiry, today);
      const insideHorizon = b.expiry <= horizonEnd;
      let atRisk = 0;
      if (daysLeft < 0) atRisk = b.qty;
      else if (insideHorizon && H) atRisk = l.lost;
      const used = daysLeft < 0 ? 0 : b.qty - (insideHorizon ? l.lost : l.rem);
      batchRows.push({
        ing, batch: b, daysLeft, state: stateOf(daysLeft), atRisk, used, insideHorizon, weekly,
        atRiskValue: atRisk * ing.unitCost,
      });
    }

    // stockout: projected stock if nothing new is ordered (open orders already placed are counted)
    const rop = stock.rop ?? 0;
    const lead = ing.lead || 1;
    const window = Math.min(lead + 1, H);
    const unmetInLead = sim.unmet.slice(0, window).some((v) => v > 1e-9);
    const belowReorder = stock.closing + stock.on_order < rop - 1e-9;
    const warn = unmetInLead || (RULES.stockoutMode === 'reorder' && belowReorder);
    let runsOut = null;
    for (let t = 0; t < H; t += 1) { if (sim.unmet[t] > 1e-9) { runsOut = horizon[t]; break; } }
    stockouts.push({
      ing, warn, why: unmetInLead ? 'unmet' : warn ? 'reorder' : '', belowReorder, rop, lead, runsOut, endStock: sim.end, unmet: sim.unmet, dem,
      exposure: exposurePerDay(st, ing), onHand, weekly, onOrder: stock.on_order, unmetWeek: sum(sim.unmet.slice(0, 7)), coverDays: weekly > 0 ? (onHand / (weekly / 7)) : null,
    });

    // excess: on hand above 1.5 x the 7-day forecast
    const week7 = weekly;
    const isExcess = H >= 7 && week7 > 0 ? onHand > RULES.excessFactor * week7 : false;
    excess.push({ ing, onHand, week7, isExcess, excessQty: Math.max(0, onHand - week7), excessValue: Math.max(0, onHand - week7) * ing.unitCost, value: onHand * ing.unitCost });
  }

  // alerts per ingredient
  const byIng = new Map();
  for (const r of batchRows) { if (!byIng.has(r.ing.id)) byIng.set(r.ing.id, []); byIng.get(r.ing.id).push(r); }
  for (const [id, rows] of byIng) {
    const portion = st.minPortion.get(id) ?? 0;
    const live = rows.filter((r) => r.atRisk >= Math.max(portion, 1e-9) && r.daysLeft >= 0 && r.daysLeft <= RULES.warningDays);
    if (!live.length) continue;
    live.sort((a, b) => a.daysLeft - b.daysLeft);
    const ing = live[0].ing;
    spoilage.push({
      ing, rows: live, daysLeft: live[0].daysLeft, state: stateOf(live[0].daysLeft),
      atRisk: sum(live.map((r) => r.atRisk)), atRiskValue: sum(live.map((r) => r.atRiskValue)),
      qty: sum(live.map((r) => r.batch.qty)), use: sum(live.map((r) => r.used)),
      expiry: live[0].batch.expiry, received: live[0].batch.received,
    });
  }
  spoilage.sort((a, b) => a.daysLeft - b.daysLeft || b.atRiskValue - a.atRiskValue);
  const excessFlag = excess.filter((e) => e.isExcess).sort((a, b) => b.excessValue - a.excessValue);
  const stockWarn = stockouts.filter((s) => s.warn).sort((a, b) => b.exposure - a.exposure);
  const excessValue = sum(excessFlag.map((e) => e.excessValue));
  return {
    batchRows, spoilage, stockouts, stockWarn, excess, excessFlag, excessValue, totalValue,
    excessShare: totalValue > 0 ? excessValue / totalValue : 0,
    alertCount: spoilage.length + stockWarn.length + excessFlag.length,
  };
};

// ---- delivery split ----------------------------------------------------------------------------------------------
// The optimiser stores one order quantity per ingredient and week. Deliveries are laid out on the supplier's own cadence
// (delivery_interval_days, first possible delivery = today + lead time) and the packs are shared out in proportion to the
// forecast demand each delivery has to cover, in whole packs.
export const deliveryPlan = (st, ing, qty, packs, weekStart) => {
  if (!(qty > 1e-9)) return [];
  const weekEnd = addDays(weekStart, 6);
  const first = addDays(st.today, ing.lead || 1);
  const lastDay = weekEnd < first ? first : weekEnd;
  const slots = [];
  for (let d = first; d <= lastDay; d = addDays(d, Math.max(1, ing.intervalDays || 1))) slots.push(d);
  if (!slots.length) slots.push(first);
  const packSize = ing.pack || qty;
  const nPacks = packs && packs > 0 ? packs : Math.max(1, Math.round(qty / packSize));
  const dem = slots.map((d, k) => {
    const next = slots[k + 1] ?? addDays(lastDay, 1);
    let s = 0;
    for (let x = d; x < next; x = addDays(x, 1)) s += st.demand(ing.id, x);
    return s;
  });
  const total = sum(dem) || slots.length;
  const shares = dem.map((v) => (sum(dem) ? v / total : 1 / slots.length) * nPacks);
  const alloc = shares.map((v) => Math.floor(v));
  let left = nPacks - sum(alloc);
  const order = shares.map((v, i) => [v - Math.floor(v), i]).sort((a, b) => b[0] - a[0]);
  for (const [, i] of order) { if (left <= 0) break; alloc[i] += 1; left -= 1; }
  const perPack = qty / nPacks;
  return slots.map((date, k) => ({ date, qty: alloc[k] * perPack, packs: alloc[k] })).filter((x) => x.packs > 0);
};

// ---- model evaluation (ingredient level) ----------------------------------------------------------------------------
const evalCache = new Map();
export const getEvaluation = async (st) => {
  // evaluation runs = held-out windows that end on or before the last warehouse day; use the train end that scored the most models (newest on ties)
  const candidates = st.runs.filter((r) => !r.is_selected && addDays(r.train_end, r.horizon_days) <= st.asOf);
  if (!candidates.length) return null;
  const groups = new Map();
  for (const r of candidates) {
    if (!groups.has(r.train_end)) groups.set(r.train_end, new Map());
    if (!groups.get(r.train_end).has(r.model_name)) groups.get(r.train_end).set(r.model_name, r);
  }
  let end = null, perModel = null;
  for (const [e, m] of groups) {
    if (!perModel || m.size > perModel.size || (m.size === perModel.size && [...m.values()][0].created_at > [...perModel.values()][0].created_at)) { end = e; perModel = m; }
  }
  const runIds = [...perModel.values()].map((r) => r.run_id).sort((a, b) => a - b);
  const key = runIds.join(',');
  if (evalCache.has(key)) return evalCache.get(key);
  const horizon = Math.max(...[...perModel.values()].map((r) => r.horizon_days));
  const testStart = addDays(end, 1), testEnd = addDays(end, horizon);
  const [fcRows, actRows] = await Promise.all([L.loadEvaluationForecast(runIds), L.loadActualUsage('2000-01-01', testEnd)]);

  const actual = new Map();
  for (const r of actRows) { if (!actual.has(r.ingredient_id)) actual.set(r.ingredient_id, new Map()); actual.get(r.ingredient_id).set(r.d, num(r.q)); }
  const fcBy = new Map();     // run -> ingredient -> date -> q
  for (const r of fcRows) {
    if (!fcBy.has(r.run_id)) fcBy.set(r.run_id, new Map());
    const m = fcBy.get(r.run_id);
    if (!m.has(r.ingredient_id)) m.set(r.ingredient_id, new Map());
    m.get(r.ingredient_id).set(r.d, num(r.q));
  }
  const weeksIn = (from, to) => { const out = []; for (let w = mondayOf(from) < from ? addDays(mondayOf(from), 7) : from; addDays(w, 6) <= to; w = addDays(w, 7)) out.push(w); return out; };
  const weekSum = (map, w) => { let s = 0; for (let k = 0; k < 7; k += 1) s += map?.get(addDays(w, k)) ?? 0; return s; };
  const testWeeks = weeksIn(testStart, testEnd);

  const models = {};
  for (const [name, r] of perModel) models[name] = { runId: r.run_id, perIng: new Map() };
  const residuals = new Map();
  const productionModel = st.productionModels.join(',');
  const weekly = [];     // per test week: value-weighted error of the production model
  const weekAcc = new Map(testWeeks.map((w) => [w, { err: 0, act: 0 }]));

  for (const ing of st.ings) {
    const a = actual.get(ing.id);
    if (!a) continue;
    const first = [...a.keys()].sort()[0];
    const trainWeeks = weeksIn(first, end);
    const trainSeries = trainWeeks.map((w) => weekSum(a, w));
    let scale = 0;
    for (let i = 1; i < trainSeries.length; i += 1) scale += Math.abs(trainSeries[i] - trainSeries[i - 1]);
    scale = trainSeries.length > 1 ? scale / (trainSeries.length - 1) : 0;
    const actW = testWeeks.map((w) => weekSum(a, w));
    const denom = sum(actW);
    for (const [name, m] of Object.entries(models)) {
      const f = fcBy.get(m.runId)?.get(ing.id);
      if (!f) continue;
      const fW = testWeeks.map((w) => weekSum(f, w));
      const err = sum(actW.map((v, i) => Math.abs(v - fW[i])));
      m.perIng.set(ing.id, { wmape: denom > 0 ? err / denom : null, mase: scale > 0 && testWeeks.length ? err / testWeeks.length / scale : null });
      if (name === st.dominantModel(ing.id)) {
        testWeeks.forEach((w, i) => { const acc = weekAcc.get(w); acc.err += ing.unitCost * Math.abs(actW[i] - fW[i]); acc.act += ing.unitCost * actW[i]; });
        const dayRes = [];
        for (let t = 0; t < horizon; t += 1) {
          const d = addDays(testStart, t);
          const av = a.get(d) ?? 0, fv = f.get(d) ?? 0;
          if (av > 0 || fv > 0) dayRes.push(av - fv);
        }
        const weekRes = actW.map((v, i) => v - fW[i]);
        const ds = dayRes.sort((x, y) => x - y), ws = [...weekRes].sort((x, y) => x - y);
        residuals.set(ing.id, {
          day: { p025: quantile(ds, 0.025), p10: quantile(ds, 0.1), p90: quantile(ds, 0.9), p975: quantile(ds, 0.975) },
          week: { p025: quantile(ws, 0.025), p10: quantile(ws, 0.1), p90: quantile(ws, 0.9), p975: quantile(ws, 0.975) },
        });
      }
    }
  }
  for (const w of testWeeks) { const acc = weekAcc.get(w); weekly.push({ weekStart: w, wmape: acc.act > 0 ? acc.err / acc.act : null }); }
  const result = { trainEnd: end, testStart, testEnd, horizon, models, residuals, weekly, productionModel };
  evalCache.set(key, result);
  return result;
};

// ---- plans ---------------------------------------------------------------------------------------------------------
export const getPlans = async (st) => {
  const runs = await L.loadPlans();
  const usable = runs.filter((r) => ['Optimal', 'Feasible (not proven optimal)'].includes(r.solver_status));
  const prodIds = new Set(st.prodRuns.map((r) => r.run_id));
  let pool = st.run ? usable.filter((r) => prodIds.has(r.forecast_run_id)) : usable;
  let stale = false;
  if (!pool.length && usable.length && st.isChampion) {            // plans exist, but for an older forecast run: show them, flagged (never for a model the user chose: its plans are simply not stored yet)
    const newest = Math.max(...usable.map((r) => r.forecast_run_id));
    pool = usable.filter((r) => r.forecast_run_id === newest);
    stale = true;
  }
  const latest = new Map();
  for (const r of pool) { const k = `${r.scenario}|${r.budget_php}`; if (!latest.has(k)) latest.set(k, { ...r, stale }); }
  return [...latest.values()];
};

export const SCENARIO_META = {
  min_spoilage: { name: 'Minimize spoilage', desc: 'Weighs waste three times as heavily as a shortage, so it buys the least that covers the forecast and accepts more shortage risk.', order: 1 },
  balanced: { name: 'Balanced', desc: 'Minimizes combined waste and shortage cost, with shortages weighted slightly above waste.', order: 2 },
  min_cost: { name: 'Minimize cost', desc: 'Adds the purchase cost to the objective, so it buys the least that still covers demand.', order: 3 },
  max_availability: { name: 'Maximize availability', desc: 'Weighs a shortage five times as heavily as waste. Highest service level, highest waste.', order: 4 },
};

export const weekOneRows = async (st, plan) => {
  const rows = await L.loadPlanRows(plan.opt_run_id);
  const week = plan.plan_week_start;
  return { week, rows: rows.filter((r) => r.week_start === week), all: rows };
};
