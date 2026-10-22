// Shared inputs of the page builders: warehouse state, risk, decisions, operations KPIs and the stored optimizer plans.
import {
  getState, computeRisk, getPlans, weekOneRows, deliveryPlan, simulate, num, pesoFmt, qtyText, unitCostText,
  RULES, SCENARIO_META, exposurePerDay,
} from '../lib/analysis.mjs';
import * as L from '../lib/load.mjs';
import { readRecommendations, latestByKey, tableFlags, userName } from '../lib/decisions.mjs';
import { addDays, diffDays, label, labelLong, todayIso, days } from '../lib/dates.mjs';

export const supCode = (id) => (id === null || id === undefined ? '—' : `SUP-${String(id).padStart(2, '0')}`);
export const sum = (a) => a.reduce((x, y) => x + y, 0);
export const pct = (v, dp = 1) => `${(v * 100).toFixed(dp)}%`;
const dateOnly = (ts) => (ts ? String(ts).slice(0, 10) : null);
export { dateOnly };

const riskMemo = new WeakMap();
export const riskOf = (st) => {
  if (!riskMemo.has(st)) riskMemo.set(st, computeRisk(st));
  return riskMemo.get(st);
};

export const keyOf = (type, code, date) => `${type}:${code}:${date}`;

export const getBundle = async () => {
  const st = await getState();
  const risk = riskOf(st);
  const [recs, plans, flags] = await Promise.all([readRecommendations(), getPlans(st), tableFlags()]);
  const decided = latestByKey(recs);
  return { st, risk, recs, decided, plans, flags };
};

export const decisionStatus = (decided, key) => {
  const r = decided.get(key);
  return r && r.status !== 'open' ? r : null;
};

export const openAlertCount = (st, risk, decided) => {
  const t = st.today;
  const open = (k) => !decisionStatus(decided, k);
  return risk.spoilage.filter((s) => open(keyOf('spoilage', s.ing.code, t))).length
    + risk.stockWarn.filter((s) => open(keyOf('stockout', s.ing.code, t))).length
    + (open(keyOf('excess', 'all', t)) ? risk.excessFlag.length : 0);
};

export const shellInfo = async (b) => {
  const { st, risk, decided, flags } = b;
  return {
    asOf: st.asOf, asOfLabel: label(st.asOf), today: st.today, todayLabel: label(st.today), todayLong: labelLong(st.today),
    staleDays: Math.max(0, diffDays(todayIso(), st.asOf)),
    badge: openAlertCount(st, risk, decided),
    user: userName(),
    model: { selected: st.selectedModel, champion: st.championModel, isChampion: st.isChampion },
    writes: { decisions: flags.recommendations, planLines: flags.planLines, wasteLog: flags.wasteLog },
  };
};

// ---- operations KPIs -----------------------------------------------------------------------------------------------
const opsMemo = new Map();
export const getOps = async (st) => {
  const key = st.asOf;
  if (opsMemo.has(key)) return opsMemo.get(key);
  const rows = await L.loadDailyOps(L.BASELINE_PERIOD.start, st.asOf);
  const agg = (rs) => {
    const n = rs.length || 1;
    const inv = sum(rs.map((r) => num(r.inv_value))) / n;
    return {
      days: rs.length, wasteKg: sum(rs.map((r) => num(r.waste_kg))), wasteValue: sum(rs.map((r) => num(r.waste_value))),
      received: sum(rs.map((r) => num(r.received_value))), cogs: sum(rs.map((r) => num(r.cogs))), inv, stockouts: sum(rs.map((r) => num(r.stockouts))),
    };
  };
  const base = agg(rows.filter((r) => r.d >= L.BASELINE_PERIOD.start && r.d <= L.BASELINE_PERIOD.end));
  const metrics = (a, weeks) => ({
    wasteKgWeek: a.wasteKg / weeks,
    spoilage: a.received > 0 ? a.wasteValue / a.received : 0,
    stockoutsWeek: a.stockouts / weeks,
    turnover: a.inv > 0 ? (a.cogs / a.inv) * (30 / a.days) : 0,
  });
  const out = {
    rows, base, baseMetrics: metrics(base, base.days / 7),
    last7: agg(rows.slice(-7)), last28: agg(rows.slice(-28)),
  };
  out.cur7 = metrics(out.last7, 1);
  out.cur28 = metrics(out.last28, 4);
  opsMemo.set(key, out);
  return out;
};

