import { ph, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { useId, useState } from "react";
import { ArrowRight, ChevronDown, Loader2, Plug, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import {
  useConnections,
  useTestConnection,
  type ConnectionCheck,
} from "@/hooks/useAcquisitionHealth";
import {
  CLIENTS,
  KIND_BADGE,
  clientCards,
  clientHost,
  formatRootRoutes,
  parseRootRoutes,
  type ClientCard,
  type ClientInfo,
  type ClientKind,
  type RootRoute,
} from "@/lib/downloadClients";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/intl";
import type {
  ReadableConfig,
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

type OnChange = <K extends keyof WritableConfig>(
  key: K,
  value: NonNullable<WritableConfig[K]>,
) => void;

interface DownloadClientsTabProps {
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: OnChange;
}

/** The settings each client's card edits; a change to any marks the card unsaved. */
const CLIENT_FIELDS: Partial<Record<string, Array<keyof WritableConfig>>> = {
  sabnzbd: [
    "sab_host",
    "sab_apikey",
    "sab_category",
    "sab_directory",
    "sab_verify",
  ],
  nzbget: [
    "nzbget_host",
    "nzbget_port",
    "nzbget_sub",
    "nzbget_username",
    "nzbget_password",
    "nzbget_category",
  ],
  qbittorrent: [
    "qbittorrent_host",
    "qbittorrent_username",
    "qbittorrent_password",
    "qbittorrent_label",
    "qbittorrent_folder",
    "qbittorrent_root_routes",
  ],
  blackhole: ["blackhole_dir"],
  watchdir: ["local_watchdir"],
  deluge: ["deluge_host", "deluge_username", "deluge_password", "deluge_label"],
  transmission: [
    "transmission_host",
    "transmission_username",
    "transmission_password",
    "transmission_directory",
  ],
};

function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation();
        onChange(!checked);
      }}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        checked ? "bg-foreground" : "bg-surface-3",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-block size-3.5 rounded-full bg-background transition-transform",
          checked
            ? "translate-x-[1.125rem] rtl:-translate-x-[1.125rem]"
            : "translate-x-[0.1875rem] rtl:-translate-x-[0.1875rem]",
        )}
      />
    </button>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  error,
  mono = true,
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "password";
  placeholder?: string;
  error?: string;
  mono?: boolean;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={cn("min-w-0", className)}>
      <label htmlFor={id} className="mb-1.5 block text-xs text-foreground-2">
        {label}
      </label>
      <Input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={type === "password" ? "new-password" : "off"}
        aria-invalid={error ? true : undefined}
        className={cn("h-8 text-sm", mono && "font-mono text-[13px]")}
      />
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  );
}

function statusOf(
  card: ClientCard,
  check: ConnectionCheck | undefined,
): { tone: string; label: string; detail: string | null } {
  if (!card.enabled) {
    return { tone: "var(--muted-foreground)", label: t`Off`, detail: null };
  }
  if (!check || check.ok === null) {
    return {
      tone: "var(--muted-foreground)",
      label: check?.result || t`Not checked yet`,
      detail: null,
    };
  }
  if (!check.ok) {
    return {
      tone: "var(--status-error)",
      label: t`Unreachable`,
      detail: check.result,
    };
  }
  if (card.client.id === "ddl") {
    return {
      tone: "var(--status-active)",
      label: t`Ready`,
      detail: t`built in`,
    };
  }
  const detail =
    check.active != null
      ? check.active > 0
        ? t`${ph({ count: check.active })} active`
        : t`idle`
      : check.latency_label === "local"
        ? t`local folder`
        : null;
  return { tone: "var(--status-active)", label: t`Connected`, detail };
}

function sendReleasesLabel(kind: ClientKind, client: string): string {
  switch (kind) {
    case "usenet":
      return t`Send Usenet releases to ${client}`;
    case "torrent":
      return t`Send torrent releases to ${client}`;
    default:
      return t`Send direct downloads to ${client}`;
  }
}

