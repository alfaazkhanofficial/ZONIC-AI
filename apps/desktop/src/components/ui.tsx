import { useEffect, useRef, useState, type ReactNode } from "react";
import { pretty } from "../lib/format";

/** DashboardCard: the one card primitive every view uses (same radius, border, spacing, hover). */
export const Card = ({ title, action, children, raised, className = "", interactive, label }: { title?: ReactNode; action?: ReactNode; children: ReactNode; raised?: boolean; className?: string; interactive?: boolean; label?: string }) => (
  <section className={`card ${raised ? "raised" : ""} ${interactive ? "interactive" : ""} ${className}`} aria-label={label}>
    {(title || action) && <div className="card-head"><h3>{title}</h3>{action}</div>}
    {children}
  </section>
);

/** Icon-only control: always has an accessible name and a tooltip. */
export const IconButton = ({ label, pressed, children, className = "", ...p }: { label: string; pressed?: boolean; children: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button type="button" aria-label={label} title={label} aria-pressed={pressed} {...p} className={`iconbtn ${className}`}>{children}</button>
);

const GLYPH: Record<string, string> = { ready: "✓", verified: "✓", completed: "✓", available: "✓", active: "✓", error: "✕", failed: "✕", high: "▲", rejected: "✕", needs_setup: "○", not_configured: "○", limited: "◐", untested: "◐", partial: "◐", permission_gated: "🔒", unavailable: "–", disabled: "–", running: "●", planning: "●", verifying: "●", cancelled: "–", waiting_for_approval: "!", pending_approval: "!", medium: "◆", low: "·", queued: "…", superseded: "·", not_applicable: "·" };
const LABEL: Record<string, string> = { needs_setup: "Needs setup", not_configured: "Not configured", untested: "Not tested", permission_gated: "Needs permission", waiting_for_approval: "Waiting for approval", pending_approval: "Awaiting approval", not_applicable: "No actions" };
/** Status is always glyph + text, never color alone. */
export const Chip = ({ state, label }: { state: string; label?: string }) => (
  <span className={`chip ${state}`}><span aria-hidden>{GLYPH[state] ?? "·"}</span>{label ?? LABEL[state] ?? pretty(state)}</span>
);

export const Btn = ({ kind, small, children, ...p }: { kind?: "primary" | "danger" | "ghost"; small?: boolean } & React.ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button type="button" {...p} className={`btn ${kind ?? ""} ${small ? "small" : ""} ${p.className ?? ""}`}>{children}</button>
);

export const Toggle = ({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; hint?: ReactNode; disabled?: boolean }) => (
  <label className="toggle">
    <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
    <span className="sw" aria-hidden />
    <span><span style={{ display: "block" }}>{label}</span>{hint && <span className="muted small">{hint}</span>}</span>
  </label>
);

export const Field = ({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) => (
  <label className="field"><span>{label}</span>{children}{hint && <span className="hint">{hint}</span>}</label>
);

export const Empty = ({ children, icon, title }: { children?: ReactNode; icon?: ReactNode; title?: string }) => (
  <div className="empty">{icon && <span className="ei" aria-hidden>{icon}</span>}{title && <b>{title}</b>}{children}</div>
);
export const EmptyState = Empty;
export const ErrorNote = ({ children }: { children: ReactNode }) => <div className="errnote" role="alert">{children}</div>;
export const Note = ({ children, warn }: { children: ReactNode; warn?: boolean }) => <div className={`note ${warn ? "warn" : ""}`}>{children}</div>;
export const ErrorState = ({ children, onRetry }: { children: ReactNode; onRetry?: () => void }) => (
  <div className="errnote row spread" role="alert"><span>{children}</span>{onRetry && <Btn small onClick={onRetry}>Retry</Btn>}</div>
);
export const Spinner = () => <span className="spinner" role="status" aria-label="Loading" />;
export const LoadingState = ({ rows = 3 }: { rows?: number }) => <div className="col" aria-busy="true">{Array.from({ length: rows }, (_, i) => <div key={i} className="shimmer" style={{ width: `${90 - i * 18}%` }} />)}</div>;

export const Loading = LoadingState;

export function Modal({ title, children, onClose, amber, role = "dialog", initialFocus }: { title: string; children: ReactNode; onClose?: () => void; amber?: boolean; role?: "dialog" | "alertdialog"; initialFocus?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    (ref.current?.querySelector<HTMLElement>(initialFocus ?? "button, input, select, textarea"))?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && onClose) onClose();
      if (e.key === "Tab" && ref.current) { // keep focus inside the dialog
        const f = ref.current.querySelectorAll<HTMLElement>("button:not(:disabled), input, select, textarea, a[href]");
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [onClose, initialFocus]);
  return (
    <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
      <div className={`modal ${amber ? "amber" : ""}`} role={role} aria-modal="true" aria-label={title} ref={ref}>
        <h2 style={{ marginBottom: 10 }}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Confirm({ title, body, confirmLabel, danger, onConfirm, onCancel }: { title: string; body: ReactNode; confirmLabel: string; danger?: boolean; onConfirm: () => void; onCancel: () => void }) {
  return (
    <Modal title={title} onClose={onCancel} initialFocus="button.cancel">
      <div className="col">{body}<div className="row spread" style={{ marginTop: 6 }}><Btn className="cancel" onClick={onCancel}>Cancel</Btn><Btn kind={danger ? "danger" : "primary"} onClick={onConfirm}>{confirmLabel}</Btn></div></div>
    </Modal>
  );
}

export function useNow(active: boolean, ms = 1000): number {
  const [n, setN] = useState(Date.now());
  useEffect(() => { if (!active) return; const t = setInterval(() => setN(Date.now()), ms); return () => clearInterval(t); }, [active, ms]);
  return n;
}
