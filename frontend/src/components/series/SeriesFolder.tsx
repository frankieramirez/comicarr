import { ph, plural, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useState } from "react";
import { FolderOpen, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import {
  useUpdateSeriesLocation,
  type SeriesLocationResult,
} from "@/hooks/useSeries";
import { ApiError } from "@/lib/api";

function stayReadable(count: number) {
  return plural(count, {
    one: "# file stays readable where it was.",
    other: "# files stay readable where they were.",
  });
}

function describeLocationChange(result: SeriesLocationResult): string {
  const location = result.comic_location ?? "";
  const previous = result.previous_location ?? "";
  const destination = t`New downloads and imports go to ${location}.`;
  const moved = result.files_moved;
  if (moved > 0 && result.files_left === 0) {
    const movedFrom = plural(moved, {
      one: `Moved # file from ${previous}.`,
      other: `Moved # files from ${previous}.`,
    });
    return `${movedFrom} ${destination}`;
  }
  if (result.files_left > 0) {
    const left = stayReadable(result.files_left);
    if (moved > 0) {
      const movedOnly = plural(moved, {
        one: "Moved # file.",
        other: "Moved # files.",
      });
      return `${movedOnly} ${left} ${destination}`;
    }
    return `${left} ${destination}`;
  }
  return destination;
}

function partialMoveMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const left = error.body?.files_left;
    if (typeof left === "number" && left > 0) {
      return `${error.userMessage} ${stayReadable(left)}`;
    }
    return error.userMessage;
  }
  return t`Comicarr could not change the folder. Try again.`;
}

interface SeriesFolderProps {
  comicId: string;
  location?: string | null;
  override: boolean;
  /** Folders that still hold files left behind by an earlier change. */
  retained: string[];
}

export function SeriesFolder({
  comicId,
  location,
  override,
  retained,
}: SeriesFolderProps) {
  const [open, setOpen] = useState(false);
  const [folder, setFolder] = useState(location ?? "");
  const [moveFiles, setMoveFiles] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mutation = useUpdateSeriesLocation();
  const { addToast } = useToast();

  const openDialog = () => {
    setFolder(location ?? "");
    setMoveFiles(false);
    setError(null);
    setOpen(true);
  };

  const save = async (nextFolder: string | null) => {
    setError(null);
    try {
      const result = await mutation.mutateAsync({
        comicId,
        folder: nextFolder,
        moveFiles,
      });
      setOpen(false);
      addToast({
        type: "success",
        title: result.override
          ? t`Series folder changed`
          : t`Series folder is automatic again`,
        description: describeLocationChange(result),
      });
    } catch (saveError) {
      setError(partialMoveMessage(saveError));
    }
  };

  const trimmed = folder.trim();

  return (
    <section
      className="rounded-lg border border-border-subtle bg-surface-1 px-4 py-3"
      aria-labelledby="series-folder-title"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              id="series-folder-title"
              className="text-[13px] font-semibold"
            >
              <Trans>Library folder</Trans>
            </span>
            <span className="mono-label">
              {override ? t`chosen` : t`automatic`}
            </span>
          </div>
          <p className="mono-meta mt-1 break-all" data-testid="series-folder">
            {location || t`Not set yet`}
          </p>
          {retained.length > 0 ? (
            <p className="mt-1 text-[13px] leading-relaxed text-foreground-2">
              {t`Earlier files are still read from ${ph({ folders: retained.join(", ") })}.`}
            </p>
          ) : null}
        </div>
        <Button variant="outline" size="sm" onClick={openDialog}>
          <FolderOpen aria-hidden="true" />
          <Trans>Change folder</Trans>
        </Button>
      </div>

      <Dialog
        open={open}
        onOpenChange={(next) => !mutation.isPending && setOpen(next)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              <Trans>Library folder</Trans>
            </DialogTitle>
            <DialogDescription>
              <Trans>
                Choose a folder on the server, inside one of your library roots.
                New downloads and imports for this series are placed, renamed
                and tagged there.
              </Trans>
            </DialogDescription>
          </DialogHeader>

          <form
            className="grid gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (trimmed) void save(trimmed);
            }}
          >
            <div className="grid gap-1.5">
              <Label htmlFor="series-folder-input">
                <Trans>Folder</Trans>
              </Label>
              <Input
                id="series-folder-input"
                value={folder}
                onChange={(event) => setFolder(event.target.value)}
                placeholder="/comics/Magazines/Wizard"
                className="font-mono"
                autoComplete="off"
                spellCheck={false}
              />
              <p className="text-xs text-muted-foreground">
                <Trans>
                  Use the path Comicarr sees. In Docker, that is the path inside
                  the container. Extra roots are listed under Settings, Folders
                  and naming.
                </Trans>
              </p>
            </div>

            <fieldset className="grid gap-2">
              <legend className="mb-1 text-sm font-medium">
                <Trans>Files already in the library</Trans>
              </legend>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="series-folder-files"
                  checked={!moveFiles}
                  onChange={() => setMoveFiles(false)}
                  className="mt-1 accent-primary"
                />
                <span>
                  <Trans>
                    Leave them where they are
                    <span className="block text-xs text-muted-foreground">
                      They stay readable from their current folder.
                    </span>
                  </Trans>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="series-folder-files"
                  checked={moveFiles}
                  onChange={() => setMoveFiles(true)}
                  className="mt-1 accent-primary"
                />
                <span>
                  <Trans>
                    Move them to the new folder
                    <span className="block text-xs text-muted-foreground">
                      Only this series&apos; files move. Nothing moves if a file
                      with the same name is already there.
                    </span>
                  </Trans>
                </span>
              </label>
            </fieldset>

            {error ? (
              <p role="alert" className="text-sm text-[var(--status-error)]">
                {error}
              </p>
            ) : null}

            <DialogFooter className="gap-2 sm:justify-between">
              {override ? (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={mutation.isPending}
                  onClick={() => void save(null)}
                >
                  <Trans>Use automatic folder</Trans>
                </Button>
              ) : (
                <span />
              )}
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={mutation.isPending}
                  onClick={() => setOpen(false)}
                >
                  <Trans>Cancel</Trans>
                </Button>
                <Button
                  type="submit"
                  disabled={!trimmed || mutation.isPending}
                  aria-busy={mutation.isPending}
                >
                  {mutation.isPending ? (
                    <LoaderCircle
                      className="animate-spin motion-reduce:animate-none"
                      aria-hidden="true"
                    />
                  ) : null}
                  {mutation.isPending ? t`Saving…` : t`Save folder`}
                </Button>
              </div>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
