import { useState } from "react";
import { Link } from "react-router-dom";
import { Bot, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const DISMISS_KEY = "dismissed_ai_banner";

function getInitialDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === "true";
  } catch {
    return false;
  }
}

export default function AiDiscoveryBanner() {
  const [dismissed, setDismissed] = useState(getInitialDismissed);

  const handleDismiss = () => {
    localStorage.setItem(DISMISS_KEY, "true");
    setDismissed(true);
  };

  if (dismissed) return null;

  return (
    <Card className="mt-6 border-dashed">
      <CardContent className="p-5">
        <div className="flex items-start gap-4">
          <div className="rounded-full bg-muted p-2 shrink-0">
            <Bot className="w-5 h-5 text-muted-foreground" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium mb-1">AI Features Available</p>
            <p className="text-sm text-muted-foreground mb-3">
              Connect a local AI model to enable smart search, metadata
              enrichment, and library insights. Runs entirely on your hardware.
            </p>
            <Link to="/settings?tab=ai">
              <Button variant="outline" size="sm">
                Configure AI
              </Button>
            </Link>
          </div>
          <button
            onClick={handleDismiss}
            className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Dismiss"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </CardContent>
    </Card>
  );
}
