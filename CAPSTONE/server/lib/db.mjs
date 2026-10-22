import 'dotenv/config';
import pg from 'pg';

// Dates stay as 'YYYY-MM-DD' strings (no timezone shifts), numerics and bigints become numbers.
pg.types.setTypeParser(1082, (value) => value);
pg.types.setTypeParser(1700, (value) => (value === null ? null : Number(value)));
pg.types.setTypeParser(20, (value) => (value === null ? null : Number(value)));

const databaseUrl = process.env.DATABASE_URL;
const isLoopback = databaseUrl ? /@(127\.0\.0\.1|localhost)[:/]/.test(databaseUrl) : false;

// Every figure on the screens comes from Supabase and nowhere else: refuse any other host (set ALLOW_NON_SUPABASE=1 only for a deliberate test).
const hostOf = (url) => { try { return new URL(url).hostname; } catch { return ''; } };
export const databaseHost = databaseUrl ? hostOf(databaseUrl) : '';
export const isSupabase = /(^|\.)supabase\.(co|com)$/.test(databaseHost);
if (databaseUrl && !isSupabase && process.env.ALLOW_NON_SUPABASE !== '1') {
  console.error('DATABASE_URL does not point to Supabase (host: ' + (databaseHost || 'unreadable') + '). The dashboard reads Supabase only, so it will not start.');
  process.exit(1);
}

export const pool = databaseUrl
  ? new pg.Pool({
      connectionString: databaseUrl,
      ssl: isLoopback || process.env.DB_SSL === 'off' ? false : { rejectUnauthorized: false },
      max: 5,
      idleTimeoutMillis: 30000,
      connectionTimeoutMillis: 10000,
    })
  : null;

export const hasDatabase = Boolean(pool);

export const query = async (text, params = []) => {
  if (!pool) throw new Error('DATABASE_URL is not configured');
  const result = await pool.query(text, params);
  return result.rows;
};

export const tableExists = async (qualified) => {
  const rows = await query('select to_regclass($1) as t', [qualified]);
  return Boolean(rows[0]?.t);
};
