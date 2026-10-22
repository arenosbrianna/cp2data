import React, { useEffect } from 'react';
import { css, cx } from '../css';
import { useApi, ShellInfo } from '../api';
import { useDss } from '../context';
import { PageState } from '../ui';

interface TrackingData {
  shell: ShellInfo; postLabel: string;
  kpis: { label: string; base: string; post: string; delta: string; good: boolean | null }[];
  waste: { weeks: { wk: string; kg: number; live: boolean; title: string }[]; baseline: number; yMax: number; goLiveIdx: number; goLiveLabel: string | null };
  adoption: { total: number; counts: { applied: number; modified: number; dismissed: number }; reasons: string[] };
  log: { date: string; type: string; rec: string; decision: 'applied' | 'modified' | 'dismissed'; reason: string; by: string; outcome: string }[];
  acc: { wk: string; v: string }[]; accNote: string; decisionsEnabled: boolean;
}

const color = (good: boolean | null) => (good === true ? '#047857' : good === false ? '#B91C1C' : '#4B5563');

export const TrackingPage: React.FC = () => {
  const { data, error, loading, reload } = useApi<TrackingData>('/api/tracking');
  const { setShell, tick } = useDss();
  useEffect(() => { if (data) setShell(data.shell); }, [data, setShell]);
  useEffect(() => { if (tick) reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <PageState loading={loading && !data} error={error && !data ? error : null} reload={reload}>
      {data && (
        <>
          <div style={css('display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 16px')}>
            <div style={css('display: flex; flex-direction: column; gap: 6px')}>
              <h1 style={css('margin: 0; font-size: 36px; font-weight: 800; letter-spacing: -0.02em')}>Tracking and baseline comparison</h1>
            </div>
            <button className="btn no-print" type="button" onClick={() => window.print()}>Export comparison (PDF)</button>
          </div>

          <section style={css('display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px')}>
            {data.kpis.map((k) => (
              <div key={k.label} className="card" style={css('padding: 18px 20px; display: flex; flex-direction: column; gap: 10px')}>
                <div style={css('font-size: 12px; font-weight: 700; color: #4B5563; letter-spacing: .05em')}>{k.label}</div>
                <div style={css('display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px')}>
                  <div><div style={css('font-size: 11px; color: #4B5563; font-weight: 700')}>BASELINE</div><div className="mono" style={css('font-size: 20px; color: #4B5563')}>{k.base}</div></div>
                  <div><div style={css('font-size: 11px; color: #1E3A8A; font-weight: 700')}>{data.postLabel}</div><div className="mono" style={css('font-size: 20px; font-weight: 600')}>{k.post}</div></div>
                </div>
                <div style={cx('font-size: 13px; font-weight: 700', { color: color(k.good) })}>{k.delta}</div>
              </div>
            ))}
          </section>

          <div style={css('display: flex; flex-wrap: wrap; gap: 20px; align-items: stretch')}>
            <WasteChart w={data.waste} />
            <section className="card" style={css('flex: 1 1 300px; min-width: 0; padding: 22px; display: flex; flex-direction: column; gap: 12px')}>
              <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>Recommendation adoption{data.adoption.total ? ` · ${data.adoption.total} decision${data.adoption.total === 1 ? '' : 's'}` : ''}</h2>
              {data.adoption.total === 0 ? (
                <p style={css('margin: 0; font-size: 14px; color: #4B5563; line-height: 1.55')}>No decision has been logged yet. Apply, modify or dismiss a recommendation on Overview or Risk alerts and it appears here.{!data.decisionsEnabled ? ' The decision log table is not created in this database yet (npm run db:migrate).' : ''}</p>
              ) : (
                <>
                  <div style={css('display: flex; height: 14px; border-radius: 999px; overflow: hidden')}>
                    <div style={{ width: `${(data.adoption.counts.applied / data.adoption.total) * 100}%`, background: '#1E3A8A' }} />
                    <div style={{ width: `${(data.adoption.counts.modified / data.adoption.total) * 100}%`, background: '#60A5FA' }} />
                    <div style={{ width: `${(data.adoption.counts.dismissed / data.adoption.total) * 100}%`, background: '#F59E0B' }} />
                  </div>
                  <div style={css('display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 12px; font-size: 14px')}>
                    {([['Applied', '#1E3A8A', data.adoption.counts.applied], ['Modified', '#60A5FA', data.adoption.counts.modified], ['Dismissed', '#F59E0B', data.adoption.counts.dismissed]] as const).map(([name, c, n]) => (
                      <React.Fragment key={name}>
                        <span style={css('display: inline-flex; gap: 8px; align-items: center')}><span style={{ width: 10, height: 10, background: c, borderRadius: 2 }} />{name}</span>
                        <span className="mono">{n} ({Math.round((n / data.adoption.total) * 100)}%)</span>
                      </React.Fragment>
                    ))}
                  </div>
                  <div style={css('border-top: 1px solid #EDEBE6; padding-top: 10px; font-size: 13px; font-weight: 700; color: #374151')}>Top dismissal reasons</div>
                  <div style={css('font-size: 13px; color: #374151; line-height: 1.6')}>{data.adoption.reasons.length ? data.adoption.reasons.join(' · ') : 'No dismissals yet.'}</div>
                </>
              )}
            </section>
          </div>

          <section className="card" style={css('padding: 0; overflow: hidden')}>
            <div style={css('padding: 20px 22px 12px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px')}>
              <div><h2 style={css('margin: 0; font-size: 20px; font-weight: 800')}>Recommendation log</h2><p style={css('margin: 4px 0 0; font-size: 13px; color: #4B5563')}>fact_recommendation · outcome measured on the next ETL cycle</p></div>
            </div>
            <div style={css('overflow-x: auto')}>
              <table style={css('width: 100%; min-width: 1000px')}>
                <thead><tr>{['Date', 'Type', 'Recommendation', 'Decision', 'By', 'Measured outcome'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
                <tbody>
                  {data.log.map((r, i) => (
                    <tr key={i}>
                      <td className="td" style={css('white-space: nowrap')}>{r.date}</td>
                      <td className="td" style={css('white-space: nowrap; color: #374151')}>{r.type}</td>
                      <td className="td" style={css('font-weight: 600')}>{r.rec}</td>
                      <td className="td" style={css('white-space: nowrap')}>
                        {r.decision === 'applied' && <span style={css('font-size: 12px; font-weight: 800; padding: 4px 8px; border-radius: 6px; background: #DBEAFE; color: #1E3A8A')}>✓ Applied</span>}
                        {r.decision === 'modified' && <span style={css('font-size: 12px; font-weight: 800; padding: 4px 8px; border-radius: 6px; background: #E0F2FE; color: #075985')}>✎ Modified</span>}
                        {r.decision === 'dismissed' && <span style={css('font-size: 12px; font-weight: 800; padding: 4px 8px; border-radius: 6px; background: #FEF3C7; color: #92400E')}>✕ Dismissed</span>}
                        {r.reason && <div style={css('font-size: 12px; color: #4B5563; margin-top: 6px; white-space: normal')}>{r.reason}</div>}
                      </td>
                      <td className="td" style={css('white-space: nowrap')}>{r.by}</td>
                      <td className="td">{r.outcome}</td>
                    </tr>
                  ))}
                  {data.log.length === 0 && <tr><td className="td" colSpan={6} style={css('color: #4B5563')}>No decision has been logged yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card" style={css('padding: 22px; display: flex; flex-direction: column; gap: 12px')}>
            <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>Forecast accuracy, last 4 weeks scored</h2>
            <p style={css('margin: 0; font-size: 13px; color: #4B5563')}>{data.accNote}</p>
            {data.acc.length ? (
              <div style={css('display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px')}>
                {data.acc.map((a) => <div key={a.wk} style={css('background: #F8FAFC; border-radius: 10px; padding: 12px 14px')}><div style={css('font-size: 12px; color: #4B5563; font-weight: 700')}>{a.wk}</div><div className="mono" style={css('font-size: 22px; font-weight: 600')}>{a.v}</div></div>)}
              </div>
            ) : <p style={css('margin: 0; font-size: 14px; color: #4B5563')}>No evaluation run is stored.</p>}
          </section>
        </>
      )}
    </PageState>
  );
};

const WasteChart: React.FC<{ w: TrackingData['waste'] }> = ({ w }) => {
  const H = 200;
  const n = w.weeks.length;
  return (
    <section className="card" style={css('flex: 999 1 520px; min-width: 0; padding: 22px; display: flex; flex-direction: column; gap: 14px')}>
      <div><h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>Weekly food waste, kg</h2><p style={css('margin: 4px 0 0; font-size: 13px; color: #4B5563')}>Weight-based ingredients, 7-day blocks ending on the last warehouse day · dashed line = baseline {w.baseline.toFixed(1)} kg</p></div>
      <div style={css('overflow-x: auto')}>
        <div style={css('min-width: 560px; display: grid; grid-template-columns: 36px minmax(0, 1fr); gap: 8px')}>
          <div className="mono" style={css('height: 200px; display: flex; flex-direction: column; justify-content: space-between; font-size: 12px; color: #4B5563; text-align: right')}><span>{w.yMax}</span><span>{w.yMax / 2}</span><span>0</span></div>
          <div style={css('position: relative; height: 200px; border-bottom: 1px solid #CBD5E1')}>
            <div style={{ position: 'absolute', left: 0, right: 0, bottom: Math.round((w.baseline / w.yMax) * H), borderTop: '1.5px dashed #4B5563' }} />
            {w.goLiveIdx >= 0 && (
              <>
                <div style={{ position: 'absolute', left: `${(w.goLiveIdx / n) * 100}%`, top: 0, bottom: 0, borderLeft: '2px solid #1E3A8A' }} />
                <div style={{ position: 'absolute', left: `calc(${(w.goLiveIdx / n) * 100}% + 6px)`, top: 0, fontSize: 12, fontWeight: 700, color: '#1E3A8A' }}>Go-live {w.goLiveLabel}</div>
              </>
            )}
            <div style={css('position: absolute; inset: 0; display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 10px; align-items: end')}>
              {w.weeks.map((x) => <div key={x.wk} title={x.title} style={{ height: Math.round((x.kg / w.yMax) * H), borderRadius: '4px 4px 0 0', background: x.live ? '#1E3A8A' : '#94A3B8' }} />)}
            </div>
          </div>
          <span />
          <div style={css('display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 10px; font-size: 11px; color: #4B5563; text-align: center')}>{w.weeks.map((x) => <span key={x.wk}>{x.wk}</span>)}</div>
        </div>
      </div>
    </section>
  );
};
