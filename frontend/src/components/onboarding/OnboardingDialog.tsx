import { useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  FolderOpen,
  Loader2,
  TriangleAlert,
  SearchCheck,
  Sparkles,
  Database,
  BookOpen,
  ChevronLeft,
} from "lucide-react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  usePreviewMigration,
  useStartMigration,
  useMigrationProgress,
  type MigrationStatus,
} from "@/hooks/useMigration";
import { Kbd } from "@/components/ui/kbd";
import Logo from "@/components/Logo";

type Step = "welcome" | "migrate" | "fresh" | "running" | "done";

interface OnboardingDialogProps {
  open: boolean;
  onFinish: () => void;
}

function MonoLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-[10px] tracking-[0.1em] uppercase text-muted-foreground">
      {children}
    </div>
  );
}

function PrimaryButton({
  children,
  onClick,
  disabled,
  type = "button",
  endKbd,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
  endKbd?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center justify-center gap-2 px-3.5 py-2 rounded-[5px] text-[12px] font-semibold disabled:opacity-60"
      style={{
        background: "var(--primary)",
        color: "var(--primary-foreground)",
      }}
    >
      {children}
      {endKbd && (
        <Kbd className="bg-black/10! border-black/20! text-black/70!">
          {endKbd}
        </Kbd>
      )}
    </button>
  );
}

function GhostButton({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 px-3 py-2 rounded-[5px] border text-[12px] text-foreground disabled:opacity-60"
      style={{ borderColor: "var(--border)" }}
    >
      {children}
    </button>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      className="px-3 py-2 rounded-[5px] border"
      style={{ borderColor: "var(--border)", background: "var(--background)" }}
    >
      <MonoLabel>{label}</MonoLabel>
      <div className="text-[18px] font-semibold tracking-tight mt-0.5">
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
    </div>
  );
}

