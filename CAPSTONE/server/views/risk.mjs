import { num, pesoFmt, qtyText, unitMeta, unitCostText, fmtNum, RULES, modelsLabel, simulate } from '../lib/analysis.mjs';
import * as L from '../lib/load.mjs';
import { addDays, label, labelShort, dayName, days } from '../lib/dates.mjs';
import {
  getBundle, shellInfo, keyOf, decisionStatus, supCode, planSummary, recommendedPlan, dishNames, sum, riskOf, pct,
} from './common.mjs';

const niceMax = (v) => {
  const raw = Math.max(v * 1.1, 1e-9);
  const mag = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * mag >= raw) return m * mag;
  return raw;
};

export const riskView = async () => {
  const b = await getBundle();
  const { st, risk, decided } = b;
  const shell = await shellInfo(b);
  const t = st.today;
  if (!st.horizon.length) return { shell, empty: true, message: 'No forecast run is stored, so risk alerts cannot be projected.' };

  const plan = recommendedPlan(b.plans);
  const planSum = plan ? await planSummary(st, plan) : null;
  const dayCols = [...days(t, 7).map(labelShort), '> 7 d'];

  // ---- summary tiles
  const spoilValue = sum(risk.spoilage.map((s) => s.atRiskValue));
  const focus = risk.stockWarn[0] ?? [...risk.stockouts].filter((s) => s.coverDays !== null).sort((a, c) => a.coverDays - c.coverDays)[0] ?? null;
  const tiles = {
    spoilage: { count: risk.spoilage.length, sub: `${pesoFmt(spoilValue)} at risk` },
    stockout: { count: risk.stockWarn.length, sub: risk.stockWarn[0] ? `${risk.stockWarn[0].ing.name} · ${risk.stockWarn[0].runsOut ? label(risk.stockWarn[0].runsOut) : 'below reorder level'}` : 'None runs out inside lead time' },
    excess: { count: risk.excessFlag.length, sub: `${pesoFmt(risk.excessValue)} tied up` },
  };

  // ---- spoilage matrix rows
  const excessIds = new Set(risk.excessFlag.map((e) => e.ing.id));
  const warnIds = new Set(risk.stockWarn.map((s) => s.ing.id));
  const alertIds = new Set(risk.spoilage.map((s) => s.ing.id));
  const rowsAll = risk.batchRows.filter((r) => r.daysLeft <= 6 || r.atRisk > 1e-9 || excessIds.has(r.ing.id) || warnIds.has(r.ing.id));
  const seenFar = new Set();
  const rows = rowsAll.filter((r) => {          // far-dated stock: only the earliest batch of an ingredient, to keep the matrix readable
    if (r.daysLeft <= 6 || r.atRisk > 1e-9) return true;
    if (seenFar.has(r.ing.id)) return false;
    seenFar.add(r.ing.id); return true;
  });
  const isAlertRow = (r) => r.atRisk > 1e-9 && r.daysLeft >= 0 && r.daysLeft <= RULES.warningDays;
  rows.sort((a, c) => (isAlertRow(a) ? 0 : 1) - (isAlertRow(c) ? 0 : 1) || a.daysLeft - c.daysLeft || a.ing.name.localeCompare(c.ing.name));
  const batches = rows.slice(0, 40).map((r) => {
    const ing = r.ing;
    const weekly = r.weekly;
    const idx = r.daysLeft < 0 ? 0 : r.daysLeft > 6 ? 7 : r.daysLeft;
    const kind = r.state === 'expired' || r.daysLeft <= RULES.criticalDays ? 'red' : r.daysLeft <= RULES.warningDays ? 'amber' : 'later';
    const cells = dayCols.map((_, i) => (i === idx ? { kind, text: r.state === 'expired' ? '● EXPIRED' : kind === 'red' ? '● EXP' : kind === 'amber' ? '▲ EXP' : 'EXP' } : { kind: i < idx ? 'alive' : 'none', text: '' }));
    const alert = isAlertRow(r);
    const alertKey = keyOf('spoilage', ing.code, t);
    const d = decisionStatus(decided, alertKey);
    let note = 'Used before expiry.';
    if (r.state === 'expired') note = `Expired ${label(r.batch.expiry)}: binned whole on the next stock count.`;
    else if (r.atRisk > 1e-9 && !alert) note = `Leftover projected after ${label(r.batch.expiry)}, ${r.daysLeft} days out. Watch, no action yet.`;
    else if (warnIds.has(ing.id)) note = 'No spoilage risk. See stockout warning.';
    else if (excessIds.has(ing.id)) note = 'Not spoiling, but excess. See gauge.';
    const useText = r.insideHorizon || r.state === 'expired' ? qtyText(ing, r.used, weekly) : `${qtyText(ing, r.used, weekly)} / ${st.horizon.length} d`;
    return {
      key: alertKey, ingredientId: ing.id, name: ing.name, rcv: label(r.batch.received), life: `${ing.shelfLife}-day life`, cells,
      onhand: qtyText(ing, r.batch.qty, weekly), use: useText,
      risk: r.atRisk > 1e-9 ? qtyText(ing, r.atRisk, weekly) : '0', riskColor: r.atRisk > 1e-9 && r.state !== 'expired' ? '#B91C1C' : '#374151',
      peso: r.atRisk > 1e-9 ? `${pesoFmt(r.atRiskValue)} at ${unitCostText(ing)}` : '—',
      alert, items: alert ? dishNames(st, ing, 3).join(', ') : '', cta: r.daysLeft <= RULES.criticalDays ? 'Create promo' : 'Notify kitchen', note, status: alert ? d?.status ?? 'open' : null,
      qty: r.atRisk, impact: r.atRiskValue,
    };
  });

  // ---- stockout section
  let stockout = null;
  if (focus) {
    const ing = focus.ing;
    const weekly = focus.weekly;
    const line = planSum?.lines.find((l) => l.ingredientId === ing.id);
    const end = planSum?.endWith.get(ing.id) ?? focus.endStock;
    const noOrder = focus.endStock.slice(0, 7), withOrder = end.slice(0, 7), dem = focus.dem.slice(0, 7);
    const m = unitMeta(ing, weekly), sc = m.scale;
    const maxV = niceMax(Math.max(...dem, ...noOrder, ...withOrder, focus.onHand, focus.rop) / sc) * sc;
    const dl = line?.deliveries ?? [];
    const packSize = ing.pack || 0;
    const shortfall = focus.unmetWeek > 0 ? focus.unmetWeek : Math.max(0, weekly - focus.onHand - focus.onOrder);
    const orderBase = line ? line.qtyBase : packSize > 0 ? Math.ceil(shortfall / packSize) * packSize : shortfall;
    const key = keyOf('stockout', ing.code, t);
    const d = decisionStatus(decided, key);
    const supplier = ing.supplierName ? `${ing.supplierName} (${supCode(ing.supplierId)})` : 'its supplier';
    const warn = focus.warn;
    stockout = {
      warn, key, ingredientId: ing.id, name: ing.name, status: d?.status ?? 'open',
      headline: warn
        ? `${ing.name} ${focus.runsOut ? `runs out ${label(focus.runsOut)} without an order` : `is below its reorder level (${qtyText(ing, focus.rop, weekly)})`}${focus.runsOut && focus.rop > 0 ? ` and its reorder level is ${qtyText(ing, focus.rop, weekly)}` : ''}.`
        : `No ingredient runs out inside its supplier lead time. Least cover: ${ing.name}, ${focus.coverDays !== null ? `${focus.coverDays.toFixed(1)} days` : 'n/a'} of stock.`,
      detail: warn
        ? { pre: 'Order ', order: qtyText(ing, orderBase, weekly), post: ` from ${supplier} today. Lead time ${ing.lead} day${ing.lead === 1 ? '' : 's'}.${dl.length ? ` Delivery split: ${line.split}.` : ''}` }
        : { pre: '', order: '', post: `${qtyText(ing, focus.onHand, weekly)} on hand against ${qtyText(ing, weekly, weekly)} forecast for 7 days. Lead time ${ing.lead} day${ing.lead === 1 ? '' : 's'}.` },
      orderBase, unit: m.unit, dp: m.dp,
      chart: {
        title: `${ing.name}: projected end-of-day stock vs forecast demand, ${m.unit}`,
        yMax: maxV / sc, start: focus.onHand / sc, demand: dem.map((x) => x / sc), noOrder: noOrder.map((x) => x / sc), withOrder: withOrder.map((x) => x / sc), rop: focus.rop / sc,
        days: days(t, 7).map((x, i) => {
          const dd = dl.find((q) => q.date === x);
          return `${labelShort(x)}${dd ? ` · +${fmtNum(dd.qty / sc, m.dp)}` : ''}`;
        }),
        leadDays: Math.min(ing.lead, 7), hasOrder: dl.length > 0,
      },
    };
  }
  const watch = risk.stockouts.filter((s) => s.belowReorder && !s.warn).map((s) => s.ing.name);

  // ---- excess gauge
  const flagged = risk.excessFlag.map((e) => ({ ...e, flag: true }));
  const rest = risk.excess.filter((e) => !e.isExcess && e.week7 > 0).sort((a, c) => (c.onHand / c.week7) - (a.onHand / a.week7));
  const excessList = [...flagged, ...rest.map((e) => ({ ...e, flag: false }))].slice(0, Math.max(4, Math.min(flagged.length, 6)));
  const excessItems = excessList.map((e) => {
    const max = Math.max(e.onHand, e.week7) * 1.1 || 1;
    const ex = Math.max(0, e.onHand - e.week7);
    return {
      name: e.ing.name,
      label: `${qtyText(e.ing, e.onHand, e.week7)} on hand · ${qtyText(e.ing, e.week7, e.week7)} forecast`,
      stockW: Math.round((e.onHand / max) * 100), fcW: Math.round((e.week7 / max) * 100), flag: e.flag,
      note: e.flag ? `Excess ${qtyText(e.ing, ex, e.week7)} = ${pesoFmt(ex * e.ing.unitCost)} · skip this cycle` : 'Within 1.5× of forecast · no action',
    };
  });
  const exKey = keyOf('excess', 'all', t);
  const exDec = decisionStatus(decided, exKey);
  const gauge = {
    value: pesoFmt(risk.excessValue), share: risk.excessShare, shareText: `${(risk.excessShare * 100).toFixed(1)}%`,
    total: pesoFmt(risk.totalValue), scale: RULES.gaugeScale, key: exKey, status: exDec?.status ?? 'open', flaggedCount: risk.excessFlag.length,
    zone: risk.excessShare > 0.2 ? 'act' : risk.excessShare >= 0.1 ? 'review' : 'ok',
  };

  // ---- waste heatmap: last 8 weeks, weight-based ingredients, average kg per weekday
  const wFrom = addDays(st.asOf, -55);
  const wasteRows = await L.loadWasteByWeekday(wFrom, st.asOf);
  const byIng = new Map();
  for (const r of wasteRows) { if (!byIng.has(r.name)) byIng.set(r.name, Array(7).fill(0)); byIng.get(r.name)[r.dow] += num(r.kg) / 8; }
  const top = [...byIng.entries()].sort((a, c) => sum(c[1]) - sum(a[1])).slice(0, 6);
  const maxCell = Math.max(0, ...top.flatMap(([, v]) => v));
  const ramp = ['#EFF6FF', '#DBEAFE', '#BFDBFE', '#93C5FD', '#3B82F6', '#1D4ED8', '#1E3A8A'];
  const heat = top.map(([name, vals]) => ({
    name,
    cells: vals.map((v, i) => {
      const k = maxCell > 0 ? Math.min(6, Math.floor((v / maxCell) * 6.99)) : 0;
      return { v, text: v.toFixed(2), bg: ramp[k], fg: k >= 4 ? '#FFFFFF' : '#1E3A8A', title: `${name}, ${['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][i]}: ${v.toFixed(2)} kg` };
    }),
  }));
  let pattern = 'No weight-based waste was recorded in the last 8 weeks.';
  if (top.length && maxCell > 0) {
    const dayTotals = Array(7).fill(0);
    for (const [, v] of top) v.forEach((x, i) => { dayTotals[i] += x; });
    const all = sum(dayTotals);
    const d = dayTotals.indexOf(Math.max(...dayTotals));
    let best = { name: '', v: 0 };
    for (const [name, v] of top) if (v[d] > best.v) best = { name, v: v[d] };
    pattern = `${['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][d]} carries the most waste (${Math.round((dayTotals[d] / all) * 100)}% of the six ingredients shown), led by ${best.name} at ${best.v.toFixed(2)} kg on average.`;
  }

  const inventory = risk.stockouts.map((s) => {
    const ex = excessIds.has(s.ing.id);
    const status = s.warn ? 'runs out' : s.belowReorder ? 'below reorder' : ex ? 'excess' : 'ok';
    return {
      name: s.ing.name, onHand: qtyText(s.ing, s.onHand, s.weekly), reorder: qtyText(s.ing, s.rop, s.weekly),
      cover: s.coverDays === null ? '—' : `${s.coverDays.toFixed(1)} days`, coverValue: s.coverDays ?? 1e9,
      status, statusText: { 'runs out': '● Runs out inside lead time', 'below reorder': '▲ Below reorder level', excess: '▲ Excess stock', ok: '✓ OK' }[status],
    };
  }).sort((a, c) => a.coverValue - c.coverValue);
  return {
    shell, empty: false, inventory, tiles, dayCols, batches, stockout, watch, gauge, excess: excessItems, heat, pattern,
    waste: { from: label(wFrom), to: label(st.asOf) },
    spoilNote: batches.length < rows.length ? `Showing ${batches.length} of ${rows.length} batches.` : null,
    model: modelsLabel(st),
  };
};
