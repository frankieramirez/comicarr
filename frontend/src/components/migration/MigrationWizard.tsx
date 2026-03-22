import { useState, useEffect } from "react";
import {
  Database,
  Download,
  FolderOpen,
  ScanSearch,
  Loader2,
  CircleCheck,
  TriangleAlert,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import {
  usePreviewMigration,
  useStartMigration,
  useMigrationProgress,
} from "@/hooks/useMigration";

interface MigrationWizardProps {
  onDismiss: () => void;
}

function MigrationWizardInner({ onDismiss }: MigrationWizardProps) {
  const [path, setPath] = useState("/mylar3");

  const preview = usePreviewMigration();
  const startMigration = useStartMigration();
  const progress = useMigrationProgress(true);

  // Derive current view from backend state
  const isMigrating =
    progress.data?.status === "migrating" ||
    progress.data?.status === "complete" ||
    progress.data?.status === "error";

  // Warn before closing during active migration
  useEffect(() => {
    if (progress.data?.status === "migrating") {
      const handler = (e: BeforeUnloadEvent) => {
        e.preventDefault();
      };
      window.addEventListener("beforeunload", handler);
      return () => window.removeEventListener("beforeunload", handler);
    }
  }, [progress.data?.status]);

  const handleValidate = () => {
    if (path.trim()) {
      preview.mutate(path.trim());
    }
  };

  const handleStartMigration = () => {
    if (path.trim()) {
      startMigration.mutate(path.trim());
    }
  };

  if (isMigrating) {
    return <ProgressView progress={progress.data!} />;
  }

  return (
    <SetupView
      path={path}
      onPathChange={setPath}
      onValidate={handleValidate}
      onStartMigration={handleStartMigration}
      onDismiss={onDismiss}
      preview={preview}
      startMigration={startMigration}
    />
  );
}

// --- Setup View ---

interface SetupViewProps {
  path: string;
  onPathChange: (path: string) => void;
  onValidate: () => void;
  onStartMigration: () => void;
  onDismiss: () => void;
  preview: ReturnType<typeof usePreviewMigration>;
  startMigration: ReturnType<typeof useStartMigration>;
}

function SetupView({
  path,
  onPathChange,
  onValidate,
  onStartMigration,
  onDismiss,
  preview,
  startMigration,
}: SetupViewProps) {
  return (
    <div className="flex flex-col gap-8">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold text-foreground">
          Migrate from Mylar3
        </h1>
        <p className="text-sm text-muted-foreground">
          Import your existing Mylar3 library, settings, and download history
          into Comicarr.
        </p>
      </div>

      {/* Path Input */}
      <div className="flex flex-col gap-2">
        <label className="text-sm font-medium text-foreground">
          Mylar3 Data Path
        </label>
        <p className="text-xs text-muted-foreground">
          Enter the path to your Mylar3 config directory (mounted as a Docker
          volume).
        </p>
        <div className="flex gap-3 items-center">
          <div className="relative flex-1">
            <FolderOpen className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={path}
              onChange={(e) => onPathChange(e.target.value)}
              className="pl-9"
              placeholder="/mylar3"
              onKeyDown={(e) => e.key === "Enter" && onValidate()}
            />
          </div>
          <Button
            onClick={onValidate}
            disabled={preview.isPending || !path.trim()}
          >
            {preview.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ScanSearch className="h-4 w-4" />
            )}
            <span className="ml-2">Validate</span>
          </Button>
        </div>
        {preview.isError && (
          <p className="text-xs text-destructive-foreground">
            {preview.error.message}
          </p>
        )}
      </div>

      {/* Preview Card */}
      {preview.data && (
        <Card>
          <CardHeader className="flex-row items-center justify-between pb-4">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Database className="h-4 w-4 text-muted-foreground" />
              Migration Preview
            </CardTitle>
            <span className="rounded bg-secondary px-2.5 py-1 text-xs font-medium text-muted-foreground">
              Mylar3 v{preview.data.version}
            </span>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {/* Stats */}
            <div className="grid grid-cols-4 gap-3">
              <StatCard label="Series" value={preview.data.series_count} />
              <StatCard
                label="Issues"
                value={preview.data.issue_count.toLocaleString()}
              />
              <StatCard
                label="Config Settings"
                value={preview.data.config_categories.length}
              />
              <StatCard label="Tables" value={preview.data.tables.length} />
            </div>

            {/* Table List */}
            <div className="border-t pt-4">
              <p className="text-xs font-semibold text-muted-foreground tracking-wide mb-3">
                Importable Tables
              </p>
              <div className="grid grid-cols-3 gap-x-4 gap-y-1.5">
                {preview.data.tables.map((table) => (
                  <div
                    key={table.name}
                    className="flex justify-between text-xs"
                  >
                    <span className="font-medium text-foreground">
                      {table.name}
                    </span>
                    <span className="text-muted-foreground">
                      {table.row_count.toLocaleString()} rows
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Path Warnings */}
            {preview.data.path_warnings.length > 0 && (
              <div className="flex items-start gap-2.5 rounded-md bg-destructive/10 border border-destructive/20 px-4 py-3">
                <TriangleAlert className="h-4 w-4 text-yellow-500 mt-0.5 shrink-0" />
                <p className="text-xs text-yellow-500">
                  {preview.data.path_warnings.length} path settings may need
                  updating for Docker — review after migration.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={onDismiss}>
          Start Fresh Instead
        </Button>
        {preview.data && (
          <Button
            onClick={onStartMigration}
            disabled={startMigration.isPending}
          >
            {startMigration.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            <span className="ml-2">Start Migration</span>
          </Button>
        )}
      </div>
    </div>
  );
}

// --- Progress View ---

interface ProgressViewProps {
  progress: {
    status: string;
    current_table: string;
    tables_complete: number;
    tables_total: number;
    error?: string | null;
  };
}

function ProgressView({ progress }: ProgressViewProps) {
  const isComplete = progress.status === "complete";
  const isError = progress.status === "error";
  const percent =
    progress.tables_total > 0
      ? Math.round((progress.tables_complete / progress.tables_total) * 100)
      : 0;

  return (
    <div className="flex flex-col gap-8">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold text-foreground">
          Migrate from Mylar3
        </h1>
        <p className="text-sm text-muted-foreground">
          {isComplete
            ? "Migration completed successfully."
            : isError
              ? "Migration encountered an error."
              : "Migration in progress \u2014 do not close this tab."}
        </p>
      </div>

      {/* Progress Card */}
      <Card>
        <CardHeader className="flex-row items-center justify-between pb-4">
          <CardTitle className="flex items-center gap-2 text-sm">
            {isComplete ? (
              <CircleCheck className="h-4 w-4 text-green-500" />
            ) : isError ? (
              <TriangleAlert className="h-4 w-4 text-destructive-foreground" />
            ) : (
              <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
            )}
            {isComplete
              ? "Migration Complete"
              : isError
                ? "Migration Failed"
                : "Migrating Data..."}
          </CardTitle>
          <span className="rounded bg-blue-500/10 px-2.5 py-1 text-xs font-medium text-blue-500">
            {progress.tables_complete} of {progress.tables_total} tables
          </span>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {/* Current table + percent */}
          {!isComplete && !isError && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                Currently importing:{" "}
                <span className="font-semibold text-foreground">
                  {progress.current_table}
                </span>
              </p>
              <span className="text-sm font-semibold text-blue-500">
                {percent}%
              </span>
            </div>
          )}

          {/* Progress bar */}
          <div className="h-2 w-full rounded-full bg-secondary">
            <div
              className={`h-2 rounded-full transition-all duration-300 ${
                isComplete
                  ? "bg-green-500"
                  : isError
                    ? "bg-destructive"
                    : "bg-blue-500"
              }`}
              style={{ width: `${percent}%` }}
            />
          </div>

          {/* Error message */}
          {isError && progress.error && (
            <p className="text-xs text-destructive-foreground">
              {progress.error}
            </p>
          )}

          {/* Completion action */}
          {isComplete && (
            <div className="flex justify-end pt-2">
              <Button onClick={() => window.location.reload()}>
                Go to Library
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// --- Stat Card ---

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-md border bg-background p-3.5">
      <span className="text-xl font-bold text-foreground">
        {typeof value === "number" ? value.toLocaleString() : value}
      </span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

// --- Exported Wrapper ---

export function MigrationWizard(props: MigrationWizardProps) {
  return (
    <ErrorBoundary>
      <MigrationWizardInner {...props} />
    </ErrorBoundary>
  );
}
