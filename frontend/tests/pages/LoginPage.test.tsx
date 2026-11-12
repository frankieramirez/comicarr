import { describe, it, expect, vi, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../mocks/server";
import { http, HttpResponse } from "msw";
import { render, screen } from "../test-utils";
import { formatAppVersion } from "@/lib/version";
import LoginPage from "@/pages/LoginPage";

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders setup form when needs_setup is true", async () => {
    server.use(
      http.get("/api/auth/check-setup", () => {
        return HttpResponse.json({ success: true, needs_setup: true });
      }),
    );

    render(<LoginPage />);

    await waitFor(() => {
      expect(screen.getByText("Create admin")).toBeTruthy();
    });

    expect(screen.getByPlaceholderText("Choose a username")).toBeTruthy();
    expect(
      screen.getByPlaceholderText("from server logs if required"),
    ).toBeTruthy();
    // The public sign-in page doesn't say which version is running.
    expect(screen.queryByText(formatAppVersion())).toBeNull();
    const confirm = screen.getByLabelText("Confirm password");
    expect(confirm).toBe(document.querySelectorAll("form input")[2]);
    expect((confirm as HTMLInputElement).placeholder).toBe("confirm");
  });

  it("submits setup token with credentials", async () => {
    let capturedBody: Record<string, string> | null = null;

    server.use(
      http.get("/api/auth/check-setup", () => {
        return HttpResponse.json({ success: true, needs_setup: true });
      }),
      http.post("/api/auth/setup", async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, string>;
        return HttpResponse.json({ success: true, username: "admin" });
      }),
    );

    render(<LoginPage />);

    await waitFor(() => {
      expect(screen.getByText("Create admin")).toBeTruthy();
    });

    await userEvent.type(
      screen.getByPlaceholderText("Choose a username"),
      "admin",
    );
    await userEvent.type(
      screen.getByPlaceholderText("min 8 characters"),
      "password123",
    );
    await userEvent.type(screen.getByPlaceholderText("confirm"), "password123");
    await userEvent.type(
      screen.getByPlaceholderText("from server logs if required"),
      "secret-token",
    );

    await userEvent.click(
      screen.getByRole("button", { name: /create account/i }),
    );

    await waitFor(() => {
      expect(capturedBody).toEqual({
        username: "admin",
        password: "password123",
        setup_token: "secret-token",
      });
    });
  });

  it("announces failed sign-in as an alert", async () => {
    server.use(
      http.get("/api/auth/check-setup", () => {
        return HttpResponse.json({ success: true, needs_setup: false });
      }),
      http.get("/api/auth/check-session", () => {
        return HttpResponse.json({ success: true, authenticated: false });
      }),
      http.post("/api/auth/login", () => {
        return HttpResponse.json({
          success: false,
          error: "Invalid username or password",
        });
      }),
    );

    render(<LoginPage />);

    await waitFor(() => {
      expect(screen.getByText("Sign in")).toBeTruthy();
    });

    await userEvent.type(screen.getByPlaceholderText("username"), "wronguser");
    await userEvent.type(screen.getByPlaceholderText("password"), "wrongpass");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Invalid username or password");
  });

  it("labels the login form fields from MonoLabel", async () => {
    render(<LoginPage />);

    await waitFor(() => {
      expect(screen.getByLabelText("Username")).toBeTruthy();
    });
    expect(screen.getByLabelText("Password")).toBeTruthy();
  });
});

describe("LoginPage cover wall", () => {
  it("draws the server's cover tiles when the wall is on", async () => {
    server.use(
      http.get("/api/auth/check-setup", () =>
        HttpResponse.json({ success: true, needs_setup: false }),
      ),
      http.get("/api/auth/cover-wall", () =>
        HttpResponse.json({ enabled: true, tiles: 2 }),
      ),
    );
    render(<LoginPage />);

    const wall = await screen.findByTestId("cover-wall");
    const sources = [...wall.querySelectorAll("img")].map((img) =>
      img.getAttribute("src"),
    );
    expect(new Set(sources)).toEqual(
      new Set(["/api/auth/cover-wall/0", "/api/auth/cover-wall/1"]),
    );
    expect(
      screen.getByText("self-hosted · your covers stay on this server"),
    ).toBeTruthy();
  });

  it("keeps the grid backdrop when the wall is off", async () => {
    server.use(
      http.get("/api/auth/check-setup", () =>
        HttpResponse.json({ success: true, needs_setup: false }),
      ),
    );
    render(<LoginPage />);
    await screen.findByText("COMICARR · READY");
    expect(screen.queryByTestId("cover-wall")).toBeNull();
  });
});
