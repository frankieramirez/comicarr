import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { server } from "../mocks/server";
import { render, screen, waitFor } from "../test-utils";
import WhatsNewModal, {
  MODAL_VERSION_CAP,
  WHATS_NEW_ARCHIVE_PATH,
} from "@/components/whats-new/WhatsNewModal";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const SECTIONS = [
  { version: "0.21.0", bullets: ["one"] },
  { version: "0.20.12", bullets: ["two"] },
  { version: "0.20.11", bullets: ["three"] },
  { version: "0.20.10", bullets: ["four"] },
  { version: "0.20.9", bullets: ["five"] },
];

function stubPending(sections = SECTIONS) {
  server.use(
    http.get("/api/system/version", () =>
      HttpResponse.json({
        release_version: "0.21.0",
        update_state: "current",
        pending_whats_new: { from: "0.20.8", to: "0.21.0" },
      }),
    ),
    http.get("/api/system/release-notes", () =>
      HttpResponse.json({ sections }),
    ),
  );
}

describe("WhatsNewModal", () => {
  it("renders nothing when there is no pending range", async () => {
    server.use(
      http.get("/api/system/version", () =>
        HttpResponse.json({
          release_version: "0.21.0",
          pending_whats_new: null,
        }),
      ),
    );

    render(createElement(WhatsNewModal));
    await waitFor(() => {
      expect(screen.queryByText("Comicarr updated")).toBeNull();
    });
  });

  it("caps at MODAL_VERSION_CAP versions and shows overflow without dismissing", async () => {
    stubPending();
    const user = userEvent.setup();
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

    render(createElement(WhatsNewModal));

    expect(await screen.findByText("Comicarr updated")).toBeTruthy();
    expect(screen.getByText("0.20.8 → 0.21.0")).toBeTruthy();
    // Wait for notes; version headings for the first three releases only.
    expect(await screen.findByRole("heading", { name: "0.21.0" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "0.20.12" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "0.20.11" })).toBeTruthy();
    // Cap: 4th version not shown as a heading in the modal body.
    expect(screen.queryByRole("heading", { name: "0.20.10" })).toBeNull();
    expect(screen.getByText("one")).toBeTruthy();
    expect(screen.queryByText("four")).toBeNull();

    const overflow = SECTIONS.length - MODAL_VERSION_CAP;
    const overflowBtn = await screen.findByRole("button", {
      name: new RegExp(`and ${overflow} earlier releases`, "i"),
    });
    await user.click(overflowBtn);

    expect(dismissCalls).toBe(0);
    expect(mockNavigate).toHaveBeenCalledWith(WHATS_NEW_ARCHIVE_PATH);
  });

  it("suppresses per-version heading on a single-release jump", async () => {
    stubPending([{ version: "0.21.0", bullets: ["only change"] }]);
    render(createElement(WhatsNewModal));

    expect(await screen.findByText("only change")).toBeTruthy();
    // Header already names the range; body heading for the sole section is omitted.
    expect(screen.queryByRole("heading", { name: "0.21.0" })).toBeNull();
  });

  it("renders unavailable with retry when notes fail, not the empty sentence", async () => {
    stubPending([{ version: "0.21.0", bullets: ["change"] }]);
    server.use(
      http.get("/api/system/release-notes", () =>
        HttpResponse.json({ detail: "unavailable" }, { status: 500 }),
      ),
    );

    render(createElement(WhatsNewModal));

    expect(await screen.findByText("Release notes unavailable")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Retry Release notes" }),
    ).toBeTruthy();
    expect(screen.getByText("Release notes could not load.")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Settings → About" })
        .getAttribute("href"),
    ).toBe(WHATS_NEW_ARCHIVE_PATH);
    expect(screen.getByRole("button", { name: "Got it" })).toBeTruthy();
    expect(
      screen.queryByText("No release notes recorded for this upgrade."),
    ).toBeNull();
  });

  it("Got it posts dismiss", async () => {
    stubPending([{ version: "0.21.0", bullets: ["change"] }]);
    const user = userEvent.setup();
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

    render(createElement(WhatsNewModal));
    expect(await screen.findByText("Got it")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Got it" }));

    await waitFor(() => {
      expect(dismissCalls).toBe(1);
    });
  });

  it("shows an alert when Got it fails", async () => {
    stubPending([{ version: "0.21.0", bullets: ["change"] }]);
    const user = userEvent.setup();
    server.use(
      http.post("/api/system/whats-new/dismiss", () =>
        HttpResponse.json({ error: "boom" }, { status: 500 }),
      ),
    );
    const rejections: unknown[] = [];
    const onRejection = (event: PromiseRejectionEvent) => {
      rejections.push(event.reason);
    };
    window.addEventListener("unhandledrejection", onRejection);
    render(createElement(WhatsNewModal));
    await user.click(await screen.findByRole("button", { name: "Got it" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(rejections).toEqual([]);
    window.removeEventListener("unhandledrejection", onRejection);
  });
});
