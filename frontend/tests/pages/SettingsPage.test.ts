import { describe, expect, it } from "vitest";
import { prepareConfigSaveData } from "@/lib/configSave";

describe("prepareConfigSaveData", () => {
  it("omits blank redacted secrets and raw API key values from saves", () => {
    const saveData = prepareConfigSaveData(
      {
        api_key: "do-not-send",
        ai_api_key: "",
        comicvine_api: "",
        mal_client_id: "",
        prowl_keys: "",
        slack_webhook_url: "",
        mattermost_webhook_url: "",
        discord_webhook_url: "",
        comic_dir: "/comics",
      },
      {
        ai_api_key_set: true,
        comicvine_api_set: true,
        mal_client_id_set: true,
        prowl_keys_set: true,
        slack_webhook_url_set: true,
        mattermost_webhook_url_set: true,
        discord_webhook_url_set: true,
      },
    );

    expect(saveData).toEqual({ comic_dir: "/comics" });
  });

  it("keeps explicit replacement secret values", () => {
    const saveData = prepareConfigSaveData(
      {
        api_key: "do-not-send",
        comicvine_api: "x".repeat(40),
        discord_webhook_url: "https://discord.com/api/webhooks/new",
      },
      {
        comicvine_api_set: true,
        discord_webhook_url_set: true,
      },
    );

    expect(saveData).toEqual({
      comicvine_api: "x".repeat(40),
      discord_webhook_url: "https://discord.com/api/webhooks/new",
    });
  });
});
