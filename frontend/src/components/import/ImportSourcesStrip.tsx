import { ph, t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Link } from "react-router-dom";
import { Inbox, Library } from "lucide-react";
import { useConfig } from "@/hooks/useConfig";
import { libraryScanFolders, SETTINGS_FOLDERS } from "@/lib/libraryFolders";

/**
 * Where Import looks, in one line: the watched inbox and the library folders.
 * Read-only; "Change" goes to Settings, where the paths are owned.
 */
export default function ImportSourcesStrip() {
  const { data: config } = useConfig();
  const inbox = config?.import_dir as string | undefined;
  const scan = libraryScanFolders(config);
  const folders = [scan.comic, scan.manga].filter((dir): dir is string =>
    Boolean(dir),
  );

  return (
    <div
      className="grid overflow-hidden rounded-lg border border-border-subtle bg-surface-1 md:grid-cols-2"
      data-testid="import-sources"
    >
      <Source
        icon={<Inbox className="size-4" />}
        title={t`Inbox`}
        state={inbox ? t`Watching` : t`Not set`}
        live={Boolean(inbox)}
        paths={inbox ? [inbox] : []}
        empty={t`Choose an import folder to watch for new files`}
      />
      <Source
        icon={<Library className="size-4" />}
        title={t`Library folders`}
        state={
          folders.length
            ? t`${ph({ count: folders.length })} configured`
            : t`Not set`
        }
        live={false}
        paths={folders}
        empty={t`Choose a library folder to scan`}
        divided
      />
    </div>
  );
}

function Source({
  icon,
  title,
  state,
  live,
  paths,
  empty,
  divided = false,
}: {
  icon: React.ReactNode;
  title: string;
  state: string;
  live: boolean;
  paths: string[];
  empty: string;
  divided?: boolean;
}) {
  return (
    <div
      className={`flex items-center gap-3 px-4 py-3 ${divided ? "border-border-subtle max-md:border-t md:border-s" : ""}`}
    >
      <span className="text-muted-foreground">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[13px]">
          <span className="font-medium text-foreground">{title}</span>
          <span
            aria-hidden="true"
            className="size-1.5 rounded-full"
            style={{
              background: live ? "var(--status-active)" : "var(--text-muted)",
            }}
          />
          <span className="text-muted-foreground">{state}</span>
        </div>
        <div className="truncate font-mono text-[11px] text-foreground-2">
          {paths.length ? paths.join("  ·  ") : empty}
        </div>
      </div>
      <Link
        to={SETTINGS_FOLDERS}
        className="shrink-0 text-[13px] text-foreground-2 hover:text-foreground"
      >
        <Trans>Change</Trans>
      </Link>
    </div>
  );
}
