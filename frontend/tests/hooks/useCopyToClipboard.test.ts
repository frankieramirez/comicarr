import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "../test-utils";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useCopyToClipboard", () => {
  it("gives a second copy its full three seconds", async () => {
    const { result } = renderHook(() => useCopyToClipboard());

    await act(() => result.current.copy("first"));
    act(() => vi.advanceTimersByTime(2000));
    await act(() => result.current.copy("second"));

    act(() => vi.advanceTimersByTime(1000));
    expect(result.current.isCopied).toBe(true);
    expect(result.current.text).toBe("second");

    act(() => vi.advanceTimersByTime(1999));
    expect(result.current.isCopied).toBe(true);

    act(() => vi.advanceTimersByTime(1));
    expect(result.current.isCopied).toBe(false);
  });
});
