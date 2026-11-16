/**
 * Locale-aware date, time, number and relative-time formatting.
 *
 * Every user-facing date or number goes through here so it follows the
 * language the app is running in (`i18n.locale`), not a hardcoded "en-US" and
 * not whatever the browser happens to default to. ESLint bans `"en-US"`,
 * `toLocaleDateString`/`toLocaleTimeString` and `new Intl.*` everywhere else,
 * so this file (src/lib/intl.ts) is the one seam.
 *
 * Formatters are cached per locale and options: building an `Intl` formatter is
 * far more expensive than calling one, and lists render many rows.
 */
import { i18n } from "@lingui/core";

/**
 * The BCP 47 tag `Intl` should use: the browser's own regional variant of the
 * language the UI is in (UI "en" + browser "en-GB" gives day-first dates),
 * otherwise the UI language itself. Dates never switch to a language the text
 * is not in.
 */
export function formatLocale(): string {
  const ui = i18n.locale || "en";
  const base = ui.split("-")[0].toLowerCase();
  const preferred =
    typeof navigator === "undefined"
      ? []
      : (navigator.languages ?? [navigator.language]);
  const regional = preferred.find(
    (tag) => tag && tag.split("-")[0].toLowerCase() === base,
  );
  return regional || ui;
}

/**
 * Base languages written right to left. Kept as a list rather than asking
 * `Intl.Locale#getTextInfo()`, which Firefox does not implement.
 */
const RTL_LANGUAGES = new Set([
  "ar",
  "arc",
  "ckb",
  "dv",
  "fa",
  "he",
  "ks",
  "ku",
  "ps",
  "sd",
  "syr",
  "ug",
  "ur",
  "yi",
]);

/** Writing direction for a BCP 47 tag, for `<html dir>` and Base UI. */
export function localeDirection(locale: string): "ltr" | "rtl" {
  const base = locale.split("-")[0].toLowerCase();
  return RTL_LANGUAGES.has(base) ? "rtl" : "ltr";
}

const cache = new Map<string, unknown>();

function cached<T>(kind: string, options: object, build: () => T): T {
  const key = `${kind}|${formatLocale()}|${JSON.stringify(options)}`;
  let formatter = cache.get(key) as T | undefined;
  if (formatter === undefined) {
    formatter = build();
    cache.set(key, formatter);
  }
  return formatter;
}

export function dateTimeFormat(
  options: Intl.DateTimeFormatOptions = {},
): Intl.DateTimeFormat {
  return cached(
    "dt",
    options,
    () => new Intl.DateTimeFormat(formatLocale(), options),
  );
}

export function numberFormat(
  options: Intl.NumberFormatOptions = {},
): Intl.NumberFormat {
  return cached(
    "num",
    options,
    () => new Intl.NumberFormat(formatLocale(), options),
  );
}

function relativeTimeFormat(
  options: Intl.RelativeTimeFormatOptions = {},
): Intl.RelativeTimeFormat {
  return cached(
    "rel",
    options,
    () => new Intl.RelativeTimeFormat(formatLocale(), options),
  );
}

export function formatDate(
  date: Date,
  options: Intl.DateTimeFormatOptions = {},
): string {
  return dateTimeFormat(options).format(date);
}

export function formatNumber(
  value: number,
  options: Intl.NumberFormatOptions = {},
): string {
  return numberFormat(options).format(value);
}

/** "a, b, and c" in the reader's language. `type: "disjunction"` gives "or". */
export function formatList(
  items: string[],
  options: Intl.ListFormatOptions = {},
): string {
  const opts: Intl.ListFormatOptions = { type: "conjunction", ...options };
  return cached(
    "list",
    opts,
    () => new Intl.ListFormat(formatLocale(), opts),
  ).format(items);
}

/** "1.4 GB". Binary multiples, labelled the way download clients label them. */
export function formatBytes(bytes: number): string {
  const units = ["byte", "kilobyte", "megabyte", "gigabyte", "terabyte"];
  const unit = Math.max(
    0,
    Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1),
  );
  return formatNumber(bytes / 1024 ** unit, {
    style: "unit",
    unit: units[unit],
    // "byte" has no short form in English ("512 byte"); narrow gives "512B".
    unitDisplay: unit === 0 ? "narrow" : "short",
    maximumFractionDigits: 1,
  });
}

type RelativeUnit = "second" | "minute" | "hour" | "day" | "month" | "year";

/**
 * The single largest whole unit for a distance, using the same thresholds as
 * date-fns `formatDistanceStrict`: seconds under a minute, minutes under an
 * hour, hours under a day, days under 30, months under 12, then years.
 */
export function largestUnit(ms: number): {
  amount: number;
  unit: RelativeUnit;
} {
  const seconds = Math.abs(ms) / 1000;
  const minutes = seconds / 60;
  const hours = minutes / 60;
  const days = hours / 24;
  if (seconds < 60) return { amount: Math.round(seconds), unit: "second" };
  if (minutes < 60) return { amount: Math.round(minutes), unit: "minute" };
  if (hours < 24) return { amount: Math.round(hours), unit: "hour" };
  if (days < 30) return { amount: Math.round(days), unit: "day" };
  const months = Math.round(days / 30);
  if (months < 12) return { amount: months, unit: "month" };
  return { amount: Math.round(days / 365), unit: "year" };
}

/** "12 minutes ago", "in 3 days". `numeric: "always"`, so never "yesterday". */
export function formatRelative(date: Date, now: Date = new Date()): string {
  const diff = date.getTime() - now.getTime();
  const { amount, unit } = largestUnit(diff);
  return relativeTimeFormat({ numeric: "always" }).format(
    diff < 0 ? -amount : amount,
    unit,
  );
}

/**
 * "9m", "2h", "3d": for narrow rails where the column already says "ago".
 * Months and years use the short form, because English narrow writes a month
 * as "m" and it would read as minutes.
 */
export function formatCompactDuration(ms: number): string {
  const { amount, unit } = largestUnit(ms);
  return formatNumber(amount, {
    style: "unit",
    unit,
    unitDisplay: unit === "month" || unit === "year" ? "short" : "narrow",
  });
}

/** Compact time since `date`, measured now: "9m". */
export function formatCompactSince(date: Date, now: Date = new Date()): string {
  return formatCompactDuration(now.getTime() - date.getTime());
}
