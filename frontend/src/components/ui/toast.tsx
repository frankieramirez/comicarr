import * as React from "react"
import { X, CheckCircle, AlertCircle, Info } from "lucide-react"
import { cn } from "@/lib/utils"

type ToastType = "success" | "error" | "info"

interface ToastData {
  id?: string
  type?: ToastType
  title?: string
  description?: string
  message?: string
  duration?: number
}

interface ToastContextValue {
  addToast: (toast: ToastData) => string
  removeToast: (id: string) => void
}

const ToastContext = React.createContext<ToastContextValue | null>(null)

interface ToastProviderProps {
  children: React.ReactNode
}

export function ToastProvider({ children }: ToastProviderProps) {
  const [toasts, setToasts] = React.useState<(ToastData & { id: string })[]>([])

  const addToast = React.useCallback((toast: ToastData): string => {
    const id = Math.random().toString(36).substr(2, 9)
    const newToast = { ...toast, id }
    setToasts((prev) => [...prev, newToast])

    // Auto-dismiss after duration (default 5s)
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, toast.duration || 5000)

    return id
  }, [])

  const removeToast = React.useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  return (
    <ToastContext.Provider value={{ addToast, removeToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-md">
        {toasts.map((toast) => (
          <Toast key={toast.id} {...toast} onClose={() => removeToast(toast.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const context = React.useContext(ToastContext)
  if (!context) {
    throw new Error("useToast must be used within ToastProvider")
  }
  return context
}

interface ToastProps extends ToastData {
  onClose: () => void
}

function Toast({ type = "info", title, description, message, onClose }: ToastProps) {
  const icons: Record<ToastType, React.ReactNode> = {
    success: <CheckCircle className="w-5 h-5" style={{ color: 'var(--status-active)' }} />,
    error: <AlertCircle className="w-5 h-5" style={{ color: 'var(--status-error)' }} />,
    info: <Info className="w-5 h-5" style={{ color: 'var(--info)' }} />,
  }

  const styles: Record<ToastType, string> = {
    success: "bg-[var(--status-active-bg)] border-[var(--status-active)]",
    error: "bg-[var(--status-error-bg)] border-[var(--status-error)]",
    info: "bg-[var(--status-wanted-bg)] border-[var(--info)]",
  }

  // Support both 'message' and 'description' for backwards compatibility
  const content = message || description

  return (
    <div
      className={cn(
        "flex items-start gap-3 p-4 rounded-lg border shadow-lg animate-in slide-in-from-right",
        styles[type]
      )}
    >
      {icons[type]}
      <div className="flex-1">
        {title && <div className="font-medium text-sm">{title}</div>}
        {content && <div className="text-sm text-gray-600 mt-1">{content}</div>}
      </div>
      <button
        onClick={onClose}
        className="text-gray-400 hover:text-gray-600 transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}
