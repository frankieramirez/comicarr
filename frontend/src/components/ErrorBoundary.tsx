import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

/**
 * Error Boundary component to catch React errors and prevent app crashes
 * Must be a class component as error boundaries require componentDidCatch
 */
class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(_error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("Error Boundary caught an error:", error, errorInfo);
    this.setState({
      error: error,
      errorInfo: errorInfo,
    });
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <main className="relative grid min-h-screen place-items-center overflow-hidden bg-background px-5 py-8 sm:p-8">
          <div
            aria-hidden="true"
            className="absolute inset-0 bg-[radial-gradient(circle_at_25%_10%,color-mix(in_oklab,var(--primary)_13%,transparent),transparent_32rem)]"
          />
          <section
            aria-labelledby="error-heading"
            className="relative grid w-full max-w-3xl overflow-hidden rounded-xl border border-border bg-card shadow-2xl shadow-black/10 md:grid-cols-[10.5rem_1fr]"
          >
            <div className="flex min-h-36 flex-col justify-between bg-[var(--primary)] px-6 py-5 text-primary-foreground md:min-h-full">
              <div className="flex items-center justify-between md:block">
                <span className="font-mono text-[10px] font-medium tracking-[0.18em] text-primary-foreground/80">
                  COMICARR
                </span>
                <span className="font-mono text-[10px] font-medium tracking-[0.18em] text-primary-foreground/80 md:mt-2 md:block">
                  RECOVERY
                </span>
              </div>
              <AlertTriangle
                aria-hidden="true"
                className="hidden h-12 w-12 stroke-[1.5] md:block"
              />
              <span className="hidden font-mono text-[10px] tracking-[0.18em] text-primary-foreground/80 md:block">
                SCREEN 01
              </span>
            </div>

            <div className="p-6 sm:p-8 md:p-10">
              <p className="mono-label text-[var(--status-error)]">App error</p>
              <h1
                id="error-heading"
                className="mt-3 max-w-lg text-2xl font-semibold leading-tight text-foreground sm:text-3xl"
              >
                This screen needs a fresh start.
              </h1>
              <p className="mt-4 max-w-xl text-sm leading-6 text-muted-foreground sm:text-base">
                Comicarr ran into a problem while rendering this page. Reload to
                start it again; this action does not change your library or
                settings.
              </p>

              <div className="mt-7 border-y border-border py-4">
                <p className="font-mono text-[11px] leading-5 text-muted-foreground">
                  If this keeps happening, check the browser console or server
                  logs for more information.
                </p>
              </div>

              {import.meta.env.DEV && this.state.error && (
                <details className="group mt-6 rounded-md border border-border bg-muted/40 px-4 py-3 text-left">
                  <summary className="cursor-pointer list-none font-mono text-[11px] font-medium text-foreground marker:content-none">
                    <span className="inline-flex items-center gap-2">
                      <span className="text-muted-foreground transition-transform group-open:rotate-90">
                        ›
                      </span>
                      Development error details
                    </span>
                  </summary>
                  <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap break-words border-t border-border pt-3 font-mono text-[11px] leading-5 text-muted-foreground">
                    {this.state.error.toString()}
                    {"\n\n"}
                    {this.state.errorInfo?.componentStack}
                  </pre>
                </details>
              )}

              <Button
                onClick={this.handleReload}
                className="mt-7 w-full sm:w-auto"
                size="lg"
              >
                <RefreshCw aria-hidden="true" />
                Reload Comicarr
              </Button>
            </div>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
