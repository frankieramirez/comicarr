/**
 * Import manually: point Comicarr at a finished download it couldn't find.
 *
 * Starts from where Comicarr expected the file (the download's folder and
 * release name) so the common fix, a path the client and Comicarr see
 * differently, is one edit away. Submits a one-key `import` with an
 * `import_source` override; the post-processor does the rest.
 */

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { useImportSource, useManualImport } from "@/hooks/useIssueStoryDetails";
import { getErrorMessage } from "@/lib/api";

export function ImportManuallyDialog({
  releaseKey,
  label,
  onClose,
}: {
  releaseKey: string;
  label?: string;
  onClose: () => void;
}) {
  const source = useImportSource(releaseKey);
  const run = useManualImport();
  const { addToast } = useToast();
  // Until the user edits a field, it shows where Comicarr last looked.
  const [editedFolder, setFolder] = useState<string | null>(null);
  const [editedName, setName] = useState<string | null>(null);
  const folder = editedFolder ?? source.data?.nzb_folder ?? "";
  const name = editedName ?? source.data?.nzb_name ?? "";

  const submit = async () => {
    try {
      await run.mutateAsync({
        release_key: releaseKey,
        nzb_folder: folder.trim() || null,
        nzb_name: name.trim() || null,
      });
      addToast({
        type: "success",
        message: `Importing ${label ?? "this issue"} from ${folder.trim()}.`,
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
          <DialogTitle>Import {label ?? "manually"}</DialogTitle>
          <DialogDescription>
            Tell Comicarr where the finished download is. It starts from where
            it last looked; change the folder if your download client saves
            somewhere Comicarr sees under a different path.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="manual-import-folder">Folder</Label>
            <Input
              id="manual-import-folder"
              value={folder}
              onChange={(event) => setFolder(event.target.value)}
              placeholder="/data/downloads/complete/comics"
              className="font-mono text-xs"
              autoComplete="off"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="manual-import-name">File or folder name</Label>
            <Input
              id="manual-import-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Absolute.Flash.018.2026.Digital"
              className="font-mono text-xs"
              autoComplete="off"
            />
          </div>
          {source.isError && (
            <p className="text-[13px] text-foreground-2">
              Comicarr doesn&apos;t know where this download went. Enter the
              folder and name yourself.
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={run.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={run.isPending || !folder.trim() || !name.trim()}
            >
              {run.isPending ? "Starting…" : "Import"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
