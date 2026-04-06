/**
 * Custom render utilities for testing React components with all required providers.
 *
 * This module provides a custom render function that wraps components
 * with all the providers they need (QueryClient, Router, Auth, Theme, etc.)
 */

import { type ReactElement, type ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, MemoryRouter } from "react-router-dom";
import { AuthProvider } from "@/contexts/AuthContext";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { ToastProvider } from "@/components/ui/toast";

// =============================================================================
// Types
// =============================================================================

interface WrapperProps {
  children: ReactNode;
}

interface CustomRenderOptions extends Omit<RenderOptions, "wrapper"> {
  /**
   * Initial route for MemoryRouter (e.g., "/search", "/series/123")
   */
  route?: string;
  /**
   * Use MemoryRouter instead of BrowserRouter (useful for testing specific routes)
   */
  useMemoryRouter?: boolean;
  /**
   * Custom QueryClient (defaults to a fresh test client)
   */
  queryClient?: QueryClient;
}

// =============================================================================
// Test Query Client Factory
// =============================================================================

/**
 * Create a fresh QueryClient configured for testing.
 *
 * Test clients have:
 * - No retries (fail fast)
 * - No caching (isolate tests)
 * - No refetching (predictable behavior)
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
        refetchOnWindowFocus: false,
        refetchOnMount: false,
        refetchOnReconnect: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

// =============================================================================
// Provider Wrappers
// =============================================================================

/**
 * Creates a wrapper component with all providers.
 */
function createAllProviders(options: CustomRenderOptions = {}): React.FC<WrapperProps> {
  const { route = "/", useMemoryRouter = false, queryClient } = options;
  const testQueryClient = queryClient ?? createTestQueryClient();

  return function AllProviders({ children }: WrapperProps) {
    const RouterComponent = useMemoryRouter ? MemoryRouter : BrowserRouter;
    const routerProps = useMemoryRouter ? { initialEntries: [route] } : {};

    return (
      <QueryClientProvider client={testQueryClient}>
        <RouterComponent {...routerProps}>
          <ThemeProvider>
            <ToastProvider>
              <AuthProvider>{children}</AuthProvider>
            </ToastProvider>
          </ThemeProvider>
        </RouterComponent>
      </QueryClientProvider>
    );
  };
}

/**
 * Minimal wrapper with just QueryClient and Router (no Auth/Theme).
 * Useful for testing isolated components.
 */
function createMinimalProviders(
  options: Pick<CustomRenderOptions, "route" | "useMemoryRouter" | "queryClient"> = {}
): React.FC<WrapperProps> {
  const { route = "/", useMemoryRouter = false, queryClient } = options;
  const testQueryClient = queryClient ?? createTestQueryClient();

  return function MinimalProviders({ children }: WrapperProps) {
    const RouterComponent = useMemoryRouter ? MemoryRouter : BrowserRouter;
    const routerProps = useMemoryRouter ? { initialEntries: [route] } : {};

    return (
      <QueryClientProvider client={testQueryClient}>
        <RouterComponent {...routerProps}>{children}</RouterComponent>
      </QueryClientProvider>
    );
  };
}

// =============================================================================
// Custom Render Functions
// =============================================================================

/**
 * Custom render function that wraps the component with all providers.
 *
 * @example
 * ```tsx
 * import { render, screen } from '../test-utils';
 *
 * test('renders component', () => {
 *   render(<MyComponent />);
 *   expect(screen.getByText('Hello')).toBeInTheDocument();
 * });
 * ```
 */
function customRender(
  ui: ReactElement,
  options: CustomRenderOptions = {}
): ReturnType<typeof render> {
  const { route, useMemoryRouter, queryClient, ...renderOptions } = options;

  return render(ui, {
    wrapper: createAllProviders({ route, useMemoryRouter, queryClient }),
    ...renderOptions,
  });
}

/**
 * Render with minimal providers (just QueryClient and Router).
 * Useful for testing components that don't need Auth/Theme contexts.
 */
function renderMinimal(
  ui: ReactElement,
  options: CustomRenderOptions = {}
): ReturnType<typeof render> {
  const { route, useMemoryRouter, queryClient, ...renderOptions } = options;

  return render(ui, {
    wrapper: createMinimalProviders({ route, useMemoryRouter, queryClient }),
    ...renderOptions,
  });
}

// =============================================================================
// Exports
// =============================================================================

// Re-export everything from @testing-library/react
export * from "@testing-library/react";

// Override render with our custom render
export { customRender as render, renderMinimal };

// Export provider factories for custom setups
export { createAllProviders, createMinimalProviders };
