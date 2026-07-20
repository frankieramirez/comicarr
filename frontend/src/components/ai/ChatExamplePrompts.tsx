import { Button } from "@/components/ui/button";
import { BookOpenText, Search, Sparkles, TimerReset } from "lucide-react";

interface ChatExamplePromptsProps {
  onSelectPrompt: (prompt: string) => void;
}

const EXAMPLE_PROMPTS = [
  {
    icon: Search,
    label: "Find collection gaps",
    prompt: "What Batman series am I missing issues from?",
  },
  {
    icon: BookOpenText,
    label: "Browse a publisher",
    prompt: "Show me everything published by Image Comics",
  },
  {
    icon: Sparkles,
    label: "Finish a run",
    prompt: "Which series are closest to complete?",
  },
  {
    icon: TimerReset,
    label: "Review recent additions",
    prompt: "What did I download this week?",
  },
];

export function ChatExamplePrompts({
  onSelectPrompt,
}: ChatExamplePromptsProps) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center px-5 py-12 text-center">
      <div className="mb-5 flex size-12 items-center justify-center rounded-2xl border bg-card shadow-sm">
        <BookOpenText className="text-primary" />
      </div>
      <p className="mono-label mb-2">Library intelligence</p>
      <h1 className="text-2xl font-semibold sm:text-3xl">
        Ask your collection
      </h1>
      <p className="mt-2 max-w-md text-sm text-muted-foreground sm:text-base">
        Find gaps, compare runs, or attach a cover for a closer look.
      </p>
      <div className="mt-8 grid w-full gap-2 sm:grid-cols-2">
        {EXAMPLE_PROMPTS.map(({ icon: Icon, label, prompt }) => (
          <Button
            key={prompt}
            type="button"
            variant="outline"
            className="h-auto justify-start gap-3 p-3 text-left whitespace-normal"
            onClick={() => onSelectPrompt(prompt)}
          >
            <Icon data-icon="inline-start" />
            <span>
              <span className="block text-sm font-medium">{label}</span>
              <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
                {prompt}
              </span>
            </span>
          </Button>
        ))}
      </div>
    </div>
  );
}
