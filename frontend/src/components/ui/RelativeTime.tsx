import { formatCompactSince, formatDate, formatRelative } from "@/lib/intl";

function parseDate(value: string): Date | null {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export default function RelativeTime({
  value,
  compact = false,
}: {
  value?: string | null;
  compact?: boolean;
}) {
  const date = parseDate(value || "");
  if (!date) return <span className="text-muted-foreground">—</span>;

  return (
    <time
      dateTime={date.toISOString()}
      title={formatDate(date, { dateStyle: "medium", timeStyle: "short" })}
      className="mono-meta whitespace-nowrap"
    >
      {compact ? formatCompactSince(date) : formatRelative(date)}
    </time>
  );
}
