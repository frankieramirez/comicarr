import { useState } from "react";
import { ArrowDown, ArrowUp, ListOrdered, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useUpdateSeriesProviderOverride } from "@/hooks/useSeries";
import { ApiError } from "@/lib/api";
import type { ProviderOverride } from "@/types";

interface Row {
  name: string;
  used: boolean;
}

function has(names: string[], name: string) {
  return names.some((value) => value.toLowerCase() === name.toLowerCase());
}

function rowsFor(available: string[], override: ProviderOverride | null) {
  const first = (override?.order ?? [])
    .map((name) => available.find((value) => has([name], value)))
    .filter((name): name is string => name !== undefined);
  const names = [...new Set([...first, ...available])];
  return names.map((name) => ({
    name,
    used: !has(override?.exclude ?? [], name),
  }));
}

function minimalOrderPrefix(arranged: string[], global: string[]) {
  for (let prefixLength = 0; prefixLength <= arranged.length; prefixLength++) {
    const head = arranged.slice(0, prefixLength);
    const rest = global.filter((name) => !head.includes(name));
    if (rest.every((name, index) => name === arranged[prefixLength + index]))
      return head;
  }
  return arranged;
}

interface SeriesSearchProvidersProps {
  comicId: string;
  /** Enabled search providers, in global order. */
  available: string[];
  override: ProviderOverride | null;
}

export function SeriesSearchProviders({
  comicId,
  available,
  override,
}: SeriesSearchProvidersProps) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const mutation = useUpdateSeriesProviderOverride();
  const { addToast } = useToast();

  const current = rowsFor(available, override);
  const used = current.filter((row) => row.used).map((row) => row.name);
  const skipped = current.filter((row) => !row.used).map((row) => row.name);

  const openDialog = () => {
    setRows(rowsFor(available, override));
    setError(null);
    setOpen(true);
  };

  const move = (index: number, by: number) => {
    const next = [...rows];
    [next[index], next[index + by]] = [next[index + by], next[index]];
    setRows(next);
  };

  const save = async (next: Row[] | null) => {
    setError(null);
    const kept = next?.filter((row) => row.used).map((row) => row.name) ?? [];
    const exclude =
      next?.filter((row) => !row.used).map((row) => row.name) ?? [];
    const order = minimalOrderPrefix(
      kept,
      available.filter((name) => !has(exclude, name)),
    );
    try {
      const result = await mutation.mutateAsync({ comicId, order, exclude });
      setOpen(false);
      addToast({
        type: "success",
        title: result.provider_override
          ? "Search providers changed"
          : "Search providers follow the global order again",
      });
    } catch (saveError) {
      setError(
        saveError instanceof ApiError
          ? saveError.userMessage
          : "Comicarr could not save the providers. Try again.",
      );
    }
  };

  return (
    <section
      className="mb-3.5 max-w-[640px] rounded-md border border-border p-3"
      aria-labelledby="series-providers-title"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span id="series-providers-title" className="text-xs font-semibold">
              Search providers
            </span>
            <span className="mono-label">
              {override ? "custom" : "global order"}
            </span>
          </div>
          <p
            className="mono-meta mt-1 break-words"
            data-testid="series-providers"
          >
            {used.length > 0 ? used.join(" → ") : "No providers enabled"}
          </p>
          {skipped.length > 0 ? (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              Skips {skipped.join(", ")} for this series.
            </p>
          ) : null}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={openDialog}
          disabled={available.length === 0}
        >
          <ListOrdered aria-hidden="true" />
          Change providers
        </Button>
      </div>

      <Dialog
        open={open}
        onOpenChange={(next) => !mutation.isPending && setOpen(next)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Search providers</DialogTitle>
            <DialogDescription>
              Searches for this series try providers from the top down. Untick a
              provider to skip it for this series only.
            </DialogDescription>
          </DialogHeader>

          <form
            className="grid gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void save(rows);
            }}
          >
            <ol className="grid gap-1.5">
              {rows.map((row, index) => (
                <li
                  key={row.name}
                  className="flex items-center gap-2 rounded-md border border-border px-2 py-1.5"
                >
                  <span className="mono-meta w-5 text-right">{index + 1}</span>
                  <label className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                    <Checkbox
                      checked={row.used}
                      onCheckedChange={(checked) =>
                        setRows(
                          rows.map((value, position) =>
                            position === index
                              ? { ...value, used: checked }
                              : value,
                          ),
                        )
                      }
                    />
                    <span
                      className={
                        row.used
                          ? "truncate"
                          : "truncate text-muted-foreground line-through"
                      }
                    >
                      {row.name}
                    </span>
                  </label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                    aria-label={`Move ${row.name} up`}
                  >
                    <ArrowUp aria-hidden="true" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    disabled={index === rows.length - 1}
                    onClick={() => move(index, 1)}
                    aria-label={`Move ${row.name} down`}
                  >
                    <ArrowDown aria-hidden="true" />
                  </Button>
                </li>
              ))}
            </ol>

            {rows.every((row) => !row.used) ? (
              <p className="text-xs text-muted-foreground">
                With every provider skipped, searches for this series stop
                without trying anything.
              </p>
            ) : null}

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
                  Use global order
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
                  disabled={mutation.isPending}
                  aria-busy={mutation.isPending}
                >
                  {mutation.isPending ? (
                    <LoaderCircle
                      className="animate-spin motion-reduce:animate-none"
                      aria-hidden="true"
                    />
                  ) : null}
                  {mutation.isPending ? "Saving…" : "Save providers"}
                </Button>
              </div>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