export const deltaText = ({ cur, base, lowerIsBetter, mode }) => {
  const diff = cur - base;
  const flat = Math.abs(diff) < (mode === 'pct' ? Math.abs(base) * 0.005 : mode === 'pts' ? 0.0005 : 0.005);
  const up = diff > 0;
  const good = flat ? null : lowerIsBetter ? !up : up;
  const arrow = flat ? '→' : up ? '↑' : '↓';
  let body;
  if (mode === 'pct') body = base > 0 ? `${Math.abs((diff / base) * 100).toFixed(0)}% vs baseline` : 'no baseline events';
  else if (mode === 'pts') body = `${Math.abs(diff * 100).toFixed(1)} pts vs baseline`;
  else body = `${Math.abs(diff).toFixed(1)}× vs baseline`;
  return { text: flat ? `${arrow} unchanged vs baseline` : `${arrow} ${body}`, good };
};

// ---- stored optimizer plans ------------------------------------------------------------------------------------------
const planMemo = new Map();
export const planBudgets = (plans) => [...new Set(plans.map((p) => num(p.budget_php)))].sort((a, b) => a - b);

export const pickPlan = (plans, scenario, budget) => {
  const budgets = planBudgets(plans);
  const b = budget && budgets.includes(Number(budget)) ? Number(budget) : budgets[0];
  return plans.find((p) => p.scenario === scenario && num(p.budget_php) === b) || null;
};

const WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const wdOf = (s) => WD[(new Date(`${s}T00:00:00Z`).getUTCDay() + 6) % 7];

