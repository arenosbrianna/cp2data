import { useCallback, useEffect, useState } from 'react';

export interface ShellInfo {
  asOf: string; asOfLabel: string; today: string; todayLabel: string; todayLong: string; staleDays: number; badge: number; user: string;
  writes: { decisions: boolean; planLines: boolean; wasteLog: boolean };
  model?: { selected: string | null; champion: string | null; isChampion: boolean };
}

// ---- the forecast model the user chose (empty = the champion) ---------------------------------------------------
export interface ModelOption {
  model: string; label: string; note: string; runId: number; isChampion: boolean; wmape: number | null; mase: number | null; beatsNaive: boolean; hasPlans: boolean;
}
export interface ModelsInfo { selected: string | null; champion: string | null; models: ModelOption[] }

const MODEL_KEY = 'makisushi-dss-model';
export const getModel = (): string => {
  try { return window.localStorage.getItem(MODEL_KEY) || ''; } catch { return ''; }
};
export const setModel = (model: string) => {
  try { if (model) window.localStorage.setItem(MODEL_KEY, model); else window.localStorage.removeItem(MODEL_KEY); } catch { /* storage can be blocked */ }
  window.dispatchEvent(new Event('dss-model-changed'));
};
export const withModel = (url: string, model: string = getModel()): string => (model ? `${url}${url.includes('?') ? '&' : '?'}model=${encodeURIComponent(model)}` : url);

export const useApi = <T,>(path: string) => {
  const [model, setModelState] = useState<string>(getModel);
  useEffect(() => {
    const onChange = () => setModelState(getModel());
    window.addEventListener('dss-model-changed', onChange);
    return () => window.removeEventListener('dss-model-changed', onChange);
  }, []);
  const url = withModel(path, model);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(url, { cache: 'no-store' });
      const payload = await response.json();
      if (response.status === 401) window.dispatchEvent(new Event('dss-unauthorized'));
      if (!response.ok) throw new Error(payload.error || 'The data service is unavailable');
      setData(payload as T);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The data service is unavailable');
    } finally {
      setLoading(false);
    }
  }, [url]);

  useEffect(() => { load(); }, [load]);
  return { data, error, loading, reload: load };
};

export const post = async <T,>(url: string, body: unknown): Promise<{ ok: boolean; status: number; payload: T & { error?: string; enabled?: boolean } }> => {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401 && !url.endsWith('/api/login')) window.dispatchEvent(new Event('dss-unauthorized'));
  return { ok: response.ok, status: response.status, payload };
};

export const fmt = (n: number, dp: number) => n.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
