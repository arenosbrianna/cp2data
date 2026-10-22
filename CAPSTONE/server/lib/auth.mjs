// Sign-in for the dashboard: one admin account whose credentials live in .env (never in code), a signed session cookie, and a small
// brute-force limit. Passwords are compared as SHA-256 digests in constant time.
import crypto from 'node:crypto';

const COOKIE = 'dss_session';
const MAX_AGE_SECONDS = 8 * 60 * 60;
const secret = process.env.DSS_SESSION_SECRET || crypto.randomBytes(32).toString('hex');   // random per start: sessions end when the API restarts

export const adminUser = () => process.env.DSS_ADMIN_USERNAME || 'admin';
export const displayName = () => process.env.DSS_USER_NAME || 'Admin';
export const loginConfigured = () => Boolean(process.env.DSS_ADMIN_PASSWORD);

const b64 = (buf) => Buffer.from(buf).toString('base64url');
const sign = (payload) => crypto.createHmac('sha256', secret).update(payload).digest('base64url');
const digest = (value) => crypto.createHash('sha256').update(String(value)).digest();
const same = (a, b) => crypto.timingSafeEqual(digest(a), digest(b));

export const credentialsOk = (username, password) => {
  if (!loginConfigured()) return false;
  const userOk = same(String(username ?? '').trim().toLowerCase(), adminUser().toLowerCase());
  const passOk = same(password ?? '', process.env.DSS_ADMIN_PASSWORD);
  return userOk && passOk;
};

export const sessionCookie = () => {
  const payload = b64(JSON.stringify({ u: adminUser(), exp: Date.now() + MAX_AGE_SECONDS * 1000 }));
  return `${COOKIE}=${payload}.${sign(payload)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${MAX_AGE_SECONDS}`;
};
export const clearCookie = () => `${COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0`;

export const sessionOf = (request) => {
  const raw = (request.headers.cookie || '').split(';').map((c) => c.trim()).find((c) => c.startsWith(`${COOKIE}=`));
  if (!raw) return null;
  const [payload, mac] = raw.slice(COOKIE.length + 1).split('.');
  if (!payload || !mac) return null;
  const expected = sign(payload);
  if (mac.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(mac), Buffer.from(expected))) return null;
  try {
    const data = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    return data.exp > Date.now() ? data : null;
  } catch { return null; }
};

// at most 5 failed attempts per address per minute
const failures = new Map();
export const tooManyAttempts = (ip) => {
  const now = Date.now();
  const list = (failures.get(ip) || []).filter((t) => now - t < 60000);
  failures.set(ip, list);
  return list.length >= 5;
};
export const noteFailure = (ip) => { failures.set(ip, [...(failures.get(ip) || []), Date.now()]); };
export const clearFailures = (ip) => failures.delete(ip);
