import { useEffect, useRef } from "react";

export function useHotKey(callback: () => void, key: string): void {
  const callbackRef = useRef(callback);
  // eslint-disable-next-line react-hooks/refs
  callbackRef.current = callback;

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key === key && (e.metaKey || e.ctrlKey)) {
        callbackRef.current();
      }
    }

    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
    };
  }, [key]);
}