export const planSummary = async (st, plan) => {
  const key = `${plan.opt_run_id}|${st.asOf}`;
  if (planMemo.has(key)) return planMemo.get(key);
  const { week, rows } = await weekOneRows(st, plan);
  const risk = riskOf(st);
  const excessIds = new Set(risk.excessFlag.map((e) => e.ing.id));
  const lines = [], notOrdered = [], deliveriesBy = new Map();
  let cost = 0, counted = 0, wasteKg = 0, shortVal = 0, reqVal = 0;
  const shortNames = [], dailyLots = [];
  for (const r of rows) {
    const ing = st.ingById.get(r.ingredient_id);
    if (!ing) continue;
    const qty = num(r.qty), lineCost = num(r.cost);
    cost += lineCost;
    if (!RULES.budgetExempt.has(ing.code)) counted += lineCost;
    if (ing.uom === 'g') wasteKg += num(r.waste) / 1000;
    shortVal += num(r.shortage) * ing.unitCost;
    reqVal += num(r.requirement) * ing.unitCost;
    if (num(r.shortage) > 1e-6) shortNames.push(ing.name);
    if (r.binding === 'daily lots') dailyLots.push(ing.name);
    if (qty > 1e-9) {
      const dl = deliveryPlan(st, ing, qty, r.packs, week);
      deliveriesBy.set(ing.id, dl);
      const first = dl[0]?.date ?? addDays(st.today, ing.lead);
      const by = addDays(first, -ing.lead) < st.today ? st.today : addDays(first, -ing.lead);
      const weekly = st.weekly(ing.id);
      lines.push({
        ingredientId: ing.id, name: ing.name, supplierId: ing.supplierId, supCode: supCode(ing.supplierId), supplier: ing.supplierName ?? '—',
        lead: ing.lead, leadText: `${ing.lead} day${ing.lead === 1 ? '' : 's'}`,
        qtyText: qtyText(ing, qty, weekly), packs: r.packs, packText: r.packs ? `${r.packs} pack${r.packs === 1 ? '' : 's'}` : null,
        split: dl.map((x) => `${qtyText(ing, x.qty, weekly).replace(/ (kg|pcs|servings)$/, '')} ${wdOf(x.date)}`).join(' · '),
        deliveries: dl.map((x) => ({ date: x.date, day: wdOf(x.date), qty: x.qty })),
        by, byText: by === st.today ? 'Today' : label(by), urgent: by === st.today,
        unitCost: unitCostText(ing), line: lineCost, lineText: pesoFmt(lineCost), exempt: RULES.budgetExempt.has(ing.code), qtyBase: qty,
      });
    } else {
      const flagged = excessIds.has(ing.id);
      const note = num(r.shortage) > 1e-6 ? 'no order in this plan' : flagged ? 'excess stock, see Risk alerts' : `${qtyText(ing, num(r.opening), st.weekly(ing.id))} on hand covers ${qtyText(ing, num(r.requirement), st.weekly(ing.id))} forecast`;
      notOrdered.push({ name: ing.name, note });
    }
  }
  lines.sort((a, b) => a.by.localeCompare(b.by) || a.name.localeCompare(b.name));

  // storage: litres of stock per day over the first 7 days of the horizon, with the plan's deliveries added
  const H = st.horizon.slice(0, 7);
  const perType = { chilled: H.map(() => 0), frozen: H.map(() => 0), ambient: H.map(() => 0) };
  const endWith = new Map();
  for (const ing of st.ings) {
    const stock = st.stockById.get(ing.id);
    if (!stock || !H.length) continue;
    const dl = deliveriesBy.get(ing.id) ?? [];
    const incoming = dl.map((x, k) => ({ id: `lp-${ing.id}-${k}`, qty: x.qty, received: x.date, expiry: addDays(x.date, ing.shelfLife - 1), incoming: true }));
    const dem = st.horizon.map((d) => st.demand(ing.id, d));
    const sim = simulate(st.batchesBy.get(ing.id) ?? [], [...(st.arrivalsBy.get(ing.id) ?? []), ...incoming], st.horizon, dem);
    endWith.set(ing.id, sim.end);
    H.forEach((_, t) => { perType[ing.storage][t] += sim.end[t] * ing.litres; });
  }
  const peak = (arr) => { let m = 0, at = 0; arr.forEach((v, i) => { if (v > m) { m = v; at = i; } }); return { litres: m, day: H[at] ?? null }; };
  const cap = Object.fromEntries(st.storage.map((s) => [s.storage_type, { capacity: num(s.capacity), pool: num(s.pool) }]));
  const storage = { chilled: peak(perType.chilled), frozen: peak(perType.frozen), cap };
  const spill = Math.max(0, storage.chilled.litres - (cap.chilled?.capacity ?? 0)) + Math.max(0, storage.frozen.litres - (cap.frozen?.capacity ?? 0));
  storage.poolNeeded = spill;
  storage.binds = spill > Math.max(cap.chilled?.pool ?? 0, cap.frozen?.pool ?? 0) + 1e-9;

  const out = {
    plan, week, lines, notOrdered, cost, counted, exemptCost: cost - counted, wasteKg,
    service: reqVal > 0 ? Math.max(0, 1 - shortVal / reqVal) : 1, shortNames, dailyLots, storage, endWith, deliveriesBy,
  };
  planMemo.set(key, out);
  return out;
};

export const scenarioList = (plans, budget) =>
  plans.filter((p) => num(p.budget_php) === budget).sort((a, b) => (SCENARIO_META[a.scenario]?.order ?? 9) - (SCENARIO_META[b.scenario]?.order ?? 9));

export const recommendedPlan = (plans) => pickPlan(plans, RULES.recommendedScenario, null) || plans[0] || null;

export const dishNames = (st, ing, n = 3) => (st.dishesBy.get(ing.id) ?? []).filter((d) => d.units > 0).concat(st.dishesBy.get(ing.id) ?? []).map((d) => d.name).filter((v, i, a) => a.indexOf(v) === i).slice(0, n);

export { days, labelLong, exposurePerDay };
