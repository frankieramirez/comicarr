/**
 * Global test setup for Vitest
 *
 * This file is loaded before each test file runs.
 * It configures the test environment, mocks, and global utilities.
 */

import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { server } from "./mocks/server";

// =============================================================================
// MSW Server Setup
// =============================================================================

// Start MSW server before all tests
beforeAll(() => {
  server.listen({
    // Unmocked fetches used to fall through to localhost, ECONNREFUSED after
    // the test finished, and race vitest 5's onUserConsoleLog RPC
    // (EnvironmentTeardownError) even when every assertion passed.
    onUnhandledRequest: "error",
  });
});

// Reset handlers after each test (remove any test-specific handlers)
afterEach(async () => {
  cleanup();
  // happy-dom kicks off <img> fetches after render; give intercepted
  // responses a turn to settle before MSW resets or the worker tears down.
  await new Promise((resolve) => setTimeout(resolve, 0));
  server.resetHandlers();
});

// Close MSW server after all tests
afterAll(async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));
  server.close();
});

// =============================================================================
// Browser API Mocks
// =============================================================================

// Mock sessionStorage
const sessionStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
    get length() {
      return Object.keys(store).length;
    },
    key: vi.fn((index: number) => Object.keys(store)[index] || null),
  };
})();

vi.stubGlobal("sessionStorage", sessionStorageMock);

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
    get length() {
      return Object.keys(store).length;
    },
    key: vi.fn((index: number) => Object.keys(store)[index] || null),
  };
})();

vi.stubGlobal("localStorage", localStorageMock);

// Mock window.scrollTo
vi.stubGlobal("scrollTo", vi.fn());

// Mock window.matchMedia
vi.stubGlobal(
  "matchMedia",
  vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
);

// Mock ResizeObserver
vi.stubGlobal(
  "ResizeObserver",
  class ResizeObserver {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
  },
);

// Mock IntersectionObserver
vi.stubGlobal(
  "IntersectionObserver",
  vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
    root: null,
    rootMargin: "",
    thresholds: [],
  })),
);

// =============================================================================
// Console Mocks (optional - suppress certain warnings during tests)
// =============================================================================

function isHappyDomTeardownAbortLog(args: unknown[]): boolean {
  const text = args
    .map((arg) => {
      if (typeof arg === "string") return arg;
      if (arg instanceof Error) return `${arg.name} ${arg.message}`;
      return "";
    })
    .join(" ");
  if (!/aborted|AbortError/i.test(text)) return false;
  return (
    text.includes("Session check failed") ||
    text.includes("Setup check failed") ||
    text.includes("Session verification failed") ||
    text.includes('Failed to execute "fetch()"') ||
    text.includes("The operation was aborted")
  );
}

// Suppress specific React warnings if needed
const originalConsoleError = console.error;
console.error = (...args: unknown[]) => {
  // Suppress certain known warnings during tests
  const suppressedWarnings = [
    "Warning: ReactDOM.render is no longer supported",
    "Warning: An update to",
  ];

  const message = args[0];
  if (
    typeof message === "string" &&
    suppressedWarnings.some((w) => message.includes(w))
  ) {
    return;
  }

  // happy-dom aborts AuthProvider session fetches during worker teardown.
  // Logging them races vitest's onUserConsoleLog RPC and fails the run with
  // EnvironmentTeardownError even when every assertion passed.
  if (isHappyDomTeardownAbortLog(args)) {
    return;
  }

  originalConsoleError.apply(console, args);
};

// =============================================================================
// Reset mocks between tests
// =============================================================================

afterEach(() => {
  // Clear all mocks
  vi.clearAllMocks();

  // Clear storage mocks
  sessionStorageMock.clear();
  localStorageMock.clear();
});

// =============================================================================
// Global test utilities
// =============================================================================

// Export storage mocks for direct manipulation in tests
export { sessionStorageMock, localStorageMock };

// =============================================================================
// i18n: every render gets an I18nProvider with the English catalog
// =============================================================================

// Components read strings through Lingui, which needs a provider. Tests render
// components directly with many different wrappers, so the provider is added
// to RTL's render/renderHook here instead of in each test.
vi.mock("@testing-library/react", async (importOriginal) => {
  const rtl = await importOriginal<typeof import("@testing-library/react")>();
  const React = await import("react");
  const { I18nProvider } = await import("@lingui/react");
  const { i18n, initI18n } = await import("@/lib/i18n");
  await initI18n();

  type Wrapper = React.JSXElementConstructor<{ children: React.ReactNode }>;
  const withI18n = (Inner?: Wrapper) =>
    function I18nWrapper({ children }: { children: React.ReactNode }) {
      const content = Inner
        ? React.createElement(Inner, null, children)
        : children;
      return React.createElement(I18nProvider, { i18n }, content);
    };

  const render: typeof rtl.render = ((ui: React.ReactNode, options = {}) =>
    rtl.render(ui, {
      ...options,
      wrapper: withI18n(options.wrapper as Wrapper | undefined),
    })) as typeof rtl.render;

  const renderHook: typeof rtl.renderHook = ((
    hook: (props: unknown) => unknown,
    options: { wrapper?: Wrapper } = {},
  ) =>
    rtl.renderHook(hook, {
      ...options,
      wrapper: withI18n(options.wrapper),
    })) as typeof rtl.renderHook;

  return { ...rtl, render, renderHook };
});
