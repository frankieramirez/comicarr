import { ph, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useProviderOrder, useUpdateProviderOrder } from "@/hooks/useConfig";
import type { ProviderOrderEntry } from "@/types";
import { SettingGroup } from "./SettingGroup";

const ROUTE_LABEL = (): Record<ProviderOrderEntry["route"], string> => ({
  nzb: t`Usenet`,
  torrent: t`Torrent`,
  ddl: t`Direct`,
});

function move<T>(items: T[], from: number, to: number): T[] {
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

function namesOf(providers: ProviderOrderEntry[]): string {
  return providers.map((provider) => provider.name).join("\n");
}

function OrderEditor({
  saved,
  onDirtyChange,
}: {
  saved: ProviderOrderEntry[];
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const updateOrder = useUpdateProviderOrder();
  const { addToast } = useToast();
  const [providers, setProviders] = useState<ProviderOrderEntry[]>(saved);
  const isDirty = namesOf(providers) !== namesOf(saved);

  useEffect(() => {
    onDirtyChange?.(isDirty);
    return () => onDirtyChange?.(false);
  }, [isDirty, onDirtyChange]);

  const save = async () => {
    try {
      await updateOrder.mutateAsync(providers.map((p) => p.name));
      addToast({ type: "success", message: t`Search order saved` });
    } catch (error) {
      addToast({
        type: "error",
        message:
          error instanceof Error
            ? error.message
            : t`Failed to save search order`,
      });
    }
  };

  return (
    <>
      <ol aria-label={t`Search order`} className="divide-y rounded-lg border">
        {providers.map((provider, index) => (
          <li key={provider.name} className="flex items-center gap-3 px-3 py-2">
            <span className="mono-meta w-5 text-right text-muted-foreground">
              {index + 1}
            </span>
            <span className="min-w-0 flex-1 truncate text-[13px]">
              {provider.name}
            </span>
            <span className="mono-label text-muted-foreground">
              {ROUTE_LABEL()[provider.route] ?? provider.route}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t`Move ${ph({ provider: provider.name })} up`}
              disabled={index === 0 || updateOrder.isPending}
              onClick={() =>
                setProviders((current) => move(current, index, index - 1))
              }
            >
              <ArrowUp />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t`Move ${ph({ provider: provider.name })} down`}
              disabled={index === providers.length - 1 || updateOrder.isPending}
              onClick={() =>
                setProviders((current) => move(current, index, index + 1))
              }
            >
              <ArrowDown />
            </Button>
          </li>
        ))}
      </ol>

      {providers.length > 1 && (
        <div className="flex flex-wrap items-center justify-end gap-2 pt-2">
          {isDirty && (
            <span className="text-[11px] text-muted-foreground">
              <Trans>Unsaved order changes</Trans>
            </span>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!isDirty || updateOrder.isPending}
            onClick={() => setProviders(saved)}
          >
            <Trans>Reset order</Trans>
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!isDirty || updateOrder.isPending}
            onClick={() => void save()}
          >
            {updateOrder.isPending && <LoaderCircle className="animate-spin" />}
            <Trans>Save order</Trans>
          </Button>
        </div>
      )}
    </>
  );
}

/** Global Search provider order (#1117): first in the list is searched first. */
export function ProviderOrderSettings({
  onDirtyChange,
}: {
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const orderQuery = useProviderOrder();
  const saved = orderQuery.data?.providers ?? [];

  return (
    <SettingGroup
      title={t`Search order`}
      description={t`Comicarr asks providers in this order and stops at the first good match. The new order applies from the next search, including issues already on your Wanted list. A series with its own provider order keeps using it.`}
    >
      {orderQuery.isLoading ? (
        <div className="flex items-center gap-2 py-4 text-[12px] text-muted-foreground">
          <LoaderCircle className="h-4 w-4 animate-spin" />{" "}
          <Trans>Loading search order…</Trans>
        </div>
      ) : orderQuery.error && !orderQuery.data ? (
        <div role="alert" className="py-3 text-[12px] text-destructive">
          {orderQuery.error instanceof Error
            ? orderQuery.error.message
            : t`Could not load the search order`}
        </div>
      ) : saved.length === 0 ? (
        <div className="rounded-lg border border-dashed px-4 py-5 text-[12px] text-muted-foreground">
          <Trans>
            No Search providers are enabled yet. Add an indexer or turn on
            Prowlarr search to set an order.
          </Trans>
        </div>
      ) : (
        // Re-keyed on the saved order so a save or an indexer change starts
        // the editor again from what the server now uses. A failed background
        // refresh keeps the editor, and any unsaved moves, in place.
        <>
          {orderQuery.error && (
            <p role="alert" className="pb-2 text-[12px] text-destructive">
              <Trans>
                Could not refresh the search order. Showing the last one loaded.
              </Trans>
            </p>
          )}
          <OrderEditor
            key={namesOf(saved)}
            saved={saved}
            onDirtyChange={onDirtyChange}
          />
        </>
      )}
    </SettingGroup>
  );
}
