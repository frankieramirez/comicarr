import { afterEach, describe, expect, it, vi } from "vitest";
import { i18n } from "@lingui/core";
import {
  formatBytes,
  formatCompactDuration,
  formatDate,
  formatLocale,
  formatNumber,
  formatRelative,
  largestUnit,
} from "@/lib/intl";

function withLocale(locale: string) {
  i18n.loadAndActivate({ locale, messages: {} });
}

afterEach(() => withLocale("en"));

describe("intl formatting follows the active language", () => {
  const day = new Date(2026, 10, 11, 21, 40);

  it("formats dates in English and German", () => {
    withLocale("en");
    expect(formatDate(day, { month: "short", day: "numeric" })).toBe("Nov 11");
    withLocale("de");
    expect(formatDate(day, { month: "short", day: "numeric" })).toBe(
      "11. Nov.",
    );
  });

  it("formats numbers with the language's separators", () => {
    withLocale("en");
    expect(formatNumber(12345.5)).toBe("12,345.5");
    withLocale("de");
    expect(formatNumber(12345.5)).toBe("12.345,5");
  });

  it("formats sizes in binary multiples", () => {
    expect(formatBytes(1.4 * 1024 ** 3)).toBe("1.4 GB");
    expect(formatBytes(512)).toBe("512B");
  });
});

describe("relative time", () => {
  const now = new Date("2026-11-16T12:00:00Z");

  it("uses the largest whole unit", () => {
    expect(largestUnit(12 * 60_000)).toEqual({ amount: 12, unit: "minute" });
    expect(largestUnit(11 * 86_400_000)).toEqual({ amount: 11, unit: "day" });
    expect(largestUnit(400 * 86_400_000)).toEqual({ amount: 1, unit: "year" });
  });

  it("says ago or in", () => {
    expect(formatRelative(new Date(now.getTime() - 3_600_000), now)).toBe(
      "1 hour ago",
    );
    expect(formatRelative(new Date(now.getTime() + 3 * 86_400_000), now)).toBe(
      "in 3 days",
    );
  });

  it("keeps months distinct from minutes in compact form", () => {
    expect(formatCompactDuration(9 * 60_000)).toBe("9m");
    expect(formatCompactDuration(2 * 3_600_000)).toBe("2h");
    expect(formatCompactDuration(60 * 86_400_000)).not.toBe("2m");
  });
});

describe("formatLocale", () => {
  it("uses the browser's regional variant of the UI language", () => {
    const spy = vi
      .spyOn(navigator, "languages", "get")
      .mockReturnValue(["en-GB", "en"]);
    withLocale("en");
    expect(formatLocale()).toBe("en-GB");
    spy.mockRestore();
  });

  it("never formats in a language the UI is not in", () => {
    const spy = vi
      .spyOn(navigator, "languages", "get")
      .mockReturnValue(["de-DE"]);
    withLocale("en");
    expect(formatLocale()).toBe("en");
    spy.mockRestore();
  });
});
