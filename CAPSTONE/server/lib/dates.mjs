// Calendar-date helpers on 'YYYY-MM-DD' strings. Everything is UTC arithmetic so no timezone can shift a day.
const DAY = 86400000;
const DN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const toMs = (s) => { const [y, m, d] = s.split('-').map(Number); return Date.UTC(y, m - 1, d); };
const toStr = (ms) => new Date(ms).toISOString().slice(0, 10);

export const addDays = (s, n) => toStr(toMs(s) + n * DAY);
export const diffDays = (a, b) => Math.round((toMs(a) - toMs(b)) / DAY);
export const dow = (s) => (new Date(toMs(s)).getUTCDay() + 6) % 7; // 0 = Monday
export const mondayOf = (s) => addDays(s, -dow(s));
export const dayName = (s) => DN[dow(s)];
export const monthName = (s) => MN[Number(s.slice(5, 7)) - 1];
export const dayNum = (s) => Number(s.slice(8, 10));
export const label = (s) => `${dayName(s)} ${dayNum(s)} ${monthName(s)}`;       // Mon 19 Oct
export const labelShort = (s) => `${dayName(s)} ${dayNum(s)}`;                    // Mon 19
export const labelDM = (s) => `${dayNum(s)} ${monthName(s)}`;                     // 19 Oct
export const labelLong = (s) => `${['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][dow(s)]}, ${dayNum(s)} ${['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][Number(s.slice(5, 7)) - 1]} ${s.slice(0, 4)}`;
export const days = (start, n) => Array.from({ length: n }, (_, i) => addDays(start, i));
export const todayIso = () => {
  const now = new Date();
  return toStr(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
};
