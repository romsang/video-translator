/* global React */
const { useState } = React;

// ── Button ─────────────────────────────────────────────────
function Button({ variant = 'primary', size = 'md', children, disabled, onClick, style }) {
  const base = {
    appearance: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'var(--font-sans)', fontWeight: 500,
    borderRadius: 'var(--radius-md)', border: '1px solid transparent',
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
    transition: 'background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out)',
    whiteSpace: 'nowrap',
  };
  const sizeMap = {
    sm: { padding: '6px 12px', fontSize: 13 },
    md: { padding: '9px 16px', fontSize: 14 },
    lg: { padding: '14px 24px', fontSize: 16, fontWeight: 600 },
  };
  const variants = {
    primary: { background: disabled ? 'var(--ink-100)' : 'var(--accent)', color: disabled ? 'var(--ink-300)' : '#FAF7F2', borderColor: disabled ? 'var(--ink-150)' : 'transparent', boxShadow: disabled ? 'none' : 'var(--shadow-sm)' },
    secondary: { background: 'var(--ink-50)', color: 'var(--ink-900)', borderColor: 'var(--ink-150)', boxShadow: 'var(--shadow-sm)' },
    ghost: { background: 'transparent', color: 'var(--ink-700)' },
  };
  return (
    <button type="button" disabled={disabled} onClick={onClick} style={{ ...base, ...sizeMap[size], ...variants[variant], ...style }}>
      {children}
    </button>
  );
}

// ── Card ───────────────────────────────────────────────────
function Card({ children, style }) {
  return (
    <div style={{
      background: 'var(--ink-50)',
      border: '1px solid var(--ink-150)',
      borderRadius: 'var(--radius-lg)',
      padding: 'var(--space-6)',
      ...style,
    }}>
      {children}
    </div>
  );
}

// ── Select ─────────────────────────────────────────────────
function Select({ label, value, onChange, options }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink-900)' }}>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        style={{
          appearance: 'none', WebkitAppearance: 'none',
          fontFamily: 'var(--font-sans)', fontSize: 14,
          padding: '10px 32px 10px 12px',
          borderRadius: 'var(--radius-md)',
          background: 'var(--ink-50)',
          border: '1px solid var(--ink-150)',
          color: 'var(--ink-900)',
          backgroundImage: "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%237A7164' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='4 6 8 10 12 6'/></svg>\")",
          backgroundRepeat: 'no-repeat', backgroundPosition: 'right 12px center',
        }}>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

// ── Checkbox ───────────────────────────────────────────────
function Checkbox({ label, checked, onChange, hint }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 9, cursor: 'pointer' }}>
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)}
          style={{ accentColor: 'var(--accent)', width: 16, height: 16 }} />
        <span style={{ fontSize: 14, color: 'var(--ink-900)' }}>{label}</span>
      </label>
      {hint && <span style={{ fontSize: 12, color: 'var(--ink-500)', paddingLeft: 25 }}>{hint}</span>}
    </div>
  );
}

// ── Pill ───────────────────────────────────────────────────
function Pill({ tone = 'pending', children }) {
  const tones = {
    pending: { bg: 'var(--ink-100)', fg: 'var(--ink-700)', dot: 'var(--ink-300)', pulse: false },
    running: { bg: 'var(--accent-soft)', fg: 'var(--accent-press)', dot: 'var(--accent)', pulse: true },
    success: { bg: 'var(--success-soft)', fg: '#1F6A40', dot: 'var(--success)', pulse: false },
    failed:  { bg: 'var(--danger-soft)',  fg: '#8B281D', dot: 'var(--danger)', pulse: false },
  };
  const t = tones[tone];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 10px 4px 8px', borderRadius: 9999,
      background: t.bg, color: t.fg, fontSize: 12, fontWeight: 500,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: 999, background: t.dot,
        animation: t.pulse ? 'vt-pulse 1.4s ease-in-out infinite' : 'none',
      }}/>
      {children}
    </span>
  );
}

// expose globally
Object.assign(window, { Button, Card, Select, Checkbox, Pill });
