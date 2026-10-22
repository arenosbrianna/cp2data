import { num, pesoFmt, qtyText, unitMeta, fmtNum, RULES, SCENARIO_META, modelsLabel } from '../lib/analysis.mjs';
import * as L from '../lib/load.mjs';
import { addDays, label, labelLong, labelShort, days } from '../lib/dates.mjs';
import {
  getBundle, shellInfo, getOps, deltaText, keyOf, decisionStatus, supCode, planSummary, recommendedPlan, planBudgets, exposurePerDay, dishNames, dateOnly, pct,
} from './common.mjs';

const niceTop = (max) => {
  const raw = Math.max(max * 1.05, 1);
  for (const step of [1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000, 100000]) if (step * 3 >= raw) return step * 3;
  return Math.ceil(raw / 3) * 3;
};

export const queueItems = async (b) => {
  const { st, risk, decided } = b;
  const t = st.today;
  const items = [];
  const model = st.run ? modelsLabel(st) : 'forecast';
  const plan = recommendedPlan(b.plans);
  const summary = plan ? await planSummary(st, plan) : null;
  const planLineFor = (ingId) => summary?.lines.find((l) => l.ingredientId === ingId);

  for (const s of risk.stockWarn) {
    const ing = s.ing;
    const line = planLineFor(ing.id);
    const weekly = s.weekly;
    const perDay = weekly / 7;
    const packSize = ing.pack || 0;
    const shortfall = s.unmetWeek > 0 ? s.unmetWeek : Math.max(0, weekly - s.onHand - s.onOrder);
    const orderBase = line ? line.qtyBase : packSize > 0 ? Math.ceil(shortfall / packSize) * packSize : shortfall;
    const supplier = ing.supplierName ? `${ing.supplierName} (${supCode(ing.supplierId)})` : 'its supplier';
    const key = keyOf('stockout', ing.code, t);
    const d = decisionStatus(decided, key);
    items.push({
      key, order: 0, severity: 'crit', type: 'Stockout risk', typeKey: 'stockout', ingredientId: ing.id, optRunId: plan?.opt_run_id ?? null,
      title: `Order ${qtyText(ing, orderBase, weekly)} ${ing.name} from ${supplier} today`,
      evidence: `${qtyText(ing, s.onHand, weekly)} on hand${s.onOrder > 0 ? `, ${qtyText(ing, s.onOrder, weekly)} already on order` : ''}. Reorder level ${qtyText(ing, s.rop, weekly)}. Forecast use is ${qtyText(ing, perDay, weekly)}/day, so stock ${s.runsOut ? `runs out ${label(s.runsOut)}` : 'falls below the reorder level'}. Supplier lead time is ${ing.lead} day${ing.lead === 1 ? '' : 's'}.`,
      impact: `≈ ${pesoFmt(exposurePerDay(st, ing))}/day in ${ing.name.toLowerCase()} dishes at risk`,
      source: `Forecast: ${model} · ${line ? 'optimizer order qty' : 'cover estimate (no optimizer line)'}`,
      cta: 'Add to purchase list', done: 'Added to purchase list · logged', qty: orderBase, pesoImpact: exposurePerDay(st, ing), status: d?.status ?? 'open', reason: d?.reason ?? null,
    });
  }
  for (const s of risk.spoilage) {
    const ing = s.ing;
    const crit = s.daysLeft <= RULES.criticalDays;
    const key = keyOf('spoilage', ing.code, t);
    const d = decisionStatus(decided, key);
    const first = s.rows[0];
    const when = s.daysLeft <= 0 ? 'today' : s.daysLeft === 1 ? 'tomorrow' : label(s.expiry);
    const dishes = dishNames(st, ing, 3);
    const weekly = st.weekly(ing.id);
    items.push({
      key, order: crit ? 1 : 2, severity: crit ? 'crit' : 'warn', type: 'Spoilage', typeKey: 'spoilage', ingredientId: ing.id, optRunId: null,
      title: crit ? `Feature ${ing.name.toLowerCase()} in today's specials: ${qtyText(ing, s.atRisk, weekly)} expires ${when}` : `Use ${qtyText(ing, s.atRisk, weekly)} ${ing.name.toLowerCase()} in prep before it expires ${when}`,
      evidence: `${s.rows.length === 1 ? `${qtyText(ing, first.batch.qty, weekly)} received ${label(first.batch.received)}, ${ing.shelfLife}-day shelf life, so it expires ${label(first.batch.expiry)}` : `${s.rows.length} batches, ${qtyText(ing, s.qty, weekly)} on hand, the earliest expires ${label(s.expiry)}`}. Forecast use before then is ${qtyText(ing, s.use, weekly)}.${dishes.length ? ` Menu items that use it (BOM): ${dishes.join(', ')}.` : ''}`,
      impact: `${qtyText(ing, s.atRisk, weekly)} · ${pesoFmt(s.atRiskValue)} at risk`,
      source: 'Spoilage matrix · BOM',
      cta: crit ? 'Create promo' : 'Notify kitchen', done: crit ? 'Promo created · logged' : 'Kitchen notified · logged', qty: s.atRisk, pesoImpact: s.atRiskValue, status: d?.status ?? 'open', reason: d?.reason ?? null,
    });
  }
  if (risk.excessFlag.length) {
    const key = keyOf('excess', 'all', t);
    const d = decisionStatus(decided, key);
    const top = risk.excessFlag.slice(0, 2);
    const names = top.map((e) => e.ing.name.toLowerCase());
    const more = risk.excessFlag.length - top.length;
    const orderedIds = new Set(summary?.lines.map((l) => l.ingredientId) ?? []);
    const stillOrdered = risk.excessFlag.filter((e) => orderedIds.has(e.ing.id)).map((e) => e.ing.name.toLowerCase());
    items.push({
      key, order: 3, severity: 'warn', type: 'Excess capital', typeKey: 'excess', ingredientId: null, optRunId: plan?.opt_run_id ?? null,
      title: `Skip this week's ${names.join(' and ')}${more > 0 ? ` and ${more} other` : ''} order${risk.excessFlag.length > 1 ? 's' : ''}`,
      evidence: `${top.map((e) => `${e.ing.name} ${qtyText(e.ing, e.onHand, e.week7)} on hand vs ${qtyText(e.ing, e.week7, e.week7)} forecast for 7 days`).join('. ')}.${stillOrdered.length ? ` The optimizer plan still orders ${stillOrdered.slice(0, 3).join(', ')}.` : ' None of the flagged items is in the optimizer order.'}`,
      impact: `${pesoFmt(risk.excessValue)} tied up`, source: 'Excess capital gauge',
      cta: 'Freeze orders', done: 'Orders frozen for this cycle · logged', qty: null, pesoImpact: risk.excessValue, status: d?.status ?? 'open', reason: d?.reason ?? null,
    });
  }
  if (plan && summary) {
    const key = keyOf('weekly_order', plan.scenario, summary.week);
    const d = decisionStatus(decided, key);
    const budget = num(plan.budget_php);
    items.push({
      key, order: 4, severity: 'info', type: 'Weekly order', typeKey: 'weekly_order', ingredientId: null, optRunId: plan.opt_run_id,
      title: `Approve the weekly purchase list: ${pesoFmt(summary.cost)} across ${summary.lines.length} ingredient${summary.lines.length === 1 ? '' : 's'}`,
      evidence: `${SCENARIO_META[plan.scenario]?.name ?? plan.scenario} scenario: ${(SCENARIO_META[plan.scenario]?.desc ?? '').replace(/\.$/, '')}. Budget ${pesoFmt(budget)} (${Math.round((summary.counted / budget) * 100)}% used${summary.exemptCost > 0 ? `, whole salmon and tuna ${pesoFmt(summary.exemptCost)} excluded` : ''}). Peak storage ${Math.round(summary.storage.chilled.litres)} L chilled, ${Math.round(summary.storage.frozen.litres)} L frozen.`,
      impact: `Projected waste ${fmtNum(summary.wasteKg, 1)} kg · service level ${pct(summary.service)}`,
      source: `Optimizer run #${plan.opt_run_id} · ${label(dateOnly(plan.created_at))}`,
      cta: 'Review & approve', done: 'Approved · sent to purchasing list', qty: null, pesoImpact: summary.cost, status: d?.status ?? 'open', reason: d?.reason ?? null,
    });
  }
  items.sort((a, c) => a.order - c.order);
  return { items, plan, summary };
};

