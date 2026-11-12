import { format, formatDistanceToNowStrict } from "date-fns";

function parseDate(value: string): Date | null {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

const COMPACT_UNITS: Record<string, string> = {
  second: "s",
  minute: "m",
  hour: "h",
  day: "d",
  month: "mo",
  year: "y",
};

/** "9 minutes ago" becomes "9m": for narrow rails where the column says when. */
function compactDistance(date: Date): string {
  const [amount, unit] = formatDistanceToNowStrict(date).split(" ");
  const key = unit.replace(/s$/, "");
  return `${amount}${COMPACT_UNITS[key] ?? key}`;
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
      title={format(date, "PPpp")}
      className="mono-meta whitespace-nowrap"
    >
      {compact
        ? compactDistance(date)
        : formatDistanceToNowStrict(date, { addSuffix: true })}
    </time>
  );
}
