import { useEffect, useRef, useState } from "react";

interface LazyModuleState<T> {
  module: T | null;
  error: Error | null;
}

const IDLE: LazyModuleState<never> = { module: null, error: null };

/**
 * Loads an optional chunk the first time `active` is true and keeps the
 * module for the rest of the session. A rejected import is reported as
 * `error` and cleared again when `active` drops, so the next activation
 * starts a fresh import instead of replaying the stale failure.
 *
 * Kept as an effect rather than `React.lazy` for the same reason as
 * RouteLoader: React caches a rejected lazy import and would never retry.
 */
export function useLazyModule<T>(
  active: boolean,
  load: () => Promise<T>,
  fallbackMessage: string,
): LazyModuleState<T> {
  const loadRef = useRef(load);
  const [state, setState] = useState<LazyModuleState<T>>(IDLE);
  const [seenActive, setSeenActive] = useState(active);

  // Adjust state during render when the trigger changes (react.dev: "you
  // might not need an effect"): a failure only lives for one activation.
  if (seenActive !== active) {
    setSeenActive(active);
    if (!active && state.error) setState(IDLE);
  }

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    if (!active || state.module || state.error) return;
    let cancelled = false;
    loadRef
      .current()
      .then((module) => {
        if (!cancelled) setState({ module, error: null });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            module: null,
            error: error instanceof Error ? error : new Error(fallbackMessage),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [active, fallbackMessage, state.error, state.module]);

  return state;
}
