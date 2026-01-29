import * as React from "react"
import { cn } from "@/lib/utils"

const Button = React.forwardRef(({ className, variant = "default", size = "default", disabled, ...props }, ref) => {
  const variants = {
    default: "bg-blue-600 text-white hover:bg-blue-700 disabled:bg-gray-400",
    destructive: "bg-red-600 text-white hover:bg-red-700",
    outline: "border border-gray-300 bg-white hover:bg-gray-50",
    ghost: "hover:bg-gray-100",
  }

  const sizes = {
    default: "h-10 px-4 py-2",
    sm: "h-9 px-3 text-sm",
    lg: "h-11 px-8",
  }

  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
        variants[variant],
        sizes[size],
        className
      )}
      ref={ref}
      disabled={disabled}
      {...props}
    />
  )
})
Button.displayName = "Button"

export { Button }
