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
          checked ? "translate-x-[1.125rem]" : "translate-x-[0.1875rem]",
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
    return { tone: "var(--muted-foreground)", label: "Off", detail: null };
  }
  if (!check || check.ok === null) {
    return {
      tone: "var(--muted-foreground)",
      label: check?.result || "Not checked yet",
      detail: null,
    };
  }
  if (!check.ok) {
    return {
      tone: "var(--status-error)",
      label: "Unreachable",
      detail: check.result,
    };
  }
  if (card.client.id === "ddl") {
    return { tone: "var(--status-active)", label: "Ready", detail: "built in" };
  }
  const detail =
    check.active != null
      ? check.active > 0
        ? `${check.active} active`
        : "idle"
      : check.latency_label === "local"
        ? "local folder"
        : null;
  return { tone: "var(--status-active)", label: "Connected", detail };
}

function testLine(check: ConnectionCheck | undefined): string | null {
  if (!check || check.checked_at == null) return null;
  if (!check.ok) return check.result;
  return [
    check.result === "Reachable" ? "Connected" : check.result,
    check.version,
    check.latency_ms != null ? `${Math.round(check.latency_ms)} ms` : null,
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
          Category per library folder
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
          + Add folder
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-border-subtle px-3 py-2 text-xs text-muted-foreground">
          Every series uses the category above. Add a library folder to send its
          series to their own category or save path.
        </p>
      ) : (
        <div className="divide-y divide-border-subtle rounded-md border border-border-subtle">
          {rows.map((route, index) => (
            <div
              key={index}
              className="grid grid-cols-[minmax(0,1.4fr)_auto_minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2 px-2 py-1.5"
            >
              <Input
                aria-label={`Library folder ${index + 1}`}
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
                aria-label={`Category for folder ${index + 1}`}
                value={route.category}
                placeholder="category"
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
                aria-label={`Save path for folder ${index + 1}`}
                value={route.savePath}
                placeholder="save path (optional)"
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
                aria-label={`Remove folder ${index + 1}`}
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
    set ? "Saved (enter a new one to change)" : undefined;

  switch (client.id) {
    case "sabnzbd":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            className="sm:col-span-2"
            label="URL"
            value={str("sab_host")}
            placeholder="http://sabnzbd:8080"
            onChange={(v) => onChange("sab_host", v)}
          />
          <Field
            label="API key"
            type="password"
            value={str("sab_apikey")}
            placeholder={saved(config.sab_apikey_set) ?? "SABnzbd API key"}
            onChange={(v) => onChange("sab_apikey", v)}
          />
          <Field
            label="Category"
            value={str("sab_category")}
            placeholder="comics"
            onChange={(v) => onChange("sab_category", v)}
          />
          <Field
            className="sm:col-span-2"
            label="Download directory"
            value={str("sab_directory")}
            placeholder="/downloads"
            onChange={(v) => onChange("sab_directory", v)}
          />
          <div className="sm:col-span-2">
            <SettingField
              label="Verify the TLS certificate"
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
            label="Host"
            value={str("nzbget_host")}
            placeholder="http://nzbget"
            onChange={(v) => onChange("nzbget_host", v)}
          />
          <Field
            label="Port"
            value={str("nzbget_port")}
            placeholder="6789"
            onChange={(v) => onChange("nzbget_port", v)}
          />
          <Field
            label="Username"
            value={str("nzbget_username")}
            onChange={(v) => onChange("nzbget_username", v)}
          />
          <Field
            label="Password"
            type="password"
            value={str("nzbget_password")}
            placeholder={saved(config.nzbget_password_set)}
            onChange={(v) => onChange("nzbget_password", v)}
          />
          <Field
            label="Category"
            value={str("nzbget_category")}
            placeholder="comics"
            onChange={(v) => onChange("nzbget_category", v)}
          />
          <Field
            label="Path"
            value={str("nzbget_sub")}
            placeholder="optional"
            onChange={(v) => onChange("nzbget_sub", v)}
          />
        </div>
      );
    case "qbittorrent":
      return (
        <div className="space-y-3">
          <Field
            label="URL"
            value={str("qbittorrent_host")}
            placeholder="http://qbittorrent:8080"
            onChange={(v) => onChange("qbittorrent_host", v)}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Username"
              value={str("qbittorrent_username")}
              onChange={(v) => onChange("qbittorrent_username", v)}
            />
            <Field
              label="Password"
              type="password"
              value={str("qbittorrent_password")}
              placeholder={saved(config.qbittorrent_password_set)}
              onChange={(v) => onChange("qbittorrent_password", v)}
            />
            <Field
              label="Category"
              value={str("qbittorrent_label")}
              placeholder="comics"
              onChange={(v) => onChange("qbittorrent_label", v)}
            />
            <Field
              label="Save path"
              value={str("qbittorrent_folder")}
              placeholder="qBittorrent's default"
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
            label="Host"
            value={str("deluge_host")}
            placeholder="deluge:58846"
            onChange={(v) => onChange("deluge_host", v)}
          />
          <Field
            label="Username"
            value={str("deluge_username")}
            onChange={(v) => onChange("deluge_username", v)}
          />
          <Field
            label="Password"
            type="password"
            value={str("deluge_password")}
            placeholder={saved(config.deluge_password_set)}
            onChange={(v) => onChange("deluge_password", v)}
          />
          <Field
            label="Label"
            value={str("deluge_label")}
            placeholder="comics"
            onChange={(v) => onChange("deluge_label", v)}
          />
        </div>
      );
    case "transmission":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            className="sm:col-span-2"
            label="URL"
            value={str("transmission_host")}
            placeholder="http://transmission:9091"
            onChange={(v) => onChange("transmission_host", v)}
          />
          <Field
            label="Username"
            value={str("transmission_username")}
            onChange={(v) => onChange("transmission_username", v)}
          />
          <Field
            label="Password"
            type="password"
            value={str("transmission_password")}
            placeholder={saved(config.transmission_password_set)}
            onChange={(v) => onChange("transmission_password", v)}
          />
          <Field
            className="sm:col-span-2"
            label="Download directory"
            value={str("transmission_directory")}
            placeholder="Transmission's default"
            onChange={(v) => onChange("transmission_directory", v)}
          />
        </div>
      );
    case "ddl":
      return (
        <p className="text-[13px] text-foreground-2">
          Built in. Comicarr downloads GetComics, Mega, MediaFire and Pixeldrain
          links itself, so there is nothing to connect.
        </p>
      );
    default:
      return (
        <p className="text-[13px] text-foreground-2">
          {client.label} settings live in the config file shown in the Settings
          header.
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
          className="min-w-0 flex-1 text-left focus-visible:outline-none"
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
            {host || "Not set up yet"}
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
          label={`Send ${KIND_BADGE[client.kind].toLowerCase()} releases to ${client.label}`}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={
            open ? `Collapse ${client.label}` : `Edit ${client.label}`
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
              label="Client"
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
                Test connection
              </Button>
              <span className="flex items-center gap-2 text-xs text-foreground-2">
                {dirty || !check ? (
                  "Save to test these settings."
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
                  "Not checked yet."
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
    ["usenet", "Usenet"],
    ["torrent", "Torrent"],
    ["ddl", "Direct download"],
  ];

  return (
    <div className="space-y-6">
      <section>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold text-foreground">
              Download clients
            </h2>
            <p className="mt-0.5 text-[13px] text-foreground-2">
              Where Comicarr sends the releases it picks: one client for each
              kind of release.
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
                Add client
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
            No download client yet. Add one so Comicarr has somewhere to send
            the releases it finds.
          </p>
        )}
      </section>

      <SettingGroup
        title="Completed downloads"
        description="The Folder Monitor checks these folders for finished downloads and imports them."
      >
        <SettingField
          label="Additional monitored folders"
          type="textarea"
          value={formData.additional_check_folders || ""}
          onChange={(v) => onChange("additional_check_folders", v as string)}
          helpText={
            config.check_folder
              ? `Scanned after the main monitored folder, ${config.check_folder}. One server path per line. In Docker, use the path inside the container.`
              : "Scanned after the main monitored folder, which is set as CHECK_FOLDER in the config file. These folders are ignored until it is set."
          }
          placeholder="/downloads/Magazines"
        />
      </SettingGroup>
    </div>
  );
}
