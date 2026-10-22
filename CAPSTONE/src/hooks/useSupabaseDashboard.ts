import { useCallback, useEffect, useState } from 'react';

export interface SupabaseDataset<T = Record<string, unknown>> {
  table: string | null;
  rows: number;
  sample: T[];
}

export interface SupabaseDashboardData {
  ok: boolean;
  provider: string;
  metrics: Record<string, number | null>;
  datasets: Record<string, SupabaseDataset>;
}

export const useSupabaseDashboard = () => {
  const [data, setData] = useState<SupabaseDashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/dashboard', { cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || 'Supabase data is unavailable');
      setData(payload);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Supabase data is unavailable');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return { data, loading, error, refresh };
};
