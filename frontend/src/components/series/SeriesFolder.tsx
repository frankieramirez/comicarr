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

function files(count: number) {
  return `${count} ${count === 1 ? "file" : "files"}`;
}

function stayReadable(count: number) {
  return count === 1
    ? "1 file stays readable where it was."
    : `${count} files stay readable where they were.`;
}

function describeLocationChange(result: SeriesLocationResult): string {
  const destination = `New downloads and imports go to ${result.comic_location}.`;
  if (result.files_moved > 0 && result.files_left === 0) {
    return `Moved ${files(result.files_moved)} from ${result.previous_location}. ${destination}`;
  }
  if (result.files_left > 0) {
    const moved =
      result.files_moved > 0 ? `Moved ${files(result.files_moved)}. ` : "";
    return `${moved}${stayReadable(result.files_left)} ${destination}`;
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
  return "Comicarr could not change the folder. Try again.";
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
          ? "Series folder changed"
          : "Series folder is automatic again",
        description: describeLocationChange(result),
      });
    } catch (saveError) {
      setError(partialMoveMessage(saveError));
    }
  };

  const trimmed = folder.trim();

  return (
    <section
      className="mb-3.5 max-w-[640px] rounded-md border border-border p-3"
      aria-labelledby="series-folder-title"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span id="series-folder-title" className="text-xs font-semibold">
              Library folder
            </span>
            <span className="mono-label">
              {override ? "chosen" : "automatic"}
            </span>
          </div>
          <p className="mono-meta mt-1 break-all" data-testid="series-folder">
            {location || "Not set yet"}
          </p>
          {retained.length > 0 ? (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              Earlier files are still read from {retained.join(", ")}.
            </p>
          ) : null}
        </div>
        <Button variant="outline" size="sm" onClick={openDialog}>
          <FolderOpen aria-hidden="true" />
          Change folder
        </Button>
      </div>

      <Dialog
        open={open}
        onOpenChange={(next) => !mutation.isPending && setOpen(next)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Library folder</DialogTitle>
            <DialogDescription>
              Choose a folder on the server, inside one of your library roots.
              New downloads and imports for this series are placed, renamed and
              tagged there.
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
              <Label htmlFor="series-folder-input">Folder</Label>
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
                Use the path Comicarr sees. In Docker, that is the path inside
                the container. Extra roots are listed under Settings → Media.
              </p>
            </div>

            <fieldset className="grid gap-2">
              <legend className="mb-1 text-sm font-medium">
                Files already in the library
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
                  Leave them where they are
                  <span className="block text-xs text-muted-foreground">
                    They stay readable from their current folder.
                  </span>
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
                  Move them to the new folder
                  <span className="block text-xs text-muted-foreground">
                    Only this series&apos; files move. Nothing moves if a file
                    with the same name is already there.
                  </span>
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
                  Use automatic folder
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
                  Cancel
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
                  {mutation.isPending ? "Saving…" : "Save folder"}
                </Button>
              </div>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
