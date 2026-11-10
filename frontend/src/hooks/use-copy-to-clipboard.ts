"use client";

import { useCallback, useRef, useState } from "react";

export function useCopyToClipboard() {
  const [text, setText] = useState<string | null>(null);
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const copy = useCallback(async (text: string) => {
    if (!navigator?.clipboard) {
      console.warn("Clipboard not supported");
      return false;
    }

    try {
      await navigator.clipboard.writeText(text);
      setText(text);
      if (resetTimer.current !== null) clearTimeout(resetTimer.current);
      resetTimer.current = setTimeout(() => setText(null), 3000);
      return true;
    } catch (error) {
      console.warn("Copy failed", error);
      setText(null);
      return false;
    }
  }, []);

  return { text, copy, isCopied: text !== null };
}
