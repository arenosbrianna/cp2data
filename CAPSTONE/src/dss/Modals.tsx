import React, { useEffect, useState } from 'react';
import { css } from './css';
import { Modal } from './ui';
import { post } from './api';
import { useDss } from './context';

const REQUIRED = ['Item name', 'SKU', 'Category', 'Items sold', 'Gross sales', 'Discounts', 'Net sales', 'DATE'];
const MONTHS: Record<string, number> = { Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5, Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11 };

const splitCsv = (line: string) => {
  const out: string[] = []; let cur = ''; let quoted = false;
  for (const ch of line) {
    if (ch === '"') quoted = !quoted;
    else if (ch === ',' && !quoted) { out.push(cur); cur = ''; } else cur += ch;
  }
  out.push(cur);
  return out.map((v) => v.trim());
};
const parseDate = (v: string) => {
  const m = /^(\d{1,2})-([A-Za-z]{3})-(\d{2,4})$/.exec(v);
  if (!m) return null;
  const year = m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3]);
  return new Date(Date.UTC(year, MONTHS[m[2]], Number(m[1])));
};
const show = (d: Date) => d.toISOString().slice(0, 10);

export const UploadModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [result, setResult] = useState<null | { name: string; rows: number; from: string; to: string; missing: string[]; badDates: number }>(null);
  const read = async (file: File) => {
    const text = (await file.text()).replace(/^﻿/, '');
    const lines = text.split(/\r?\n/).filter((l) => l.trim());
    const header = splitCsv(lines[0] ?? '');
    const missing = REQUIRED.filter((c) => !header.includes(c));
    const dateIdx = header.indexOf('DATE');
    let from: Date | null = null, to: Date | null = null, bad = 0;
    for (const line of lines.slice(1)) {
      const d = parseDate(splitCsv(line)[dateIdx] ?? '');
      if (!d) { bad += 1; continue; }
      if (!from || d < from) from = d;
      if (!to || d > to) to = d;
    }
    setResult({ name: file.name, rows: Math.max(0, lines.length - 1), from: from ? show(from) : '—', to: to ? show(to) : '—', missing, badDates: bad });
  };
  return (
    <Modal title="Upload Loyverse CSV" onClose={onClose}>
      <p style={css('font-size: 14px; color: #374151; line-height: 1.55')}>Choose the item-sales export from Loyverse. The file is checked here in the browser; nothing is sent to the database.</p>
      <input type="file" accept=".csv,text/csv" aria-label="Loyverse CSV file" onChange={(e) => { const f = e.target.files?.[0]; if (f) void read(f); }} />
      {result && (
        <div role="status" style={css('background: #F8FAFC; border-radius: 10px; padding: 12px 14px; font-size: 14px; line-height: 1.6')}>
          <div style={css('font-weight: 700')}>{result.name}</div>
          <div>{result.rows.toLocaleString('en-US')} sale lines · {result.from} to {result.to}</div>
          {result.missing.length > 0
            ? <div style={css('color: #991B1B; font-weight: 700')}>✕ Missing columns: {result.missing.join(', ')}</div>
            : <div style={css('color: #047857; font-weight: 700')}>✓ All required columns are present{result.badDates ? ` (${result.badDates} rows have an unreadable DATE)` : ''}</div>}
        </div>
      )}
      <p style={css('font-size: 13px; color: #4B5563; line-height: 1.55')}>Loading a checked file into the warehouse is done by the ETL scripts (clean_sales.py, then supabase_final/03_transform.sql), which reload every table. After that run, choose Refresh data.</p>
      <div style={css('display: flex; justify-content: flex-end')}><button type="button" className="btn" onClick={onClose}>Close</button></div>
    </Modal>
  );
};

interface IngredientOption { id: number; name: string; unit: string; scale: number }

export const WasteModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const { toast, shell } = useDss();
  const [options, setOptions] = useState<IngredientOption[]>([]);
  const [ingredient, setIngredient] = useState('');
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState('expiry');
  const [note, setNote] = useState('');
  const [date, setDate] = useState(shell?.asOf ?? '');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch('/api/ingredients').then((r) => r.json()).then((d) => { setOptions(d.ingredients); if (!date) setDate(d.asOf); }).catch(() => undefined);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const chosen = options.find((o) => String(o.id) === ingredient);
  const save = async () => {
    if (!chosen) return;
    setBusy(true);
    const result = await post('/api/waste-log', { date, ingredientId: chosen.id, qtyBase: Number(qty) * chosen.scale, reason, note });
    setBusy(false);
    if (result.ok) { toast('Waste logged'); onClose(); } else toast(result.payload.error || 'Could not log the waste', 'err');
  };
  return (
    <Modal title="Log waste" onClose={onClose}>
      <label style={css('display: flex; flex-direction: column; gap: 6px')}><span className="lbl">Date</span><input className="inp" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
      <label style={css('display: flex; flex-direction: column; gap: 6px')}>
        <span className="lbl">Ingredient</span>
        <select className="inp" value={ingredient} onChange={(e) => setIngredient(e.target.value)}>
          <option value="">Choose an ingredient</option>
          {options.map((o) => <option key={o.id} value={o.id}>{o.name} ({o.unit})</option>)}
        </select>
      </label>
      <label style={css('display: flex; flex-direction: column; gap: 6px')}><span className="lbl">Quantity wasted{chosen ? ` (${chosen.unit})` : ''}</span><input className="inp" type="number" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} /></label>
      <label style={css('display: flex; flex-direction: column; gap: 6px')}>
        <span className="lbl">Reason</span>
        <select className="inp" value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="expiry">Expired</option><option value="over_ordering">Over-ordered</option><option value="prep">Prep loss</option><option value="damaged">Damaged</option><option value="other">Other</option>
        </select>
      </label>
      <label style={css('display: flex; flex-direction: column; gap: 6px')}><span className="lbl">Note (optional)</span><input className="inp" value={note} onChange={(e) => setNote(e.target.value)} style={css('font-family: inherit; font-size: 14px')} /></label>
      <div style={css('display: flex; gap: 10px; justify-content: flex-end')}>
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn pri" disabled={!chosen || !(Number(qty) > 0) || !date || busy} onClick={save}>Save</button>
      </div>
    </Modal>
  );
};
