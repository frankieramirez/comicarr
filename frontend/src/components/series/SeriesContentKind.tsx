import { LoaderCircle } from "lucide-react";
import type { ContentType } from "@/types";

const KIND_COPY: Record<ContentType, { label: string; description: string }> = {
  comic: {
    label: "Comic",
    description: "Use comic issue labels and matching rules.",
  },
  manga: {
    label: "Manga",
    description: "Use manga chapter labels and matching rules.",
  },
};

interface SeriesContentKindProps {
  value: ContentType;
  provider: string;
  pending: boolean;
  onChange: (value: ContentType) => void;
}

export function SeriesContentKind({
  value,
  provider,
  pending,
  onChange,
}: SeriesContentKindProps) {
  return (
    <section
      className="mb-3.5 max-w-[640px] rounded-[6px] border p-3"
      style={{
        borderColor: "var(--border)",
        background: "color-mix(in oklab, var(--primary) 4%, var(--background))",
      }}
      aria-labelledby="content-kind-title"
    >
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px] sm:items-center">
        <div>
          <div id="content-kind-title" className="text-[12px] font-semibold">
            Catalog this as
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            {KIND_COPY[value].description} Metadata still comes from {provider}.
          </p>
          <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
            Future labels and matching follow this choice. Existing files and
            issue history stay unchanged. Switching to manga also stores the
            series under the manga destination so downloads can import; files
            already on disk are not moved.
          </p>
        </div>
        <div
          role="radiogroup"
          aria-label="Content kind"
          aria-busy={pending}
          className="relative grid grid-cols-2 rounded-[5px] border border-border bg-background p-0.5"
        >
          {(Object.keys(KIND_COPY) as ContentType[]).map((kind) => {
            const active = value === kind;
            return (
              <button
                key={kind}
                type="button"
                role="radio"
                aria-checked={active}
                disabled={pending}
                onClick={() => onChange(kind)}
                onKeyDown={(event) => {
                  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight")
                    return;
                  event.preventDefault();
                  onChange(kind === "comic" ? "manga" : "comic");
                }}
                className={`rounded-[3px] px-3 py-2 font-mono text-[12px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-wait disabled:opacity-70 ${
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground"
                }`}
              >
                {KIND_COPY[kind].label}
              </button>
            );
          })}
          {pending ? (
            <span className="pointer-events-none absolute inset-0 grid place-items-center rounded-[3px] bg-background/70">
              <LoaderCircle
                className="size-4 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
              <span className="sr-only">Saving content kind</span>
            </span>
          ) : null}
        </div>
      </div>
    </section>
  );
}
