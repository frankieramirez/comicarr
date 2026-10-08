import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import WhatsNewArchive from "@/components/whats-new/WhatsNewArchive";

describe("WhatsNewArchive", () => {
  it("shows recent history when nothing is pending", async () => {
    server.use(
      http.get("/api/system/whats-new/archive", () =>
        HttpResponse.json({
          sections: [
            { version: "0.21.0", bullets: ["a"] },
            { version: "0.20.12", bullets: ["b"] },
          ],
          pending: null,
          current: "0.21.0",
          last_seen: "0.21.0",
        }),
      ),
    );

    render(createElement(WhatsNewArchive));

    const summary = await screen.findByTestId("whats-new-archive-summary");
    expect(summary.textContent).toMatch(/Running 0\.21\.0\. Nothing unread/);
    expect(screen.getByRole("button", { name: /0\.21\.0/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Mark as read" })).toBeNull();
  });

  it("shows unread badge and Mark as read when pending", async () => {
    server.use(
      http.get("/api/system/whats-new/archive", () =>
        HttpResponse.json({
          sections: [
            { version: "0.21.0", bullets: ["new thing"] },
            { version: "0.20.12", bullets: ["older"] },
          ],
          pending: { from: "0.20.12", to: "0.21.0" },
          current: "0.21.0",
          last_seen: "0.20.12",
        }),
      ),
    );
    let dismissCalls = 0;
    server.use(
      http.post("/api/system/whats-new/dismiss", () => {
        dismissCalls += 1;
        return HttpResponse.json({
          success: true,
          last_seen_version: "0.21.0",
        });
      }),
    );

    const user = userEvent.setup();
    render(createElement(WhatsNewArchive));

    expect((await screen.findByTestId("whats-new-unread")).textContent).toBe(
      "1 unread",
    );
    expect(screen.getByTestId("whats-new-archive-summary").textContent).toMatch(
      /You upgraded from 0\.20\.12/,
    );
    await user.click(screen.getByRole("button", { name: "Mark as read" }));
    await waitFor(() => {
      expect(dismissCalls).toBe(1);
    });
  });

  it("always shows version rows in the archive list", async () => {
    server.use(
      http.get("/api/system/whats-new/archive", () =>
        HttpResponse.json({
          sections: [{ version: "0.21.0", bullets: ["solo"] }],
          pending: { from: "0.20.12", to: "0.21.0" },
          current: "0.21.0",
          last_seen: "0.20.12",
        }),
      ),
    );

    render(createElement(WhatsNewArchive));
    expect(
      await screen.findByRole("button", { name: /0\.21\.0/ }),
    ).toBeTruthy();
  });

  it("shows an alert when Mark as read fails", async () => {
    server.use(
      http.get("/api/system/whats-new/archive", () =>
        HttpResponse.json({
          sections: [{ version: "0.21.0", bullets: ["new thing"] }],
          pending: { from: "0.20.12", to: "0.21.0" },
          current: "0.21.0",
          last_seen: "0.20.12",
        }),
      ),
      http.post("/api/system/whats-new/dismiss", () =>
        HttpResponse.json({ error: "boom" }, { status: 500 }),
      ),
    );
    const rejections: unknown[] = [];
    const onRejection = (event: PromiseRejectionEvent) => {
      rejections.push(event.reason);
    };
    window.addEventListener("unhandledrejection", onRejection);
    const user = userEvent.setup();
    render(createElement(WhatsNewArchive));
    await user.click(
      await screen.findByRole("button", { name: "Mark as read" }),
    );
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(rejections).toEqual([]);
    window.removeEventListener("unhandledrejection", onRejection);
  });
});
