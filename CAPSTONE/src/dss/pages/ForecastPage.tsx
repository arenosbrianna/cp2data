import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { css, cx } from '../css';
import { useApi, ShellInfo, fmt } from '../api';
import { useDss } from '../context';
import { Modal, PageState } from '../ui';

interface Model { key: string; name: string; selected: boolean; wmape: string | null; mase: string | null; width: number; note: string }
interface Ingredient {
  id: number; name: string; unit: string; dp: number; value: number; model: string; week: string; lo: string | null; hi: string | null; wmape: string | null; mase: string | null; fails: boolean;
  chart: { actual: number[]; forecast: number[]; lo80: (number | null)[]; hi80: (number | null)[]; lo95: (number | null)[]; hi95: (number | null)[]; last: number; yMax: number };
  models: Model[];
  feed: { week: string; onhand: string; onOrder: string | null; safety: string; order: string; hasInterval: boolean; lp: string | null };
}
interface ForecastData {
  shell: ShellInfo; empty: boolean; message?: string; intro: string;
  run: { model: string; runId: number; retrained: string; trainEnd: string; horizonDays: number };
  evaluation: { holdout: string; days: number; trainEnd: string } | null;
  chart: { dates: string[]; aCount: number; todayLabel: string; weekStarts: { i: number; d: string; text: string }[]; holidays: { i: number; text: string }[] };
  tabs: number[]; ingredients: Ingredient[];
}

const W = 1000, H = 280;

