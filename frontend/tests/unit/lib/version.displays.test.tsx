/**
 * Render-level coverage for every user-facing version display consumer (#412).
 * Each surface must show the shared formatAppVersion() helper output.
 */
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { waitFor } from "@testing-library/react";
import { server } from "../../mocks/server";
import { render, screen } from "../../test-utils";
import { formatAppVersion } from "@/lib/version";
import { SidebarProvider } from "@/components/ui/sidebar";
import AppSidebar from "@/components/layout/AppSidebar";
import OnboardingDialog from "@/components/onboarding/OnboardingDialog";
import LoginPage from "@/pages/LoginPage";
import SettingsPage from "@/pages/SettingsPage";

describe("version display consumers", () => {
  it("LoginPage badge uses formatAppVersion()", async () => {
    server.use(
      http.get("/api/auth/check-setup", () =>
        HttpResponse.json({ success: true, needs_setup: false }),
      ),
    );
    render(createElement(LoginPage));
    expect(await screen.findByText(formatAppVersion())).toBeTruthy();
  });

  it("OnboardingDialog welcome label uses formatAppVersion()", async () => {
    render(
      createElement(OnboardingDialog, {
        open: true,
        onFinish: vi.fn(),
      }),
    );
    expect(
      await screen.findByText(`Welcome · ${formatAppVersion()}`),
    ).toBeTruthy();
  });

  it("AppSidebar badge uses formatAppVersion(false)", async () => {
    server.use(
      http.get("/api/ai/chat/threads", () =>
        HttpResponse.json({ threads: [], next_cursor: null }),
      ),
    );
    render(createElement(SidebarProvider, null, createElement(AppSidebar)));
    expect(await screen.findByText(formatAppVersion(false))).toBeTruthy();
  });

  it("Settings header and About use formatAppVersion()", async () => {
    server.use(
      http.get("/api/config", () =>
        HttpResponse.json({
          version: "0.19.13",
          config_path: "/config/config.ini",
          data_dir: "/data",
          python_version: "3.12.0",
        }),
      ),
    );
    const user = userEvent.setup();
    render(createElement(SettingsPage));

    expect(
      await screen.findByText(`${formatAppVersion()} · /config/config.ini`, {
        exact: false,
      }),
    ).toBeTruthy();
    expect(screen.queryByText(/0\.19\.13/)).toBeNull();

    await user.click(screen.getAllByRole("button", { name: "About" })[0]);
    await waitFor(() => {
      expect(screen.getByText(formatAppVersion(false))).toBeTruthy();
    });
    expect(screen.queryByText("0.19.13")).toBeNull();
  });
});
