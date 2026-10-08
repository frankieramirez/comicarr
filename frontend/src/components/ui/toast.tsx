import * as React from "react";
import { X, CheckCircle, AlertCircle, Info } from "lucide-react";
import { cn } from "@/lib/utils";

type ToastType = "success" | "error" | "info";

interface ToastData {
  id?: string;
  type?: ToastType;
  title?: string;
  description?: string;
  message?: string;
  duration?: number;
}

interface ToastContextValue {
  addToast: (toast: ToastData) => string;
  removeToast: (id: string) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

interface ToastProviderProps {
  children: React.ReactNode;
}

export function ToastProvider({ children }: ToastProviderProps) {
  const [toasts, setToasts] = React.useState<(ToastData & { id: string })[]>(
    [],
  );

  const addToast = React.useCallback((toast: ToastData): string => {
    const id = Math.random().toString(36).substr(2, 9);
    const newToast = { ...toast, id };
    setToasts((prev) => [...prev, newToast]);
    return id;
  }, []);

  const removeToast = React.useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ addToast, removeToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-md">
        {/* Persistent polite live region without role="status": page
            summaries (ImportPage, RouteLoader, etc.) already own that role. */}
        <div
          data-testid="toast-live-region"
          aria-live="polite"
          aria-relevant="additions text"
          className="flex flex-col gap-2"
        >
          {toasts
            .filter((toast) => toast.type !== "error")
            .map((toast) => (
              <Toast
                key={toast.id}
                {...toast}
                onClose={() => removeToast(toast.id)}
              />
            ))}
        </div>
        <div data-testid="toast-alert-region" className="flex flex-col gap-2">
          {toasts
            .filter((toast) => toast.type === "error")
            .map((toast) => (
              <Toast
                key={toast.id}
                {...toast}
                onClose={() => removeToast(toast.id)}
              />
            ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = React.useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return context;
}

interface ToastProps extends ToastData {
  onClose: () => void;
}

function Toast({
  type = "info",
  title,
  description,
  message,
  duration,
  onClose,
}: ToastProps) {
  const remainingMsRef = React.useRef(duration || 5000);
  const startedAtRef = React.useRef(0);
  const timeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const onCloseRef = React.useRef(onClose);
  const toastRef = React.useRef<HTMLDivElement>(null);
  const hoveredRef = React.useRef(false);
  const focusedRef = React.useRef(false);

  React.useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  const clearTimer = React.useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const startTimer = React.useCallback(() => {
    clearTimer();
    startedAtRef.current = Date.now();
    timeoutRef.current = setTimeout(() => {
      onCloseRef.current();
    }, remainingMsRef.current);
  }, [clearTimer]);

  const pauseTimer = React.useCallback(() => {
    if (timeoutRef.current === null) {
      return;
    }
    remainingMsRef.current = Math.max(
      0,
      remainingMsRef.current - (Date.now() - startedAtRef.current),
    );
    clearTimer();
  }, [clearTimer]);

  const resumeTimerIfIdle = React.useCallback(() => {
    if (!hoveredRef.current && !focusedRef.current) {
      startTimer();
    }
  }, [startTimer]);

  React.useEffect(() => {
    startTimer();
    return clearTimer;
  }, [startTimer, clearTimer]);

  const icons: Record<ToastType, React.ReactNode> = {
    success: (
      <CheckCircle
        className="w-5 h-5"
        style={{ color: "var(--status-active)" }}
      />
    ),
    error: (
      <AlertCircle
        className="w-5 h-5"
        style={{ color: "var(--status-error)" }}
      />
    ),
    info: (
      <Info className="w-5 h-5" style={{ color: "var(--status-wanted)" }} />
    ),
  };

  const styles: Record<ToastType, string> = {
    success: "bg-[var(--status-active-bg)] border-[var(--status-active)]",
    error: "bg-[var(--status-error-bg)] border-[var(--status-error)]",
    info: "bg-[var(--status-wanted-bg)] border-[var(--status-wanted)]",
  };

  const content = message || description;

  return (
    <div
      ref={toastRef}
      role={type === "error" ? "alert" : undefined}
      onMouseEnter={() => {
        hoveredRef.current = true;
        pauseTimer();
      }}
      onMouseLeave={() => {
        hoveredRef.current = false;
        resumeTimerIfIdle();
      }}
      onFocus={() => {
        focusedRef.current = true;
        pauseTimer();
      }}
      onBlur={(event: React.FocusEvent<HTMLDivElement>) => {
        const next = event.relatedTarget;
        if (next instanceof Node && toastRef.current?.contains(next)) {
          return;
        }
        focusedRef.current = false;
        resumeTimerIfIdle();
      }}
      data-testid="toast"
      className={cn(
        "flex items-start gap-3 p-4 rounded-lg border shadow-lg animate-in slide-in-from-right",
        styles[type],
      )}
    >
      {icons[type]}
      <div className="flex-1">
        {title && <div className="font-medium text-sm">{title}</div>}
        {content && (
          <div className="text-sm text-muted-foreground mt-1">{content}</div>
        )}
      </div>
      <button
        onClick={onClose}
        aria-label="Dismiss notification"
        className="text-muted-foreground hover:text-foreground transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
