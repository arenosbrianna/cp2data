import { num, pesoFmt, fmtNum, RULES, SCENARIO_META, MODEL_LABEL } from '../lib/analysis.mjs';
import { label, labelDM, addDays } from '../lib/dates.mjs';
import { readPlanLines } from '../lib/decisions.mjs';
import {
  getBundle, shellInfo, planSummary, planBudgets, scenarioList, pickPlan, keyOf, decisionStatus, dateOnly, pct,
} from './common.mjs';

const WEIGHTS = { balanced: [1.0, 1.25, 0], min_spoilage: [3.0, 1.25, 0], max_availability: [1.0, 5.0, 0], min_cost: [1.0, 1.25, 0.1] };

export const purchasingView = async (budgetParam) => {
  const b = await getBundle();
  const { st, decided } = b;
  const shell = await shellInfo(b);
  const budgets = planBudgets(b.plans);
  if (!budgets.length) {
    return { shell, empty: true, message: st.isChampion ? 'No optimizer run is stored for the current forecast run.'
      : `No optimizer plan is stored yet for the ${MODEL_LABEL[st.selectedModel] ?? st.selectedModel} forecast. Choose another model in the header, or solve plans for it and load them (run_pipeline.py --forecast-model ${st.selectedModel}).` };
  }
  const budget = budgetParam && budgets.includes(Number(budgetParam)) ? Number(budgetParam) : budgets[0];
  const runs = scenarioList(b.plans, budget);
  const recommended = pickPlan(b.plans, RULES.recommendedScenario, budget) ?? runs[0];

  const scenarios = [];
  for (const run of runs) {
    const sum = await planSummary(st, run);
    const lines = await readPlanLines(run.opt_run_id);
    const over = sum.counted > budget + 0.5;
    const meta = SCENARIO_META[run.scenario] ?? { name: run.scenario, desc: '' };
    const w = WEIGHTS[run.scenario] ?? [1, 1.25, 0];
    const peak = sum.storage;
    const fish = sum.exemptCost > 0;
    const binding = [];
    binding.push(over
      ? `Budget binds and is exceeded by ${pesoFmt(sum.counted - budget)}. Raise it or reduce scope.`
      : sum.counted >= budget * 0.97
        ? `Budget binds: ${pesoFmt(sum.counted)} of ${pesoFmt(budget)} used.`
        : `Budget not binding: ${pesoFmt(budget - sum.counted)} slack.`);
    binding.push(peak.binds
      ? `Storage binds: chilled peak ${Math.round(peak.chilled.litres)} L and frozen peak ${Math.round(peak.frozen.litres)} L need ${Math.round(peak.poolNeeded)} L of the shared pool.`
      : `Storage not binding: peak ${Math.round(peak.chilled.litres)} L chilled (${peak.chilled.day ? label(peak.chilled.day) : '—'}) of ${Math.round(peak.cap.chilled?.capacity ?? 0)} L, ${Math.round(peak.frozen.litres)} L frozen of ${Math.round(peak.cap.frozen?.capacity ?? 0)} L.`);
    if (sum.dailyLots.length) binding.push(`Shelf life drives ${sum.dailyLots.length} short-life ingredient${sum.dailyLots.length === 1 ? '' : 's'} (${sum.dailyLots.slice(0, 4).join(', ')}${sum.dailyLots.length > 4 ? ', …' : ''}): ordered per delivery lot, whole packs only.`);
    if (fish) binding.push('Whole salmon and tuna follow the client delivery cadence (at most 2 orders in 4 weeks) and sit outside the weekly budget.');
    scenarios.push({
      id: run.scenario, optRunId: run.opt_run_id, name: meta.name, desc: meta.desc, recommended: run.scenario === RULES.recommendedScenario,
      cost: pesoFmt(sum.cost), costValue: sum.cost, counted: sum.counted, waste: `${fmtNum(sum.wasteKg, 1)} kg`, service: pct(sum.service),
      over, overText: `✕ Over budget by ${pesoFmt(sum.counted - budget)}`,
      shortage: sum.shortNames.length ? `▲ Expected shortage: ${sum.shortNames.slice(0, 2).join(', ')}${sum.shortNames.length > 2 ? ` +${sum.shortNames.length - 2}` : ''}` : null,
      binding, budgetPct: Math.min(100, Math.round((sum.counted / budget) * 100)), budgetUsed: pesoFmt(sum.counted),
      solver: run.solver_status, created: label(dateOnly(run.created_at)), weights: w,
      objective: [
        `min Σᵢ (${w[0]}·wasteᵢ + ${w[1]}·shortᵢ${w[2] ? ` + ${w[2]}·costᵢ` : ''})`,
        's.t. Σᵢ costᵢ·packsᵢ ≤ budget (excl. whole fish)',
        'litres of stock ≤ storage, ∀t',
        'cover ≤ shelf lifeᵢ, orders ≥ lead timeᵢ',
      ],
      lines: sum.lines.map((l) => {
        const t = lines.get(l.ingredientId);
        return { ...l, done: Boolean(t?.ordered) };
      }),
      notOrdered: sum.notOrdered,
      weekStart: sum.week, status: decisionStatus(decided, keyOf('weekly_order', run.scenario, sum.week))?.status ?? 'open',
    });
  }
  const weekStart = scenarios[0] ? runs[0].plan_week_start : st.today;
  const storage = st.storage.map((s) => ({ type: s.storage_type, capacity: num(s.capacity), pool: num(s.pool) }));
  return {
    shell, empty: false, budget, budgets, scenarios, recommendedId: recommended?.scenario ?? scenarios[0]?.id,
    week: `${label(weekStart)} – ${label(addDays(weekStart, 6))}`,
    storage,
    storageText: `Chilled ${Math.round(storage.find((s) => s.type === 'chilled')?.capacity ?? 0)} L · Frozen ${Math.round(storage.find((s) => s.type === 'frozen')?.capacity ?? 0)} L · shared pool ${Math.round(Math.max(...storage.map((s) => s.pool), 0))} L`,
    runInfo: recommended ? `Optimizer run #${recommended.opt_run_id}, ${label(dateOnly(recommended.created_at))}, status ${recommended.solver_status}` : '',
  };
};
