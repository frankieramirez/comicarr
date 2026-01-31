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
    onUnhandledRequest: "warn", // Warn about unhandled requests during tests
  });
});

// Reset handlers after each test (remove any test-specific handlers)
afterEach(() => {
  cleanup();
  server.resetHandlers();
});

// Close MSW server after all tests
afterAll(() => {
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
  }))
);

// Mock ResizeObserver
vi.stubGlobal(
  "ResizeObserver",
  vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  }))
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
  }))
);

// =============================================================================
// Console Mocks (optional - suppress certain warnings during tests)
// =============================================================================

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
