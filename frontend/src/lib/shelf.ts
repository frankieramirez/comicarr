import { t } from "@lingui/core/macro";
import { ApiError } from "@/lib/api";
import { formatNumber } from "@/lib/intl";

/** A price for display: "4.99". The shelf keeps no currency. */
export function formatCents(cents: number): string {
  return formatNumber(cents / 100, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * "4.99", "4,99" or "5" typed into the price box, as whole cents.
 * Empty is null; anything else unreadable is undefined.
 */
export function parseCents(text: string): number | null | undefined {
  const normalized = text.trim().replace(",", ".");
  if (!normalized) return null;
  if (!/^\d{1,9}(\.\d{0,2})?$/.test(normalized)) return undefined;
  const [whole, fraction = ""] = normalized.split(".");
  return Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
}

export function centsToInput(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "";
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

/** The shelf API's error code, translated. */
export function shelfErrorMessage(error: unknown): string {
  const code = error instanceof ApiError ? error.body?.code : undefined;
  switch (code) {
    case "series_not_found":
      return t`This series is no longer in the library.`;
    case "item_not_found":
      return t`This issue is no longer in the library.`;
    case "copy_not_found":
      return t`This copy was already removed.`;
    case "field_too_long":
      return t`That text is too long.`;
    default:
      return t`The shelf could not be updated. Please try again.`;
  }
}
