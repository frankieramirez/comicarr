import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { useDeleteCopy, useSaveCopy, useShelfCopies } from "@/hooks/useShelf";
import { centsToInput, formatCents, parseCents } from "@/lib/shelf";
import type { ShelfCopy, ShelfItem } from "@/types";

export interface ShelfSheetTarget {
  item: ShelfItem;
  /** "Starfall Saga #64" or "Paper Tigers Vol. 3". */
  title: string;
}

interface ShelfSheetProps {
  target: ShelfSheetTarget | null;
  onClose: () => void;
}

interface FormState {
  variant: string;
  grade: string;
  paid: string;
  storage: string;
  notes: string;
}

const LAST_STORAGE = "comicarr.shelf.storage";

/** The box the last copy went into: the next one usually goes there too. */
function lastStorage(): string {
  try {
    return window.localStorage.getItem(LAST_STORAGE) ?? "";
  } catch {
    return "";
  }
}

function formFor(copy: ShelfCopy | null): FormState {
  return {
    variant: copy?.VariantName ?? "",
    grade: copy?.Grade ?? "",
    paid: centsToInput(copy?.PaidCents),
    storage: copy ? (copy.Storage ?? "") : lastStorage(),
    notes: copy?.Notes ?? "",
  };
}

/** One line under a copy's name: "NM · Long box 03 · 4.99". */
function copyDetails(copy: ShelfCopy): string {
  return [
    copy.Grade,
    copy.Storage,
    copy.PaidCents === null ? null : formatCents(copy.PaidCents),
  ]
    .filter(Boolean)
    .join(" · ");
}

const FIELD = "space-y-1 text-[12px] text-muted-foreground";

/** The print copies of one issue or volume: list them, add one, change one. */
export function ShelfSheet({ target, onClose }: ShelfSheetProps) {
  const copies = useShelfCopies(
    {
      comic_id: target?.item.ComicID,
      item_id: target?.item.ItemID,
      volume_number: target?.item.VolumeNumber,
    },
    Boolean(target),
  );
  const save = useSaveCopy();
  const remove = useDeleteCopy();
  // The copy in the form: one from the list, "new", or none (list only).
  const [editing, setEditing] = useState<ShelfCopy | "new" | null>(null);
  const [form, setForm] = useState<FormState>(() => formFor(null));
  const [badPrice, setBadPrice] = useState(false);
  const busy = save.isPending || remove.isPending;
  const list = copies.data?.results ?? [];
  const empty = copies.isSuccess && list.length === 0;

  const open = (copy: ShelfCopy | "new" | null) => {
    setEditing(copy);
    setForm(formFor(copy === "new" ? null : copy));
    setBadPrice(false);
  };

  const set = (key: keyof FormState, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!target) return;
    const paid = parseCents(form.paid);
    if (paid === undefined) {
      setBadPrice(true);
      return;
    }
    await save.mutateAsync({
      item: target.item,
      copyId: editing && editing !== "new" ? editing.CopyID : undefined,
      fields: {
        VariantName: form.variant,
        Grade: form.grade,
        PaidCents: paid,
        Storage: form.storage,
        Notes: form.notes,
      },
    });
    try {
      if (form.storage.trim()) {
        window.localStorage.setItem(LAST_STORAGE, form.storage.trim());
      }
    } catch {
      // Private windows refuse storage; the sheet still works.
    }
    open(null);
  };

  const showForm = editing !== null || empty;

  return (
    <Sheet
      open={Boolean(target)}
      onOpenChange={(next) => {
        if (next) return;
        open(null);
        onClose();
      }}
    >
      <SheetContent className="flex h-full w-full flex-col gap-0 overflow-y-auto p-0 sm:max-w-md">
        <SheetHeader className="border-b border-border p-5 pe-12 text-start">
          <SheetTitle>
            <Trans>Print copies</Trans>
          </SheetTitle>
          <SheetDescription>{target?.title}</SheetDescription>
        </SheetHeader>

        {list.length > 0 && (
          <ul className="border-b border-border" data-testid="shelf-copies">
            {list.map((copy) => (
              <li
                key={copy.CopyID}
                className="flex items-center gap-3 border-b border-border-subtle px-5 py-2.5 last:border-b-0"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px]">
                    {copy.VariantName || t`Standard cover`}
                  </div>
                  <div className="truncate text-[12px] text-muted-foreground">
                    {copyDetails(copy) || t`No details yet`}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="compact"
                  disabled={busy}
                  onClick={() => open(copy)}
                >
                  <Trans>Edit</Trans>
                </Button>
              </li>
            ))}
          </ul>
        )}

        {showForm ? (
          <form className="space-y-4 p-5" onSubmit={(e) => void submit(e)}>
            <div className="text-[13px] font-medium">
              {editing && editing !== "new" ? t`Edit copy` : t`Add a copy`}
            </div>
            <label className={`block ${FIELD}`}>
              <span>
                <Trans>Variant</Trans>
              </span>
              <Input
                value={form.variant}
                maxLength={200}
                placeholder={t`Cover B, 2nd printing…`}
                onChange={(event) => set("variant", event.target.value)}
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className={FIELD}>
                <span>
                  <Trans>Grade</Trans>
                </span>
                <Input
                  value={form.grade}
                  maxLength={32}
                  placeholder={t`NM, CGC 9.8…`}
                  onChange={(event) => set("grade", event.target.value)}
                />
              </label>
              <label className={FIELD}>
                <span>
                  <Trans>Paid</Trans>
                </span>
                <Input
                  value={form.paid}
                  inputMode="decimal"
                  placeholder="4.99"
                  aria-invalid={badPrice}
                  onChange={(event) => set("paid", event.target.value)}
                />
              </label>
            </div>
            <label className={`block ${FIELD}`}>
              <span>
                <Trans>Storage</Trans>
              </span>
              <Input
                value={form.storage}
                maxLength={200}
                placeholder={t`Long box 1`}
                onChange={(event) => set("storage", event.target.value)}
              />
            </label>
            <label className={`block ${FIELD}`}>
              <span>
                <Trans>Notes</Trans>
              </span>
              <Textarea
                value={form.notes}
                maxLength={4000}
                rows={3}
                onChange={(event) => set("notes", event.target.value)}
              />
            </label>
            {badPrice ? (
              <p
                role="alert"
                className="text-[12px] text-[var(--status-error)]"
              >
                <Trans>Enter a price such as 4.99.</Trans>
              </p>
            ) : null}
            <div className="flex items-center gap-2">
              {editing && editing !== "new" ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="toolbar"
                  disabled={busy}
                  className="text-[var(--status-error)]"
                  onClick={() =>
                    void remove
                      .mutateAsync(editing.CopyID)
                      .then(() => open(null))
                  }
                >
                  <Trans>Remove</Trans>
                </Button>
              ) : null}
              <span className="flex-1" />
              {empty ? null : (
                <Button
                  type="button"
                  variant="ghost"
                  size="toolbar"
                  disabled={busy}
                  onClick={() => open(null)}
                >
                  <Trans>Cancel</Trans>
                </Button>
              )}
              <Button type="submit" size="toolbar" disabled={busy}>
                {editing && editing !== "new" ? (
                  <Trans>Save</Trans>
                ) : (
                  <Trans>Add to shelf</Trans>
                )}
              </Button>
            </div>
          </form>
        ) : (
          <div className="p-5">
            <Button
              type="button"
              variant="outline"
              size="toolbar"
              disabled={copies.isLoading}
              onClick={() => open("new")}
            >
              <Trans>Add another copy</Trans>
            </Button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
