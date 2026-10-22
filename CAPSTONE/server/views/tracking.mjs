import { num, getEvaluation, fmtNum, MODEL_LABEL, modelsLabel } from '../lib/analysis.mjs';
import { addDays, label, labelDM, days } from '../lib/dates.mjs';
import { getBundle, shellInfo, getOps, deltaText, dateOnly, sum } from './common.mjs';

const TYPE_LABEL = { stockout: 'Stockout', spoilage: 'Spoilage', excess: 'Excess capital', weekly_order: 'Weekly order' };

export const trackingView = async () => {
  const b = await getBundle();
  const { st, recs } = b;
  const [shell, ops, ev] = await Promise.all([shellInfo(b), getOps(st), getEvaluation(st)]);

  const decidedRows = recs.filter((r) => r.status !== 'open');
  const goLiveDate = decidedRows.length ? dateOnly(decidedRows[decidedRows.length - 1].decided_at ?? decidedRows[decidedRows.length - 1].created_at) : null;

  // KPI cards: baseline vs the latest 28 days (post-DSS once decisions are logged)
  const base = ops.baseMetrics, cur = ops.cur28;
  const wasteD = deltaText({ cur: cur.wasteKgWeek, base: base.wasteKgWeek, lowerIsBetter: true, mode: 'pct' });
  const spoilD = deltaText({ cur: cur.spoilage, base: base.spoilage, lowerIsBetter: true, mode: 'pts' });
  const stockD = deltaText({ cur: cur.stockoutsWeek, base: base.stockoutsWeek, lowerIsBetter: true, mode: 'pct' });
  const turnD = deltaText({ cur: cur.turnover, base: base.turnover, lowerIsBetter: false, mode: 'x' });
  const kpis = [
    { label: 'AVG WEEKLY FOOD WASTE', base: `${fmtNum(base.wasteKgWeek, 1)} kg`, post: `${fmtNum(cur.wasteKgWeek, 1)} kg`, delta: `${wasteD.text.replace(' vs baseline', '')}${cur.wasteKgWeek !== base.wasteKgWeek ? ` (${fmtNum(Math.abs(base.wasteKgWeek - cur.wasteKgWeek), 1)} kg/week ${cur.wasteKgWeek < base.wasteKgWeek ? 'less' : 'more'})` : ''}`, good: wasteD.good },
    { label: 'SPOILAGE RATE (WASTE ÷ RECEIVED)', base: `${fmtNum(base.spoilage * 100, 1)}%`, post: `${fmtNum(cur.spoilage * 100, 1)}%`, delta: spoilD.text.replace(' vs baseline', ''), good: spoilD.good },
    { label: 'STOCKOUT FREQUENCY', base: `${fmtNum(base.stockoutsWeek, 1)} / wk`, post: `${fmtNum(cur.stockoutsWeek, 1)} / wk`, delta: stockD.text.replace(' vs baseline', ''), good: stockD.good },
    { label: 'INVENTORY TURNOVER', base: `${fmtNum(base.turnover, 1)}× / mo`, post: `${fmtNum(cur.turnover, 1)}× / mo`, delta: `${turnD.text.replace(' vs baseline', '')}${turnD.good === true ? ' (stock moves faster)' : turnD.good === false ? ' (stock moves slower)' : ''}`, good: turnD.good },
  ];

  // 12 weekly blocks of 7 days ending on the last warehouse day
  const rows = ops.rows;
  const weeks = [];
  for (let k = 11; k >= 0; k -= 1) {
    const to = addDays(st.asOf, -7 * k), from = addDays(to, -6);
    const part = rows.filter((r) => r.d >= from && r.d <= to);
    weeks.push({ wk: labelDM(from), from, to, kg: sum(part.map((r) => num(r.waste_kg))) });
  }
  const goLiveIdx = goLiveDate ? weeks.findIndex((w) => goLiveDate <= w.to) : -1;
  const yMax = Math.max(5, Math.ceil(Math.max(base.wasteKgWeek, ...weeks.map((w) => w.kg)) * 1.15 / 5) * 5);

  // adoption
  const counts = { applied: 0, modified: 0, dismissed: 0 };
  for (const r of decidedRows) counts[r.status] += 1;
  const total = decidedRows.length;
  const reasonCount = new Map();
  for (const r of decidedRows.filter((x) => x.status === 'dismissed' && x.reason)) reasonCount.set(r.reason, (reasonCount.get(r.reason) ?? 0) + 1);
  const reasons = [...reasonCount.entries()].sort((a, c) => c[1] - a[1]).slice(0, 4).map(([t, n]) => `${t} (${n})`);

  // log
  const log = decidedRows.slice(0, 40).map((r) => ({
    date: label(dateOnly(r.decided_at ?? r.created_at)), type: TYPE_LABEL[r.type] ?? r.type, rec: r.title, decision: r.status, reason: r.reason ?? '', by: r.decided_by ?? '—',
    outcome: r.outcome_text || 'Pending: measured after the next ETL cycle',
  }));

  // forecast accuracy: value-weighted weekly WMAPE of the production model, last 4 scored weeks
  const acc = ev && ev.weekly.length
    ? ev.weekly.slice(-4).map((w, i, arr) => ({ wk: `Wk ${i + 1} · ${labelDM(w.weekStart)}`, v: w.wmape === null ? '—' : `${(w.wmape * 100).toFixed(1)}%` }))
    : [];

  return {
    shell, kpis, postLabel: goLiveDate ? 'POST-DSS' : 'LATEST 4 WK',
    waste: { weeks: weeks.map((w, i) => ({ wk: w.wk, kg: w.kg, live: goLiveIdx >= 0 && i >= goLiveIdx, title: `Week of ${w.wk}: ${w.kg.toFixed(1)} kg` })), baseline: base.wasteKgWeek, yMax, goLiveIdx, goLiveLabel: goLiveDate ? label(goLiveDate) : null },
    adoption: { total, counts, reasons },
    log, acc,
    accNote: ev ? `Value-weighted WMAPE across all perishable ingredients on the last four weeks of the selected model${st.productionModels.length > 1 ? 's' : ''} (${modelsLabel(st)}) on the held-out window (${labelDM(ev.testStart)} – ${labelDM(ev.testEnd)}), weighted by standard cost.` : 'No evaluation run is stored.',
    decisionsEnabled: shell.writes.decisions,
  };
};
