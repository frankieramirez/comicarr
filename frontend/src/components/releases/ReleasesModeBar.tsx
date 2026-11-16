import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
import { Check } from "lucide-react";
import { ToggleChip } from "@/components/ui/toggle-chip";
import { SEGMENTED_GROUP, SEGMENTED_ITEM } from "@/lib/segmented";
import {
  FORMAT_LABEL,
  type ReleaseFormat,
} from "@/components/releases/releaseFormat";

/**
 * The controls both Releases views share: which formats to show and
 * whether to show only the library's own series.
 */
export default function ReleasesModeBar({
  formats,
  format,
  onFormatChange,
  counts,
  libraryOnly,
  onLibraryOnlyChange,
}: {
  formats: ReleaseFormat[];
  format: ReleaseFormat;
  onFormatChange: (format: ReleaseFormat) => void;
  counts?: Partial<Record<ReleaseFormat, number>>;
  libraryOnly: boolean;
  onLibraryOnlyChange: (libraryOnly: boolean) => void;
}) {
  return (
    <>
      <div
        className={`${SEGMENTED_GROUP} max-w-full overflow-x-auto`}
        role="group"
        aria-label={t`Format`}
        data-testid="release-formats"
      >
        {formats.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={format === option}
            onClick={() => onFormatChange(option)}
            className={`${SEGMENTED_ITEM} shrink-0`}
          >
            {FORMAT_LABEL()[option]}
            {counts?.[option] != null && (
              <span className="mono-meta">{counts[option]}</span>
            )}
          </button>
        ))}
      </div>
      <ToggleChip
        size="md"
        className="h-8"
        pressed={libraryOnly}
        onPressedChange={onLibraryOnlyChange}
        data-testid="library-only-toggle"
      >
        {libraryOnly && <Check className="h-3.5 w-3.5" aria-hidden="true" />}
        <Trans>Only my library</Trans>
      </ToggleChip>
    </>
  );
}
