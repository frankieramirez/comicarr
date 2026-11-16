import { describe, expect, it } from "vitest";
import { i18n } from "@lingui/core";
import {
  AVAILABLE_LOCALES,
  activateLocale,
  localeName,
  matchLocale,
} from "@/lib/i18n";

describe("matchLocale", () => {
  const available = ["en", "de", "pt-BR"];

  it("prefers an exact match, ignoring case", () => {
    expect(matchLocale(["pt-br"], available)).toBe("pt-BR");
  });

  it("falls back from a region to its base language", () => {
    expect(matchLocale(["de-AT"], available)).toBe("de");
  });

  it("falls back from a base language to a regional catalog", () => {
    expect(matchLocale(["pt"], available)).toBe("pt-BR");
  });

  it("walks the preference list in order", () => {
    expect(matchLocale(["ja", "de"], available)).toBe("de");
  });

  it("uses English when nothing matches", () => {
    expect(matchLocale(["ja", "ko"], available)).toBe("en");
    expect(matchLocale([], available)).toBe("en");
  });
});

describe("locales", () => {
  it("always offers English first", () => {
    expect(AVAILABLE_LOCALES[0]).toBe("en");
  });

  it("names a language in its own language", () => {
    expect(localeName("en")).toBe("English");
    expect(localeName("de")).toBe("Deutsch");
  });

  it("activates English for an unknown locale and marks the document", async () => {
    await activateLocale("xx-unknown");
    expect(i18n.locale).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    expect(document.documentElement.dir).toBe("ltr");
  });

  it("marks the document right-to-left for Arabic", async () => {
    await activateLocale("ar");
    expect(i18n.locale).toBe("ar");
    expect(document.documentElement.dir).toBe("rtl");
    await activateLocale("en");
    expect(document.documentElement.dir).toBe("ltr");
  });
});
