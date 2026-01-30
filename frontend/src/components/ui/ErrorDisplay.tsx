import { AlertCircle, RefreshCw, WifiOff, ServerOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getErrorMessage, isRetryableError } from "@/lib/api";

interface ErrorDisplayProps {
  error: Error | unknown;
  title?: string;
  onRetry?: () => void;
  isRetrying?: boolean;
}

/**
 * User-friendly error display component with retry functionality
 */
export default function ErrorDisplay({
  error,
  title,
  onRetry,
  isRetrying = false,
}: ErrorDisplayProps) {
  const message = getErrorMessage(error);
  const canRetry = isRetryableError(error);

  // Determine icon based on error type
  const getIcon = () => {
    if (error instanceof Error) {
      if (
        error.message.includes("fetch") ||
        error.message.includes("network")
      ) {
        return <WifiOff className="w-8 h-8 text-[var(--status-error)]" />;
      }
      const httpMatch = error.message.match(/status: (\d+)/);
      if (httpMatch) {
        const status = parseInt(httpMatch[1], 10);
        if (status >= 500) {
          return <ServerOff className="w-8 h-8 text-[var(--status-error)]" />;
        }
      }
    }
    return <AlertCircle className="w-8 h-8 text-[var(--status-error)]" />;
  };

  return (
    <div className="flex flex-col items-center justify-center py-12 px-4">
      <div className="bg-[var(--status-error-bg)] rounded-full p-4 mb-4">
        {getIcon()}
      </div>
      <h3 className="text-lg font-semibold text-foreground mb-2">
        {title || "Something went wrong"}
      </h3>
      <p className="text-muted-foreground text-center max-w-md mb-6">
        {message}
      </p>
      {onRetry && canRetry && (
        <Button
          onClick={onRetry}
          disabled={isRetrying}
          variant="outline"
          className="flex items-center"
        >
          <RefreshCw
            className={`w-4 h-4 mr-2 ${isRetrying ? "animate-spin" : ""}`}
          />
          {isRetrying ? "Retrying..." : "Try Again"}
        </Button>
      )}
    </div>
  );
}