export const overviewView = async () => {
  const b = await getBundle();
  const { st } = b;
  const [shell, ops, { items, plan, summary }] = await Promise.all([shellInfo(b), getOps(st), queueItems(b)]);

  const c = ops.cur7, c28 = ops.cur28, base = ops.baseMetrics;
  const wasteDelta = deltaText({ cur: c.wasteKgWeek, base: base.wasteKgWeek, lowerIsBetter: true, mode: 'pct' });
  const spoilDelta = deltaText({ cur: c28.spoilage, base: base.spoilage, lowerIsBetter: true, mode: 'pts' });
  const stockDelta = deltaText({ cur: c.stockoutsWeek, base: base.stockoutsWeek, lowerIsBetter: true, mode: 'pct' });
  const turnDelta = deltaText({ cur: c28.turnover, base: base.turnover, lowerIsBetter: false, mode: 'x' });
  const kpis = [
    { label: 'WEEKLY FOOD WASTE', value: fmtNum(c.wasteKgWeek, 1), unit: 'kg', base: `${fmtNum(base.wasteKgWeek, 1)} kg`, delta: wasteDelta.text, good: wasteDelta.good },
    { label: 'SPOILAGE RATE', value: fmtNum(c28.spoilage * 100, 1), unit: '%', base: `${fmtNum(base.spoilage * 100, 1)}% of received`, delta: spoilDelta.text, good: spoilDelta.good },
    { label: 'STOCKOUTS THIS WEEK', value: String(ops.last7.stockouts), unit: ops.last7.stockouts === 1 ? 'event' : 'events', base: `${fmtNum(base.stockoutsWeek, 1)} / week`, delta: stockDelta.text, good: stockDelta.good },
    { label: 'INVENTORY TURNOVER', value: fmtNum(c28.turnover, 1), unit: '× / month', base: `${fmtNum(base.turnover, 1)}×`, delta: turnDelta.text, good: turnDelta.good },
  ];
  const winFrom = addDays(st.asOf, -6);
  const kpiNote = `Baseline = pre-DSS average, Jun–Aug 2026 (§1.3). Waste and stockouts: last 7 days, ${label(winFrom)} – ${label(st.asOf)}. Spoilage rate and turnover: trailing 28 days. Waste is weighed in kg for weight-based ingredients; piece-counted items are in the spoilage rate.`;

  // yesterday = the last warehouse day
  const salesRows = await L.loadDailySales(addDays(st.asOf, -6), st.asOf);
  const sales = new Map(salesRows.map((r) => [r.d, r]));
  const y = sales.get(st.asOf);
  const tops = await L.loadTopDishes(st.asOf);
  const yesterday = {
    label: `Yesterday · ${label(st.asOf)}`,
    revenue: y ? pesoFmt(num(y.revenue)) : '₱0', receipts: y ? fmtNum(num(y.units), 0) : '0',
    avg: y && num(y.units) > 0 ? pesoFmt(num(y.revenue) / num(y.units)) : '—',
    tops: tops.map((r, i) => ({ rank: String(i + 1), name: r.name, qty: `${fmtNum(num(r.qty), 0)} sold · ${pesoFmt(num(r.revenue) / Math.max(num(r.qty), 1))} each`, rev: pesoFmt(num(r.revenue)) })),
  };

  // revenue chart: 7 days actual + 7 days forecast (forecast units x recent net price per unit)
  const price = (id) => st.prices.recent.get(id)?.price ?? st.prices.list.get(id) ?? 0;
  const fcRevenue = (d) => { let s = 0; for (const [id, m] of st.itemFc) s += (m.get(d) ?? 0) * price(id); return s; };
  const actualDays = days(winFrom, 7), fcDays = st.horizon.slice(0, 7);
  const rev = [
    ...actualDays.map((d) => ({ date: d, day: labelShort(d), v: num(sales.get(d)?.revenue), kind: 'actual' })),
    ...fcDays.map((d) => ({ date: d, day: labelShort(d), v: fcRevenue(d), kind: 'forecast' })),
  ];
  const yMax = niceTop(Math.max(1, ...rev.map((r) => r.v)));

  const budgets = planBudgets(b.plans);
  const planCard = plan && summary ? {
    spend: pesoFmt(summary.cost), counted: summary.counted, budget: num(plan.budget_php), pct: Math.round((summary.counted / num(plan.budget_php)) * 100),
    note: `${Math.round((summary.counted / num(plan.budget_php)) * 100)}% of ${pesoFmt(num(plan.budget_php))} weekly budget${summary.exemptCost > 0 ? ` (whole salmon and tuna ${pesoFmt(summary.exemptCost)} outside it)` : ''} · ${SCENARIO_META[plan.scenario]?.name ?? plan.scenario} scenario`,
    budgets,
  } : null;

  const open = items.filter((i) => i.status === 'open').length;
  return {
    shell, dateLong: labelLong(st.today), count: items.length, open, kpis, kpiNote, queue: items, yesterday, rev: { yMax, bars: rev }, planCard,
    revenueNote: st.run ? `Actual from Loyverse · forecast from the ${modelsLabel(st)} run${st.productionModels.length > 1 ? 's' : ''}, summed across menu items` : 'Actual from Loyverse · no forecast run stored',
    hasForecast: Boolean(st.run && st.horizon.length),
  };
};
