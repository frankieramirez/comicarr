import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { render, screen } from "../test-utils";
import { ToggleChip } from "@/components/ui/toggle-chip";
import ReleasesPage from "@/pages/ReleasesPage";
import SettingsPage from "@/pages/SettingsPage";

function pressedName(name: string) {
  return screen.getByRole("button", { name }).getAttribute("aria-pressed");
}

function settingsChip(name: string) {
  const match = screen
    .getAllByRole("button", { name })
    .find((el) => el.hasAttribute("aria-pressed"));
  if (!match) {
    throw new Error(`no pressed-aware chip named ${name}`);
  }
  return match;
}

describe("ToggleChip", () => {
  it("moves aria-pressed when clicked", async () => {
    function Pair() {
      const [which, setWhich] = useState<"a" | "b">("a");
      return (
        <>
          <ToggleChip
            pressed={which === "a"}
            onPressedChange={() => setWhich("a")}
          >
            Alpha
          </ToggleChip>
          <ToggleChip
            pressed={which === "b"}
            onPressedChange={() => setWhich("b")}
          >
            Bravo
          </ToggleChip>
        </>
      );
    }
    const user = userEvent.setup();
    render(<Pair />);
    expect(pressedName("Alpha")).toBe("true");
    expect(pressedName("Bravo")).toBe("false");
    await user.click(screen.getByRole("button", { name: "Bravo" }));
    expect(pressedName("Alpha")).toBe("false");
    expect(pressedName("Bravo")).toBe("true");
  });

  it("uses foreground text when pressed so light theme stays readable", () => {
    render(
      <ToggleChip pressed onPressedChange={() => undefined}>
        Chip
      </ToggleChip>,
    );
    expect(screen.getByRole("button").className).toContain("text-foreground");
    expect(screen.getByRole("button").className).not.toContain("text-primary");
  });

  it("gives inactive chips a foreground hover", () => {
    render(
      <ToggleChip pressed={false} onPressedChange={() => undefined}>
        Chip
      </ToggleChip>,
    );
    expect(screen.getByRole("button").className).toContain(
      "hover:text-foreground",
    );
  });

  it("sizes xs ledger chips at 10px", () => {
    render(
      <ToggleChip
        size="xs"
        pressed={false}
        onPressedChange={() => undefined}
      >
        All 12
      </ToggleChip>,
    );
    expect(screen.getByRole("button").className).toContain("text-[10px]");
  });

  it("keeps a focus ring class on both sizes", () => {
    const { rerender } = render(
      <ToggleChip pressed={false} onPressedChange={() => undefined}>
        Chip
      </ToggleChip>,
    );
    expect(screen.getByRole("button").className).toContain(
      "focus-visible:ring-1",
    );
    rerender(
      <ToggleChip pressed size="md" onPressedChange={() => undefined}>
        Chip
      </ToggleChip>,
    );
    expect(screen.getByRole("button").className).toContain(
      "focus-visible:ring-ring",
    );
  });
});

describe("Releases filter chips", () => {
  it("presses exactly one of wanted-only / include-downloaded", async () => {
    const user = userEvent.setup();
    render(<ReleasesPage />);
    await screen.findByRole("button", { name: "wanted only" });
    expect(pressedName("wanted only")).toBe("true");
    expect(pressedName("include downloaded")).toBe("false");
    await user.click(
      screen.getByRole("button", { name: "include downloaded" }),
    );
    expect(pressedName("wanted only")).toBe("false");
    expect(pressedName("include downloaded")).toBe("true");
  });
});

describe("Settings mobile section chips", () => {
  it("presses exactly one section chip and moves on click", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);
    await screen.findByRole("heading", { level: 1, name: "Settings" });
    const group = screen.getByRole("group", { name: "Settings sections" });
    const chips = () =>
      [...group.querySelectorAll("button")].filter((el) =>
        el.hasAttribute("aria-pressed"),
      );
    const pressed = chips().filter(
      (el) => el.getAttribute("aria-pressed") === "true",
    );
    expect(pressed).toHaveLength(1);
    expect(pressed[0].textContent).toBe("General");
    await user.click(settingsChip("Logs"));
    const next = chips().filter(
      (el) => el.getAttribute("aria-pressed") === "true",
    );
    expect(next).toHaveLength(1);
    expect(next[0].textContent).toBe("Logs");
  });
});
