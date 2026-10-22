import 'dotenv/config';
import http from 'node:http';
import { pool, hasDatabase, query, databaseHost } from './lib/db.mjs';
import { getState, resetState, unitMeta } from './lib/analysis.mjs';
import { recordDecision, recordPlanLine, recordWaste, resetFlags } from './lib/decisions.mjs';
import { getBundle, shellInfo } from './views/common.mjs';
import { overviewView } from './views/overview.mjs';
import { modelsView } from './views/models.mjs';
import { modelScope } from './lib/modelcontext.mjs';
import { forecastView } from './views/forecast.mjs';
import { riskView } from './views/risk.mjs';
import { purchasingView } from './views/purchasing.mjs';
import { trackingView } from './views/tracking.mjs';
import { credentialsOk, sessionCookie, clearCookie, sessionOf, loginConfigured, displayName, tooManyAttempts, noteFailure, clearFailures } from './lib/auth.mjs';

const port = Number(process.env.API_PORT || 3001);

const send = (response, status, payload, headers = {}) => {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...headers });
  response.end(JSON.stringify(payload));
};

const readBody = (request) => new Promise((resolve, reject) => {
  let raw = '';
  request.on('data', (chunk) => { raw += chunk; if (raw.length > 100000) { reject(new Error('Body too large')); request.destroy(); } });
  request.on('end', () => { try { resolve(raw ? JSON.parse(raw) : {}); } catch { reject(new Error('Invalid JSON')); } });
  request.on('error', reject);
});

const GET = {
  '/api/overview': () => overviewView(),
  '/api/forecast': () => forecastView(),
  '/api/risk': () => riskView(),
  '/api/purchasing': (url) => purchasingView(url.searchParams.get('budget')),
  '/api/tracking': () => trackingView(),
  '/api/shell': async () => shellInfo(await getBundle()),
  '/api/models': () => modelsView(),
  '/api/ingredients': async () => {
    const st = await getState();
    return { asOf: st.asOf, today: st.today, ingredients: st.ings.map((i) => { const m = unitMeta(i, st.weekly(i.id)); return { id: i.id, name: i.name, unit: m.unit, scale: m.scale }; }) };
  },
  '/api/health': async () => {
    const [row] = await query('select now() as database_time');
    const st = await getState();
    return { ok: true, provider: 'supabase', host: databaseHost, databaseTime: row.database_time, asOf: st.asOf, forecastRuns: st.prodRuns.map((r) => r.run_id) };
  },
};

const handler = async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  try {
    // ---- sign-in (public) ----
    if (url.pathname === '/api/session' && request.method === 'GET') {
      const s = sessionOf(request);
      send(response, 200, { authenticated: Boolean(s), user: s ? displayName() : null, loginConfigured: loginConfigured() });
      return;
    }
    if (url.pathname === '/api/login' && request.method === 'POST') {
      const ip = request.socket.remoteAddress || 'unknown';
      if (!loginConfigured()) { send(response, 503, { ok: false, error: 'Sign-in is not configured on the server (DSS_ADMIN_PASSWORD).' }); return; }
      if (tooManyAttempts(ip)) { send(response, 429, { ok: false, error: 'Too many attempts. Wait a minute and try again.' }); return; }
      const body = await readBody(request);
      if (!credentialsOk(body.username, body.password)) {
        noteFailure(ip);
        await new Promise((r) => setTimeout(r, 400));
        send(response, 401, { ok: false, error: 'The username or password is not correct.' });
        return;
      }
      clearFailures(ip);
      send(response, 200, { ok: true, user: displayName() }, { 'Set-Cookie': sessionCookie() });
      return;
    }
    if (url.pathname === '/api/logout' && request.method === 'POST') {
      send(response, 200, { ok: true }, { 'Set-Cookie': clearCookie() });
      return;
    }
    // everything else needs a session
    if (!sessionOf(request)) { send(response, 401, { ok: false, error: 'Sign in required' }); return; }

    if (!hasDatabase) { send(response, 503, { ok: false, error: 'DATABASE_URL is not configured' }); return; }

    if (request.method === 'GET' && GET[url.pathname]) {
      send(response, 200, await GET[url.pathname](url));
      return;
    }
    if (request.method === 'POST') {
      const body = await readBody(request);
      if (url.pathname === '/api/decisions') {
        const st = await getState();
        const result = await recordDecision(body, st.asOf);
        if (result.ok) resetState();
        send(response, result.ok ? 200 : result.enabled ? 400 : 409, result);
        return;
      }
      if (url.pathname === '/api/plan-lines') {
        const result = await recordPlanLine({ optRunId: Number(body.optRunId), ingredientId: Number(body.ingredientId), ordered: body.ordered });
        send(response, result.ok ? 200 : 409, result);
        return;
      }
      if (url.pathname === '/api/waste-log') {
        const result = await recordWaste({ date: body.date, ingredientId: Number(body.ingredientId), qtyBase: Number(body.qtyBase), reason: body.reason, note: body.note });
        send(response, result.ok ? 200 : result.enabled ? 400 : 409, result);
        return;
      }
      if (url.pathname === '/api/refresh') {
        resetState(); resetFlags();
        send(response, 200, await shellInfo(await getBundle()));
        return;
      }
    }
    send(response, 404, { error: 'Not found' });
  } catch (error) {
    console.error(`${request.method} ${url.pathname} failed:`, error.stack || error.message);
    const connection = /ECONN|ETIMEDOUT|ENOTFOUND|timeout|terminated|password|SSL/i.test(error.message);
    send(response, connection ? 503 : 500, { ok: false, error: connection ? 'Database connection failed' : error.message });
  }
};

// every request runs inside the model the user chose (query parameter `model`, a model name such as SES); none = the champion
const server = http.createServer((request, response) => {
  const asked = new URL(request.url, 'http://localhost').searchParams.get('model');
  const model = asked && /^[A-Z_]{2,24}$/.test(asked) ? asked : null;
  return modelScope.run({ model }, () => handler(request, response));
});

server.listen(port, () => {
  console.log(`Makisushi API listening on http://127.0.0.1:${port}`);
});

const shutdown = async () => {
  await pool?.end();
  server.close(() => process.exit(0));
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
