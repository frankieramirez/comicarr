import { describe, expect, it } from "vitest";
import { settingValueErrors, typedInteger } from "@/lib/settingValues";
import { CONFIG_MINIMUMS } from "@/types/config.generated";

describe("settingValueErrors", () => {
  it("passes every minimum exactly", () => {
    expect(settingValueErrors({ ...CONFIG_MINIMUMS }, false)).toEqual({});
  });

  it("names each field below its minimum", () => {
    const errors = settingValueErrors(
      { search_interval: -5, search_delay: 4, ai_rpm_limit: 0 },
      false,
    );
    expect(Object.keys(errors).sort()).toEqual([
      "ai_rpm_limit",
      "search_delay",
      "search_interval",
    ]);
    expect(errors.search_interval).toBe(
      "Search interval must be 360 minutes or more.",
    );
  });

  it("refuses an empty number instead of inventing a default", () => {
    expect(typedInteger("")).toBeNaN();
    expect(typedInteger("12")).toBe(12);
    expect(
      settingValueErrors({ rss_checkinterval: typedInteger("") }, false),
    ).toEqual({ rss_checkinterval: "Enter a whole number." });
  });

  it("checks MangaDex lists but lets an empty list mean the default", () => {
    expect(
      settingValueErrors(
        {
          mangadex_languages: "en, pt-BR, english",
          mangadex_content_rating: "",
        },
        false,
      ),
    ).toEqual({
      mangadex_languages:
        "Unknown MangaDex language code: english. Use codes like en, ja or pt-br.",
    });
    expect(
      settingValueErrors({ mangadex_content_rating: "safe,spicy" }, false)
        .mangadex_content_rating,
    ).toContain("spicy");
  });

  it("needs a Discord webhook only when none is stored", () => {
    expect(
      settingValueErrors({ discord_enabled: true }, false).discord_webhook_url,
    ).toBeTruthy();
    expect(settingValueErrors({ discord_enabled: true }, true)).toEqual({});
    expect(
      settingValueErrors(
        { discord_enabled: true, discord_webhook_url: "https://x.example/h" },
        false,
      ),
    ).toEqual({});
  });
});
