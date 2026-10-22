import React, { useEffect, useRef, useState } from 'react';
import { css } from './css';

export const PageState: React.FC<{ loading: boolean; error: string | null; reload: () => void; empty?: string | null; children: React.ReactNode }> = ({ loading, error, reload, empty, children }) => {
  if (loading) return <div className="card" style={css('padding: 28px; font-size: 15px; color: #374151')} role="status">Reading the warehouse…</div>;
  if (error) return (
    <div className="card" role="alert" style={css('padding: 28px; display: flex; flex-direction: column; gap: 10px; align-items: flex-start')}>
      <h2 style={css('font-size: 18px; font-weight: 800')}>Data is unavailable</h2>
      <p style={css('font-size: 14px; color: #4B5563')}>{error}</p>
      <button className="btn" type="button" onClick={reload}>Try again</button>
    </div>
  );
  if (empty) return (
    <div className="card" style={css('padding: 28px; display: flex; flex-direction: column; gap: 8px')}>
      <h2 style={css('font-size: 18px; font-weight: 800')}>Nothing to show yet</h2>
      <p style={css('font-size: 14px; color: #4B5563')}>{empty}</p>
    </div>
  );
  return <>{children}</>;
};

export const Modal: React.FC<{ title: string; onClose: () => void; children: React.ReactNode }> = ({ title, onClose, children }) => {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    ref.current?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="dss-modal-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dss-modal" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <h2 style={css('font-size: 20px; font-weight: 800')}>{title}</h2>
        {children}
      </div>
    </div>
  );
};

export const DISMISS_REASONS = ['Supplier out of stock', 'Bulk discount offered', 'Event booking not in data', 'Other'];

export const ReasonModal: React.FC<{ title: string; label: string; confirm: string; presets?: string[]; onSubmit: (reason: string) => Promise<void> | void; onClose: () => void }> = ({ title, label, confirm, presets, onSubmit, onClose }) => {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose}>
      {presets && (
        <div style={css('display: flex; flex-wrap: wrap; gap: 8px')}>
          {presets.map((p) => (
            <button key={p} type="button" className={`tab${text === p ? ' on' : ''}`} onClick={() => setText(p === 'Other' ? '' : p)}>{p}</button>
          ))}
        </div>
      )}
      <label style={css('display: flex; flex-direction: column; gap: 6px')}>
        <span className="lbl">{label}</span>
        <textarea className="inp" rows={3} value={text} onChange={(e) => setText(e.target.value)} style={css('font-family: inherit; font-size: 14px')} />
      </label>
      <div style={css('display: flex; gap: 10px; justify-content: flex-end; flex-wrap: wrap')}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn pri" disabled={!text.trim() || busy} onClick={async () => { setBusy(true); await onSubmit(text.trim()); setBusy(false); }}>{confirm}</button>
      </div>
    </Modal>
  );
};

export const SeverityChip: React.FC<{ severity: 'crit' | 'warn' | 'info' }> = ({ severity }) => {
  if (severity === 'crit') return <span style={css('font-size: 11px; font-weight: 800; letter-spacing: .04em; padding: 4px 8px; border-radius: 6px; background: #FEE2E2; color: #991B1B; align-self: flex-start')}>● CRITICAL</span>;
  if (severity === 'warn') return <span style={css('font-size: 11px; font-weight: 800; letter-spacing: .04em; padding: 4px 8px; border-radius: 6px; background: #FEF3C7; color: #92400E; align-self: flex-start')}>▲ WARNING</span>;
  return <span style={css('font-size: 11px; font-weight: 800; letter-spacing: .04em; padding: 4px 8px; border-radius: 6px; background: #DBEAFE; color: #1E3A8A; align-self: flex-start')}>◆ ROUTINE</span>;
};

export const useDecisionUi = () => {
  const [dismiss, setDismiss] = useState<null | string>(null);
  const [modify, setModify] = useState<null | string>(null);
  return { dismiss, setDismiss, modify, setModify };
};
