import { describe, expect, it, vi } from "vitest";
import { SidebarProvider } from "@/components/ui/sidebar";
import AppSidebar from "@/components/layout/AppSidebar";
import { renderMinimal, screen } from "../test-utils";

// The sidebar only launches Chat now. Keeping this mocked module explosive
// makes an accidental reintroduction of the eager thread query fail loudly.
vi.mock("@/hooks/useLibraryChat", () => ({
  useChatThreads: () => {
    throw new Error("sidebar must not load chat threads");
  },
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: { username: "tester" },
    logout: vi.fn(),
  }),
}));

vi.mock("@/contexts/ThemeContext", () => ({
  useTheme: () => ({ theme: "dark", toggleTheme: vi.fn() }),
}));

vi.mock("@/components/ui/toast", async () => {
  const actual = await vi.importActual<typeof import("@/components/ui/toast")>(
    "@/components/ui/toast",
  );
  return { ...actual, useToast: () => ({ addToast: vi.fn() }) };
});

describe("AppSidebar", () => {
  it("does not fetch chat threads just to render the chat launcher", () => {
    renderMinimal(
      <SidebarProvider>
        <AppSidebar />
      </SidebarProvider>,
      { useMemoryRouter: true },
    );

    expect(screen.getByText("ask about your library")).toBeTruthy();
  });
});
