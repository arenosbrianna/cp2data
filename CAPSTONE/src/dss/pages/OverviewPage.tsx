import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { css, cx } from '../css';
import { useApi, ShellInfo } from '../api';
import { useDss, DecisionTarget, Status } from '../context';
import { PageState, ReasonModal, SeverityChip, DISMISS_REASONS } from '../ui';
import { UploadModal, WasteModal } from '../Modals';

interface QueueItem extends DecisionTarget {
  severity: 'crit' | 'warn' | 'info'; type: string; evidence: string; impact: string; source: string; cta: string; done: string; status: Status; reason: string | null;
}
interface Kpi { label: string; value: string; unit: string; base: string; delta: string; good: boolean | null }
interface OverviewData {
  shell: ShellInfo; dateLong: string; count: number; open: number; kpis: Kpi[]; kpiNote: string; queue: QueueItem[];
  yesterday: { label: string; revenue: string; receipts: string; avg: string; tops: { rank: string; name: string; qty: string; rev: string }[] };
  rev: { yMax: number; bars: { date: string; day: string; v: number; kind: 'actual' | 'forecast' }[] };
  planCard: { spend: string; pct: number; note: string } | null; revenueNote: string; hasForecast: boolean;
}

const peso = (v: number) => `₱${Math.round(v).toLocaleString('en-US')}`;
const axis = (v: number) => `₱${+(v / 1000).toFixed(1)}k`;
const deltaColor = (good: boolean | null) => (good === true ? '#047857' : good === false ? '#B91C1C' : '#4B5563');

