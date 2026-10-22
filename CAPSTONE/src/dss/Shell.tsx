import React, { useEffect, useRef, useState } from 'react';
import { Navigate, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { css } from './css';
import { useDss } from './context';
import { getModel, ModelsInfo, setModel, withModel } from './api';

const links = [
  { to: '/', label: 'Overview', end: true },
  { to: '/forecasting', label: 'Demand forecasts' },
  { to: '/risk', label: 'Risk alerts', badge: true },
  { to: '/purchasing', label: 'Purchasing' },
  { to: '/tracking', label: 'Tracking' },
];


const SushiAvatar: React.FC = () => (
  <span aria-hidden="true" style={{ width: 40, height: 40, borderRadius: '50%', background: '#EEF2FF', border: '1px solid #DBE2F7', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flex: 'none' }}>
    <svg viewBox="0 0 64 40" width="35" height="22" focusable="false" style={{ display: 'block' }}>
      <path d="M8 22c0-5 8-8 24-8s24 3 24 8v8c0 5-8 8-24 8S8 35 8 30z" fill="#FFFFFF" stroke="#94A3B8" strokeWidth="1.6" />
      <path d="M12 33c5 3 12 4 20 4s15-1 20-4" stroke="#CBD5E1" strokeWidth="2" strokeLinecap="round" fill="none" />
      <path d="M3 21C6 8 20 3 32 3s26 5 29 18c-9 4-19 5-29 5S12 25 3 21z" fill="#F97316" />
      <path d="M3 21c9 4 19 5 29 5s20-1 29-5c-1 3-3 5-6 6-7 2-15 3-23 3s-16-1-23-3c-3-1-5-3-6-6z" fill="#DC5A12" />
      <path d="M12 15c6-4 14-5 21-4M24 21c8-3 17-3 26 0" stroke="#FFE0C2" strokeWidth="2.6" strokeLinecap="round" fill="none" />
      <rect x="27" y="1" width="10" height="38" rx="2.5" fill="#1B2540" />
      <path d="M30 5v30" stroke="#4B5D8A" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  </span>
);

/** The forecast model the whole app runs on: the champion by default, any model with a stored production forecast on request. */
const ModelPicker: React.FC = () => {
  const { shell, tick } = useDss();
  const [info, setInfo] = useState<ModelsInfo | null>(null);
  useEffect(() => {
    let live = true;
    fetch(withModel('/api/models'), { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((d) => { if (live && d && Array.isArray(d.models)) setInfo(d as ModelsInfo); }).catch(() => undefined);
    return () => { live = false; };
  }, [tick, shell?.model?.selected]);
  // a remembered choice that no longer exists is answered by the champion: forget it
  useEffect(() => { if (info && getModel() && info.selected !== getModel()) setModel(''); }, [info]);
  if (!info || info.models.length < 2) return null;
  const current = info.models.find((m) => m.model === info.selected);
  const chip = (text: string, color: string, bg: string) => (
    <span style={css(`font-size: 11px; font-weight: 800; color: ${color}; background: ${bg}; border-radius: 999px; padding: 2px 8px`)}>{text}</span>
  );
  return (
    <label style={css('display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; font-weight: 600; color: #374151; background: #F1F5F9; border-radius: 999px; padding: 6px 8px 6px 14px')}>
      <span>Forecast model</span>
      <select aria-label="Forecast model" value={info.selected ?? ''} onChange={(e) => setModel(e.target.value === info.champion ? '' : e.target.value)}
        style={css('font: inherit; font-size: 13px; font-weight: 700; color: #111827; background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 999px; padding: 5px 10px; cursor: pointer')}>
        {info.models.map((m) => <option key={m.model} value={m.model}>{m.label}{m.isChampion ? ' · champion' : ''}</option>)}
      </select>
      {current && current.wmape !== null && current.mase !== null && (
        <span style={css('font-size: 12px; font-weight: 500; color: #4B5563')} title="Weighted MAPE and MASE on the 367-day held-out test year">WMAPE {(current.wmape * 100).toFixed(1)}% · MASE {current.mase.toFixed(2)}</span>
      )}
      {current && !current.beatsNaive && chip('fails MASE < 1', '#92400E', '#FEF3C7')}
      {current && !current.hasPlans && chip('no purchase plans stored', '#991B1B', '#FEE2E2')}
    </label>
  );
};

export const Shell: React.FC = () => {
  const { shell, auth, justSignedOut, signOut, user } = useDss();
  const navigate = useNavigate();
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menu) return undefined;
    const onDown = (e: MouseEvent) => { if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(false); };
    document.addEventListener('mousedown', onDown); document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [menu]);
  useEffect(() => { document.title = 'Makisushi Decision Support System'; }, []);
  if (auth === 'checking') return <div className="dss-root" aria-busy="true" />;
  if (auth === 'out' && !justSignedOut) return <Navigate to="/login" replace />;
  if (auth === 'out') {
    return (
      <div className="dss-root" style={css('display: flex; align-items: center; justify-content: center; padding: 24px')}>
        <div className="card" style={css('padding: 32px; width: min(420px, 100%); display: flex; flex-direction: column; gap: 14px; align-items: flex-start')}>
          <img src="/makisushi-logo.png" alt="Makisushi Japanese Restaurant" style={css('height: 56px; width: 250px; object-fit: contain; object-position: left')} />
          <h1 style={css('font-size: 24px; font-weight: 800')}>You are signed out</h1>
          <p style={css('font-size: 14px; color: #4B5563; line-height: 1.55')}>Sign in again to open the Makisushi decision support system.</p>
          <button type="button" className="btn pri" onClick={() => navigate('/login')}>Sign in as Admin</button>
        </div>
      </div>
    );
  }
  return (
    <div className="dss-root">
      <header style={css('background: #FFFFFF; border-bottom: 1px solid #E7E5E0; padding: 12px 24px; display: flex; flex-wrap: wrap; align-items: center; gap: 16px; justify-content: space-between')}>
        <NavLink to="/" aria-label="Makisushi Japanese Restaurant, Overview" style={css('display: flex; align-items: center')}>
          <img src="/makisushi-logo.png" alt="Makisushi Japanese Restaurant" draggable={false} style={css('height: 56px; width: 250px; object-fit: contain; object-position: left')} />
        </NavLink>
        <div style={css('display: flex; align-items: center; gap: 10px; flex-wrap: wrap')}>
          <ModelPicker />
          <span style={css('display: inline-flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #374151; background: #F1F5F9; border-radius: 999px; padding: 8px 14px')}>
            <span style={css('width: 8px; height: 8px; border-radius: 50%; background: #2563EB')} />
            {shell ? `Data as of ${shell.asOfLabel} · Loyverse export` : 'Reading data…'}
            {shell && shell.staleDays > 2 && <span style={css('color: #92400E; font-weight: 700')}>▲ {shell.staleDays} days old</span>}
          </span>
          <div ref={menuRef} style={css('position: relative')}>
            <button type="button" aria-haspopup="menu" aria-expanded={menu} aria-label={`Account menu, signed in as ${shell?.user ?? 'Admin'}`} onClick={() => setMenu((v) => !v)}
              style={css('display: inline-flex; align-items: center; gap: 8px; background: none; border: 0; padding: 4px 6px; border-radius: 10px; cursor: pointer; font: inherit')}>
              <SushiAvatar />
              <span style={css('font-size: 14px; font-weight: 600; color: #374151')}>{user ?? shell?.user ?? 'Admin'}</span>
              <span aria-hidden="true" style={css('font-size: 10px; color: #4B5563')}>▾</span>
            </button>
            {menu && (
              <div role="menu" style={css('position: absolute; right: 0; top: 46px; z-index: 50; width: 208px; background: #FFFFFF; border: 1px solid #E7E5E0; border-radius: 12px; padding: 8px; box-shadow: 0 12px 24px -8px rgba(15, 23, 42, .2)')}>
                <div style={css('padding: 8px 10px; font-size: 12px; color: #4B5563; border-bottom: 1px solid #EDEBE6')}>Signed in as <strong style={css('color: #111827')}>{shell?.user ?? 'Admin'}</strong></div>
                <button type="button" role="menuitem" onClick={() => { setMenu(false); void signOut(); }}
                  style={css('width: 100%; text-align: left; margin-top: 6px; padding: 10px; border: 0; border-radius: 8px; background: none; font: inherit; font-size: 14px; font-weight: 700; color: #B91C1C; cursor: pointer')}>Sign out</button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div style={css('display: flex; flex-wrap: wrap; align-items: flex-start')}>
        <nav aria-label="Main" style={css('flex: 1 1 240px; max-width: 100%; box-sizing: border-box; padding: 20px 16px; display: flex; flex-direction: column; gap: 4px')}>
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end} className={({ isActive }) => `nav${isActive ? ' on' : ''}`}>
              {l.label}
              {l.badge && shell && shell.badge > 0 && (
                <span aria-label={`${shell.badge} open alerts`} style={css('margin-left: auto; font-size: 12px; font-weight: 800; background: #FEE2E2; color: #991B1B; border-radius: 999px; padding: 2px 8px')}>{shell.badge}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <main style={css('flex: 999 1 560px; min-width: 0; box-sizing: border-box; padding: 28px 24px 64px; display: flex; flex-direction: column; gap: 24px')}>
          <Outlet />
        </main>
      </div>
    </div>
  );
};
