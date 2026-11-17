import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  LoaderCircle,
  Plus,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { useUpdateSearchProviders } from "@/hooks/useConfig";
import { apiRequest } from "@/lib/api";
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

type IndexerTestResult = {
  success: boolean;
  latency_ms?: number | null;
  error?: string;
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
  test: (index: number) => string;
  verifyRow: (index: number) => string;
  idPrefix: string;
  showRssUid: boolean;
};

const COPY = (): Record<SearchProviderKind, EditorCopy> => ({
  newznab: {
    enableLabel: t`Enable Newznab indexers`,
    enableHelp: t`At least one enabled indexer is required for Usenet search.`,
    empty: t`No Usenet indexers are configured. Add a Newznab-compatible indexer to make the NZB route searchable.`,
    add: t`Add indexer`,
    reset: t`Reset indexers`,
    save: t`Save indexers`,
    saved: t`Search indexers saved`,
    unsaved: t`Unsaved indexer changes`,
    heading: (index) => t`Indexer ${index}`,
    remove: (index) => t`Remove indexer ${index}`,
    name: t`Indexer name`,
    host: t`Indexer URL`,
    hostPlaceholder: "https://indexer.example/api",
    key: t`Indexer API key`,
    categoriesHelp: t`Newznab category IDs, comma-separated. 7030 is Books/Comics.`,
    enableRow: (index) => t`Enable indexer ${index}`,
    test: (index) => t`Test indexer ${index}`,
    verifyRow: (index) => t`Verify TLS for indexer ${index}`,
    idPrefix: "indexer",
    showRssUid: true,
  },
  torznab: {
    enableLabel: t`Enable Torznab indexers`,
    enableHelp: t`At least one enabled indexer is required for torrent search.`,
    empty: t`No torrent indexers are configured. Add a Torznab-compatible indexer to make the torrent route searchable.`,
    add: t`Add Torznab indexer`,
    reset: t`Reset Torznab indexers`,
    save: t`Save Torznab indexers`,
    saved: t`Torznab indexers saved`,
    unsaved: t`Unsaved Torznab indexer changes`,
    heading: (index) => t`Torznab indexer ${index}`,
    remove: (index) => t`Remove Torznab indexer ${index}`,
    name: t`Torznab indexer name`,
    host: t`Torznab indexer URL`,
    hostPlaceholder: "https://prowlarr.example/1/api",
    key: t`Torznab indexer API key`,
    categoriesHelp: t`Torznab category IDs, comma-separated. Use the IDs your indexer documents for comics.`,
    enableRow: (index) => t`Enable Torznab indexer ${index}`,
    test: (index) => t`Test Torznab indexer ${index}`,
    verifyRow: (index) => t`Verify TLS for Torznab indexer ${index}`,
    idPrefix: "torznab-indexer",
    showRssUid: false,
  },
});

function blankProvider(kind: SearchProviderKind): EditableProvider {
  return {
    name: "",
    host: "",
    verify: true,
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
  const copy = COPY()[kind];
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
    // An indexer added under a switched-off group is saved and silently never
    // searched. Adding one is asking for it to be used.
    setEnabled(true);
  };

  const [testing, setTesting] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<
    Record<number, IndexerTestResult>
  >({});

  const testProvider = async (index: number) => {
    const provider = providers[index];
    setTesting(index);
    setTestResults((current) => {
      const { [index]: _previous, ...rest } = current;
      return rest;
    });
    let result: IndexerTestResult;
    try {
      result = await apiRequest<IndexerTestResult>(
        "POST",
        "/api/config/providers/test",
        {
          type: kind,
          id: provider.id,
          name: provider.name,
          host: provider.host,
          api_key: provider.api_key,
          verify: provider.verify,
        },
      );
    } catch (error) {
      result = {
        success: false,
        error:
          error instanceof Error ? error.message : t`Connection test failed`,
      };
    }
    setTestResults((current) => ({ ...current, [index]: result }));
    setTesting(null);
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
        message: t`Each indexer needs a name, URL, and API key.`,
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
        message: t`Enter the API key again when changing an indexer server.`,
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
          error instanceof Error ? error.message : t`Failed to save indexers`,
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
        <Trans>
          Indexer edits are saved separately from the page-level settings
          controls.
        </Trans>
      </p>

      {providers.length === 0 ? (
        <div className="rounded-lg border border-dashed px-4 py-5 text-[12px] text-muted-foreground">
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
                className="rounded-lg border p-4"
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
                    onClick={() => {
                      setTestResults({});
                      setProviders((current) =>
                        current.filter(
                          (_, providerIndex) => providerIndex !== index,
                        ),
                      );
                    }}
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
                          ? t`API key saved (enter a new value to change)`
                          : t`Enter the indexer API key`
                      }
                      onChange={(event) =>
                        updateProvider(index, { api_key: event.target.value })
                      }
                    />
                  </div>
                  <div>
                    <Label htmlFor={`${copy.idPrefix}-categories-${suffix}`}>
                      <Trans>Categories</Trans>
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
                        <Trans>RSS user ID</Trans>
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
                        <Trans>
                          The <code>i=</code> parameter of this indexer&rsquo;s
                          RSS URL. Leave as 1 unless your indexer says
                          otherwise.
                        </Trans>
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
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={
                      testing !== null ||
                      !provider.host.trim() ||
                      (!provider.api_key.trim() && !provider.api_key_set)
                    }
                    onClick={() => void testProvider(index)}
                  >
                    {testing === index ? (
                      <LoaderCircle className="animate-spin" />
                    ) : (
                      <Zap />
                    )}
                    {copy.test(index + 1)}
                  </Button>
                  {testResults[index] && (
                    <p
                      role={testResults[index].success ? "status" : "alert"}
                      className="flex items-center gap-2 text-[12px]"
                    >
                      {testResults[index].success ? (
                        <CheckCircle2 className="h-4 w-4 text-[var(--status-active)]" />
                      ) : (
                        <XCircle className="h-4 w-4 text-[var(--status-error)]" />
                      )}
                      {testResults[index].success
                        ? t`Indexer answered`
                        : testResults[index].error || t`Connection test failed`}
                    </p>
                  )}
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
