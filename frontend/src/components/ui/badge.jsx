import * as React from "react"
import { cn } from "@/lib/utils"

const Badge = React.forwardRef(({ className, variant = "default", ...props }, ref) => {
  const variants = {
    default: "bg-gray-100 text-gray-800",
    active: "bg-green-100 text-green-800",
    paused: "bg-yellow-100 text-yellow-800",
    ended: "bg-gray-100 text-gray-600",
    error: "bg-red-100 text-red-800",
    wanted: "bg-blue-100 text-blue-800",
    downloaded: "bg-green-100 text-green-800",
    skipped: "bg-gray-100 text-gray-600",
  }

  return (
    <span
      ref={ref}
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors",
        variants[variant],
        className
      )}
      {...props}
    />
  )
})
Badge.displayName = "Badge"

export { Badge }
