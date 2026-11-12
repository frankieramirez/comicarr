/**
 * Week helpers shared by Releases > Mine and Industry. Weeks are
 * Sunday-based, matching the weekly pull list the backend stores.
 */

export function isoDay(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** Local midnight for an ISO day, so day arithmetic never crosses a zone. */
export function parseDay(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

/** The Sunday that opens the week holding `today`. */
export function weekStart(today: Date): string {
  const sunday = new Date(today);
  sunday.setHours(0, 0, 0, 0);
  sunday.setDate(today.getDate() - today.getDay());
  return isoDay(sunday);
}

/** Seven ISO days starting at `start`. */
export function weekDays(start: string): string[] {
  const first = parseDay(start);
  return Array.from({ length: 7 }, (_, i) => {
    const day = new Date(first);
    day.setDate(first.getDate() + i);
    return isoDay(day);
  });
}

export function formatDay(iso: string, withYear: boolean): string {
  return parseDay(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: withYear ? "numeric" : undefined,
  });
}

/** "Wednesday, Nov 11", for a day group heading. */
export function dayHeading(iso: string): string {
  return parseDay(iso).toLocaleDateString("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}

export function weekLabel(offset: number): string {
  if (offset === 0) return "This week";
  if (offset === 1) return "Next week";
  if (offset === -1) return "Last week";
  return offset > 1 ? `In ${offset} weeks` : `${-offset} weeks ago`;
}
