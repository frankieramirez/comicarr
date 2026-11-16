import { Trans } from "@lingui/react/macro";
import { cn } from "@/lib/utils";
import type { ReleaseNotesSection } from "@/types/version";

/** Changesets are Markdown, so a note can carry **bold** and `code`.
 *  Only those two inline forms are rendered; everything else stays text. */
function InlineMarkdown({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
          return (
            <strong key={i} className="font-medium text-foreground">
              {part.slice(2, -2)}
            </strong>
          );
        }
        if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
          return (
            <code key={i} className="font-mono text-[0.92em] text-foreground">
              {part.slice(1, -1)}
            </code>
          );
        }
        return part;
      })}
    </>
  );
}

const SUB_BULLET = /^\s*[-*]\s+/;

/**
 * Multi-paragraph bullet bodies from the mechanical transform (#450). A
 * changeset's own `- ` lines become a nested list instead of running into
 * the paragraph before them.
 */
export function BulletBody({ text }: { text: string }) {
  const blocks: { kind: "p" | "ul"; lines: string[] }[] = [];
  for (const para of text.split(/\n{2,}/)) {
    let current: { kind: "p" | "ul"; lines: string[] } | null = null;
    for (const line of para.split("\n")) {
      if (!line.trim()) continue;
      const bullet = SUB_BULLET.test(line);
      if (bullet) {
        if (current?.kind !== "ul") {
          current = { kind: "ul", lines: [] };
          blocks.push(current);
        }
        current.lines.push(line.replace(SUB_BULLET, ""));
      } else if (current?.kind === "ul" && /^\s/.test(line)) {
        // An indented continuation of the sub-bullet above it.
        current.lines[current.lines.length - 1] += ` ${line.trim()}`;
      } else {
        if (current?.kind !== "p") {
          current = { kind: "p", lines: [] };
          blocks.push(current);
        }
        current.lines.push(line.trim());
      }
    }
  }
  return (
    <>
      {blocks.map((block, i) =>
        block.kind === "ul" ? (
          <ul
            key={i}
            className={cn("list-disc space-y-1 ps-4", i > 0 && "mt-1.5")}
          >
            {block.lines.map((line, j) => (
              <li key={j}>
                <InlineMarkdown text={line} />
              </li>
            ))}
          </ul>
        ) : (
          <p key={i} className={i > 0 ? "mt-1.5" : undefined}>
            <InlineMarkdown text={block.lines.join(" ")} />
          </p>
        ),
      )}
    </>
  );
}

export function VersionSection({
  section,
  density = "comfortable",
  hideHeading = false,
}: {
  section: ReleaseNotesSection;
  density?: "comfortable" | "compact";
  hideHeading?: boolean;
}) {
  const compact = density === "compact";
  return (
    <section>
      {!hideHeading && (
        <div className="flex items-baseline gap-2">
          <h3
            className={cn(
              "font-mono font-semibold text-foreground",
              compact ? "text-[12px]" : "text-[13px]",
            )}
          >
            {section.version}
          </h3>
        </div>
      )}

      {section.bullets.length === 0 ? (
        <p
          className={cn(
            "mt-1 italic text-muted-foreground/70",
            compact ? "text-[11px]" : "text-[12px]",
          )}
        >
          <Trans>No notes recorded for this release.</Trans>
        </p>
      ) : (
        <ul
          className={cn(
            "mt-1.5 space-y-1.5 text-muted-foreground",
            compact
              ? "text-[11.5px] leading-snug"
              : "text-[12.5px] leading-relaxed",
          )}
        >
          {section.bullets.map((b, i) => (
            <li key={i} className="flex gap-2">
              <span
                aria-hidden
                className="mt-[0.45em] h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50"
              />
              <div className="min-w-0">
                <BulletBody text={b} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
