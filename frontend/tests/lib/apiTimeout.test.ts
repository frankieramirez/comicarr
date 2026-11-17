import { describe, expect, it } from "vitest";
import { delay, http, HttpResponse } from "msw";
import { server } from "../mocks/server";
import { apiGetWithTimeout } from "@/lib/api";

describe("apiGetWithTimeout", () => {
  it("turns a hung request into an error the page can show (#1500)", async () => {
    server.use(
      http.get("/api/hang", async () => {
        await delay("infinite");
        return HttpResponse.json({});
      }),
    );
    await expect(apiGetWithTimeout("/api/hang", 50)).rejects.toThrow(
      /took more than 0 seconds/,
    );
  });

  it("returns the answer when it comes in time", async () => {
    server.use(http.get("/api/quick", () => HttpResponse.json({ ok: 1 })));
    await expect(apiGetWithTimeout("/api/quick", 1000)).resolves.toEqual({
      ok: 1,
    });
  });
});
