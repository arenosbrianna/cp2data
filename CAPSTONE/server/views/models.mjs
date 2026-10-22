// The forecast models the user can choose from: one production run per model, the champion flagged, with its test-year accuracy and whether plans are stored for it.
import { getState, MODEL_LABEL, MODEL_NOTE } from '../lib/analysis.mjs';
import * as L from '../lib/load.mjs';

const USABLE = ['Optimal', 'Feasible (not proven optimal)'];

export const modelsView = async () => {
  const st = await getState();
  const plans = await L.loadPlans();
  const withPlans = new Set(plans.filter((p) => USABLE.includes(p.solver_status)).map((p) => p.forecast_run_id));
  return {
    selected: st.selectedModel, champion: st.championModel,
    models: st.availableModels.map((m) => ({
      model: m.model, label: MODEL_LABEL[m.model] ?? m.model, note: MODEL_NOTE[m.model] ?? '', runId: m.runId, isChampion: m.isChampion,
      wmape: m.wmape, mase: m.mase, beatsNaive: m.mase !== null && m.mase < 1, hasPlans: withPlans.has(m.runId),
    })),
  };
};
