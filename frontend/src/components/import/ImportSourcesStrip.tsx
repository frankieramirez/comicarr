import { Link } from "react-router-dom";
import { Inbox, Library } from "lucide-react";
import { useConfig } from "@/hooks/useConfig";

/**
 * Where Import looks, in one line: the watched inbox and the library folders.
 * Read-only; "Change" goes to Settings, where the paths are owned.
 */
export default function ImportSourcesStrip() {
  const { data: config } = useConfig();
  const inbox = config?.import_dir as string | undefined;
  const folders = [config?.comic_dir, config?.manga_dir].filter(
    (dir): dir is string => typeof dir === "string" && dir.length > 0,
  );

  return (
    <div
      className="grid overflow-hidden rounded-lg border border-border-subtle bg-surface-1 md:grid-cols-2"
      data-testid="import-sources"
    >
      <Source
        icon={<Inbox className="size-4" />}
        title="Inbox"
        state={inbox ? "Watching" : "Not set"}
        live={Boolean(inbox)}
        paths={inbox ? [inbox] : []}
        empty="Set an import directory to watch for new files"
      />
      <Source
        icon={<Library className="size-4" />}
        title="Library folders"
        state={folders.length ? `${folders.length} configured` : "Not set"}
        live={false}
        paths={folders}
        empty="Set a comic or manga directory to scan"
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
      className={`flex items-center gap-3 px-4 py-3 ${divided ? "border-border-subtle max-md:border-t md:border-l" : ""}`}
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
        to="/settings?section=media"
        className="shrink-0 text-[13px] text-foreground-2 hover:text-foreground"
      >
        Change
      </Link>
    </div>
  );
}
