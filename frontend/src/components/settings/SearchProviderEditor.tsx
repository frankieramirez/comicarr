import { useEffect, useMemo, useState } from "react";
import { LoaderCircle, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { useUpdateSearchProviders } from "@/hooks/useConfig";
import { httpOrigin } from "@/lib/httpOrigin";
import type {
  NewznabProvider,
  SearchProviderKind,
  TorznabProvider,
} from "@/types";
import { SettingField } from "./SettingField";

type EditableProvider = {
  id?: number;
  name: string;
  host: string;
  verify: boolean;
  categories: string;
  enabled: boolean;
  api_key_set: boolean;
  api_key: string;
  rss_uid?: string;
};

type ProviderGroup = {
  enabled: boolean;
  providers: Array<NewznabProvider | TorznabProvider>;
};

type EditorCopy = {
  enableLabel: string;
  enableHelp: string;
  empty: string;
  add: string;
  reset: string;
  save: string;
  saved: string;
  unsaved: string;
  heading: (index: number) => string;
  remove: (index: number) => string;
  name: string;
  host: string;
  hostPlaceholder: string;
  key: string;
  categoriesHelp: string;
  enableRow: (index: number) => string;
  verifyRow: (index: number) => string;
  idPrefix: string;
  showRssUid: boolean;
};

const COPY: Record<SearchProviderKind, EditorCopy> = {
  newznab: {
    enableLabel: "Enable Newznab indexers",
    enableHelp: "At least one enabled indexer is required for Usenet search.",
    empty:
      "No Usenet indexers are configured. Add a Newznab-compatible indexer to make the NZB route searchable.",
    add: "Add indexer",
    reset: "Reset indexers",
    save: "Save indexers",
    saved: "Search indexers saved",
    unsaved: "Unsaved indexer changes",
    heading: (index) => `Indexer ${index}`,
    remove: (index) => `Remove indexer ${index}`,
    name: "Indexer name",
    host: "Indexer URL",
    hostPlaceholder: "https://indexer.example/api",
    key: "Indexer API key",
    categoriesHelp:
      "Newznab category IDs, comma-separated. 7030 is Books/Comics.",
    enableRow: (index) => `Enable indexer ${index}`,
    verifyRow: (index) => `Verify TLS for indexer ${index}`,
    idPrefix: "indexer",
    showRssUid: true,
  },
  torznab: {
    enableLabel: "Enable Torznab indexers",
    enableHelp: "At least one enabled indexer is required for torrent search.",
    empty:
      "No torrent indexers are configured. Add a Torznab-compatible indexer to make the torrent route searchable.",
    add: "Add Torznab indexer",
    reset: "Reset Torznab indexers",
    save: "Save Torznab indexers",
    saved: "Torznab indexers saved",
    unsaved: "Unsaved Torznab indexer changes",
    heading: (index) => `Torznab indexer ${index}`,
    remove: (index) => `Remove Torznab indexer ${index}`,
    name: "Torznab indexer name",
    host: "Torznab indexer URL",
    hostPlaceholder: "https://prowlarr.example/1/api",
    key: "Torznab indexer API key",
    categoriesHelp:
      "Torznab category IDs, comma-separated. Use the IDs your indexer documents for comics.",
    enableRow: (index) => `Enable Torznab indexer ${index}`,
    verifyRow: (index) => `Verify TLS for Torznab indexer ${index}`,
    idPrefix: "torznab-indexer",
    showRssUid: false,
  },
};

function blankProvider(kind: SearchProviderKind): EditableProvider {
  return {
    name: "",
    host: "",
    verify: true,
    // 7030 is Books/Comics in the standard Newznab category numbering.
    // The old 5030 default was a TV category — harmless while categories
    // were being discarded before reaching the search, and wrong now that
    // they are not. Torznab indexers that speak the same numbering use it too.
    categories: "7030",
    enabled: true,
    api_key_set: false,
    api_key: "",
    ...(kind === "newznab" ? { rss_uid: "1" } : {}),
  };
}

export function SearchProviderEditor({
  kind,
  initial,
  onDirtyChange,
}: {
  kind: SearchProviderKind;
  initial: ProviderGroup;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const copy = COPY[kind];
  const { addToast } = useToast();
  const updateProviders = useUpdateSearchProviders();
  const [enabled, setEnabled] = useState(initial.enabled);
  const initialProviders = useMemo(
    () => initial.providers.map((provider) => ({ ...provider, api_key: "" })),
    [initial.providers],
  );
  const [providers, setProviders] =
    useState<EditableProvider[]>(initialProviders);
  const isDirty =
    enabled !== initial.enabled ||
    JSON.stringify(providers) !== JSON.stringify(initialProviders);

  useEffect(() => {
    onDirtyChange?.(isDirty);
    return () => onDirtyChange?.(false);
  }, [isDirty, onDirtyChange]);

  const updateProvider = (index: number, patch: Partial<EditableProvider>) => {
    setProviders((current) =>
      current.map((provider, providerIndex) =>
        providerIndex === index ? { ...provider, ...patch } : provider,
      ),
    );
  };

  const addProvider = () => {
    setProviders((current) => [...current, blankProvider(kind)]);
  };

  const resetProviders = () => {
    setEnabled(initial.enabled);
    setProviders(initialProviders);
  };

  const saveProviders = async () => {
    const incomplete = providers.some(
      (provider) =>
        !provider.name.trim() ||
        !provider.host.trim() ||
        (!provider.api_key_set && !provider.api_key.trim()),
    );
    if (incomplete) {
      addToast({
        type: "error",
        message: "Each indexer needs a name, URL, and API key.",
      });
      return;
    }
    const redirectedSecret = providers.some((provider) => {
      if (!provider.api_key_set || provider.api_key.trim()) return false;
      const original = initial.providers.find(
        (candidate) => candidate.id === provider.id,
      );
      return Boolean(
        original && httpOrigin(original.host) !== httpOrigin(provider.host),
      );
    });
    if (redirectedSecret) {
      addToast({
        type: "error",
        message: "Enter the API key again when changing an indexer server.",
      });
      return;
    }
    const payload = providers.map((provider) => {
      if (kind === "newznab") return provider;
      const { rss_uid: _rssUid, ...torznab } = provider;
      return torznab;
    });
    try {
      await updateProviders.mutateAsync({
        type: kind,
        enabled,
        providers: payload,
      });
      addToast({ type: "success", message: copy.saved });
    } catch (error) {
      addToast({
        type: "error",
        message:
          error instanceof Error ? error.message : "Failed to save indexers",
      });
    }
  };

  return (
    <div className="space-y-4">
      <SettingField
        label={copy.enableLabel}
        type="checkbox"
        checked={enabled}
        onChange={(value) => setEnabled(value as boolean)}
        helpText={copy.enableHelp}
      />

      <p className="text-[12px] text-muted-foreground">
        Indexer edits are saved separately from the page-level settings
        controls.
      </p>

      {providers.length === 0 ? (
        <div className="rounded-[6px] border border-dashed px-4 py-5 text-[12px] text-muted-foreground">
          {copy.empty}
        </div>
      ) : (
        <div className="space-y-3">
          {providers.map((provider, index) => {
            const suffix =
              provider.id != null ? `saved-${provider.id}` : `new-${index}`;
            return (
              <article
                key={provider.id ?? `new-${index}`}
                className="rounded-[6px] border p-4"
                style={{ borderColor: "var(--border)" }}
              >
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="font-mono text-[11px] font-semibold uppercase tracking-[0.06em]">
                    {copy.heading(index + 1)}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={copy.remove(index + 1)}
                    onClick={() =>
                      setProviders((current) =>
                        current.filter(
                          (_, providerIndex) => providerIndex !== index,
                        ),
                      )
                    }
                  >
                    <Trash2 />
                  </Button>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <Label htmlFor={`${copy.idPrefix}-name-${suffix}`}>
                      {copy.name}
                    </Label>
                    <Input
                      id={`${copy.idPrefix}-name-${suffix}`}
                      className="mt-1.5"
                      value={provider.name}
                      onChange={(event) =>
                        updateProvider(index, { name: event.target.value })
                      }
                    />
                  </div>
                  <div>
                    <Label htmlFor={`${copy.idPrefix}-host-${suffix}`}>
                      {copy.host}
                    </Label>
                    <Input
                      id={`${copy.idPrefix}-host-${suffix}`}
                      className="mt-1.5"
                      value={provider.host}
                      placeholder={copy.hostPlaceholder}
                      onChange={(event) =>
                        updateProvider(index, { host: event.target.value })
                      }
                    />
                  </div>
                  <div>
                    <Label htmlFor={`${copy.idPrefix}-key-${suffix}`}>
                      {copy.key}
                    </Label>
                    <Input
                      id={`${copy.idPrefix}-key-${suffix}`}
                      className="mt-1.5"
                      type="password"
                      value={provider.api_key}
                      placeholder={
                        provider.api_key_set
                          ? "API key saved (enter a new value to change)"
                          : "Enter the indexer API key"
                      }
                      onChange={(event) =>
                        updateProvider(index, { api_key: event.target.value })
                      }
                    />
                  </div>
                  <div>
                    <Label htmlFor={`${copy.idPrefix}-categories-${suffix}`}>
                      Categories
                    </Label>
                    <Input
                      id={`${copy.idPrefix}-categories-${suffix}`}
                      className="mt-1.5"
                      value={provider.categories}
                      placeholder="7030"
                      onChange={(event) =>
                        updateProvider(index, {
                          categories: event.target.value,
                        })
                      }
                    />
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {copy.categoriesHelp}
                    </p>
                  </div>
                  {copy.showRssUid ? (
                    <div>
                      <Label htmlFor={`${copy.idPrefix}-rss-uid-${suffix}`}>
                        RSS user ID
                      </Label>
                      <Input
                        id={`${copy.idPrefix}-rss-uid-${suffix}`}
                        className="mt-1.5"
                        value={provider.rss_uid ?? ""}
                        placeholder="1"
                        onChange={(event) =>
                          updateProvider(index, {
                            rss_uid: event.target.value,
                          })
                        }
                      />
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        The <code>i=</code> parameter of this indexer&rsquo;s
                        RSS URL. Leave as 1 unless your indexer says otherwise.
                      </p>
                    </div>
                  ) : null}
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <SettingField
                    label={copy.enableRow(index + 1)}
                    type="checkbox"
                    checked={provider.enabled}
                    onChange={(value) =>
                      updateProvider(index, { enabled: value as boolean })
                    }
                  />
                  <SettingField
                    label={copy.verifyRow(index + 1)}
                    type="checkbox"
                    checked={provider.verify}
                    onChange={(value) =>
                      updateProvider(index, { verify: value as boolean })
                    }
                  />
                </div>
              </article>
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button type="button" variant="outline" size="sm" onClick={addProvider}>
          <Plus /> {copy.add}
        </Button>
        <div className="flex items-center gap-2">
          {isDirty && (
            <span className="text-[11px] text-muted-foreground">
              {copy.unsaved}
            </span>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!isDirty}
            onClick={resetProviders}
          >
            {copy.reset}
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!isDirty || updateProviders.isPending}
            onClick={() => void saveProviders()}
          >
            {updateProviders.isPending && (
              <LoaderCircle className="animate-spin" />
            )}
            {copy.save}
          </Button>
        </div>
      </div>
    </div>
  );
}
