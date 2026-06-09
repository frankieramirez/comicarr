import { describe, it, expect, vi, beforeEach } from "vitest";
import { waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "../mocks/server";
import { http, HttpResponse } from "msw";
import { render, screen } from "../test-utils";
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
});
