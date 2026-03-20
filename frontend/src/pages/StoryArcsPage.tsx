import { BookMarked, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function StoryArcsPage() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-16 page-transition">
      <div className="text-center">
        <div className="bg-muted rounded-full p-8 inline-flex mb-8">
          <BookMarked className="w-16 h-16 text-muted-foreground" />
        </div>

        <h1 className="text-3xl font-bold text-foreground mb-4">Story Arcs</h1>

        <p className="text-lg text-muted-foreground mb-8 max-w-md mx-auto">
          Track your favorite story arcs that span across multiple series and
          issues. This feature is currently under development.
        </p>

        <div className="bg-card border border-card-border rounded-lg p-6 mb-8 text-left">
          <h2 className="font-semibold text-foreground mb-4">
            Planned Features
          </h2>
          <ul className="space-y-3 text-muted-foreground">
            <li className="flex items-start">
              <span className="text-primary mr-3">1.</span>
              <span>Browse and search story arcs from Comic Vine</span>
            </li>
            <li className="flex items-start">
              <span className="text-primary mr-3">2.</span>
              <span>Track reading progress across arc issues</span>
            </li>
            <li className="flex items-start">
              <span className="text-primary mr-3">3.</span>
              <span>Automatically want issues that belong to tracked arcs</span>
            </li>
            <li className="flex items-start">
              <span className="text-primary mr-3">4.</span>
              <span>View arc completion status and missing issues</span>
            </li>
          </ul>
        </div>

        <a
          href="https://github.com/frankieramirez/comicarr/issues"
          target="_blank"
          rel="noopener noreferrer"
        >
          <Button variant="outline" className="inline-flex items-center">
            <ExternalLink className="w-4 h-4 mr-2" />
            View Roadmap on GitHub
          </Button>
        </a>
      </div>
    </div>
  );
}
