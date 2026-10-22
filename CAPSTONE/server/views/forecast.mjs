import { num, getEvaluation, unitMeta, fmtNum, qtyText, MODEL_LABEL, MODEL_NOTE, MODEL_ORDER, RULES, modelsLabel } from '../lib/analysis.mjs';
import * as L from '../lib/load.mjs';
import { addDays, label, labelDM, labelShort, days } from '../lib/dates.mjs';
import { getBundle, shellInfo, dateOnly, planSummary, recommendedPlan, riskOf, sum } from './common.mjs';

const ACTUAL = RULES.chartActualDays, AHEAD = RULES.chartForecastDays;

export const forecastView = async () => {
  const b = await getBundle();
  const { st } = b;
  const [shell, ev] = await Promise.all([shellInfo(b), getEvaluation(st)]);
  const risk = riskOf(st);
  const run = st.run;
  const empty = !run || !st.horizon.length;
  if (empty) return { shell, empty: true, message: run ? 'The selected forecast run has no future dates.' : 'No forecast run is stored in the warehouse yet.' };

  const aFrom = addDays(st.asOf, -(ACTUAL - 1));
  const [theo, offActual, holidays] = await Promise.all([L.loadActualUsage(aFrom, st.asOf), L.loadOffPosActual(aFrom, st.asOf), L.loadHolidays(aFrom, addDays(st.today, AHEAD - 1))]);
  const actualBy = new Map();
  for (const r of [...theo, ...offActual]) { const k = `${r.ingredient_id}|${r.d}`; actualBy.set(k, (actualBy.get(k) ?? 0) + num(r.q)); }
  const aDays = days(aFrom, ACTUAL);
  const fDays = st.horizon.slice(0, AHEAD);
  const chartDays = [...aDays, ...fDays];
  const holIdx = holidays.map((h) => chartDays.indexOf(h.d)).filter((i) => i >= 0);

  const plan = recommendedPlan(b.plans);
  const planSum = plan ? await planSummary(st, plan) : null;
  const runLabel = modelsLabel(st);
  const retrained = dateOnly(run.created_at);

  const ingredients = st.ings.map((ing) => {
    const m = unitMeta(ing, st.weekly(ing.id));
    const runModel = st.dominantModel(ing.id);
    const modelKeys = MODEL_ORDER.filter((k) => ev?.models[k] || k === runModel);
    if (runModel && !modelKeys.includes(runModel)) modelKeys.push(runModel);
    const sc = m.scale;
    const v = (x) => x / sc;
    const res = ev?.residuals.get(ing.id);
    const demand = fDays.map((d) => st.demand(ing.id, d));
    const lastActual = actualBy.get(`${ing.id}|${st.asOf}`) ?? 0;
    const lo80 = [], hi80 = [], lo95 = [], hi95 = [];
    demand.forEach((f) => {
      if (!res) { lo80.push(null); hi80.push(null); lo95.push(null); hi95.push(null); return; }
      const d = res.day;
      lo80.push(v(Math.max(0, f + Math.min(d.p10, 0)))); hi80.push(v(f + Math.max(d.p90, 0)));
      lo95.push(v(Math.max(0, f + Math.min(d.p025, 0)))); hi95.push(v(f + Math.max(d.p975, 0)));
    });
    const week = sum(demand.slice(0, 7));
    const w = res?.week;
    const weekLo = w ? Math.max(0, week + Math.min(w.p10, 0)) : null;
    const weekHi = w ? week + Math.max(w.p90, 0) : null;

    // models
    const scores = modelKeys.map((key) => {
      const s = ev?.models[key]?.perIng.get(ing.id);
      return { key, wmape: s?.wmape ?? null, mase: s?.mase ?? null };
    });
    const best = Math.max(0.0001, ...scores.map((s) => s.wmape ?? 0));
    const models = scores.map((s) => ({
      key: s.key, name: MODEL_LABEL[s.key] ?? s.key, selected: s.key === runModel,
      wmape: s.wmape === null ? null : `${(s.wmape * 100).toFixed(1)}%`, mase: s.mase === null ? null : s.mase.toFixed(2),
      width: s.wmape === null ? 0 : Math.round((s.wmape / (best * 1.1)) * 100),
      note: MODEL_NOTE[s.key] + (s.mase !== null && s.mase >= 1 ? ' · fails MASE < 1' : s.wmape === null ? ' · not scored on this ingredient' : ''),
    }));
    const sel = scores.find((s) => s.key === runModel);

    // "how this feeds the order"
    const rows = risk.batchRows.filter((r) => r.ing.id === ing.id && r.daysLeft >= 0);
    const usable = sum(rows.map((r) => r.batch.qty - (r.insideHorizon && r.daysLeft <= 6 ? r.atRisk : 0)));
    const onOrder = st.stockById.get(ing.id)?.on_order ?? 0;
    const safety = w ? Math.max(w.p90, 0) : 0;
    const orderInput = Math.max(0, week - usable - onOrder + safety);
    const lp = planSum?.lines.find((l) => l.ingredientId === ing.id);
    const fmt = (x) => fmtNum(x / sc, m.dp);

    return {
      id: ing.id, name: ing.name, unit: m.unit, dp: m.dp, value: week * ing.unitCost,
      model: MODEL_LABEL[runModel] ?? runModel, week: fmt(week), lo: weekLo === null ? null : fmt(weekLo), hi: weekHi === null ? null : fmt(weekHi),
      wmape: sel?.wmape == null ? null : `${(sel.wmape * 100).toFixed(1)}%`, mase: sel?.mase == null ? null : sel.mase.toFixed(2),
      chart: {
        actual: aDays.map((d) => v(actualBy.get(`${ing.id}|${d}`) ?? 0)),
        forecast: demand.map(v), lo80, hi80, lo95, hi95, last: v(lastActual),
        yMax: Math.max(...demand, ...aDays.map((d) => actualBy.get(`${ing.id}|${d}`) ?? 0), ...hi95.map((x) => (x === null ? 0 : x * sc)), 1e-9) * 1.15 / sc,
      },
      models,
      feed: { week: fmt(week), onhand: fmt(usable), onOrder: onOrder > 0 ? fmt(onOrder) : null, safety: fmt(safety), order: fmt(orderInput), hasInterval: Boolean(w), lp: lp ? `${qtyText(ing, lp.qtyBase, week)} (${lp.packText ?? 'packs'})` : null },
      fails: sel?.mase != null && sel.mase >= 1,
    };
  });

  const tabsSorted = [...ingredients].sort((a, c) => c.value - a.value);
  return {
    shell, empty: false,
    run: { model: runLabel, runId: run.run_id, retrained: retrained ? label(retrained) : '—', trainEnd: label(run.train_end), horizonDays: st.horizon.length },
    evaluation: ev ? { holdout: `${labelDM(ev.testStart)} ${ev.testStart.slice(0, 4)} – ${labelDM(ev.testEnd)} ${ev.testEnd.slice(0, 4)}`, days: ev.horizon, trainEnd: ev.trainEnd } : null,
    chart: {
      dates: chartDays, aCount: ACTUAL, todayLabel: `Today · ${label(st.today)}`,
      weekStarts: chartDays.map((d, i) => ({ i, d, text: label(d) })).filter((x) => new Date(`${x.d}T00:00:00Z`).getUTCDay() === 1),
      holidays: holIdx.map((i) => ({ i, text: label(chartDays[i]) })),
    },
    tabs: tabsSorted.slice(0, 8).map((i) => i.id), ingredients,
    intro: `Ingredient demand is derived from menu-item sales through the bill of materials. The forecast comes from the ${runLabel} run${ev ? ` and each model is scored on ${ev.horizon} held-out days` : ''}; only models with MASE below 1 (better than a naive forecast) qualify as the selected model.`,
  };
};
