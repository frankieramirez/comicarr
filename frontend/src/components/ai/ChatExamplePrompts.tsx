import { t } from "@lingui/core/macro";
import { Trans } from "@lingui/react/macro";
interface ChatExamplePromptsProps {
  onSelectPrompt: (prompt: string) => void;
}

const EXAMPLE_PROMPTS = () => [
  {
    label: t`Find the gaps`,
    prompt: t`Which runs am I missing issues from?`,
  },
  {
    label: t`Almost done`,
    prompt: t`Which series are closest to complete?`,
  },
  {
    label: t`By publisher`,
    prompt: t`Show me everything from Image Comics`,
  },
  {
    label: t`This week`,
    prompt: t`What landed in the last seven days?`,
  },
];

/**
 * Opening state for a draft thread. It sits directly above the composer rather
 * than centred in the viewport, so the prompts land where the eye already is.
 */
export function ChatExamplePrompts({
  onSelectPrompt,
}: ChatExamplePromptsProps) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 pb-5 sm:px-6">
      <div className="flex flex-col gap-1.5">
        <h2 className="text-2xl font-semibold tracking-tight sm:text-[26px]">
          <Trans>What are we hunting today?</Trans>
        </h2>
        <p className="text-sm text-muted-foreground sm:text-[15px]">
          <Trans>
            Ask about anything in your collection — gaps, publishers, duplicates
            — or drop a cover and I&rsquo;ll tell you what it is.
          </Trans>
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {EXAMPLE_PROMPTS().map(({ label, prompt }) => (
          <button
            key={prompt}
            type="button"
            className="flex flex-col gap-0.5 rounded-xl border bg-card/40 px-3.5 py-3 text-start transition-colors hover:border-ring hover:bg-card"
            onClick={() => onSelectPrompt(prompt)}
          >
            <span className="text-[13px] font-medium">{label}</span>
            <span className="text-xs text-muted-foreground">{prompt}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
