import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { post, ShellInfo, withModel } from './api';

export interface DecisionTarget {
  key: string; type: string; typeKey: string; title: string; ingredientId?: number | null; qty?: number | null; pesoImpact?: number | null; optRunId?: number | null;
}
export type Status = 'open' | 'applied' | 'modified' | 'dismissed';
export type AuthState = 'checking' | 'in' | 'out';

interface Ctx {
  auth: AuthState;
  justSignedOut: boolean;
  user: string | null;
  signIn: (username: string, password: string) => Promise<string | null>;
  signOut: () => Promise<void>;
  shell: ShellInfo | null;
  setShell: (s: ShellInfo) => void;
  toast: (message: string, kind?: 'ok' | 'err') => void;
  decide: (target: DecisionTarget, status: Exclude<Status, 'open'>, reason?: string) => Promise<boolean>;
  statusOf: (key: string, serverStatus: Status) => Status;
  refreshAll: () => Promise<void>;
  tick: number;
}

const DssContext = createContext<Ctx | null>(null);
export const useDss = () => {
  const ctx = useContext(DssContext);
  if (!ctx) throw new Error('DssContext missing');
  return ctx;
};

const LOCAL_KEY = 'makisushi-dss-local-decisions';
const readLocal = (): Record<string, Status> => {
  try { return JSON.parse(window.localStorage.getItem(LOCAL_KEY) || '{}'); } catch { return {}; }
};
const writeLocal = (value: Record<string, Status>) => {
  try { window.localStorage.setItem(LOCAL_KEY, JSON.stringify(value)); } catch { /* storage can be blocked */ }
};

export const DssProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [auth, setAuth] = useState<AuthState>('checking');
  const [user, setUser] = useState<string | null>(null);
  const [justSignedOut, setJustSignedOut] = useState(false);
  const [shell, setShell] = useState<ShellInfo | null>(null);
  const [message, setMessage] = useState<{ text: string; kind: 'ok' | 'err' } | null>(null);
  const [local, setLocal] = useState<Record<string, Status>>(readLocal);
  const [tick, setTick] = useState(0);

  const toast = useCallback((text: string, kind: 'ok' | 'err' = 'ok') => {
    setMessage({ text, kind });
    window.setTimeout(() => setMessage((m) => (m && m.text === text ? null : m)), 4200);
  }, []);

  // who is signed in? (the session cookie is set by the API)
  useEffect(() => {
    fetch('/api/session', { cache: 'no-store' }).then((r) => r.json())
      .then((s) => { setAuth(s.authenticated ? 'in' : 'out'); setUser(s.user ?? null); })
      .catch(() => setAuth('out'));
  }, []);
  // choosing another forecast model changes every number: reload the shell too
  useEffect(() => {
    const onModel = () => setTick((n) => n + 1);
    window.addEventListener('dss-model-changed', onModel);
    return () => window.removeEventListener('dss-model-changed', onModel);
  }, []);
  // any API call answered with 401 means the session ended
  useEffect(() => {
    const onDenied = () => { setAuth('out'); setUser(null); setShell(null); };
    window.addEventListener('dss-unauthorized', onDenied);
    return () => window.removeEventListener('dss-unauthorized', onDenied);
  }, []);

  const signIn = useCallback<Ctx['signIn']>(async (username, password) => {
    try {
      const result = await post<{ user?: string }>('/api/login', { username, password });
      if (!result.ok) return result.payload.error || 'Sign-in failed';
      setUser(result.payload.user ?? 'Admin'); setJustSignedOut(false); setAuth('in'); setTick((n) => n + 1);
      return null;
    } catch {
      return 'The data service is unreachable. Try again in a moment.';
    }
  }, []);

  const signOut = useCallback(async () => {
    try { await post('/api/logout', {}); } catch { /* the cookie also expires on its own */ }
    setJustSignedOut(true); setAuth('out'); setUser(null); setShell(null);
  }, []);

  useEffect(() => {
    if (auth !== 'in') return;
    fetch(withModel('/api/shell'), { cache: 'no-store' }).then((r) => (r.status === 401 ? window.dispatchEvent(new Event('dss-unauthorized')) : r.json()))
      .then((s) => { if (s && s.asOf) setShell(s); }).catch(() => undefined);
  }, [tick, auth]);

  const decide = useCallback<Ctx['decide']>(async (target, status, reason) => {
    const body = { key: target.key, type: target.typeKey, title: target.title, ingredientId: target.ingredientId ?? null, qty: target.qty ?? null, impact: target.pesoImpact ?? null, status, reason, optRunId: target.optRunId ?? null };
    try {
      const result = await post('/api/decisions', body);
      if (result.ok) { setTick((n) => n + 1); return true; }
      if (result.payload.enabled === false) {
        // the decision-log table does not exist in this database yet: keep the choice in this browser only
        const next = { ...readLocal(), [target.key]: status };
        writeLocal(next); setLocal(next); setTick((n) => n + 1);
        toast('Saved in this browser only: the decision log table is not created in the database yet (npm run db:migrate).', 'err');
        return true;
      }
      toast(result.payload.error || 'The decision could not be saved', 'err');
      return false;
    } catch {
      toast('The decision could not be saved: the data service is unreachable', 'err');
      return false;
    }
  }, [toast]);

  const statusOf = useCallback((key: string, serverStatus: Status): Status => (serverStatus !== 'open' ? serverStatus : local[key] ?? 'open'), [local]);
  const refreshAll = useCallback(async () => {
    await post('/api/refresh', {});
    setTick((n) => n + 1);
  }, []);

  const value = useMemo(
    () => ({ auth, justSignedOut, user, signIn, signOut, shell, setShell, toast, decide, statusOf, refreshAll, tick }),
    [auth, justSignedOut, user, signIn, signOut, shell, toast, decide, statusOf, refreshAll, tick],
  );
  return (
    <DssContext.Provider value={value}>
      {children}
      {message && <div role="status" className={`dss-toast${message.kind === 'err' ? ' err' : ''}`}>{message.text}</div>}
    </DssContext.Provider>
  );
};
