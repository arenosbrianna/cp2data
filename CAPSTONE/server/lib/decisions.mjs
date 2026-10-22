// Recommendation log, purchasing-list ticks and manual waste log. These live in three small tables (server/sql/001_dss_tables.sql);
// when they have not been created yet every read returns empty and every write reports `enabled: false`, so the pages still render.
import { query } from './db.mjs';
import * as L from './load.mjs';

let flags = { at: 0, value: null };
export const tableFlags = async () => {
  if (flags.value && Date.now() - flags.at < 30000) return flags.value;
  flags = { at: Date.now(), value: await L.loadDecisionTables() };
  return flags.value;
};
export const resetFlags = () => { flags = { at: 0, value: null }; };

export const userName = () => process.env.DSS_USER_NAME || 'Admin';

export const readRecommendations = async () => {
  const f = await tableFlags();
  if (!f.recommendations) return [];
  return L.loadRecommendations();
};

// Latest row per key wins (apply, then modify, is two rows). Rows arrive newest first.
export const latestByKey = (rows) => {
  const map = new Map();
  for (const r of rows) if (!map.has(r.rec_key)) map.set(r.rec_key, r);
  return map;
};

const STATUS = new Set(['applied', 'modified', 'dismissed']);
const TYPES = new Set(['stockout', 'spoilage', 'excess', 'weekly_order']);

export const recordDecision = async (body, asOf) => {
  const f = await tableFlags();
  if (!f.recommendations) return { ok: false, enabled: false, error: 'The decision log table has not been created (npm run db:migrate).' };
  if (!STATUS.has(body.status) || !TYPES.has(body.type) || !body.key || !body.title) return { ok: false, enabled: true, error: 'Invalid decision' };
  if (body.status === 'dismissed' && !String(body.reason || '').trim()) return { ok: false, enabled: true, error: 'A reason is required to dismiss' };
  const rows = await query(
    `insert into dw.fact_recommendation (rec_key, type, title, ingredient_id, recommended_qty, peso_impact, status, decided_by, decided_at, reason, data_as_of, opt_run_id)
     values ($1, $2, $3, $4, $5, $6, $7, $8, now(), $9, $10, $11) returning rec_id`,
    [body.key, body.type, String(body.title).slice(0, 400), body.ingredientId ?? null, body.qty ?? null, body.impact ?? null, body.status,
      userName(), body.reason ? String(body.reason).slice(0, 400) : null, asOf, body.optRunId ?? null]);
  return { ok: true, enabled: true, recId: rows[0].rec_id };
};

export const readPlanLines = async (optRunId) => {
  const f = await tableFlags();
  if (!f.planLines || !optRunId) return new Map();
  const rows = await L.loadPlanLines(optRunId);
  return new Map(rows.map((r) => [r.ingredient_id, r]));
};

export const recordPlanLine = async ({ optRunId, ingredientId, ordered }) => {
  const f = await tableFlags();
  if (!f.planLines) return { ok: false, enabled: false, error: 'The purchasing-list table has not been created (npm run db:migrate).' };
  await query(
    `insert into dw.plan_line_status (opt_run_id, ingredient_id, ordered, ordered_by, ordered_at) values ($1, $2, $3, $4, now())
     on conflict (opt_run_id, ingredient_id) do update set ordered = excluded.ordered, ordered_by = excluded.ordered_by, ordered_at = now()`,
    [optRunId, ingredientId, Boolean(ordered), userName()]);
  return { ok: true, enabled: true };
};

const WASTE_REASONS = new Set(['expiry', 'over_ordering', 'prep', 'damaged', 'other']);
export const recordWaste = async ({ date, ingredientId, qtyBase, reason, note }) => {
  const f = await tableFlags();
  if (!f.wasteLog) return { ok: false, enabled: false, error: 'The waste-log table has not been created (npm run db:migrate).' };
  if (!(qtyBase > 0) || !WASTE_REASONS.has(reason) || !ingredientId || !date) return { ok: false, enabled: true, error: 'Invalid waste entry' };
  await query(`insert into dw.manual_waste_log (waste_date, ingredient_id, qty_base, reason, note, logged_by) values ($1, $2, $3, $4, $5, $6)`,
    [date, ingredientId, qtyBase, reason, note ? String(note).slice(0, 300) : null, userName()]);
  return { ok: true, enabled: true };
};
