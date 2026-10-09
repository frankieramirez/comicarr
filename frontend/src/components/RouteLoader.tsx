import {
  Component,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { Button } from "@/components/ui/button";

type RouteModule = { default: ComponentType };

interface RouteLoaderProps {
  load: () => Promise<RouteModule>;
}

interface RouteErrorBoundaryProps {
  children: ReactNode;
  onRetry: () => void;
  retryKey: number;
}

interface RouteErrorBoundaryState {
  error: Error | null;
}

class RouteErrorBoundary extends Component<
  RouteErrorBoundaryProps,
  RouteErrorBoundaryState
> {
  state: RouteErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): RouteErrorBoundaryState {
    return { error };
  }

  componentDidUpdate(previousProps: RouteErrorBoundaryProps) {
    if (this.state.error && previousProps.retryKey !== this.props.retryKey) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <section
          className="flex min-h-[12rem] items-center justify-center p-6"
          role="alert"
        >
          <div
            className="max-w-md rounded-lg border p-5 text-center"
            style={{
              borderColor:
                "color-mix(in oklab, var(--status-error) 35%, transparent)",
              background: "var(--status-error-bg)",
            }}
          >
            <h1 className="text-base font-semibold">
              Unable to load this page
            </h1>
            <p className="mt-2 text-[12px] text-muted-foreground">
              The page code did not load. Try again or choose another section.
            </p>
            <Button className="mt-4" onClick={this.props.onRetry} type="button">
              Try again
            </Button>
          </div>
        </section>
      );
    }

    return this.props.children;
  }
}

function RouteLoading() {
  return (
    <div
      className="flex min-h-[12rem] items-center justify-center p-6 font-mono text-[11px] text-muted-foreground"
      role="status"
      aria-live="polite"
    >
      Loading page…
    </div>
  );
}

/**
 * Loads a route module with a visible fallback and starts a fresh import on
 * retry. Keeping the module promise in an effect avoids React's cached lazy
 * rejection while preserving application navigation.
 */
export function RouteLoader({ load }: RouteLoaderProps) {
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);
  const [loaded, setLoaded] = useState<{
    attempt: number;
    component: ComponentType;
  } | null>(null);
  const [loadError, setLoadError] = useState<{
    attempt: number;
    error: Error;
  } | null>(null);

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    let cancelled = false;

    loadRef
      .current()
      .then((module) => {
        if (!cancelled) {
          setLoadError(null);
          setLoaded({ attempt, component: module.default });
        }
      })
      .catch((loadError: unknown) => {
        if (!cancelled) {
          setLoaded(null);
          setLoadError({
            attempt,
            error:
              loadError instanceof Error
                ? loadError
                : new Error("Route module failed to load"),
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = () => setAttempt((current) => current + 1);
  const LoadedRoute = loaded?.attempt === attempt ? loaded.component : null;
  const error = loadError?.attempt === attempt ? loadError.error : null;

  return (
    <RouteErrorBoundary onRetry={retry} retryKey={attempt}>
      {error ? (
        <RouteLoadError error={error} onRetry={retry} />
      ) : LoadedRoute ? (
        <LoadedRoute />
      ) : (
        <RouteLoading />
      )}
    </RouteErrorBoundary>
  );
}

function RouteLoadError({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => void;
}) {
  return (
    <section
      className="flex min-h-[12rem] items-center justify-center p-6"
      role="alert"
    >
      <div
        className="max-w-md rounded-lg border p-5 text-center"
        style={{
          borderColor:
            "color-mix(in oklab, var(--status-error) 35%, transparent)",
          background: "var(--status-error-bg)",
        }}
      >
        <h1 className="text-base font-semibold">Unable to load this page</h1>
        <p className="mt-2 text-[12px] text-muted-foreground">
          {error.message ||
            "The page code did not load. Try again or choose another section."}
        </p>
        <Button className="mt-4" onClick={onRetry} type="button">
          Try again
        </Button>
      </div>
    </section>
  );
}
