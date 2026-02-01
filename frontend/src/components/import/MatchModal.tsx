import { useState, useMemo } from "react";
import { Search, X, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSearchComics } from "@/hooks/useSearch";
import type { ImportGroup, SearchResult } from "@/types";

interface MatchModalProps {
  isOpen: boolean;
  onClose: () => void;
  importGroup: ImportGroup | null;
  onMatch: (comicId: string, comicName: string) => void;
  isMatching?: boolean;
}

// Inner component that resets when importGroup changes
function MatchModalContent({
  importGroup,
  onClose,
  onMatch,
  isMatching = false,
}: Omit<MatchModalProps, "isOpen">) {
  // Initialize search query from importGroup - this will reset when the key changes
  const initialQuery = importGroup?.ComicName || "";
  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const [selectedComic, setSelectedComic] = useState<SearchResult | null>(null);

  const {
    data: searchData,
    isLoading: isSearching,
    error: searchError,
  } = useSearchComics(searchQuery, 1);

  const handleMatch = () => {
    if (selectedComic) {
      const comicId = selectedComic.comicid || selectedComic.id;
      const comicName = selectedComic.comicname || selectedComic.name;
      onMatch(comicId, comicName);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-card border border-card-border rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-card-border">
          <div>
            <h2 className="text-lg font-semibold">Match Import</h2>
            {importGroup && (
              <p className="text-sm text-muted-foreground">
                {importGroup.ComicName}
                {importGroup.Volume && ` (${importGroup.Volume})`}
                {" - "}
                {importGroup.FileCount} file
                {importGroup.FileCount !== 1 ? "s" : ""}
              </p>
            )}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>

        {/* Search Input */}
        <div className="p-4 border-b border-card-border">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search for a comic series..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10"
              autoFocus
            />
          </div>
        </div>

        {/* Results */}
        <div className="overflow-y-auto max-h-[400px] p-4">
          {isSearching && (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
              <span className="ml-2 text-muted-foreground">Searching...</span>
            </div>
          )}

          {searchError && (
            <div className="text-center py-8 text-destructive">
              Error searching: {searchError.message}
            </div>
          )}

          {!isSearching && searchData?.results && searchData.results.length === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              No results found. Try a different search term.
            </div>
          )}

          {!isSearching && searchData?.results && searchData.results.length > 0 && (
            <div className="space-y-2">
              {searchData.results.map((result) => {
                const comicId = result.comicid || result.id;
                const isSelected = selectedComic?.id === result.id ||
                  selectedComic?.comicid === result.comicid;

                return (
                  <div
                    key={comicId}
                    onClick={() => setSelectedComic(result)}
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      isSelected
                        ? "border-primary bg-primary/10"
                        : "border-card-border hover:bg-muted/50"
                    }`}
                  >
                    {/* Cover Image */}
                    <div className="w-12 h-16 bg-muted rounded overflow-hidden flex-shrink-0">
                      {result.image || result.comicimage ? (
                        <img
                          src={result.image || result.comicimage || ""}
                          alt=""
                          className="w-full h-full object-cover"
                          onError={(e) => {
                            (e.target as HTMLImageElement).style.display = "none";
                          }}
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-muted-foreground text-xs">
                          N/A
                        </div>
                      )}
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">
                        {result.comicname || result.name}
                      </div>
                      <div className="text-sm text-muted-foreground">
                        {result.comicyear || result.start_year}
                        {result.publisher && ` - ${result.publisher}`}
                      </div>
                      {result.count_of_issues && (
                        <div className="text-xs text-muted-foreground">
                          {result.count_of_issues} issues
                        </div>
                      )}
                    </div>

                    {/* Selection indicator */}
                    {isSelected && (
                      <Check className="w-5 h-5 text-primary flex-shrink-0" />
                    )}

                    {/* In library indicator */}
                    {result.in_library && (
                      <span className="text-xs bg-green-500/20 text-green-600 dark:text-green-400 px-2 py-1 rounded">
                        In Library
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 p-4 border-t border-card-border bg-muted/30">
          <Button variant="outline" onClick={onClose} disabled={isMatching}>
            Cancel
          </Button>
          <Button
            onClick={handleMatch}
            disabled={!selectedComic || isMatching}
          >
            {isMatching ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Matching...
              </>
            ) : (
              "Match Selected"
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function MatchModal({
  isOpen,
  onClose,
  importGroup,
  onMatch,
  isMatching = false,
}: MatchModalProps) {
  // Generate a unique key based on importGroup to reset internal state when it changes
  const modalKey = useMemo(() => {
    if (!importGroup) return "closed";
    return `${importGroup.DynamicName}-${importGroup.Volume || "null"}-${isOpen}`;
  }, [importGroup, isOpen]);

  if (!isOpen) return null;

  // Using key prop to reset the inner component's state when importGroup changes
  return (
    <MatchModalContent
      key={modalKey}
      importGroup={importGroup}
      onClose={onClose}
      onMatch={onMatch}
      isMatching={isMatching}
    />
  );
}