export const ForecastPage: React.FC = () => {
  const { data, error, loading, reload } = useApi<ForecastData>('/api/forecast');
  const { setShell, refreshAll, tick } = useDss();
  const [selId, setSelId] = useState<number | null>(null);
  const [retrain, setRetrain] = useState(false);

  useEffect(() => { if (data) setShell(data.shell); }, [data, setShell]);
  useEffect(() => { if (tick) reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const byId = useMemo(() => new Map((data?.ingredients ?? []).map((i) => [i.id, i])), [data]);
  const cur = (selId !== null ? byId.get(selId) : undefined) ?? (data && !data.empty ? byId.get(data.tabs[0]) : undefined);

  return (
    <PageState loading={loading && !data} error={error && !data ? error : null} reload={reload} empty={data?.empty ? data.message ?? 'No forecast available.' : null}>
      {data && !data.empty && cur && (
        <>
          <div style={css('display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 16px')}>
            <div style={css('display: flex; flex-direction: column; gap: 6px')}>
              <div style={css('font-size: 14px; font-weight: 700; color: #1E3A8A')}>Predictive analytics</div>
              <h1 style={css('margin: 0; font-size: 36px; font-weight: 800; letter-spacing: -0.02em')}>Demand forecasts</h1>
              <p style={css('margin: 0; font-size: 15px; color: #4B5563; max-width: 760px')}>{data.intro}</p>
            </div>
            <button className="btn" type="button" onClick={() => setRetrain(true)}>Retrain models</button>
          </div>

          <div role="tablist" aria-label="Ingredient" style={css('display: flex; flex-wrap: wrap; gap: 8px')}>
            {data.tabs.map((id) => {
              const t = byId.get(id)!;
              const on = id === cur.id;
              return <button key={id} role="tab" type="button" aria-selected={on} className={on ? 'tab on' : 'tab'} onClick={() => setSelId(id)}>{t.name}</button>;
            })}
            {data.ingredients.length > data.tabs.length && (
              <select aria-label="Other ingredients" className={data.tabs.includes(cur.id) ? 'tab' : 'tab on'} value={data.tabs.includes(cur.id) ? '' : cur.id}
                onChange={(e) => { if (e.target.value) setSelId(Number(e.target.value)); }}>
                <option value="">More ingredients…</option>
                {data.ingredients.filter((i) => !data.tabs.includes(i.id)).sort((a, b) => a.name.localeCompare(b.name)).map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
              </select>
            )}
          </div>

          <section className="card" style={css('padding: 22px; display: flex; flex-direction: column; gap: 16px')}>
            <div style={css('display: flex; justify-content: space-between; flex-wrap: wrap; gap: 16px')}>
              <div>
                <h2 style={css('margin: 0; font-size: 20px; font-weight: 800')}>{cur.name}: daily demand, {cur.unit}</h2>
                <p style={css('margin: 4px 0 0; font-size: 13px; color: #4B5563')}>{data.chart.aCount} days actual (sales × recipe + staff/prep use) · {cur.chart.forecast.length}-day forecast · model: <b style={css('color: #111827')}>{cur.model}</b></p>
              </div>
              <div style={css('display: flex; gap: 20px; flex-wrap: wrap')}>
                <div>
                  <div style={css('font-size: 12px; color: #4B5563; font-weight: 700')}>NEXT 7 DAYS</div>
                  <div className="mono" style={css('font-size: 22px; font-weight: 600')}>{cur.week} {cur.unit}</div>
                  <div style={css('font-size: 12px; color: #4B5563')}>{cur.lo !== null ? `80% interval ${cur.lo}–${cur.hi}` : '80% interval not available'}</div>
                </div>
                <div><div style={css('font-size: 12px; color: #4B5563; font-weight: 700')}>WMAPE</div><div className="mono" style={css('font-size: 22px; font-weight: 600')}>{cur.wmape ?? '—'}</div></div>
                <div><div style={css('font-size: 12px; color: #4B5563; font-weight: 700')}>MASE</div><div className="mono" style={css('font-size: 22px; font-weight: 600')}>{cur.mase ?? '—'}</div></div>
              </div>
            </div>
            <DemandChart ing={cur} chart={data.chart} />
          </section>

          <div style={css('display: flex; flex-wrap: wrap; gap: 20px; align-items: flex-start')}>
            <section className="card" style={css('flex: 1 1 420px; min-width: 0; padding: 22px; display: flex; flex-direction: column; gap: 12px')}>
              <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>Model comparison: {cur.name}</h2>
              <p style={css('margin: 0; font-size: 13px; color: #4B5563')}>{data.evaluation ? `Holdout: ${data.evaluation.holdout} (${data.evaluation.days} days, scored by week). Lower is better on both metrics.` : 'No evaluation run is stored, so models cannot be compared.'}</p>
              {cur.models.map((m) => (
                <div key={m.key} style={css('display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 2fr) 64px; gap: 12px; align-items: center; padding: 8px 0; border-top: 1px solid #EDEBE6')}>
                  <div style={css('font-size: 14px; font-weight: 700')}>{m.name}{m.selected && <span style={css('margin-left: 8px; font-size: 11px; font-weight: 800; background: #1E3A8A; color: #FFFFFF; padding: 2px 6px; border-radius: 4px')}>SELECTED</span>}</div>
                  <div style={css('height: 10px; background: #F1F5F9; border-radius: 999px; overflow: hidden')}><div style={cx('height: 100%; border-radius: 999px', { width: `${m.width}%`, background: m.selected ? '#1E3A8A' : '#94A3B8' })} /></div>
                  <div className="mono" style={css('font-size: 13px; text-align: right')}>{m.wmape ?? '—'}</div>
                  <div style={css('grid-column: 1 / -1; font-size: 12px; color: #4B5563')}>MASE {m.mase ?? '—'} · {m.note}</div>
                </div>
              ))}
            </section>

            <section className="card" style={css('flex: 1 1 360px; min-width: 0; padding: 22px; display: flex; flex-direction: column; gap: 10px')}>
              <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>How this feeds the order</h2>
              <div style={css('display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px 16px; font-size: 14px')}>
                <span style={css('color: #374151')}>Forecast demand, next 7 days</span><span className="mono">{cur.feed.week} {cur.unit}</span>
                <span style={css('color: #374151')}>− Usable on hand before expiry</span><span className="mono">{cur.feed.onhand} {cur.unit}</span>
                {cur.feed.onOrder && <><span style={css('color: #374151')}>− Already on order</span><span className="mono">{cur.feed.onOrder} {cur.unit}</span></>}
                <span style={css('color: #374151')}>+ Safety stock (from 80% interval)</span><span className="mono">{cur.feed.hasInterval ? `${cur.feed.safety} ${cur.unit}` : 'n/a'}</span>
                <span style={css('font-weight: 800; border-top: 1px solid #E7E5E0; padding-top: 8px')}>LP order input</span><span className="mono" style={css('font-weight: 600; border-top: 1px solid #E7E5E0; padding-top: 8px')}>{cur.feed.order} {cur.unit}</span>
              </div>
              <p style={css('margin: 4px 0 0; font-size: 13px; color: #4B5563; line-height: 1.5')}>The LP then adjusts quantity and delivery split for budget, storage, whole packs and shelf life. {cur.feed.lp ? `Stored plan for this ingredient: ${cur.feed.lp}.` : 'The stored plan does not order this ingredient this week.'} See Purchasing.</p>
              <Link to="/purchasing" style={css('font-size: 14px; font-weight: 700')}>Open purchasing list →</Link>
            </section>
          </div>

          <section className="card" style={css('padding: 0; overflow: hidden')}>
            <div style={css('padding: 20px 22px 12px')}><h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>All perishable ingredients</h2></div>
            <div style={css('overflow-x: auto')}>
              <table className="tbl-fc" style={css('width: 100%; min-width: 860px')}>
                <thead><tr>{['Ingredient', 'Selected model', 'Next 7 days', '80% interval', 'WMAPE', 'MASE', 'Last retrained'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
                <tbody>
                  {data.ingredients.map((r) => (
                    <tr key={r.id}>
                      <td className="td" style={css('font-weight: 700')}><button type="button" onClick={() => { setSelId(r.id); window.scrollTo({ top: 0, behavior: 'smooth' }); }} style={css('background: none; border: 0; padding: 0; font: inherit; font-weight: 700; color: #1E3A8A; cursor: pointer; text-align: left')}>{r.name}</button></td>
                      <td className="td">{r.model}</td>
                      <td className="td mono">{r.week} {r.unit}</td>
                      <td className="td mono">{r.lo !== null ? `${r.lo}–${r.hi}` : '—'}</td>
                      <td className="td mono">{r.wmape ?? '—'}</td>
                      <td className="td mono">{r.mase ?? '—'}{r.fails ? ' ▲' : ''}</td>
                      <td className="td" style={css('color: #4B5563')}>{data.run.retrained}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p style={css('margin: 0; padding: 12px 22px 18px; font-size: 12px; color: #4B5563')}>▲ MASE of 1 or more: the model is no better than repeating last week. WMAPE and MASE are scored on weekly ingredient demand (sales × recipe) over the holdout.</p>
          </section>
        </>
      )}
      {retrain && (
        <Modal title="Retrain models" onClose={() => setRetrain(false)}>
          <p style={css('font-size: 14px; line-height: 1.6; color: #374151')}>Models are trained by the forecasting engine (engines/forecast_engine.py), which scores SES, SARIMA, Holt-Winters and ML regression and stores a new run in the warehouse. This page always shows the latest stored run{data && !data.empty ? ` (run ${data.run.runId}, ${data.run.retrained})` : ''}.</p>
          <div style={css('display: flex; gap: 10px; justify-content: flex-end; flex-wrap: wrap')}>
            <button type="button" className="btn" onClick={() => setRetrain(false)}>Close</button>
            <button type="button" className="btn pri" onClick={async () => { await refreshAll(); setRetrain(false); }}>Reload latest run</button>
          </div>
        </Modal>
      )}
    </PageState>
  );
};

const DemandChart: React.FC<{ ing: Ingredient; chart: ForecastData['chart'] }> = ({ ing, chart }) => {
  const c = ing.chart;
  const A = chart.aCount;
  const F = c.forecast.length;
  const N = A + F;
  const fx = (i: number) => (i / (N - 1)) * W;
  const fy = (v: number) => H - (v / c.yMax) * H;
  const line = (from: number, to: number, src: number[]) => src.slice(0, to - from + 1).map((v, k) => `${k === 0 ? 'M' : 'L'}${fx(from + k).toFixed(1)} ${fy(v).toFixed(1)}`).join(' ');
  const actualPath = line(0, A - 1, c.actual);
  const fcPath = line(A - 1, N - 1, [c.last, ...c.forecast]);
  const band = (lo: (number | null)[], hi: (number | null)[]) => {
    if (lo.some((v) => v === null)) return '';
    const l = lo as number[], h = hi as number[];
    let up = `M${fx(A - 1).toFixed(1)} ${fy(c.last).toFixed(1)} `;
    h.forEach((v, k) => { up += `L${fx(A + k).toFixed(1)} ${fy(v).toFixed(1)} `; });
    let dn = '';
    for (let k = l.length - 1; k >= 0; k -= 1) dn += `L${fx(A + k).toFixed(1)} ${fy(l[k]).toFixed(1)} `;
    return `${up}${dn}L${fx(A - 1).toFixed(1)} ${fy(c.last).toFixed(1)} Z`;
  };
  const todayX = fx(A);
  const first = chart.holidays.find((h) => h.i >= A) ?? chart.holidays[0];
  return (
    <>
      <div style={css('display: grid; grid-template-columns: 48px minmax(0, 1fr); gap: 8px')}>
        <div className="mono" style={css('height: 280px; display: flex; flex-direction: column; justify-content: space-between; font-size: 12px; color: #4B5563; text-align: right')}>
          <span>{fmt(c.yMax, ing.dp)}</span><span>{fmt(c.yMax / 2, ing.dp)}</span><span>0</span>
        </div>
        <div style={css('position: relative; height: 280px; border-left: 1px solid #CBD5E1; border-bottom: 1px solid #CBD5E1')}>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`${ing.name} demand: ${A} days actual and ${F}-day forecast, about ${ing.week} ${ing.unit} over the next 7 days`} style={css('position: absolute; inset: 0; width: 100%; height: 100%')}>
            <line x1="0" y1="140" x2="1000" y2="140" stroke="#EDEBE6" strokeWidth="1" vectorEffect="non-scaling-stroke" />
            <rect x={todayX} y="0" width={W - todayX} height="280" fill="#F5F7FF" />
            <path d={band(c.lo95, c.hi95)} fill="#E0E7FF" />
            <path d={band(c.lo80, c.hi80)} fill="#C7D2FE" />
            <path d={actualPath} fill="none" stroke="#111827" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            <path d={fcPath} fill="none" stroke="#1E3A8A" strokeWidth="2.5" strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
            <line x1={todayX} y1="0" x2={todayX} y2="280" stroke="#1E3A8A" strokeWidth="1" vectorEffect="non-scaling-stroke" />
            {chart.holidays.map((h) => <line key={h.i} x1={fx(h.i)} y1="0" x2={fx(h.i)} y2="280" stroke="#B45309" strokeWidth="1" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />)}
          </svg>
          <div style={cx('position: absolute; top: 8px; font-size: 12px; font-weight: 700; color: #1E3A8A; background: #FFFFFF; padding: 2px 6px; border-radius: 4px', { left: `${(todayX / W) * 100}%` })}>{chart.todayLabel}</div>
          {first && <div style={cx('position: absolute; top: 34px; font-size: 12px; font-weight: 700; color: #92400E; background: #FFFFFF; padding: 2px 6px; border-radius: 4px; text-align: right', { right: first.i >= N - 3 ? 6 : undefined, left: first.i >= N - 3 ? undefined : `${(fx(first.i) / W) * 100}%` })}>{first.text}<br />is_holiday = 1</div>}
        </div>
      </div>
      <div style={css('display: grid; grid-template-columns: 48px minmax(0, 1fr); gap: 8px')}>
        <span />
        <div style={css('position: relative; height: 18px; font-size: 12px; color: #4B5563')}>
          {chart.weekStarts.map((w) => <span key={w.i} style={cx('position: absolute; top: 0; white-space: nowrap', { left: `${(w.i / (N - 1)) * 100}%`, transform: w.i === 0 ? 'none' : w.i >= N - 2 ? 'translateX(-100%)' : 'translateX(-50%)' })}>{w.text}</span>)}
        </div>
      </div>
      <div style={css('display: flex; gap: 18px; flex-wrap: wrap; font-size: 13px; color: #374151')}>
        <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 18px; height: 2px; background: #111827')} />Actual</span>
        <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 18px; height: 0; border-top: 2px dashed #1E3A8A')} />Forecast</span>
        <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 14px; height: 10px; background: #C7D2FE')} />80% interval</span>
        <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 14px; height: 10px; background: #E0E7FF')} />95% interval</span>
      </div>
    </>
  );
};
