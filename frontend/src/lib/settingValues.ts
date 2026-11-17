import { ph, t } from "@lingui/core/macro";
import {
  CONFIG_MINIMUMS,
  type SettingsFormData,
} from "@/types/config.generated";

/**
 * Settings values the server refuses instead of changing quietly (#1492).
 *
 * The server check lives in `comicarr/app/config/setting_values.py` and
 * answers with a `code`, the `field` and `params`. The same codes are checked
 * here first, so most mistakes show on the field before a request is sent,
 * and the server's answer is shown with the same words when one slips past.
 */

type MinimumField = keyof typeof CONFIG_MINIMUMS;

export interface SettingRefusal {
  code: string;
  field: string;
  params?: Record<string, unknown>;
}

function belowMinimum(field: MinimumField, minimum: number): string {
  switch (field) {
    case "search_delay":
      return t`Search delay must be ${ph({ minimum })} seconds or more.`;
    case "search_interval":
      return t`Search interval must be ${ph({ minimum })} minutes or more.`;
    case "rss_checkinterval":
      return t`RSS check interval must be ${ph({ minimum })} minutes or more.`;
    case "dbupdate_interval":
      return t`Database update interval must be ${ph({ minimum })} minutes or more.`;
    case "ai_rpm_limit":
      return t`Requests per minute must be ${ph({ minimum })} or more.`;
  }
}

/** Help text naming a field's real minimum, so nobody has to guess it. */
export function minimumHint(field: MinimumField): string {
  const minimum = CONFIG_MINIMUMS[field];
  return t`Minimum ${ph({ minimum })}.`;
}

/** The message for a refusal, or null for a code this page doesn't know. */
export function settingRefusalMessage(refusal: SettingRefusal): string | null {
  const params = refusal.params ?? {};
  switch (refusal.code) {
    case "setting_below_minimum": {
      const minimum = Number(params.minimum);
      if (refusal.field in CONFIG_MINIMUMS && Number.isFinite(minimum)) {
        return belowMinimum(refusal.field as MinimumField, minimum);
      }
      return null;
    }
    case "setting_not_whole_number":
      return t`Enter a whole number.`;
    case "mangadex_language_unknown": {
      const codes = String(params.codes ?? "");
      return t`Unknown MangaDex language code: ${ph({ codes })}. Use codes like en, ja or pt-br.`;
    }
    case "mangadex_rating_unknown": {
      const ratings = String(params.ratings ?? "");
      return t`Unknown MangaDex content rating: ${ph({ ratings })}. Use safe, suggestive, erotica or pornographic.`;
    }
    case "discord_webhook_required":
      return t`Enter a Discord webhook URL to turn on Discord notifications.`;
    default:
      return null;
  }
}

/** Read a refusal out of an API error body, if it carries one. */
export function refusalFromBody(body: unknown): SettingRefusal | null {
  if (!body || typeof body !== "object") return null;
  const { code, field, params } = body as Record<string, unknown>;
  if (typeof code !== "string" || typeof field !== "string") return null;
  return {
    code,
    field,
    params:
      params && typeof params === "object"
        ? (params as Record<string, unknown>)
        : undefined,
  };
}

const LANGUAGE_CODE = /^[a-z]{2}(-[a-z]{2})?$/;
const CONTENT_RATINGS = ["safe", "suggestive", "erotica", "pornographic"];

function splitList(value: unknown): string[] {
  return String(value ?? "")
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean);
}

/**
 * The refusals the server would give for this form, checked before saving.
 * Keyed by field, one message each.
 */
export function settingValueErrors(
  data: SettingsFormData,
  discordWebhookStored: boolean,
): Record<string, string> {
  const errors: Record<string, string> = {};
  const add = (refusal: SettingRefusal) => {
    const message = settingRefusalMessage(refusal);
    if (message && !(refusal.field in errors)) errors[refusal.field] = message;
  };

  for (const [field, minimum] of Object.entries(CONFIG_MINIMUMS)) {
    const value = data[field as MinimumField];
    if (value === undefined) continue;
    if (!Number.isInteger(value)) {
      add({ code: "setting_not_whole_number", field });
    } else if (value < minimum) {
      add({ code: "setting_below_minimum", field, params: { minimum } });
    }
  }

  const languages = splitList(data.mangadex_languages).filter(
    (code) => !LANGUAGE_CODE.test(code),
  );
  if (languages.length > 0) {
    add({
      code: "mangadex_language_unknown",
      field: "mangadex_languages",
      params: { codes: languages.join(", ") },
    });
  }

  const ratings = splitList(data.mangadex_content_rating).filter(
    (rating) => !CONTENT_RATINGS.includes(rating),
  );
  if (ratings.length > 0) {
    add({
      code: "mangadex_rating_unknown",
      field: "mangadex_content_rating",
      params: { ratings: ratings.join(", ") },
    });
  }

  const webhook =
    typeof data.discord_webhook_url === "string"
      ? data.discord_webhook_url.trim()
      : "";
  if (data.discord_enabled === true && !webhook && !discordWebhookStored) {
    add({ code: "discord_webhook_required", field: "discord_webhook_url" });
  }

  return errors;
}

/**
 * Read a typed number without inventing one. An empty or unreadable field
 * becomes NaN, which the check above refuses, instead of a default that
 * would be saved silently.
 */
export function typedInteger(value: unknown): number {
  const text = String(value ?? "").trim();
  return /^-?\d+$/.test(text) ? Number(text) : Number.NaN;
}
