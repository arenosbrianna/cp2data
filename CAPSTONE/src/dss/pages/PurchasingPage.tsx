import React, { useEffect, useState } from 'react';
import { css, cx } from '../css';
import { useApi, ShellInfo, post } from '../api';
import { useDss, Status } from '../context';
import { PageState } from '../ui';

interface Line {
  ingredientId: number; name: string; supCode: string; supplier: string; leadText: string; qtyText: string; packText: string | null; split: string; by: string; byText: string; urgent: boolean;
  unitCost: string; lineText: string; line: number; done: boolean; exempt: boolean;
}
interface Scenario {
  id: string; optRunId: number; name: string; desc: string; recommended: boolean; cost: string; costValue: number; waste: string; service: string; over: boolean; overText: string; shortage: string | null;
  binding: string[]; budgetPct: number; budgetUsed: string; solver: string; created: string; objective: string[]; lines: Line[]; notOrdered: { name: string; note: string }[]; weekStart: string; status: Status;
}
interface PurchasingData {
  shell: ShellInfo; empty: boolean; message?: string; budget: number; budgets: number[]; scenarios: Scenario[]; recommendedId: string; week: string; storageText: string; runInfo: string;
}

const peso = (v: number) => `₱${Math.round(v).toLocaleString('en-US')}`;
const ORDERED_KEY = 'makisushi-dss-ordered';
const readOrdered = (): Record<string, boolean> => { try { return JSON.parse(window.localStorage.getItem(ORDERED_KEY) || '{}'); } catch { return {}; } };

