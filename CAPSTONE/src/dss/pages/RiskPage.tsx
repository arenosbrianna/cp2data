import React, { useEffect, useState } from 'react';
import { css, cx } from '../css';
import { useApi, ShellInfo, fmt } from '../api';
import { useDss, DecisionTarget, Status } from '../context';
import { PageState } from '../ui';

interface Cell { kind: 'red' | 'amber' | 'later' | 'alive' | 'none'; text: string }
interface Batch {
  key: string; ingredientId: number; name: string; rcv: string; life: string; cells: Cell[]; onhand: string; use: string; risk: string; riskColor: string; peso: string;
  alert: boolean; items: string; cta: string; note: string; status: Status | null; qty: number; impact: number;
}
interface Stockout {
  warn: boolean; key: string; ingredientId: number; name: string; status: Status; headline: string; detail: { pre: string; order: string; post: string }; orderBase: number; unit: string; dp: number;
  chart: { title: string; yMax: number; start: number; demand: number[]; noOrder: number[]; withOrder: number[]; rop: number; days: string[]; leadDays: number; hasOrder: boolean };
}
interface RiskData {
  shell: ShellInfo; empty: boolean; message?: string;
  tiles: { spoilage: { count: number; sub: string }; stockout: { count: number; sub: string }; excess: { count: number; sub: string } };
  inventory: { name: string; onHand: string; reorder: string; cover: string; status: string; statusText: string }[];
  dayCols: string[]; batches: Batch[]; stockout: Stockout | null; watch: string[]; spoilNote: string | null;
  gauge: { value: string; share: number; shareText: string; total: string; scale: number; key: string; status: Status; flaggedCount: number; zone: string };
  excess: { name: string; label: string; stockW: number; fcW: number; flag: boolean; note: string }[];
  heat: { name: string; cells: { text: string; bg: string; fg: string; title: string }[] }[]; pattern: string; waste: { from: string; to: string };
}

const WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export const RiskPage: React.FC = () => {
  const { data, error, loading, reload } = useApi<RiskData>('/api/risk');
  const { setShell, decide, statusOf, tick } = useDss();
  const [showAll, setShowAll] = useState(false);
  const [showStock, setShowStock] = useState(false);
  useEffect(() => { if (data) setShell(data.shell); }, [data, setShell]);
  useEffect(() => { if (tick) reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = (key: string, status: Status | null, type: string, typeKey: string, title: string, extra: Partial<DecisionTarget> = {}) =>
    decide({ key, type, typeKey, title, ...extra }, 'applied');

  return (
    <PageState loading={loading && !data} error={error && !data ? error : null} reload={reload} empty={data?.empty ? data.message ?? 'No data.' : null}>
      {data && !data.empty && (
        <>
          <div style={css('display: flex; flex-direction: column; gap: 6px')}>
            <div style={css('font-size: 14px; font-weight: 700; color: #1E3A8A')}>Prescriptive alerts · recomputed on every refresh against today's date</div>
            <h1 style={css('margin: 0; font-size: 36px; font-weight: 800; letter-spacing: -0.02em')}>Risk alerts</h1>
            <p style={css('margin: 0; font-size: 15px; color: #4B5563; max-width: 820px')}>Three risk states from §3.4.2: <b>expiration</b> (stock that will spoil before it's used), <b>under-ordering</b> (stock that runs out inside the supplier lead time), and <b>over-ordering</b> (cash tied up above forecast). Only perishable raw materials are in scope.</p>
          </div>

          <div style={css('display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px')}>
            {[
              { href: '#spoil', n: data.tiles.spoilage.count, color: '#B91C1C', title: 'Spoilage alerts', sub: data.tiles.spoilage.sub },
              { href: '#stockout', n: data.tiles.stockout.count, color: '#B91C1C', title: 'Stockout warning', sub: data.tiles.stockout.sub },
              { href: '#excess', n: data.tiles.excess.count, color: '#B45309', title: 'Excess stock', sub: data.tiles.excess.sub },
            ].map((t) => (
              <a key={t.href} href={t.href} className="card" style={css('padding: 16px 18px; text-decoration: none; color: #111827; display: flex; gap: 14px; align-items: center')}>
                <span className="mono" style={cx('font-size: 30px; font-weight: 600', { color: t.color })}>{t.n}</span>
                <span style={css('font-size: 14px; font-weight: 700; line-height: 1.35')}>{t.title}<br /><span style={css('font-weight: 500; color: #4B5563')}>{t.sub}</span></span>
              </a>
            ))}
          </div>

          <section id="spoil" className="card" style={css('padding: 0; overflow: hidden')}>
            <div style={css('padding: 22px 22px 14px; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px')}>
              <div>
                <h2 style={css('margin: 0; font-size: 20px; font-weight: 800')}>Spoilage alert matrix</h2>
                <p style={css('margin: 4px 0 0; font-size: 13px; color: #4B5563')}>Expiry = last usable day of the batch. At risk = on hand − forecast use before expiry. Red ≤ 1 day, amber 2–3 days. Alerts are raised for batches expiring within 3 days.{data.spoilNote ? ` ${data.spoilNote}` : ''}</p>
              </div>
              <div style={css('display: flex; gap: 14px; font-size: 12px; color: #374151; align-items: center; flex-wrap: wrap')}>
                <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 14px; height: 14px; border-radius: 3px; background: #DC2626')} />Expires ≤ 1 day</span>
                <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 14px; height: 14px; border-radius: 3px; background: #F59E0B')} />2–3 days</span>
                <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 14px; height: 14px; border-radius: 3px; background: #E0E7FF')} />Usable</span>
              </div>
            </div>
            <div style={css('overflow-x: auto')}>
              <table className="tbl-risk" style={css('width: 100%; min-width: 1120px')}>
                <thead><tr>
                  <th className="th">Ingredient · batch</th>
                  {data.dayCols.map((d) => <th key={d} className="th" style={css('text-align: center')}>{d}</th>)}
                  <th className="th">On hand</th><th className="th">Use before expiry</th><th className="th">At risk</th><th className="th">Action</th>
                </tr></thead>
                <tbody>
                  {(showAll ? data.batches : data.batches.slice(0, 12)).map((b, row) => {
                    const status = b.alert ? statusOf(b.key, b.status ?? 'open') : null;
                    return (
                      <tr key={`${b.key}-${row}`}>
                        <td className="td"><div style={css('font-weight: 700')}>{b.name}</div><div style={css('font-size: 12px; color: #4B5563')}>Rcvd {b.rcv} · {b.life}</div></td>
                        {b.cells.map((c, i) => (
                          <td key={i} className="td" style={css('padding: 6px 4px; min-width: 64px')}>
                            {c.kind === 'red' && <div className="cell" style={css('background: #DC2626; color: #FFFFFF')}>{c.text}</div>}
                            {c.kind === 'amber' && <div className="cell" style={css('background: #F59E0B; color: #1F2937')}>{c.text}</div>}
                            {c.kind === 'later' && <div className="cell" style={css('background: #C7D2FE; color: #1E3A8A')}>{c.text}</div>}
                            {c.kind === 'alive' && <div className="cell" style={css('background: #E0E7FF')} />}
                          </td>
                        ))}
                        <td className="td mono">{b.onhand}</td>
                        <td className="td mono">{b.use}</td>
                        <td className="td"><span className="mono" style={cx('font-weight: 600', { color: b.riskColor })}>{b.risk}</span><div style={css('font-size: 12px; color: #4B5563')}>{b.peso}</div></td>
                        <td className="td" style={css('white-space: normal; min-width: 220px')}>
                          {b.alert ? (
                            <div style={css('display: flex; flex-direction: column; gap: 6px')}>
                              {b.items && <span style={css('font-size: 12px; color: #374151')}>Promote: {b.items}</span>}
                              {status === 'open' || status === null
                                ? <button className="btn pri sm" type="button" style={css('align-self: flex-start')} onClick={() => act(b.key, status, 'Spoilage', 'spoilage', `${b.cta}: ${b.name}, ${b.risk} at risk`, { ingredientId: b.ingredientId, qty: b.qty, pesoImpact: b.impact })}>{b.cta}</button>
                                : <span style={css('font-size: 13px; font-weight: 700; color: #1E3A8A')}>{status === 'applied' ? '✓ Logged' : status === 'modified' ? '✎ Modified' : '✕ Dismissed'}</span>}
                            </div>
                          ) : <span style={css('font-size: 13px; color: #4B5563')}>{b.note}</span>}
                        </td>
                      </tr>
                    );
                  })}
                  {data.batches.length === 0 && <tr><td className="td" colSpan={13} style={css('white-space: normal; color: #4B5563')}>No batch expires within the next 7 days and no leftover is projected.</td></tr>}
                </tbody>
              </table>
            </div>
            {data.batches.length > 12 && <div style={css('padding: 12px 22px 18px')}><button type="button" className="btn sm" onClick={() => setShowAll((v) => !v)}>{showAll ? 'Show fewer batches' : `Show all ${data.batches.length} batches`}</button></div>}
          </section>

          <section className="card" style={css('padding: 0; overflow: hidden')}>
            <div style={css('padding: 22px 22px 14px')}>
              <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>Inventory status</h2>
              <p style={css('margin: 4px 0 0; font-size: 13px; color: #4B5563')}>Stock against reorder level, with days of cover at the 7-day forecast rate. Lowest cover first.</p>
            </div>
            <div style={css('overflow-x: auto')}>
              <table style={css('width: 100%; min-width: 640px')}>
                <thead><tr>{['Ingredient', 'On hand', 'Reorder level', 'Days of cover', 'Status'].map((h) => <th key={h} className="th">{h}</th>)}</tr></thead>
                <tbody>
                  {(showStock ? data.inventory : data.inventory.slice(0, 8)).map((r) => (
                    <tr key={r.name}>
                      <td className="td" style={css('font-weight: 700')}>{r.name}</td>
                      <td className="td mono">{r.onHand}</td>
                      <td className="td mono">{r.reorder}</td>
                      <td className="td mono">{r.cover}</td>
                      <td className="td" style={cx('font-weight: 700; white-space: nowrap', { color: r.status === 'runs out' ? '#B91C1C' : r.status === 'ok' ? '#047857' : '#92400E' })}>{r.statusText}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.inventory.length > 8 && <div style={css('padding: 12px 22px 18px')}><button type="button" className="btn sm" onClick={() => setShowStock((v) => !v)}>{showStock ? 'Show fewer ingredients' : `Show all ${data.inventory.length} ingredients`}</button></div>}
          </section>

          <section id="stockout" className="card" style={css('padding: 22px; display: flex; flex-direction: column; gap: 16px')}>
            {data.stockout ? <Stockout s={data.stockout} watch={data.watch} /> : <p style={css('margin: 0; font-size: 14px; color: #4B5563')}>No ingredient has forecast demand, so no stockout projection is available.</p>}
          </section>

          <div style={css('display: flex; flex-wrap: wrap; gap: 20px; align-items: stretch')}>
            <section id="excess" className="card" style={css('flex: 1 1 420px; min-width: 0; padding: 22px; display: flex; flex-direction: column; gap: 14px')}>
              <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>Excess capital gauge</h2>
              <p style={css('margin: 0; font-size: 13px; color: #4B5563')}>Flags stock above 1.5× its 7-day forecast. Share of total on-hand value ({data.gauge.total}).</p>
              <Gauge g={data.gauge} />
              {data.excess.map((e) => (
                <div key={e.name} style={css('border-top: 1px solid #EDEBE6; padding-top: 12px; display: flex; flex-direction: column; gap: 6px')}>
                  <div style={css('display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap')}><span style={css('font-size: 14px; font-weight: 700')}>{e.name}</span><span className="mono" style={css('font-size: 13px')}>{e.label}</span></div>
                  <div style={css('position: relative; height: 12px; background: #F1F5F9; border-radius: 999px')}>
                    <div style={cx('position: absolute; left: 0; top: 0; height: 100%; border-radius: 999px', { width: `${e.stockW}%`, background: e.flag ? '#F59E0B' : '#93C5FD' })} />
                    <div style={cx('position: absolute; top: -3px; width: 2px; height: 18px; background: #111827', { left: `${e.fcW}%` })} />
                  </div>
                  <div style={css('font-size: 12px; color: #4B5563')}>{e.flag ? '▲ ' : ''}{e.note}</div>
                </div>
              ))}
              {(() => {
                const s = statusOf(data.gauge.key, data.gauge.status);
                return s === 'open'
                  ? <button className="btn" type="button" style={css('align-self: flex-start')} disabled={data.gauge.flaggedCount === 0} onClick={() => act(data.gauge.key, s, 'Excess capital', 'excess', `Freeze next order for ${data.gauge.flaggedCount} flagged items (${data.gauge.value} tied up)`, { pesoImpact: Number(data.gauge.value.replace(/[^\d]/g, '')) })}>Freeze next order for flagged items</button>
                  : <span style={css('font-size: 13px; font-weight: 700; color: #1E3A8A')}>{s === 'applied' ? '✓ Orders frozen for this cycle · logged' : s === 'modified' ? '✎ Modified · logged' : '✕ Dismissed · logged'}</span>;
              })()}
            </section>

            <section className="card" style={css('flex: 1 1 420px; min-width: 0; padding: 22px; display: flex; flex-direction: column; gap: 14px')}>
              <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>Where waste concentrates</h2>
              <p style={css('margin: 0; font-size: 13px; color: #4B5563')}>Average kg wasted by weekday, last 8 weeks ({data.waste.from} – {data.waste.to}, weight-based ingredients, fact_waste). Darker = more.</p>
              {data.heat.length ? (
                <div style={css('overflow-x: auto')}>
                  <div style={css('min-width: 420px; display: grid; grid-template-columns: 120px repeat(7, minmax(0, 1fr)); gap: 4px; font-size: 12px')}>
                    <span />
                    {WD.map((w) => <span key={w} style={css('text-align: center; color: #4B5563; font-weight: 700')}>{w}</span>)}
                    {data.heat.map((r) => (
                      <React.Fragment key={r.name}>
                        <span style={css('font-weight: 700; font-size: 13px; align-self: center')}>{r.name}</span>
                        {r.cells.map((c, i) => <div key={i} className="mono" title={c.title} style={cx('height: 34px; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 12px', { background: c.bg, color: c.fg })}>{c.text}</div>)}
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              ) : <p style={css('margin: 0; font-size: 14px; color: #4B5563')}>No weight-based waste in the last 8 weeks.</p>}
              <p style={css('margin: 0; font-size: 13px; color: #374151; line-height: 1.5')}><b>Pattern:</b> {data.pattern}</p>
            </section>
          </div>
        </>
      )}
    </PageState>
  );
};

const Stockout: React.FC<{ s: Stockout; watch: string[] }> = ({ s, watch }) => {
  const { decide, statusOf } = useDss();
  const status = statusOf(s.key, s.status);
  const c = s.chart;
  const W = 700, H = 240;
  const Y = (v: number) => H - (v / c.yMax) * H;
  const X = (i: number) => 50 + i * 100;
  const path = (vals: number[]) => `M0 ${Y(c.start).toFixed(1)} ${vals.map((v, i) => `L${X(i)} ${Y(v).toFixed(1)}`).join(' ')}`;
  const labels = [c.yMax, (c.yMax * 2) / 3, c.yMax / 3, 0];
  return (
    <>
      {s.warn ? (
        <div role="alert" style={css('background: #FEF2F2; border: 1px solid #FCA5A5; border-radius: 12px; padding: 16px 18px; display: flex; flex-wrap: wrap; gap: 14px; align-items: center; justify-content: space-between')}>
          <div style={css('display: flex; flex-direction: column; gap: 4px; max-width: 760px')}>
            <div style={css('font-size: 12px; font-weight: 800; color: #991B1B; letter-spacing: .05em')}>● STOCKOUT RISK WARNING</div>
            <div style={css('font-size: 16px; font-weight: 700')}>{s.headline}</div>
            <div style={css('font-size: 14px; color: #374151')}>{s.detail.pre}<b className="mono">{s.detail.order}</b>{s.detail.post}</div>
          </div>
          {status === 'open'
            ? <button className="btn pri" type="button" onClick={() => decide({ key: s.key, type: 'Stockout risk', typeKey: 'stockout', title: `Order ${s.detail.order} ${s.name}`, ingredientId: s.ingredientId, qty: s.orderBase }, 'applied')}>Add to purchase list</button>
            : <span style={css('font-size: 13px; font-weight: 700; color: #1E3A8A; background: #EEF2FF; border-radius: 8px; padding: 8px 12px')}>{status === 'applied' ? '✓ Added to purchase list · logged' : status === 'modified' ? '✎ Modified · logged' : '✕ Dismissed · logged'}</span>}
        </div>
      ) : (
        <div role="status" style={css('background: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 12px; padding: 16px 18px; display: flex; flex-direction: column; gap: 4px')}>
          <div style={css('font-size: 12px; font-weight: 800; color: #1E3A8A; letter-spacing: .05em')}>◆ NO STOCKOUT WARNING</div>
          <div style={css('font-size: 16px; font-weight: 700')}>{s.headline}</div>
          <div style={css('font-size: 14px; color: #374151')}>{s.detail.post}</div>
        </div>
      )}
      {watch.length > 0 && <p style={css('margin: 0; font-size: 13px; color: #4B5563; line-height: 1.5')}><b>Below reorder level, not yet running out ({watch.length}):</b> {watch.join(', ')}.</p>}
      <div style={css('display: flex; justify-content: space-between; flex-wrap: wrap; gap: 10px')}>
        <h2 style={css('margin: 0; font-size: 18px; font-weight: 800')}>{c.title}</h2>
        <div style={css('display: flex; gap: 16px; font-size: 13px; color: #374151; flex-wrap: wrap')}>
          <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 12px; height: 12px; background: #CBD5E1; border-radius: 2px')} />Forecast demand</span>
          <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 18px; height: 0; border-top: 2.5px solid #1E3A8A')} />Stock with LP order</span>
          <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 18px; height: 0; border-top: 2.5px dashed #DC2626')} />Stock, no order</span>
          <span style={css('display: inline-flex; gap: 6px; align-items: center')}><span style={css('width: 18px; height: 0; border-top: 1.5px dashed #B45309')} />Reorder level</span>
        </div>
      </div>
      <div style={css('display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 8px')}>
        <div className="mono" style={css('height: 240px; display: flex; flex-direction: column; justify-content: space-between; font-size: 12px; color: #4B5563; text-align: right')}>
          {labels.map((l, i) => <span key={i}>{fmt(l, s.dp > 1 ? 2 : l < 10 ? 1 : 0)}</span>)}
        </div>
        <div style={css('position: relative; height: 240px; border-left: 1px solid #CBD5E1; border-bottom: 1px solid #CBD5E1')}>
          <div style={css('position: absolute; inset: 0; display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 24px; padding: 0 16px; align-items: end')}>
            {c.demand.map((d, i) => <div key={i} style={cx('background: #CBD5E1; border-radius: 4px 4px 0 0', { height: Math.round((d / c.yMax) * H) })} />)}
          </div>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`${s.name} stock without an order and with the optimizer order over the next 7 days`} style={css('position: absolute; inset: 0; width: 100%; height: 100%')}>
            <rect x="0" y="0" width={(c.leadDays + 1) * 100} height={H} fill="#FEF3C7" opacity="0.5" />
            <line x1="0" y1={Y(c.rop)} x2={W} y2={Y(c.rop)} stroke="#B45309" strokeWidth="1.5" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
            <path d={path(c.noOrder)} fill="none" stroke="#DC2626" strokeWidth="2.5" strokeDasharray="7 5" vectorEffect="non-scaling-stroke" />
            <path d={path(c.withOrder)} fill="none" stroke="#1E3A8A" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
          </svg>
          <div style={css('position: absolute; top: 6px; left: 8px; font-size: 12px; font-weight: 700; color: #92400E')}>Lead-time window</div>
        </div>
      </div>
      <div style={css('display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 8px')}>
        <span />
        <div style={css('display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 24px; padding: 0 16px; font-size: 12px; color: #4B5563; text-align: center')}>
          {c.days.map((d) => <span key={d}>{d}</span>)}
        </div>
      </div>
      {!c.hasOrder && <p style={css('margin: 0; font-size: 12px; color: #4B5563')}>The stored optimizer plan has no order for {s.name} this week, so both stock lines are the same.</p>}
    </>
  );
};

const Gauge: React.FC<{ g: RiskData['gauge'] }> = ({ g }) => {
  const frac = Math.min(1, g.share / g.scale);
  const theta = Math.PI * (1 - frac);
  const nx = 100 + 76 * Math.cos(theta), ny = 100 - 76 * Math.sin(theta);
  const zoneText = g.zone === 'act' ? 'red' : g.zone === 'review' ? 'amber' : 'blue';
  return (
    <div style={css('display: flex; gap: 20px; align-items: center; flex-wrap: wrap')}>
      <svg viewBox="0 0 200 116" width="200" height="116" role="img" aria-label={`${g.shareText} of inventory value is excess, in the ${zoneText} zone`}>
        <path d="M 16 100 A 84 84 0 0 1 184 100" fill="none" stroke="#E5E7EB" strokeWidth="18" />
        <path d="M 16 100 A 84 84 0 0 1 40.6 40.6" fill="none" stroke="#93C5FD" strokeWidth="18" />
        <path d="M 40.6 40.6 A 84 84 0 0 1 100 16" fill="none" stroke="#FCD34D" strokeWidth="18" />
        <path d="M 100 16 A 84 84 0 0 1 184 100" fill="none" stroke="#FCA5A5" strokeWidth="18" />
        <line x1="100" y1="100" x2={nx.toFixed(1)} y2={ny.toFixed(1)} stroke="#111827" strokeWidth="3" strokeLinecap="round" />
        <circle cx="100" cy="100" r="6" fill="#111827" />
      </svg>
      <div>
        <div className="mono" style={css('font-size: 30px; font-weight: 600')}>{g.value}</div>
        <div style={css('font-size: 14px; color: #374151')}>{g.shareText} of inventory value · {g.zone === 'act' ? '▲ act' : g.zone === 'review' ? '▲ review' : 'ok'}</div>
        <div style={css('font-size: 12px; color: #4B5563')}>Scale 0–{Math.round(g.scale * 100)}% · &lt;10% ok · 10–20% review · &gt;20% act</div>
      </div>
    </div>
  );
};