function testLine(check: ConnectionCheck | undefined): string | null {
  if (!check || check.checked_at == null) return null;
  if (!check.ok) return check.result;
  return [
    check.result === "Reachable" ? t`Connected` : check.result,
    check.version,
    check.latency_ms != null
      ? formatNumber(Math.round(check.latency_ms), {
          style: "unit",
          unit: "millisecond",
        })
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function RootRoutes({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const routes = parseRootRoutes(value);
  const update = (next: RootRoute[]) => onChange(formatRootRoutes(next));
  const rows = routes.length ? routes : [];
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs text-foreground-2">
          <Trans>Category per library folder</Trans>
        </span>
        <button
          type="button"
          onClick={() =>
            onChange(
              `${value ? `${value}\n` : ""}/library/root | category`.trim(),
            )
          }
          className="text-xs text-foreground-2 hover:text-foreground"
        >
          <Trans>+ Add folder</Trans>
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-border-subtle px-3 py-2 text-xs text-muted-foreground">
          <Trans>
            Every series uses the category above. Add a library folder to send
            its series to their own category or save path.
          </Trans>
        </p>
      ) : (
        <div className="divide-y divide-border-subtle rounded-md border border-border-subtle">
          {rows.map((route, index) => (
            <div
              key={index}
              className="grid grid-cols-[minmax(0,1.4fr)_auto_minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2 px-2 py-1.5"
            >
              <Input
                aria-label={t`Library folder ${ph({ number: index + 1 })}`}
                value={route.root}
                onChange={(event) =>
                  update(
                    rows.map((r, i) =>
                      i === index ? { ...r, root: event.target.value } : r,
                    ),
                  )
                }
                className="h-7 border-transparent bg-transparent font-mono text-[13px]"
              />
              <ArrowRight
                aria-hidden="true"
                className="size-3.5 text-muted-foreground"
              />
              <Input
                aria-label={t`Category for folder ${ph({ number: index + 1 })}`}
                value={route.category}
                placeholder={t`category`}
                onChange={(event) =>
                  update(
                    rows.map((r, i) =>
                      i === index ? { ...r, category: event.target.value } : r,
                    ),
                  )
                }
                className="h-7 border-transparent bg-transparent font-mono text-[13px]"
              />
              <Input
                aria-label={t`Save path for folder ${ph({ number: index + 1 })}`}
                value={route.savePath}
                placeholder={t`save path (optional)`}
                onChange={(event) =>
                  update(
                    rows.map((r, i) =>
                      i === index ? { ...r, savePath: event.target.value } : r,
                    ),
                  )
                }
                className="h-7 border-transparent bg-transparent font-mono text-[13px]"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={t`Remove folder ${ph({ number: index + 1 })}`}
                onClick={() => update(rows.filter((_, i) => i !== index))}
              >
                <X />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ClientFields({
  client,
  config,
  formData,
  onChange,
}: {
  client: ClientInfo;
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: OnChange;
}) {
  const str = (key: keyof SettingsFormData) => {
    const value = formData[key];
    return value == null ? "" : String(value);
  };
  const saved = (set: boolean | undefined) =>
    set ? t`Saved (enter a new one to change)` : undefined;

  switch (client.id) {
    case "sabnzbd":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            className="sm:col-span-2"
            label={t`URL`}
            value={str("sab_host")}
            placeholder="http://sabnzbd:8080"
            onChange={(v) => onChange("sab_host", v)}
          />
          <Field
            label={t`API key`}
            type="password"
            value={str("sab_apikey")}
            placeholder={saved(config.sab_apikey_set) ?? t`SABnzbd API key`}
            onChange={(v) => onChange("sab_apikey", v)}
          />
          <Field
            label={t`Category`}
            value={str("sab_category")}
            placeholder={t`comics`}
            onChange={(v) => onChange("sab_category", v)}
          />
          <Field
            className="sm:col-span-2"
            label={t`Download directory`}
            value={str("sab_directory")}
            placeholder="/downloads"
            onChange={(v) => onChange("sab_directory", v)}
          />
          <div className="sm:col-span-2">
            <SettingField
              label={t`Verify the TLS certificate`}
              type="checkbox"
              checked={Boolean(formData.sab_verify)}
              onChange={(value) => onChange("sab_verify", value as boolean)}
            />
          </div>
        </div>
      );
    case "nzbget":
      return (
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem]">
          <Field
            label={t`Host`}
            value={str("nzbget_host")}
            placeholder="http://nzbget"
            onChange={(v) => onChange("nzbget_host", v)}
          />
          <Field
            label={t`Port`}
            value={str("nzbget_port")}
            placeholder="6789"
            onChange={(v) => onChange("nzbget_port", v)}
          />
          <Field
            label={t`Username`}
            value={str("nzbget_username")}
            onChange={(v) => onChange("nzbget_username", v)}
          />
          <Field
            label={t`Password`}
            type="password"
            value={str("nzbget_password")}
            placeholder={saved(config.nzbget_password_set)}
            onChange={(v) => onChange("nzbget_password", v)}
          />
          <Field
            label={t`Category`}
            value={str("nzbget_category")}
            placeholder={t`comics`}
            onChange={(v) => onChange("nzbget_category", v)}
          />
          <Field
            label={t`Path`}
            value={str("nzbget_sub")}
            placeholder={t`optional`}
            onChange={(v) => onChange("nzbget_sub", v)}
          />
        </div>
      );
    case "qbittorrent":
      return (
        <div className="space-y-3">
          <Field
            label={t`URL`}
            value={str("qbittorrent_host")}
            placeholder="http://qbittorrent:8080"
            onChange={(v) => onChange("qbittorrent_host", v)}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label={t`Username`}
              value={str("qbittorrent_username")}
              onChange={(v) => onChange("qbittorrent_username", v)}
            />
            <Field
              label={t`Password`}
              type="password"
              value={str("qbittorrent_password")}
              placeholder={saved(config.qbittorrent_password_set)}
              onChange={(v) => onChange("qbittorrent_password", v)}
            />
            <Field
              label={t`Category`}
              value={str("qbittorrent_label")}
              placeholder={t`comics`}
              onChange={(v) => onChange("qbittorrent_label", v)}
            />
            <Field
              label={t`Save path`}
              value={str("qbittorrent_folder")}
              placeholder={t`qBittorrent's default`}
              onChange={(v) => onChange("qbittorrent_folder", v)}
            />
          </div>
          <RootRoutes
            value={str("qbittorrent_root_routes")}
            onChange={(v) => onChange("qbittorrent_root_routes", v)}
          />
        </div>
      );
    case "deluge":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            className="sm:col-span-2"
            label={t`Host`}
            value={str("deluge_host")}
            placeholder="deluge:58846"
            onChange={(v) => onChange("deluge_host", v)}
          />
          <Field
            label={t`Username`}
            value={str("deluge_username")}
            onChange={(v) => onChange("deluge_username", v)}
          />
          <Field
            label={t`Password`}
            type="password"
            value={str("deluge_password")}
            placeholder={saved(config.deluge_password_set)}
            onChange={(v) => onChange("deluge_password", v)}
          />
          <Field
            label={t`Label`}
            value={str("deluge_label")}
            placeholder={t`comics`}
            onChange={(v) => onChange("deluge_label", v)}
          />
        </div>
      );
    case "transmission":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            className="sm:col-span-2"
            label={t`URL`}
            value={str("transmission_host")}
            placeholder="http://transmission:9091"
            onChange={(v) => onChange("transmission_host", v)}
          />
          <Field
            label={t`Username`}
            value={str("transmission_username")}
            onChange={(v) => onChange("transmission_username", v)}
          />
          <Field
            label={t`Password`}
            type="password"
            value={str("transmission_password")}
            placeholder={saved(config.transmission_password_set)}
            onChange={(v) => onChange("transmission_password", v)}
          />
          <Field
            className="sm:col-span-2"
            label={t`Download directory`}
            value={str("transmission_directory")}
            placeholder={t`Transmission's default`}
            onChange={(v) => onChange("transmission_directory", v)}
          />
        </div>
      );
    case "ddl":
      return (
        <p className="text-[13px] text-foreground-2">
          <Trans>
            Built in. Comicarr downloads GetComics, Mega, MediaFire and
            Pixeldrain links itself, so there is nothing to connect.
          </Trans>
        </p>
      );
    case "blackhole":
      return (
        <div className="grid gap-3">
          <Field
            label={t`Folder`}
            value={str("blackhole_dir")}
            placeholder="/downloads/blackhole"
            onChange={(v) => onChange("blackhole_dir", v)}
          />
          <p className="text-[13px] text-foreground-2">
            <Trans>
              Comicarr drops each .nzb file here. Point your usenet client's
              watch folder at the same place, as Comicarr sees it.
            </Trans>
          </p>
        </div>
      );
    case "watchdir":
      return (
        <div className="grid gap-3">
          <Field
            label={t`Folder`}
            value={str("local_watchdir")}
            placeholder="/downloads/watch"
            onChange={(v) => onChange("local_watchdir", v)}
          />
          <p className="text-[13px] text-foreground-2">
            <Trans>
              Comicarr drops each .torrent file here. Point your torrent
              client's watch folder at the same place, as Comicarr sees it.
            </Trans>
          </p>
        </div>
      );
    default:
      return (
        <p className="text-[13px] text-foreground-2">
          {t`${ph({ client: client.label })} settings live in the config file shown in the Settings header.`}
        </p>
      );
  }
}

function ClientRow({
  card,
  config,
  formData,
  onChange,
  check,
  open,
  onToggleOpen,
  onEnable,
  onSwitchClient,
}: {
  card: ClientCard;
  config: ReadableConfig;
  formData: SettingsFormData;
  onChange: OnChange;
  check: ConnectionCheck | undefined;
  open: boolean;
  onToggleOpen: () => void;
  onEnable: (enabled: boolean) => void;
  onSwitchClient: (client: ClientInfo) => void;
}) {
  const { client } = card;
  const test = useTestConnection();
  const status = statusOf(card, check);
  const host = clientHost(client.id, formData);
  const dirty = (CLIENT_FIELDS[client.id] ?? []).some((key) => {
    const now = formData[key as keyof SettingsFormData];
    const was = (config as Record<string, unknown>)[key];
    return (now ?? "") !== (was ?? "") && !(now === "" && was == null);
  });
  const siblings = CLIENTS.filter((other) => other.kind === client.kind);
  const tested = testLine(check);
  const bodyId = useId();

  return (
    <div className="border-b border-border-subtle last:border-b-0">
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={onToggleOpen}
          className="min-w-0 flex-1 text-start focus-visible:outline-none"
        >
          <span className="flex items-center gap-2">
            <span className="text-sm font-semibold text-foreground">
              {client.label}
            </span>
            <span className="rounded border border-border-subtle px-1.5 py-px mono-label text-foreground-2">
              {KIND_BADGE[client.kind]}
            </span>
          </span>
          <span className="mt-0.5 block truncate font-mono text-xs text-muted-foreground">
            {host || t`Not set up yet`}
          </span>
        </button>
        <span
          className="flex shrink-0 items-center gap-2 text-[13px]"
          title={
            status.detail ? `${status.label} · ${status.detail}` : status.label
          }
        >
          <span
            aria-hidden="true"
            className="size-1.5 rounded-full"
            style={{ background: status.tone }}
          />
          <span className="text-foreground-2 max-sm:sr-only">
            {status.label}
          </span>
          {status.detail && (
            <span className="max-w-48 truncate font-mono text-xs text-muted-foreground max-sm:hidden">
              {status.detail}
            </span>
          )}
        </span>
        <Switch
          checked={card.enabled}
          onChange={onEnable}
          label={sendReleasesLabel(client.kind, client.label)}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={
            open
              ? t`Collapse ${ph({ client: client.label })}`
              : t`Edit ${ph({ client: client.label })}`
          }
          onClick={onToggleOpen}
        >
          <ChevronDown
            className={cn("transition-transform", open && "rotate-180")}
          />
        </Button>
      </div>
      {open && (
        <div id={bodyId} className="space-y-4 px-4 pb-4">
          {siblings.length > 1 && (
            <SettingField
              label={t`Client`}
              type="select"
              value={client.id}
              options={siblings.map((other) => ({
                value: other.id,
                label: other.label,
              }))}
              onChange={(value) => {
                const next = siblings.find((other) => other.id === value);
                if (next) onSwitchClient(next);
              }}
            />
          )}
          <ClientFields
            client={client}
            config={config}
            formData={formData}
            onChange={onChange}
          />
          {client.id !== "ddl" && (
            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!check || dirty || test.isPending}
                onClick={() => test.mutate(client.id)}
              >
                {test.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Plug />
                )}
                <Trans>Test connection</Trans>
              </Button>
              <span className="flex items-center gap-2 text-xs text-foreground-2">
                {dirty || !check ? (
                  t`Save to test these settings.`
                ) : tested ? (
                  <>
                    <span
                      aria-hidden="true"
                      className="size-1.5 rounded-full"
                      style={{
                        background: check.ok
                          ? "var(--status-active)"
                          : "var(--status-error)",
                      }}
                    />
                    <span className="font-mono">{tested}</span>
                  </>
                ) : (
                  t`Not checked yet.`
                )}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function DownloadClientsTab({
  config,
  formData,
  onChange,
}: DownloadClientsTabProps) {
  const [added, setAdded] = useState<Set<ClientKind>>(new Set());
  const [openId, setOpenId] = useState<string | null>(null);
  const connections = useConnections();
  const checks = connections.data?.connections ?? [];
  const values = { ...config, ...formData };
  const cards = clientCards(values, added);
  const shownKinds = new Set(cards.map((card) => card.client.kind));
  const addable = CLIENTS.filter((client) => !shownKinds.has(client.kind));

  function choose(client: ClientInfo, enable = true) {
    if (client.kind === "usenet") {
      onChange("nzb_downloader", client.code as number);
    } else if (client.kind === "torrent") {
      onChange("torrent_downloader", client.code as number);
      if (enable) onChange("enable_torrents", true);
    } else {
      onChange("enable_ddl", true);
    }
    setAdded((current) => new Set(current).add(client.kind));
    setOpenId(client.id);
  }

  function enable(card: ClientCard, on: boolean) {
    const { client } = card;
    if (client.kind === "usenet") {
      onChange("nzb_downloader", on ? (client.code as number) : 3);
    } else if (client.kind === "torrent") {
      onChange("enable_torrents", on);
    } else {
      onChange("enable_ddl", on);
    }
  }

  const groups: Array<[ClientKind, string]> = [
    ["usenet", t`Usenet`],
    ["torrent", t`Torrent`],
    ["ddl", t`Direct download`],
  ];

  return (
    <div className="space-y-6">
      <section>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold text-foreground">
              <Trans>Download clients</Trans>
            </h2>
            <p className="mt-0.5 text-[13px] text-foreground-2">
              <Trans>
                Where Comicarr sends the releases it picks: one client for each
                kind of release.
              </Trans>
            </p>
          </div>
          {addable.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button type="button" variant="outline" size="toolbar" />
                }
              >
                <Plus />
                <Trans>Add client</Trans>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                {groups.map(([kind, label], index) => {
                  const options = addable.filter((c) => c.kind === kind);
                  if (!options.length) return null;
                  return (
                    <DropdownMenuGroup key={kind}>
                      {index > 0 && <DropdownMenuSeparator />}
                      <DropdownMenuLabel className="mono-label">
                        {label}
                      </DropdownMenuLabel>
                      {options.map((client) => (
                        <DropdownMenuItem
                          key={client.id}
                          onClick={() => choose(client)}
                        >
                          {client.label}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuGroup>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
        {cards.length > 0 ? (
          <div
            data-testid="download-client-cards"
            className="rounded-lg border border-border-subtle bg-surface-1"
          >
            {cards.map((card) => (
              <ClientRow
                key={card.client.kind}
                card={card}
                config={config}
                formData={formData}
                onChange={onChange}
                check={checks.find((c) => c.key === card.client.id)}
                open={openId === card.client.id}
                onToggleOpen={() =>
                  setOpenId((current) =>
                    current === card.client.id ? null : card.client.id,
                  )
                }
                onEnable={(on) => enable(card, on)}
                onSwitchClient={(next) => choose(next, card.enabled)}
              />
            ))}
          </div>
        ) : (
          <p className="rounded-lg border border-dashed border-border-subtle px-4 py-6 text-sm text-foreground-2">
            <Trans>
              No download client yet. Add one so Comicarr has somewhere to send
              the releases it finds.
            </Trans>
          </p>
        )}
      </section>

      <SettingGroup
        title={t`Completed downloads`}
        description={t`The Folder Monitor checks these folders for finished downloads and imports them.`}
      >
        <SettingField
          label={t`Completed downloads folder`}
          type="text"
          value={formData.check_folder ?? ""}
          onChange={(v) => onChange("check_folder", v as string)}
          helpText={t`Where your download client puts finished comics, as Comicarr sees it. In Docker, use the path inside the container. Leave empty to turn the Folder Monitor off.`}
          placeholder="/downloads/complete"
        />
        <SettingField
          label={t`Additional monitored folders`}
          type="textarea"
          value={formData.additional_check_folders || ""}
          onChange={(v) => onChange("additional_check_folders", v as string)}
          helpText={
            config.check_folder
              ? t`Scanned after the main monitored folder, ${ph({ folder: config.check_folder })}. One server path per line. In Docker, use the path inside the container.`
              : t`Scanned after the completed downloads folder above. These folders are ignored until it is set.`
          }
          placeholder="/downloads/Magazines"
        />
      </SettingGroup>
    </div>
  );
}
