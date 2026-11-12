import { Button } from "@/components/ui/button";

interface SaveButtonProps {
  isDirty: boolean;
  onSave: () => void;
  onCancel: () => void;
  isSaving?: boolean;
}

/**
 * The save bar: pinned to the bottom of the settings column while there is
 * something to save, and gone otherwise.
 */
export function SaveButton({
  isDirty,
  onSave,
  onCancel,
  isSaving,
}: SaveButtonProps) {
  if (!isDirty) return null;

  return (
    <div
      role="region"
      aria-label="Unsaved changes"
      className="z-10 flex shrink-0 items-center gap-3 border-t border-border-subtle bg-background px-8 py-3"
    >
      <span
        aria-hidden="true"
        className="size-1.5 rounded-full"
        style={{ background: "var(--status-wanted)" }}
      />
      <span className="text-[13px] font-medium text-foreground">
        Unsaved changes
      </span>
      <div className="ml-auto flex items-center gap-2">
        <Button variant="ghost" onClick={onCancel} disabled={isSaving}>
          Cancel
        </Button>
        <Button onClick={onSave} disabled={isSaving}>
          {isSaving ? "Saving..." : "Save Changes"}
        </Button>
      </div>
    </div>
  );
}
