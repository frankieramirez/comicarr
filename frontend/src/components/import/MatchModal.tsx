import { useEffect, useRef, useState, type RefObject } from "react";
import { Search, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useSearchComics, useSearchManga } from "@/hooks/useSearch";
import { useContentSources } from "@/hooks/useContentSources";
import {
  detectImportSearchMode,
  getImportGroupTypeLabel,
  getImportIssueRange,
} from "@/lib/importUtils";
import type { ImportGroup, SearchResult } from "@/types";

interface MatchModalProps {
  isOpen: boolean;
  onClose: () => void;
  importGroup: ImportGroup | null;
  onMatch: (comicId: string, comicName: string) => void;
  isMatching?: boolean;
}

function resolveFocusTarget(trigger: HTMLElement | null): HTMLElement | null {
  if (trigger?.isConnected) return trigger;
  const label =
    trigger?.getAttribute("aria-label") ?? trigger?.textContent?.trim();
  if (!label) return null;
  const named = document.querySelectorAll<HTMLElement>(
    "button, [href], input, select, textarea, [tabindex]",
  );
  for (const node of named) {
    if (
      node.getAttribute("aria-label") === label ||
      node.textContent?.trim() === label
    ) {
      return node;
    }
  }
  return null;
}

function MatchModalContent({
  importGroup,
  onClose,
  onMatch,
  isMatching = false,
  finalFocus,
}: Omit<MatchModalProps, "isOpen"> & {
  finalFocus: RefObject<HTMLElement | null>;
}) {
  const searchMode = detectImportSearchMode(importGroup);
  const { mangaEnabled, isLoaded } = useContentSources();
  const mangaLoading = searchMode === "manga" && !isLoaded;
  const mangaBlocked = isLoaded && searchMode === "manga" && !mangaEnabled;
  const mangaSearchEnabled = searchMode === "manga" && isLoaded && mangaEnabled;

  const initialQuery = importGroup?.ComicName || "";
  const [searchQuery, setSearchQuery] = useState(initialQuery);
  const [selectedComic, setSelectedComic] = useState<SearchResult | null>(null);

  const comicSearch = useSearchComics(
    searchMode === "comic" ? searchQuery : "",
    1,
  );
  const mangaSearch = useSearchManga(mangaSearchEnabled ? searchQuery : "", 1);

  const {
    data: searchData,
    isLoading: isSearching,
    error: searchError,
  } = searchMode === "manga" ? mangaSearch : comicSearch;

  const handleMatch = () => {
    if (selectedComic) {
      const comicId = selectedComic.comicid || selectedComic.id;
      const comicName = selectedComic.comicname || selectedComic.name;
      onMatch(comicId, comicName);
    }
  };

  const placeholder =
    searchMode === "manga"
      ? "Search for a manga series..."
      : "Search for a comic series...";
  const fileCount = importGroup?.FileCount ?? importGroup?.files.length ?? 0;
  const matchContext = importGroup
    ? [
        getImportGroupTypeLabel(importGroup),
        `${fileCount} file${fileCount === 1 ? "" : "s"}`,
        getImportIssueRange(importGroup),
      ].filter(Boolean)
    : [];
  const matchDescription = importGroup
    ? `${importGroup.ComicName}${importGroup.Volume ? ` (${importGroup.Volume})` : ""} - ${matchContext.join(" | ")}`
    : undefined;

  return (
    <DialogContent
      className="max-h-[80vh] max-w-2xl gap-0 overflow-hidden p-0 sm:rounded-lg"
      finalFocus={() => resolveFocusTarget(finalFocus.current)}
    >
      <DialogHeader className="space-y-1 border-b border-border p-4 pr-12 text-left">
        <DialogTitle>Match Import</DialogTitle>
        {matchDescription && (
          <DialogDescription>{matchDescription}</DialogDescription>
        )}
      </DialogHeader>

      <div className="border-b border-border p-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={placeholder}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
            autoFocus
            disabled={mangaBlocked || mangaLoading}
          />
        </div>
      </div>

      <div className="max-h-[400px] overflow-y-auto p-4">
        {mangaLoading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-muted-foreground">Loading...</span>
          </div>
        )}

        {mangaBlocked && (
          <div className="py-8 text-center text-muted-foreground">
            Manga search requires MangaDex or MyAnimeList to be enabled in
            Settings.
          </div>
        )}

        {!mangaBlocked && !mangaLoading && isSearching && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-muted-foreground">Searching...</span>
          </div>
        )}

        {!mangaBlocked && !mangaLoading && searchError && (
          <div className="py-8 text-center text-destructive">
            Error searching: {searchError.message}
          </div>
        )}

        {!mangaBlocked &&
          !mangaLoading &&
          !isSearching &&
          searchData?.results &&
          searchData.results.length === 0 && (
            <div className="py-8 text-center text-muted-foreground">
              No results found. Try a different search term.
            </div>
          )}

        {!mangaBlocked &&
          !mangaLoading &&
          !isSearching &&
          searchData?.results &&
          searchData.results.length > 0 && (
            <div className="space-y-2">
              {searchData.results.map((result) => {
                const comicId = result.comicid || result.id;
                const isSelected =
                  selectedComic?.id === result.id ||
                  selectedComic?.comicid === result.comicid;

                return (
                  <button
                    key={comicId}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => setSelectedComic(result)}
                    className={`flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors ${
                      isSelected
                        ? "border-primary bg-primary/10"
                        : "border-border hover:bg-muted/50"
                    }`}
                  >
                    <div className="h-16 w-12 flex-shrink-0 overflow-hidden rounded bg-muted">
                      {result.image || result.comicimage ? (
                        <img
                          src={result.image || result.comicimage || ""}
                          alt=""
                          className="h-full w-full object-cover"
                          onError={(e) => {
                            (e.target as HTMLImageElement).style.display =
                              "none";
                          }}
                        />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center text-xs text-muted-foreground">
                          N/A
                        </div>
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">
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

                    {isSelected && (
                      <Check className="h-5 w-5 flex-shrink-0 text-primary" />
                    )}

                    {result.in_library && (
                      <span className="rounded bg-green-500/20 px-2 py-1 text-xs text-green-600 dark:text-green-400">
                        In Library
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
      </div>

      <DialogFooter className="border-t border-border bg-muted/30 p-4 sm:justify-end">
        <Button variant="outline" onClick={onClose} disabled={isMatching}>
          Cancel
        </Button>
        <Button onClick={handleMatch} disabled={!selectedComic || isMatching}>
          {isMatching ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Matching...
            </>
          ) : (
            "Match Selected"
          )}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

export default function MatchModal({
  isOpen,
  onClose,
  importGroup,
  onMatch,
  isMatching = false,
}: MatchModalProps) {
  const [keepMounted, setKeepMounted] = useState(isOpen);
  const [heldGroup, setHeldGroup] = useState(importGroup);
  const triggerRef = useRef<HTMLElement | null>(null);
  const mounted = isOpen || keepMounted;

  if (isOpen && !keepMounted) {
    setKeepMounted(true);
  }
  if (importGroup && importGroup !== heldGroup) {
    setHeldGroup(importGroup);
  }

  useEffect(() => {
    if (isOpen) return undefined;
    const rememberTrigger = (event: FocusEvent) => {
      if (event.target instanceof HTMLElement) {
        triggerRef.current = event.target;
      }
    };
    document.addEventListener("focusin", rememberTrigger);
    return () => document.removeEventListener("focusin", rememberTrigger);
  }, [isOpen]);

  const displayedGroup = importGroup ?? heldGroup;
  const modalKey = displayedGroup
    ? `${displayedGroup.DynamicName}-${displayedGroup.Volume || "null"}`
    : "closed";

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) {
          const trigger = triggerRef.current;
          onClose();
          requestAnimationFrame(() => {
            resolveFocusTarget(trigger)?.focus();
          });
        }
      }}
      onOpenChangeComplete={(open) => {
        if (!open) setKeepMounted(false);
      }}
    >
      {mounted && displayedGroup ? (
        <MatchModalContent
          key={modalKey}
          importGroup={displayedGroup}
          onClose={onClose}
          onMatch={onMatch}
          isMatching={isMatching}
          finalFocus={triggerRef}
        />
      ) : null}
    </Dialog>
  );
}
