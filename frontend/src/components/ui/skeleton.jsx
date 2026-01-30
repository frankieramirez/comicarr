import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-muted/50 relative overflow-hidden",
        "before:absolute before:inset-0",
        "before:bg-gradient-to-r before:from-transparent before:via-background/40 before:to-transparent",
        "before:animate-shimmer",
        className
      )}
      {...props}
    />
  )
}

export { Skeleton }
