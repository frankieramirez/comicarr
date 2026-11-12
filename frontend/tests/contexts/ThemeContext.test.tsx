import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { ThemeProvider, useTheme } from "@/contexts/ThemeContext";

function Probe() {
  const { theme, preference, setPreference } = useTheme();
  return (
    <div>
      <span data-testid="state">{`${preference}:${theme}`}</span>
      <button onClick={() => setPreference("light")}>light</button>
      <button onClick={() => setPreference("system")}>system</button>
    </div>
  );
}

/** A matchMedia whose dark-mode answer the test can flip. */
function stubSystem(dark: boolean) {
  let listener: (() => void) | null = null;
  const media = {
    matches: dark,
    addEventListener: (_: string, fn: () => void) => (listener = fn),
    removeEventListener: vi.fn(),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => media),
  );
  return (next: boolean) => {
    media.matches = next;
    listener?.();
  };
}

describe("ThemeProvider", () => {
  afterEach(() => {
    localStorage.removeItem("comicarr-theme");
  });

  it("follows the OS by default and keeps following it", () => {
    const setSystem = stubSystem(true);
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("state").textContent).toBe("system:dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    act(() => setSystem(false));
    expect(screen.getByTestId("state").textContent).toBe("system:light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(localStorage.getItem("comicarr-theme")).toBe("system");
  });

  it("keeps an explicit choice when the OS changes", () => {
    const setSystem = stubSystem(true);
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    act(() => screen.getByRole("button", { name: "light" }).click());
    act(() => setSystem(true));
    expect(screen.getByTestId("state").textContent).toBe("light:light");
    expect(localStorage.getItem("comicarr-theme")).toBe("light");
  });

  it("restores a saved choice", () => {
    stubSystem(false);
    localStorage.setItem("comicarr-theme", "dark");
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("state").textContent).toBe("dark:dark");
  });
});