export const PurchasingPage: React.FC = () => {
  const [budget, setBudget] = useState<number | null>(null);
  const { data, error, loading, reload } = useApi<PurchasingData>(budget ? `/api/purchasing?budget=${budget}` : '/api/purchasing');
  const { setShell, decide, statusOf, tick, toast, refreshAll } = useDss();
  const [scenario, setScenario] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, boolean>>(readOrdered);

  useEffect(() => { if (data) setShell(data.shell); }, [data, setShell]);
  useEffect(() => { if (tick) reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const sc = data && !data.empty ? data.scenarios.find((s) => s.id === (scenario ?? data.recommendedId)) ?? data.scenarios[0] : undefined;
  const lineKey = (s: Scenario, l: Line) => `${s.optRunId}:${l.ingredientId}`;
  const isDone = (s: Scenario, l: Line) => overrides[lineKey(s, l)] ?? l.done;

  const toggle = async (s: Scenario, l: Line, value: boolean) => {
    const k = lineKey(s, l);
    setOverrides((o) => ({ ...o, [k]: value }));
    const result = await post('/api/plan-lines', { optRunId: s.optRunId, ingredientId: l.ingredientId, ordered: value });
    if (!result.ok) {
      const next = { ...readOrdered(), [k]: value };
      try { window.localStorage.setItem(ORDERED_KEY, JSON.stringify(next)); } catch { /* storage can be blocked */ }
      if (result.payload.enabled === false) toast('Tick kept in this browser only: the purchasing-list table is not created in the database yet (npm run db:migrate).', 'err');
      else toast(result.payload.error || 'The tick could not be saved', 'err');
    }
  };

  return (
    <PageState loading={loading && !data} error={error && !data ? error : null} reload={reload} empty={data?.empty ? data.message ?? 'No plan.' : null}>
      {data && !data.empty && sc && (
        <>
          <div style={css('display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 16px')}>
            <div style={css('display: flex; flex-direction: column; gap: 6px')}>
              <div style={css('font-size: 14px; font-weight: 700; color: #1E3A8A')}>Prescriptive analytics · linear programming (PuLP)</div>
              <h1 style={css('margin: 0; font-size: 36px; font-weight: 800; letter-spacing: -0.02em')}>Purchasing plan · {data.week}</h1>
              <p style={css('margin: 0; font-size: 15px; color: #4B5563; max-width: 820px')}>Pick a scenario, check the constraints, then work through the purchasing list. Orders are placed by phone or messaging outside the system (§3.3.6). Tick each line when it's done so Tracking can match deliveries.</p>
            </div>
            <div className="no-print" style={css('display: flex; gap: 10px; flex-wrap: wrap')}>
              <button className="btn" type="button" onClick={() => window.print()}>Print / PDF</button>
              {(() => {
                const s = statusOf(`weekly_order:${sc.id}:${sc.weekStart}`, sc.status);
                return s === 'open'
                  ? <button className="btn pri" type="button" onClick={() => decide({ key: `weekly_order:${sc.id}:${sc.weekStart}`, type: 'Weekly order', typeKey: 'weekly_order', title: `Approve the ${sc.name} purchase list: ${sc.cost} across ${sc.lines.length} ingredients`, pesoImpact: sc.costValue, optRunId: sc.optRunId }, 'applied')}>Approve plan</button>
                  : <span className="btn" style={css('cursor: default')}>✓ Plan approved · logged</span>;
              })()}
            </div>
          </div>

          <div style={css('display: flex; flex-wrap: wrap; gap: 20px; align-items: flex-start')}>
            <section className="card no-print" style={css('flex: 1 1 300px; min-width: 0; padding: 22px; display: flex; flex-direction: column; gap: 14px')}>
              <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>Constraints</h2>
              <label style={css('display: flex; flex-direction: column; gap: 6px')}>
                <span className="lbl">Weekly budget (₱)</span>
                <select className="inp" value={data.budget} onChange={(e) => { setBudget(Number(e.target.value)); setScenario(null); }}>
                  {data.budgets.map((b) => <option key={b} value={b}>{b.toLocaleString('en-US')}</option>)}
                </select>
              </label>
              <div style={css('display: flex; flex-direction: column; gap: 6px')}><span className="lbl">Storage capacity</span><div className="inp" style={css('font-size: 13px; line-height: 1.5; height: auto; background: #F8FAFC; color: #4B5563')}>{data.storageText}</div></div>
              <label style={css('display: flex; flex-direction: column; gap: 6px')}>
                <span className="lbl">Safety stock</span>
                <select className="inp" disabled value="none" style={css('font-size: 13px')}><option value="none">Not used by the optimizer</option></select>
              </label>
              <label style={css('display: flex; gap: 10px; align-items: center; font-size: 14px; min-height: 44px')}><input type="checkbox" checked readOnly disabled style={css('width: 20px; height: 20px')} /><span>Enforce shelf life (split deliveries)</span></label>
              <label style={css('display: flex; gap: 10px; align-items: center; font-size: 14px; min-height: 44px')}><input type="checkbox" checked readOnly disabled style={css('width: 20px; height: 20px')} /><span>Respect supplier lead times</span></label>
              <button className="btn" type="button" onClick={async () => { await refreshAll(); toast(`Showing the latest stored optimizer runs. ${data.runInfo}. New runs are produced by the optimization engine (engines/run_pipeline.py).`); }}>Re-run optimizer</button>
              <div style={css('border-top: 1px solid #EDEBE6; padding-top: 12px; display: flex; flex-direction: column; gap: 6px')}>
                <div className="lbl">Objective · {sc.name}</div>
                <div className="mono" style={css('font-size: 12px; line-height: 1.6; color: #374151; background: #F8FAFC; border-radius: 8px; padding: 10px')}>
                  {sc.objective.map((l, i) => <React.Fragment key={i}>{i > 0 && <br />}{l}</React.Fragment>)}
                </div>
              </div>
            </section>

            <div style={css('flex: 999 1 560px; min-width: 0; display: flex; flex-direction: column; gap: 14px')}>
              <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>Decision alternatives</h2>
              <div role="radiogroup" aria-label="Scenario" className="no-print" style={css('display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px')}>
                {data.scenarios.map((s) => (
                  <button key={s.id} type="button" role="radio" aria-checked={s.id === sc.id} className={s.id === sc.id ? 'scn on' : 'scn'} onClick={() => setScenario(s.id)}>
                    <div style={css('display: flex; justify-content: space-between; align-items: center; gap: 8px')}><span style={css('font-size: 15px; font-weight: 800')}>{s.name}</span>{s.recommended && <span style={css('font-size: 11px; font-weight: 800; background: #1E3A8A; color: #FFFFFF; padding: 3px 7px; border-radius: 4px')}>RECOMMENDED</span>}</div>
                    <div style={css('font-size: 13px; color: #4B5563; line-height: 1.45')}>{s.desc}</div>
                    <div style={css('display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; border-top: 1px solid #EDEBE6; padding-top: 10px')}>
                      <div><div style={css('font-size: 11px; font-weight: 700; color: #4B5563')}>COST</div><div className="mono" style={css('font-size: 15px; font-weight: 600')}>{s.cost}</div></div>
                      <div><div style={css('font-size: 11px; font-weight: 700; color: #4B5563')}>WASTE</div><div className="mono" style={css('font-size: 15px; font-weight: 600')}>{s.waste}</div></div>
                      <div><div style={css('font-size: 11px; font-weight: 700; color: #4B5563')}>SERVICE</div><div className="mono" style={css('font-size: 15px; font-weight: 600')}>{s.service}</div></div>
                    </div>
                    {s.over && <div style={css('font-size: 12px; font-weight: 700; color: #991B1B; background: #FEE2E2; border-radius: 6px; padding: 6px 8px')}>{s.overText}</div>}
                    {s.shortage && <div style={css('font-size: 12px; font-weight: 700; color: #92400E; background: #FEF3C7; border-radius: 6px; padding: 6px 8px')}>{s.shortage}</div>}
                  </button>
                ))}
              </div>
              <div className="card" style={css('padding: 16px 18px; display: flex; flex-direction: column; gap: 8px')}>
                <div className="lbl">Binding constraints · {sc.name}</div>
                {sc.binding.map((b, i) => <div key={i} style={css('font-size: 14px; color: #374151; line-height: 1.5')}>• {b}</div>)}
                <div style={css('display: flex; flex-direction: column; gap: 6px; margin-top: 6px')}>
                  <div style={css('display: flex; justify-content: space-between; font-size: 13px')}><span>Budget used (excl. whole salmon and tuna)</span><span className="mono">{sc.budgetUsed} / {peso(data.budget)}</span></div>
                  <div style={css('height: 10px; background: #E5E7EB; border-radius: 999px; overflow: hidden')}><div style={cx('height: 100%', { width: `${sc.budgetPct}%`, background: sc.over ? '#DC2626' : '#1E3A8A' })} /></div>
                </div>
              </div>
            </div>
          </div>

          <section className="card" style={css('padding: 0; overflow: hidden')}>
            <div style={css('padding: 20px 22px 12px; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; align-items: flex-end')}>
              <div><h2 style={css('margin: 0; font-size: 20px; font-weight: 800')}>Supplier purchasing list</h2><p style={css('margin: 4px 0 0; font-size: 13px; color: #4B5563')}>{sc.name} · optimizer run #{sc.optRunId} ({sc.solver}, {sc.created}) joined to dim_supplier · sorted by order-by time</p></div>
              <span style={css('font-size: 14px; font-weight: 700')}>{sc.lines.filter((l) => isDone(sc, l)).length} of {sc.lines.length} lines ordered</span>
            </div>
            <div style={css('overflow-x: auto')}>
              <table style={css('width: 100%; min-width: 1060px')}>
                <thead><tr>
                  {['Ordered', 'Order by', 'Ingredient', 'Supplier', 'Contact', 'Lead', 'Qty · deliveries'].map((h) => <th key={h} className="th">{h}</th>)}
                  <th className="th" style={css('text-align: right')}>Unit cost</th><th className="th" style={css('text-align: right')}>Line cost</th>
                </tr></thead>
                <tbody>
                  {sc.lines.map((l) => (
                    <tr key={l.ingredientId}>
                      <td className="td"><label style={css('display: inline-flex; min-width: 44px; min-height: 44px; align-items: center')}><input type="checkbox" checked={isDone(sc, l)} onChange={(e) => toggle(sc, l, e.target.checked)} aria-label={`Mark ${l.name} as ordered`} style={css('width: 20px; height: 20px')} /></label></td>
                      <td className="td" style={cx('font-weight: 700; white-space: nowrap', { color: l.urgent ? '#B91C1C' : '#111827' })}>{l.urgent ? '● ' : ''}{l.byText}</td>
                      <td className="td" style={css('font-weight: 700')}>{l.name}</td>
                      <td className="td"><div style={css('font-weight: 600')}>{l.supplier}</div><div className="mono" style={css('font-size: 12px; color: #4B5563')}>{l.supCode}</div></td>
                      <td className="td" style={css('white-space: nowrap')}><div style={css('font-size: 12px; color: #4B5563')}>Not on file</div></td>
                      <td className="td" style={css('white-space: nowrap')}>{l.leadText}</td>
                      <td className="td"><div className="mono" style={css('font-weight: 600')}>{l.qtyText}</div><div style={css('font-size: 12px; color: #4B5563')}>{l.packText ? `${l.packText} · ` : ''}{l.split}</div></td>
                      <td className="td mono" style={css('text-align: right')}>{l.unitCost}</td>
                      <td className="td mono" style={css('text-align: right; font-weight: 600')}>{l.lineText}</td>
                    </tr>
                  ))}
                  {sc.lines.length === 0 && <tr><td className="td" colSpan={9} style={css('color: #4B5563')}>This scenario orders nothing this week.</td></tr>}
                  <tr><td className="td" colSpan={8} style={css('font-weight: 800; text-align: right')}>Total</td><td className="td mono" style={css('text-align: right; font-weight: 600')}>{sc.cost}</td></tr>
                </tbody>
              </table>
            </div>
            <div style={css('padding: 14px 22px 20px; font-size: 13px; color: #374151; line-height: 1.6')}>
              <b>Not ordered this cycle:</b> {sc.notOrdered.length ? sc.notOrdered.map((n) => `${n.name} (${n.note})`).join(' · ') : 'every ingredient has an order.'}
              <div style={css('margin-top: 6px; color: #4B5563')}>Supplier phone and contact person are not stored in dim_supplier, so they are not shown. Delivery days follow each supplier's delivery cadence and the forecast demand each delivery has to cover.</div>
            </div>
          </section>
        </>
      )}
    </PageState>
  );
};
