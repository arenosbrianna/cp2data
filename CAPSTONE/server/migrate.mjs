import 'dotenv/config';
import { readFile } from 'node:fs/promises';
import { pool } from './lib/db.mjs';

if (!pool) {
  console.error('DATABASE_URL is not configured');
  process.exit(1);
}
const sql = await readFile(new URL('./sql/001_dss_tables.sql', import.meta.url), 'utf8');
const client = await pool.connect();
try {
  await client.query('begin');
  await client.query(sql);
  await client.query('commit');
  console.log('dw.fact_recommendation, dw.plan_line_status and dw.manual_waste_log are in place.');
} catch (error) {
  await client.query('rollback');
  console.error('Migration rolled back:', error.message);
  process.exitCode = 1;
} finally {
  client.release();
  await pool.end();
}
