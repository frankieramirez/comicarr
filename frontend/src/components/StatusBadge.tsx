import { statusTone } from "@/lib/statusTone";

interface StatusBadgeProps {
  status?: string | null;
  showIcon?: boolean;
  variant?: "pill" | "dot";
  /** Override the vocabulary label (health chips keep their own copy). */
  label?: string;
  title?: string;
  className?: string;
}

export default function StatusBadge({
  status,
  showIcon = true,
  variant = "pill",
  label,
  title,
  className,
}: StatusBadgeProps) {
  const tone = statusTone(status);
  if (!tone) return null;

  const text = label ?? tone.label;
  const caption = title;

  // v2: status is always a 6px dot plus plain text. The dot carries the
  // tone; the words stay in readable secondary text. "pill" keeps a slightly
  // larger label for headers, "dot" is the dense row form.
  const textClass =
    variant === "dot"
      ? "inline-flex items-center gap-1.5 text-xs text-foreground-2"
      : "inline-flex items-center gap-2 text-[13px] text-foreground-2";
  // "Needs you" states keep the words at full contrast, not just the dot.
  const needsYou = tone.badgeVariant === "error";
  return (
    <span
      className={className ?? textClass}
      title={caption}
      aria-label={caption ? `${text}: ${caption}` : text}
    >
      {showIcon && (
        <span
          data-testid="status-dot"
          className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: tone.token }}
        />
      )}
      <span className={needsYou ? "text-foreground" : undefined}>{text}</span>
    </span>
  );
}
