import { Badge } from "@/components/ui/badge";
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
  const caption = title ?? tone.description;

  if (variant === "dot") {
    return (
      <span
        className={
          className ??
          "inline-flex items-center gap-1.5 font-mono text-[10px] uppercase"
        }
        style={{ color: tone.token }}
        title={caption}
        aria-label={caption ? `${text}: ${caption}` : text}
      >
        {showIcon && (
          <span
            data-testid="status-dot"
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: tone.token }}
          />
        )}
        {text}
      </span>
    );
  }

  return (
    <Badge
      variant={tone.badgeVariant}
      className={className ?? "gap-1.5 rounded-full px-2.5 py-1"}
      title={caption}
    >
      {showIcon && (
        <span
          data-testid="status-dot"
          className="inline-block h-1.5 w-1.5 rounded-full"
          style={{
            backgroundColor: tone.token,
            boxShadow: `0 0 8px 2px color-mix(in srgb, ${tone.glowColor} 50%, transparent)`,
          }}
        />
      )}
      {text}
    </Badge>
  );
}