export const OverviewPage: React.FC = () => {
  const { data, error, loading, reload } = useApi<OverviewData>('/api/overview');
  const { setShell, decide, statusOf, tick, toast, refreshAll } = useDss();
  const [modal, setModal] = useState<null | { kind: 'dismiss' | 'modify'; item: QueueItem }>(null);
  const [upload, setUpload] = useState(false);
  const [waste, setWaste] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (data) setShell(data.shell); }, [data, setShell]);
  useEffect(() => { if (tick) reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const queue = (data?.queue ?? []).map((q) => ({ ...q, status: statusOf(q.key, q.status) }));
  const handled = queue.filter((q) => q.status !== 'open').length;

  return (
    <PageState loading={loading && !data} error={error && !data ? error : null} reload={reload}>
      {data && (
        <>
          <div style={css('display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 16px')}>
            <div style={css('display: flex; flex-direction: column; gap: 6px')}>
              <div style={css('font-size: 14px; font-weight: 700; color: #1E3A8A')}>{data.dateLong}</div>
              <h1 style={css('margin: 0; font-size: 36px; font-weight: 800; letter-spacing: -0.02em')}>Today's decisions</h1>            </div>
            <div style={css('display: flex; gap: 10px; flex-wrap: wrap')}>
              <button className="btn" type="button" onClick={() => setUpload(true)}>Upload Loyverse CSV</button>
              <button className="btn" type="button" onClick={() => setWaste(true)}>Log waste</button>
              <button className="btn pri" type="button" disabled={busy} onClick={async () => { setBusy(true); await refreshAll(); setBusy(false); toast('Data refreshed from the warehouse'); }}>Refresh data</button>
            </div>
          </div>

          <section aria-label="Baseline KPIs" style={css('display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px')}>
            {data.kpis.map((k) => (
              <div key={k.label} className="card" style={css('padding: 18px 20px; display: flex; flex-direction: column; gap: 8px')}>
                <div style={css('font-size: 12px; font-weight: 700; color: #4B5563; letter-spacing: .05em')}>{k.label}</div>
                <div style={css('display: flex; align-items: baseline; gap: 6px')}><span className="mono" style={css('font-size: 32px; font-weight: 600')}>{k.value}</span><span style={css('font-size: 14px; color: #4B5563')}>{k.unit}</span></div>
                <div style={css('font-size: 13px; color: #374151')}>Baseline <span className="mono">{k.base}</span></div>
                <div style={cx('font-size: 13px; font-weight: 700', { color: deltaColor(k.good) })}>{k.delta}</div>
              </div>
            ))}
          </section>
          <div style={css('font-size: 12px; color: #4B5563; margin-top: -12px')}>{data.kpiNote}</div>

          <div style={css('display: flex; flex-wrap: wrap; gap: 20px; align-items: flex-start')}>
            <section className="card" style={css('flex: 999 1 520px; min-width: 0; padding: 22px; display: flex; flex-direction: column; gap: 4px')}>
              <div style={css('display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 12px; flex-wrap: wrap')}>
                <h2 style={css('margin: 0; font-size: 20px; font-weight: 800')}>Decision queue</h2>
                <span style={css('font-size: 13px; color: #4B5563')}>{handled} of {queue.length} handled · each choice is logged to Tracking</span>
              </div>
              {queue.length === 0 && <p style={css('font-size: 14px; color: #4B5563; padding: 12px 0')}>No decisions are waiting. There are no stockout, spoilage or excess alerts and no stored purchase plan.</p>}
              {queue.map((q) => (
                <article key={q.key} style={css('border-top: 1px solid #EDEBE6; padding: 16px 0; display: grid; grid-template-columns: 112px minmax(0, 1fr); gap: 16px')}>
                  <div style={css('display: flex; flex-direction: column; gap: 6px')}>
                    <SeverityChip severity={q.severity} />
                    <span style={css('font-size: 12px; font-weight: 600; color: #4B5563')}>{q.type}</span>
                  </div>
                  <div style={css('display: flex; flex-direction: column; gap: 8px')}>
                    <h3 style={css('margin: 0; font-size: 16px; font-weight: 700; line-height: 1.4')}>{q.title}</h3>
                    <p style={css('margin: 0; font-size: 14px; line-height: 1.55; color: #374151')}>{q.evidence}</p>
                    <div style={css('display: flex; flex-wrap: wrap; gap: 8px; align-items: center')}>
                      <span className="mono" style={css('font-size: 13px; font-weight: 600; background: #F1F5F9; border-radius: 6px; padding: 4px 8px')}>{q.impact}</span>
                      <span style={css('font-size: 12px; color: #4B5563')}>{q.source}</span>
                    </div>
                    {q.status === 'open' ? (
                      <div style={css('display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px')}>
                        <button className="btn pri" type="button" onClick={() => decide(q, 'applied')}>{q.cta}</button>
                        <button className="btn" type="button" onClick={() => setModal({ kind: 'modify', item: q })}>Modify</button>
                        <button className="btn" type="button" onClick={() => setModal({ kind: 'dismiss', item: q })}>Dismiss…</button>
                      </div>
                    ) : (
                      <div style={css('font-size: 13px; font-weight: 700; color: #1E3A8A; background: #EEF2FF; border-radius: 8px; padding: 8px 12px; align-self: flex-start')}>
                        {q.status === 'applied' ? `✓ ${q.done}` : q.status === 'modified' ? `✎ Modified · logged${q.reason ? `: ${q.reason}` : ''}` : `✕ Dismissed · reason recorded${q.reason ? `: ${q.reason}` : ''}`}
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </section>

            <div style={css('flex: 1 1 320px; min-width: 0; display: flex; flex-direction: column; gap: 20px')}>
              <section className="card" style={css('padding: 22px; display: flex; flex-direction: column; gap: 14px')}>
                <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>{data.yesterday.label}</h2>
                <div style={css('display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px')}>
                  <div><div style={css('font-size: 12px; color: #4B5563; font-weight: 600')}>Revenue</div><div className="mono" style={css('font-size: 18px; font-weight: 600')}>{data.yesterday.revenue}</div></div>
                  <div><div style={css('font-size: 12px; color: #4B5563; font-weight: 600')}>Items sold</div><div className="mono" style={css('font-size: 18px; font-weight: 600')}>{data.yesterday.receipts}</div></div>
                  <div><div style={css('font-size: 12px; color: #4B5563; font-weight: 600')}>Avg per item</div><div className="mono" style={css('font-size: 18px; font-weight: 600')}>{data.yesterday.avg}</div></div>
                </div>
                <div style={css('font-size: 13px; font-weight: 700; color: #374151; margin-top: 4px')}>Top items by revenue</div>
                {data.yesterday.tops.map((t) => (
                  <div key={t.rank} style={css('display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; gap: 10px; align-items: baseline; border-top: 1px solid #EDEBE6; padding-top: 10px')}>
                    <span className="mono" style={css('font-size: 13px; color: #1E3A8A; font-weight: 600')}>{t.rank}</span>
                    <div><div style={css('font-size: 14px; font-weight: 700')}>{t.name}</div><div style={css('font-size: 12px; color: #4B5563')}>{t.qty}</div></div>
                    <span className="mono" style={css('font-size: 14px; font-weight: 600')}>{t.rev}</span>
                  </div>
                ))}
              </section>

              <section className="card" style={css('padding: 22px; display: flex; flex-direction: column; gap: 10px')}>
                <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>This week's order plan</h2>
                {data.planCard ? (
                  <>
                    <div style={css('display: flex; justify-content: space-between; font-size: 14px')}><span style={css('color: #374151')}>Recommended spend</span><span className="mono" style={css('font-weight: 600')}>{data.planCard.spend}</span></div>
                    <div style={css('height: 10px; background: #E5E7EB; border-radius: 999px; overflow: hidden')}><div style={cx('height: 100%; background: #1E3A8A', { width: `${Math.min(100, data.planCard.pct)}%` })} /></div>
                    <div style={css('font-size: 12px; color: #4B5563')}>{data.planCard.note}</div>
                  </>
                ) : <div style={css('font-size: 13px; color: #4B5563')}>No optimizer run is stored for the current forecast.</div>}
                <Link className="btn" to="/purchasing" style={css('align-self: flex-start; margin-top: 6px')}>Open purchasing list →</Link>
              </section>
            </div>
          </div>

          <RevenueChart data={data} />
        </>
      )}
      {modal?.kind === 'dismiss' && (
        <ReasonModal title="Dismiss recommendation" label="Why are you dismissing it?" confirm="Dismiss" presets={DISMISS_REASONS} onClose={() => setModal(null)}
          onSubmit={async (reason) => { if (await decide(modal.item, 'dismissed', reason)) setModal(null); }} />
      )}
      {modal?.kind === 'modify' && (
        <ReasonModal title="Modify recommendation" label="What did you change (for example the quantity)?" confirm="Log change" onClose={() => setModal(null)}
          onSubmit={async (reason) => { if (await decide(modal.item, 'modified', reason)) setModal(null); }} />
      )}
      {upload && <UploadModal onClose={() => setUpload(false)} />}
      {waste && <WasteModal onClose={() => setWaste(false)} />}
    </PageState>
  );
};

const RevenueChart: React.FC<{ data: OverviewData }> = ({ data }) => {
  const { yMax, bars } = data.rev;
  const labels = [yMax, (yMax * 2) / 3, yMax / 3, 0];
  return (
    <section className="card" style={css('padding: 22px; display: flex; flex-direction: column; gap: 14px')}>
      <div style={css('display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px')}>
        <div>
          <h2 style={css('margin: 0; font-size: 20px; font-weight: 800')}>Daily revenue: last 7 days and next 7 days</h2>
          <p style={css('margin: 4px 0 0; font-size: 13px; color: #4B5563')}>{data.revenueNote}</p>
        </div>
        <div style={css('display: flex; gap: 16px; font-size: 13px; color: #374151; align-items: center')}>
          <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 12px; height: 12px; background: #1E3A8A; border-radius: 3px')} />Actual</span>
          <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 12px; height: 12px; background: #C7D2FE; border: 1px dashed #1E3A8A; border-radius: 3px')} />Forecast</span>
        </div>
      </div>
      <div style={css('overflow-x: auto')}>
        <div style={css('min-width: 720px; display: grid; grid-template-columns: 56px minmax(0, 1fr); gap: 8px')}>
          <div className="mono" style={css('display: flex; flex-direction: column; justify-content: space-between; height: 220px; font-size: 12px; color: #4B5563; text-align: right')}>
            {labels.map((l, i) => <span key={i}>{l === 0 ? '₱0' : axis(l)}</span>)}
          </div>
          <div style={css('display: flex; flex-direction: column; gap: 8px')}>
            <div style={css('height: 220px; display: grid; grid-template-columns: repeat(14, minmax(0, 1fr)); gap: 8px; align-items: end; border-bottom: 1px solid #CBD5E1; background: linear-gradient(#EDEBE6 1px, transparent 1px) 0 0 / 100% 73.33px')}>
              {Array.from({ length: 14 }).map((_, i) => {
                const r = bars[i];
                if (!r) return <div key={i} />;
                const h = Math.round((r.v / yMax) * 220);
                const title = `${r.day}: ${peso(r.v)}${r.kind === 'forecast' ? ' (forecast)' : ''}`;
                return (
                  <div key={i} style={css('display: flex; flex-direction: column; justify-content: flex-end; height: 100%')}>
                    {r.kind === 'actual'
                      ? <div title={title} style={cx('background: #1E3A8A; border-radius: 5px 5px 0 0', { height: h })} />
                      : <div title={title} style={cx('background: #C7D2FE; border: 1px dashed #1E3A8A; border-bottom: 0; box-sizing: border-box; border-radius: 5px 5px 0 0', { height: h })} />}
                  </div>
                );
              })}
            </div>
            <div style={css('display: grid; grid-template-columns: repeat(14, minmax(0, 1fr)); gap: 8px; font-size: 11px; color: #4B5563; text-align: center')}>
              {Array.from({ length: 14 }).map((_, i) => <span key={i}>{bars[i]?.day ?? ''}</span>)}
            </div>
          </div>
        </div>
      </div>
      {!data.hasForecast && <p style={css('margin: 0; font-size: 13px; color: #92400E')}>▲ No forecast run is stored, so only the last 7 days are shown.</p>}
    </section>
  );
};
