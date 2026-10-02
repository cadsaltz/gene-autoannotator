const BADGE_TONES = {
  neutral: "border-line bg-surface-muted text-fg-secondary",
  brand: "border-brand-line bg-brand-tint text-brand-fg",
  success: "border-success-line bg-success-tint text-success-fg",
  warning: "border-warning-line bg-warning-tint text-warning-fg",
};

export function Badge({ tone = "neutral", dot = false, title, className = "", children }) {
  return (
    <span
      title={title}
      className={`inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium leading-[18px] ${BADGE_TONES[tone]} ${className}`}
    >
      {dot ? <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-current" /> : null}
      <span className="truncate">{children}</span>
    </span>
  );
}

export function Card({ as: Tag = "section", className = "", children, ...props }) {
  return (
    <Tag className={`min-w-0 rounded-xl border border-line bg-surface shadow-xs ${className}`} {...props}>
      {children}
    </Tag>
  );
}

export function CardHeader({ title, aside = null }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h3 className="shrink-0 text-sm font-semibold text-fg">{title}</h3>
      {aside}
    </div>
  );
}

export function Meter({ value, className = "" }) {
  const percent = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <span className={`block h-1.5 flex-1 overflow-hidden rounded-full bg-surface-sunken ${className}`}>
      <span className="block h-full rounded-full bg-brand-fg" style={{ width: `${percent}%` }} />
    </span>
  );
}
