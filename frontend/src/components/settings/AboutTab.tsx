import { SettingGroup } from "./SettingGroup";
import { SettingField } from "./SettingField";
import { SupportBundleSection } from "./SupportBundleSection";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useForceVersionCheck, useVersionInfo } from "@/hooks/useVersion";
import { formatAppVersion } from "@/lib/version";
import { formatUpdateDiagnostic } from "@/lib/updateStatus";
import WhatsNewArchive from "@/components/whats-new/WhatsNewArchive";
import type { Config } from "@/types";
import type {
  SettingsFormData,
  WritableConfig,
} from "../../types/config.generated";

interface AboutTabProps {
  config: Config;
  formData: SettingsFormData;
  onChange: <K extends keyof WritableConfig>(
    key: K,
    value: NonNullable<WritableConfig[K]>,
  ) => void;
}

export function AboutTab({ config, formData, onChange }: AboutTabProps) {
  const { addToast } = useToast();
  const versionQuery = useVersionInfo();
  const forceCheck = useForceVersionCheck();

  const checkForUpdates = formData.check_github ?? true;
  const announceReleases = formData.announce_releases ?? false;
  const diagnostic = formatUpdateDiagnostic(versionQuery.data);

  const handleCheckNow = async () => {
    try {
      const result = await forceCheck.mutateAsync();
      const summary = formatUpdateDiagnostic(result);
      const toastType =
        result.update_state === "unknown"
          ? "info"
          : result.update_state === "behind"
            ? "info"
            : "success";
      addToast({ type: toastType, message: summary });
    } catch (err) {
      addToast({
        type: "error",
        message:
          err instanceof Error ? err.message : "Could not check for updates",
      });
    }
  };

  const buildRows: Array<[string, string]> = [
    ["version", formatAppVersion(false)],
    ["config path", config.config_path || "/config/config.ini"],
    ["data directory", config.data_dir || "—"],
    ["python", config.python_version || "—"],
  ];

  return (
    <div className="space-y-6">
      <SettingGroup
        title="Updates"
        description="Automatic release checks and outbound announcements."
      >
        <SettingField
          label="Check for updates"
          type="checkbox"
          checked={checkForUpdates}
          onChange={(checked) => onChange("check_github", checked as boolean)}
          helpText="When enabled, Comicarr checks for new releases automatically on a schedule. Turn off to stop automatic checks; you can still use Check now."
        />
        <SettingField
          label="Announce releases to notifiers"
          type="checkbox"
          checked={announceReleases}
          onChange={(checked) =>
            onChange("announce_releases", checked as boolean)
          }
          helpText="When enabled, send a message through enabled notifiers when a new release is available. Uses enabled notifiers only; does not reuse snatch or grab flags."
        />

        <div
          className="rounded-lg border px-3 py-2.5"
          style={{
            borderColor: "var(--border)",
            background: "var(--card)",
          }}
          data-testid="update-diagnostic"
        >
          <div className="text-[11px] uppercase tracking-[0.05em] text-muted-foreground">
            Status
          </div>
          <div className="mt-0.5 text-[13px]">{diagnostic}</div>
        </div>

        <div className="flex items-center gap-2 pt-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleCheckNow}
            disabled={forceCheck.isPending}
          >
            {forceCheck.isPending ? "Checking…" : "Check now"}
          </Button>
        </div>
      </SettingGroup>

      <SettingGroup
        title="What's new"
        description="Release notes for this install, newest first."
      >
        <WhatsNewArchive />
      </SettingGroup>

      <SupportBundleSection />

      <SettingGroup
        title="Build / environment"
        description="Install identity and paths for this instance."
      >
        <div
          className="rounded-lg border divide-y"
          style={{ borderColor: "var(--border)" }}
        >
          {buildRows.map(([k, v]) => (
            <div
              key={k}
              className="grid gap-1 sm:gap-0 sm:items-center px-3.5 py-2.5 font-mono text-[11.5px] grid-cols-1 sm:[grid-template-columns:160px_1fr]"
            >
              <div className="text-muted-foreground tracking-[0.05em] uppercase text-[10px]">
                {k}
              </div>
              <div className="truncate break-all">{v}</div>
            </div>
          ))}
        </div>
      </SettingGroup>
    </div>
  );
}
