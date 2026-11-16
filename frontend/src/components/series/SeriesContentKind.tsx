import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { LoaderCircle } from "lucide-react";
import type { SeriesKind } from "@/types";

const KIND_COPY = (): Record<
  SeriesKind,
  { label: string; description: string }
> => ({
  comic: {
    label: t`Comic`,
    description: t`Use comic issue labels and matching rules.`,
  },
  manga: {
    label: t`Manga`,
    description: t`Use manga chapter labels and matching rules.`,
  },
  magazine: {
    label: t`Magazine`,
    description: t`Search and download like a comic, and keep it with your magazines.`,
  },
});

const KINDS = Object.keys(KIND_COPY()) as SeriesKind[];

interface SeriesContentKindProps {
  value: SeriesKind;
  provider: string;
  pending: boolean;
  onChange: (value: SeriesKind) => void;
}

export function SeriesContentKind({
  value,
  provider,
  pending,
  onChange,
}: SeriesContentKindProps) {
  return (
    <section
      className="rounded-lg border border-border-subtle bg-surface-1 px-4 py-3"
      aria-labelledby="content-kind-title"
    >
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px] sm:items-center">
        <div>
          <div id="content-kind-title" className="text-[13px] font-semibold">
            <Trans>Catalog this as</Trans>
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-foreground-2">
            {KIND_COPY()[value].description}{" "}
            <Trans>Metadata still comes from {provider}.</Trans>
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            <Trans>
              Future labels and matching follow this choice. Existing files and
              issue history stay unchanged. Switching to manga or magazine also
              stores the series under that destination so downloads import
              there, unless you chose its folder; files already on disk are not
              moved.
            </Trans>
          </p>
        </div>
        <div
          role="radiogroup"
          aria-label={t`Content kind`}
          aria-busy={pending}
          className="relative grid grid-cols-3 rounded-md border border-border-subtle bg-background p-0.5"
        >
          {KINDS.map((kind, index) => {
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
                  const step = event.key === "ArrowRight" ? 1 : -1;
                  onChange(KINDS[(index + step + KINDS.length) % KINDS.length]);
                }}
                className={`rounded-control px-3 py-1.5 text-[13px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-wait disabled:opacity-70 ${
                  active
                    ? "bg-surface-3 text-foreground"
                    : "text-foreground-2 hover:text-foreground"
                }`}
              >
                {KIND_COPY()[kind].label}
              </button>
            );
          })}
          {pending ? (
            <span className="pointer-events-none absolute inset-0 grid place-items-center rounded-[3px] bg-background/70">
              <LoaderCircle
                className="size-4 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
              <span className="sr-only">
                <Trans>Saving content kind</Trans>
              </span>
            </span>
          ) : null}
        </div>
      </div>
    </section>
  );
}
