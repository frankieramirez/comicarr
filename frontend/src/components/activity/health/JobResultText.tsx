import { t } from "@lingui/core/macro";
import { useState } from "react";
import { cn } from "@/lib/utils";

/** Results shorter than this fit on the row and need no toggle. */
const SHORT = 72;

/**
 * A job's last result on one line, with a toggle that shows all of it.
 * A failing job's error is often a path or a stack frame, and cutting it off
 * hid exactly the part that says what broke (#1493).
 */
export function JobResultText({
  text,
  failing,
  className,
}: {
  text: string;
  failing: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const style = failing ? { color: "var(--status-error)" } : undefined;
  const tone = failing ? "font-mono text-xs" : "text-foreground-2";
  if (text.length <= SHORT) {
    return (
      <span className={cn("truncate", tone, className)} style={style}>
        {text}
      </span>
    );
  }
  return (
    <button
      type="button"
      aria-expanded={open}
      onClick={() => setOpen((value) => !value)}
      title={open ? t`Show less` : t`Show the full message`}
      className={cn(
        "min-w-0 text-start hover:underline",
        open ? "whitespace-pre-wrap break-words" : "truncate",
        tone,
        className,
      )}
      style={style}
    >
      {text}
    </button>
  );
}
