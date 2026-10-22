import type { CSSProperties } from 'react';

const cache = new Map<string, CSSProperties>();

/** Turns a CSS declaration string (as written in docs/mockups) into a React style object. */
export const css = (declarations: string): CSSProperties => {
  const hit = cache.get(declarations);
  if (hit) return hit;
  const style: Record<string, string> = {};
  for (const part of declarations.split(';')) {
    const index = part.indexOf(':');
    if (index < 0) continue;
    const key = part.slice(0, index).trim();
    const value = part.slice(index + 1).trim();
    if (!key) continue;
    const camel = key.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());
    style[camel] = value;
  }
  cache.set(declarations, style as CSSProperties);
  return style as CSSProperties;
};

/** css() with a per-call patch, for values that change at runtime. */
export const cx = (declarations: string, extra: CSSProperties = {}): CSSProperties => ({ ...css(declarations), ...extra });