export default function OnboardingDialog({
  open,
  onFinish,
}: OnboardingDialogProps) {
  const [step, setStep] = useState<Step>("welcome");
  const [path, setPath] = useState("/mylar3");

  const preview = usePreviewMigration();
  const start = useStartMigration();
  const progress = useMigrationProgress(step === "running");

  // Derive the visible step: once we're in `running`, advance to `done` as
  // soon as the backend reports a terminal status. This avoids a setState-
  // in-effect pattern and keeps the source of truth in backend progress.
  const terminal =
    step === "running" &&
    (progress.data?.status === "complete" || progress.data?.status === "error");
  const visibleStep: Step = terminal ? "done" : step;
  const migrating = visibleStep === "running";

  // Warn on unload during an active migration
  useEffect(() => {
    if (!migrating) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [migrating]);

  const startMigration = () => {
    start.mutate(path.trim(), {
      onSuccess: () => setStep("running"),
    });
  };

  return (
    <DialogPrimitive.Root open={open} modal>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0"
          // Dismissing via overlay disabled — must use in-dialog actions
          onPointerDown={(e) => e.preventDefault()}
        />
        <DialogPrimitive.Content
          onEscapeKeyDown={(e) => {
            if (migrating) e.preventDefault();
          }}
          onPointerDownOutside={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
          className="fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[min(560px,calc(100vw-32px))] max-h-[min(640px,calc(100vh-32px))] overflow-hidden rounded-[10px] border bg-card shadow-[0_30px_80px_rgba(0,0,0,0.5)] data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
          style={{ borderColor: "var(--border)" }}
        >
          <DialogPrimitive.Title className="sr-only">
            Comicarr onboarding
          </DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            Guided setup to migrate from Mylar3 or start with a fresh library.
          </DialogPrimitive.Description>
          {/* Header */}
          <div
            className="flex items-center gap-2 px-5 py-3 border-b"
            style={{ borderColor: "var(--border)" }}
          >
            <Logo className="h-3.5 w-auto text-foreground" />
            <span className="font-mono text-[10px] text-muted-foreground px-1.5 py-0.5 border border-border rounded-sm">
              onboarding
            </span>
            <div className="ml-auto flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
              <StepDots step={visibleStep} />
            </div>
          </div>

          {/* Body */}
          <div className="px-5 py-5">
            {visibleStep === "welcome" && (
              <WelcomeStep
                onMigrate={() => setStep("migrate")}
                onFresh={() => setStep("fresh")}
              />
            )}

            {visibleStep === "migrate" && (
              <MigrateStep
                path={path}
                setPath={setPath}
                preview={preview}
                start={start}
                onBack={() => setStep("welcome")}
                onStart={startMigration}
              />
            )}

            {visibleStep === "fresh" && <FreshStep onFinish={onFinish} />}

            {visibleStep === "running" && (
              <RunningStep progress={progress.data} />
            )}

            {visibleStep === "done" && (
              <DoneStep
                progress={progress.data}
                onFinish={onFinish}
                onRetry={() => setStep("migrate")}
              />
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

// ============ Steps ============

function StepDots({ step }: { step: Step }) {
  const order: Step[] = ["welcome", "migrate", "running", "done"];
  const index = step === "fresh" ? 1 : Math.max(0, order.indexOf(step as Step));
  return (
    <div className="flex items-center gap-1.5">
      {[0, 1, 2, 3].map((i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full"
          style={{
            background: i <= index ? "var(--primary)" : "var(--border)",
          }}
        />
      ))}
    </div>
  );
}

function WelcomeStep({
  onMigrate,
  onFresh,
}: {
  onMigrate: () => void;
  onFresh: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <MonoLabel>Welcome · v0.15.1</MonoLabel>
      <div className="text-[20px] font-semibold tracking-tight">
        Let's get your library set up.
      </div>
      <div className="text-[13px] text-muted-foreground leading-relaxed">
        Comicarr can start fresh or pull your existing series, issues, and
        download history from a Mylar3 installation.
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
        <ChoiceCard
          icon={Database}
          eyebrow="Migrate"
          title="I'm coming from Mylar3"
          description="Import my library and settings."
          onClick={onMigrate}
        />
        <ChoiceCard
          icon={Sparkles}
          eyebrow="Start fresh"
          title="I'm new to Comicarr"
          description="Begin with an empty library."
          onClick={onFresh}
        />
      </div>
    </div>
  );
}

function ChoiceCard({
  icon: Icon,
  eyebrow,
  title,
  description,
  onClick,
}: {
  icon: typeof Database;
  eyebrow: string;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group text-left p-3.5 rounded-[6px] border bg-background hover:border-[var(--primary)] transition-colors"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="flex items-center gap-2 mb-2">
        <Icon
          className="w-3.5 h-3.5"
          style={{ color: "var(--primary)" }}
          strokeWidth={1.75}
        />
        <MonoLabel>{eyebrow}</MonoLabel>
      </div>
      <div className="text-[13px] font-semibold tracking-tight mb-0.5">
        {title}
      </div>
      <div className="text-[11.5px] text-muted-foreground leading-snug">
        {description}
      </div>
      <div className="mt-3 inline-flex items-center gap-1 font-mono text-[10px] text-muted-foreground group-hover:text-[var(--primary)]">
        choose <ArrowRight className="w-3 h-3" />
      </div>
    </button>
  );
}

function MigrateStep({
  path,
  setPath,
  preview,
  start,
  onBack,
  onStart,
}: {
  path: string;
  setPath: (v: string) => void;
  preview: ReturnType<typeof usePreviewMigration>;
  start: ReturnType<typeof useStartMigration>;
  onBack: () => void;
  onStart: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1 font-mono text-[10px] text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="w-3 h-3" />
          back
        </button>
      </div>

      <MonoLabel>Migrate from Mylar3</MonoLabel>
      <div className="text-[18px] font-semibold tracking-tight">
        Point us at your Mylar3 data directory.
      </div>
      <div className="text-[12px] text-muted-foreground leading-relaxed">
        Typically mounted into the container as a Docker volume. We'll read it,
        but won't modify anything.
      </div>

      <div>
        <MonoLabel>Mylar3 path</MonoLabel>
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-[5px] border bg-background mt-1.5"
          style={{ borderColor: "var(--border)" }}
        >
          <FolderOpen
            className="w-3.5 h-3.5"
            style={{ color: "var(--muted-foreground)" }}
          />
          <input
            type="text"
            aria-label="Mylar3 data directory path"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") preview.mutate(path.trim());
            }}
            placeholder="/mylar3"
            className="flex-1 bg-transparent outline-none text-[13px] font-mono placeholder:text-[var(--text-muted)]"
          />
          <button
            type="button"
            onClick={() => preview.mutate(path.trim())}
            disabled={preview.isPending || !path.trim()}
            className="inline-flex items-center gap-1.5 font-mono text-[10px] px-2 py-1 rounded border disabled:opacity-60"
            style={{
              borderColor: "var(--border)",
              color: "var(--muted-foreground)",
            }}
          >
            {preview.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <SearchCheck className="w-3 h-3" />
            )}
            validate
          </button>
        </div>
      </div>

      {preview.isError && (
        <div
          className="flex items-start gap-2 p-2.5 rounded-md text-[12px] font-mono"
          style={{
            color: "var(--status-error)",
            background: "var(--status-error-bg)",
          }}
        >
          <TriangleAlert className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>{preview.error.message}</span>
        </div>
      )}

      {preview.data && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <MonoLabel>Preview</MonoLabel>
            <span className="font-mono text-[10px] text-muted-foreground">
              mylar3 v{preview.data.version}
            </span>
          </div>
          <div className="grid grid-cols-4 gap-2">
            <Stat label="series" value={preview.data.series_count} />
            <Stat label="issues" value={preview.data.issue_count} />
            <Stat
              label="config"
              value={preview.data.config_categories.length}
            />
            <Stat label="tables" value={preview.data.tables.length} />
          </div>
          {preview.data.path_warnings.length > 0 && (
            <div
              className="flex items-start gap-2 p-2.5 rounded-md text-[11.5px]"
              style={{
                color: "var(--status-paused)",
                background: "var(--status-paused-bg)",
              }}
            >
              <TriangleAlert className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>
                {preview.data.path_warnings.length} path settings may need
                updating for Docker — review after migration.
              </span>
            </div>
          )}
        </div>
      )}

      <div
        className="flex items-center justify-between pt-3 mt-1 border-t"
        style={{ borderColor: "var(--border)" }}
      >
        <GhostButton onClick={onBack}>Cancel</GhostButton>
        {preview.data && (
          <PrimaryButton
            onClick={onStart}
            disabled={start.isPending}
            endKbd="↵"
          >
            {start.isPending ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Starting…
              </>
            ) : (
              <>Start migration</>
            )}
          </PrimaryButton>
        )}
      </div>
    </div>
  );
}

function FreshStep({ onFinish }: { onFinish: () => void }) {
  return (
    <div className="flex flex-col gap-4">
      <MonoLabel>Start fresh</MonoLabel>
      <div className="text-[18px] font-semibold tracking-tight">
        You're all set.
      </div>
      <div className="text-[12px] text-muted-foreground leading-relaxed">
        A few quick things you can do next — none are required.
      </div>

      <div
        className="rounded-[6px] border divide-y"
        style={{ borderColor: "var(--border)" }}
      >
        {[
          {
            label: "Connect a provider",
            hint: "Settings → API & providers (Comic Vine, MangaDex)",
            icon: Database,
          },
          {
            label: "Configure library paths",
            hint: "Settings → Media (comic + manga directories)",
            icon: FolderOpen,
          },
          {
            label: "Add your first series",
            hint: "Library → Add, or press N from anywhere",
            icon: BookOpen,
          },
        ].map(({ label, hint, icon: Icon }) => (
          <div key={label} className="flex items-start gap-3 px-3.5 py-3">
            <Icon
              className="w-3.5 h-3.5 mt-0.5 shrink-0"
              style={{ color: "var(--primary)" }}
              strokeWidth={1.75}
            />
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-medium">{label}</div>
              <div className="font-mono text-[10.5px] text-muted-foreground mt-0.5">
                {hint}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div
        className="flex justify-end pt-3 border-t"
        style={{ borderColor: "var(--border)" }}
      >
        <PrimaryButton onClick={onFinish} endKbd="↵">
          Take me to the dashboard
        </PrimaryButton>
      </div>
    </div>
  );
}

function RunningStep({
  progress,
}: {
  progress?: {
    current_table: string;
    tables_complete: number;
    tables_total: number;
  };
}) {
  const pct = progress?.tables_total
    ? Math.round((progress.tables_complete / progress.tables_total) * 100)
    : 0;
  return (
    <div className="flex flex-col gap-4">
      <MonoLabel>Migrating · do not close this tab</MonoLabel>
      <div className="text-[18px] font-semibold tracking-tight">
        Importing your library…
      </div>

      <div className="flex items-center gap-3">
        <Loader2
          className="w-4 h-4 animate-spin"
          style={{ color: "var(--primary)" }}
        />
        <div className="flex-1 min-w-0">
          <div className="font-mono text-[11px] text-muted-foreground truncate">
            current:{" "}
            <span className="text-foreground">
              {progress?.current_table || "—"}
            </span>
          </div>
        </div>
        <div className="font-mono text-[11px] text-muted-foreground">
          {progress?.tables_complete ?? 0} / {progress?.tables_total ?? 0}
        </div>
      </div>

      <div
        className="h-[3px] rounded-full overflow-hidden"
        style={{ background: "var(--secondary)" }}
      >
        <div
          className="h-full transition-all duration-500"
          style={{ width: `${pct}%`, background: "var(--primary)" }}
        />
      </div>

      <div className="font-mono text-[10px] text-muted-foreground text-right">
        {pct}%
      </div>
    </div>
  );
}

function DoneStep({
  progress,
  onFinish,
  onRetry,
}: {
  progress?: { status: MigrationStatus; error?: string };
  onFinish: () => void;
  onRetry: () => void;
}) {
  const errored = progress?.status === "error";

  if (errored) {
    return (
      <div className="flex flex-col gap-4">
        <MonoLabel>Migration failed</MonoLabel>
        <div className="text-[18px] font-semibold tracking-tight">
          Something went wrong.
        </div>
        <div
          className="p-3 rounded-md font-mono text-[11.5px]"
          style={{
            color: "var(--status-error)",
            background: "var(--status-error-bg)",
          }}
        >
          {progress?.error || "Unknown error"}
        </div>
        <div
          className="flex justify-between pt-3 border-t"
          style={{ borderColor: "var(--border)" }}
        >
          <GhostButton onClick={onFinish}>Skip for now</GhostButton>
          <PrimaryButton onClick={onRetry}>Try again</PrimaryButton>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <MonoLabel>Migration complete</MonoLabel>
      <div className="flex items-center gap-2 text-[18px] font-semibold tracking-tight">
        <Check
          className="w-5 h-5"
          style={{ color: "var(--status-active)" }}
          strokeWidth={2.25}
        />
        Your library is ready.
      </div>
      <div className="text-[12px] text-muted-foreground leading-relaxed">
        Everything from Mylar3 has been imported. You may need to refresh
        metadata on a few series.
      </div>
      <div
        className="flex justify-end pt-3 border-t"
        style={{ borderColor: "var(--border)" }}
      >
        <PrimaryButton onClick={onFinish} endKbd="↵">
          Go to dashboard
        </PrimaryButton>
      </div>
    </div>
  );
}
