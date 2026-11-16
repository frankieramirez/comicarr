import { ph, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ImageOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useAddManga, useSearchManga } from "@/hooks/useSearch";
import { getErrorMessage } from "@/lib/api";
import type { SearchResult } from "@/types";

const MAX_MATCHES = 5;

function providerLabel(result: SearchResult): string {
  const source = (result.metadata_source || "").toLowerCase();
  if (source.includes("mal") || source.includes("myanimelist"))
    return "MyAnimeList";
  if (source.includes("mangadex")) return "MangaDex";
  return result.id.startsWith("mal-") ? "MyAnimeList" : "MangaDex";
}

/**
 * Adding a MangaUpdates release (#1383). Comicarr adds manga by MangaDex or
 * MyAnimeList id, so this finds the series there first and lets the
 * operator confirm the match before anything is added.
 */
export default function MangaAddDialog({
  title,
  onClose,
}: {
  title: string;
  onClose: () => void;
}) {
  const search = useSearchManga(title);
  const addManga = useAddManga();
  const queryClient = useQueryClient();
  const { addToast } = useToast();
  const matches = (search.data?.results ?? [])
    .filter((result) => !result.in_library)
    .slice(0, MAX_MATCHES);
  const [picked, setPicked] = useState<string | null>(null);
  const chosen = matches.some((match) => match.id === picked)
    ? picked
    : (matches[0]?.id ?? null);

  const add = async () => {
    const match = matches.find((result) => result.id === chosen);
    if (!match) return;
    try {
      await addManga.mutateAsync(match.id);
      queryClient.invalidateQueries({ queryKey: ["weekly"] });
      addToast({
        type: "success",
        title: t`Adding ${ph({ name: match.name })}`,
        description: t`The series is being added to your library.`,
      });
      onClose();
    } catch (err) {
      addToast({ type: "error", message: getErrorMessage(err) });
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            <Trans>Add {title}</Trans>
          </DialogTitle>
          <DialogDescription>
            <Trans>
              This release comes from MangaUpdates, so Comicarr looks for the
              same series in your manga provider. Pick the match to add.
            </Trans>
          </DialogDescription>
        </DialogHeader>

        <div
          className="space-y-2"
          role="radiogroup"
          aria-label={t`Matching series`}
        >
          {search.isLoading ? (
            Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-16 w-full" />
            ))
          ) : search.error ? (
            <p className="text-[13px]" style={{ color: "var(--status-error)" }}>
              {getErrorMessage(search.error)}
            </p>
          ) : matches.length === 0 ? (
            <p className="text-[13px] text-muted-foreground">
              <Trans>
                No match for “{title}” that isn’t already in your library. Try
                Add a series with another of its titles.
              </Trans>
            </p>
          ) : (
            matches.map((match) => {
              const selected = match.id === chosen;
              const year = match.comicyear || match.start_year;
              return (
                <button
                  key={match.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => setPicked(match.id)}
                  className={`flex w-full items-center gap-3 rounded-md border p-2 text-left text-[13px] transition-colors ${
                    selected
                      ? "border-primary bg-surface-2"
                      : "border-border-subtle hover:bg-surface-1"
                  }`}
                >
                  <span className="h-14 w-10 shrink-0 overflow-hidden rounded bg-muted">
                    {match.image ? (
                      <img
                        src={match.image}
                        alt=""
                        loading="lazy"
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <span className="flex h-full w-full items-center justify-center text-muted-foreground/50">
                        <ImageOff className="h-4 w-4" />
                      </span>
                    )}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium">
                      {match.name}
                    </span>
                    <span className="block text-muted-foreground">
                      {[providerLabel(match), year, match.status]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                </button>
              );
            })
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            <Trans>Cancel</Trans>
          </Button>
          <Button
            onClick={() => void add()}
            disabled={!chosen || addManga.isPending}
          >
            {addManga.isPending ? t`Adding…` : t`Add series`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
