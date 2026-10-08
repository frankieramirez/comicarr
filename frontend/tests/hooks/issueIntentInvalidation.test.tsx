import { describe, expect, it, vi } from "vitest";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createTestQueryClient, renderHook, waitFor } from "../test-utils";
import { useQueueIssue, useUnqueueIssue } from "@/hooks/useSeries";
import { useBulkQueueIssues, useBulkUnqueueIssues } from "@/hooks/useQueue";

function invalidatedKeys(spy: ReturnType<typeof vi.spyOn>): string[] {
  return spy.mock.calls.map((call) => {
    const filters = call[0] as { queryKey?: readonly unknown[] };
    return (filters.queryKey ?? []).join("/");
  });
}

function wrapperFor(queryClient: ReturnType<typeof createTestQueryClient>) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("issue intent mutations stale every status view", () => {
  it("queue invalidates dashboard upcoming", async () => {
    const queryClient = createTestQueryClient();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useQueueIssue(), {
      wrapper: wrapperFor(queryClient),
    });
    await result.current.mutateAsync("iss-1");
    await waitFor(() => {
      expect(invalidatedKeys(spy)).toContain("dashboard/upcoming");
    });
  });

  it("unqueue invalidates dashboard upcoming", async () => {
    const queryClient = createTestQueryClient();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useUnqueueIssue(), {
      wrapper: wrapperFor(queryClient),
    });
    await result.current.mutateAsync("iss-1");
    await waitFor(() => {
      expect(invalidatedKeys(spy)).toContain("dashboard/upcoming");
    });
  });

  it("bulk queue invalidates dashboard upcoming", async () => {
    const queryClient = createTestQueryClient();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useBulkQueueIssues(), {
      wrapper: wrapperFor(queryClient),
    });
    await result.current.mutateAsync(["iss-1"]);
    await waitFor(() => {
      expect(invalidatedKeys(spy)).toContain("dashboard/upcoming");
    });
  });

  it("bulk unqueue invalidates dashboard upcoming", async () => {
    const queryClient = createTestQueryClient();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useBulkUnqueueIssues(), {
      wrapper: wrapperFor(queryClient),
    });
    await result.current.mutateAsync(["iss-1"]);
    await waitFor(() => {
      expect(invalidatedKeys(spy)).toContain("dashboard/upcoming");
    });
  });
});
