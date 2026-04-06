import { MessageSquare } from "lucide-react";

interface ChatExamplePromptsProps {
  onSelectPrompt: (prompt: string) => void;
}

const EXAMPLE_PROMPTS = [
  "What Batman series am I missing issues from?",
  "Show me everything published by Image Comics",
  "Which series are closest to complete?",
  "What did I download this week?",
];

export function ChatExamplePrompts({
  onSelectPrompt,
}: ChatExamplePromptsProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full px-4 py-8">
      <MessageSquare className="h-10 w-10 text-muted-foreground mb-4" />
      <h3 className="text-base font-medium text-foreground mb-2">
        Ask about your library
      </h3>
      <p className="text-sm text-muted-foreground text-center mb-6">
        Ask questions about your comic collection in plain English.
      </p>
      <div className="w-full space-y-2">
        {EXAMPLE_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            onClick={() => onSelectPrompt(prompt)}
            className="w-full text-left rounded-lg border border-border px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-accent hover:border-accent transition-colors"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}
