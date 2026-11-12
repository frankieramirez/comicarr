/**
 * Core entity type definitions
 */

/** Comic series status */
export type SeriesStatus = "Active" | "Paused" | "Ended" | "Loading" | "Error";

/** Issue status */
export type IssueStatus =
  | "Downloaded"
  | "Wanted"
  | "Skipped"
  | "Ignored"
  | "Reserved"
  | "Snatched"
  | "Archived"
  | "Failed";

/** Statuses an operator can set on an issue (PUT /api/series/issues/{id}/status). */
export type SettableIssueStatus = "Wanted" | "Skipped" | "Ignored" | "Archived";

/** User or policy intent, independent of the acquisition evidence. */
export type AcquisitionIntent = "policy" | "wanted" | "skipped" | "ignored";

/** Evidence-backed acquisition state, independent of user intent. */
export type FulfillmentState =
  | "unknown"
  | "missing"
  | "reserved"
  | "snatched"
  | "downloaded"
  | "archived"
  | "failed";

/** Compact state shown in issue tables and filters. */
export type IssueDisplayState =
  | "Unknown"
  | "Missing"
  | "Wanted"
  | "Skipped"
  | "Ignored"
  | "Reserved"
  | "Snatched"
  | "Downloaded"
  | "Archived"
  | "Failed";

/** The policy explanation included with the canonical issue projection. */
export interface IssueEligibility {
  eligible: boolean;
  reason: string;
  date: string | null;
  source: "releaseDate" | "digitalDate" | "issueDate" | null;
}

/** Comic series entity from getIndex/getComic */
export interface Comic {
  ComicID: string;
  ComicName: string;
  ComicYear?: string | null;
  ComicPublisher?: string | null;
  ComicImage?: string | null;
  ComicImageURL?: string | null;
  Status: SeriesStatus;
  Total?: number;
  Have?: number;
  LatestDate?: string | null;
  LastUpdated?: string | null;
  DateAdded?: string | null;
  Description?: string | null;
  DetailURL?: string | null;
  ComicLocation?: string | null;
  Corrected_SeriesYear?: string | null;
  ForceContinuing?: boolean;
  AlternateSearch?: string | null;
  ComicVersion?: string | null;
  ContentType?: SeriesKind | null;
  /** Per-series pack/bundle matching flag — Text column, "1" when enabled */
  AllowPacks?: string | number | null;
  /** Per-series booktype-mismatch override — Integer flag column */
  IgnoreType?: number | null;
  /** Per-series bare-number interpretation: auto | volumes | chapters */
  BareNumberMode?: "auto" | "volumes" | "chapters" | null;
  /** Per-series auto-search frontier: blended | volumes | chapters */
  MonitorMode?: "blended" | "volumes" | "chapters" | null;
  /** 1 when the operator chose ComicLocation instead of Comicarr deriving it */
  LocationOverride?: number | null;
  /** JSON list of folders that still hold files left behind by a folder change */
  RetainedLocations?: string | null;
}

/** Issue entity */
export interface Issue {
  IssueID: string;
  ComicID: string;
  ComicName?: string;
  ComicYear?: string | null;
  Issue_Number: string;
  IssueName?: string | null;
  IssueDate?: string | null;
  ReleaseDate?: string | null;
  DateAdded?: string | null;
  Status: IssueStatus;
  Location?: string | null;
  ImageURL?: string | null;
  ImageURL_ALT?: string | null;
  Int_IssueNumber?: number | null;
  Arc?: string | null;
  chapterNumber?: string | null;
  volumeNumber?: string | null;
  legacyStatus?: string | null;
  rawAcquisitionIntent?: string | null;
  displayState?: IssueDisplayState | null;
  acquisitionIntent?: AcquisitionIntent | null;
  intentExplicit?: boolean;
  fulfillment?: FulfillmentState | null;
  fulfillmentEvidence?: string | null;
  eligible?: boolean;
  eligibility?: IssueEligibility;
  eligibilityDate?: string | null;
  eligibilityDateSource?: "releaseDate" | "digitalDate" | "issueDate" | null;
  owned?: boolean;
  physicalOwned?: boolean;
  archived?: boolean;
  inFlight?: boolean;
  future?: boolean;
  deferred?: boolean;
  missing?: boolean;
  monitored?: boolean;
  eligibilityReason?: string | null;
  annual?: boolean;
  id?: string;
  number?: string | null;
  name?: string | null;
  releaseDate?: string | null;
  issueDate?: string | null;
  status?: string | null;
  imageURL?: string | null;
  location?: string | null;
  digitalDate?: string | null;
  comicId?: string;
  comicName?: string | null;
}

/** Aggregated issue projection counts from series detail */
export interface SeriesIssueSummary {
  total?: number;
  issues?: number;
  annuals?: number;
  owned?: number;
  physicalOwned?: number;
  archived?: number;
  inFlight?: number;
  missing?: number;
  monitored?: number;
  wanted?: number;
  skipped?: number;
  ignored?: number;
  failed?: number;
  unknown?: number;
  future?: number;
  eligible?: number;
  deferred?: number;
  completionPercent?: number;
}

/** Preview row for search-all-missing */
export interface SearchMissingPreviewItem {
  issueId: string;
  issueNumber?: string | null;
  entityType?: "issue" | "annual";
  displayState?: IssueDisplayState | null;
  reason?: string | null;
  eligibilityReason?: string | null;
}

/** Route readiness snippet on search-missing preview */
export interface SearchMissingRoute {
  viable: boolean;
  reason?: string | null;
}

/** GET /api/series/{id}/search-missing/preview */
export interface SearchMissingPreview {
  success: boolean;
  comicId?: string;
  eligibleCount: number;
  excludedCount: number;
  eligible?: SearchMissingPreviewItem[];
  excluded?: SearchMissingPreviewItem[];
  route?: SearchMissingRoute;
  summary?: SeriesIssueSummary;
  canSearch: boolean;
  preview_token?: string;
  fingerprint?: string;
  error?: string;
}

/** Input used by the UI to confirm a one-shot Search all missing preview. */
export interface SearchMissingConfirmationInput {
  comicId: string;
  previewToken: string;
  fingerprint: string;
}

/** POST /api/series/{id}/search-missing */
export interface SearchMissingResult {
  success: boolean;
  status?:
    | "accepted"
    | "blocked"
    | "noop"
    | "pending_dispatch"
    | "stale_preview"
    | "invalid_preview"
    | "failed";
  accepted?: number;
  rejected?: number;
  run_id?: string | null;
  idempotent?: boolean;
  message?: string;
  error?: string;
  preview?: SearchMissingPreview;
}

export interface SearchRunRetryResult {
  success: boolean;
  status?: "accepted" | "partial" | "failed";
  run_id: string;
  dispatched: number;
  errors: string[];
  message?: string;
  run?: SearchRun;
  error?: string;
}

/** Scheduler acceptance state for a durable search run. */
export type SearchRunDispatchState =
  "pending" | "accepted" | "error" | "missed" | "max_instances";

/** Completion state calculated from the run's individual issue outcomes. */
export type SearchRunCompletionState =
  "pending" | "running" | "completed" | "partial" | "blocked" | "failed";

export type SearchRunItemState =
  | "accepted"
  | "running"
  | "succeeded"
  | "no_match"
  | "blocked"
  | "failed"
  | "quarantined"
  | "cancelled";

/** Sanitized durable search run returned by GET /api/search/runs/{id}. */
export interface SearchRun {
  run_id: string;
  command_kind: "search";
  trigger: string;
  scope_type: string | null;
  scope_id: string | null;
  dispatch_state: SearchRunDispatchState;
  completion_state: SearchRunCompletionState;
  accepted_count: number;
  terminal_count: number;
  succeeded_count: number;
  no_match_count: number;
  blocked_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  queue_priority: "interactive" | "routine" | "recovery";
}

export interface SearchRunItem {
  entity_type: string;
  entity_id: string;
  state: SearchRunItemState;
  attempt_count: number;
  reason: string | null;
  updated_at: string;
  completed_at: string | null;
  queue_priority: "interactive" | "routine" | "recovery";
  attempt_status: "queued" | "searching" | SearchRunItemState;
}

export interface SearchRunResult {
  success: boolean;
  run: SearchRun;
  items: SearchRunItem[];
}

/** POST /api/search/force outcome */
export interface ForceSearchResult {
  success: boolean;
  status?: "accepted" | "partial" | "no_match" | "blocked" | "failed";
  run_id?: string;
  accepted?: number;
  message?: string;
  error?: string;
}

/** Search result from findComic */
export interface SearchResult {
  id: string;
  name: string;
  comicid?: string;
  comicname?: string;
  comicyear?: string | null;
  start_year?: string | null;
  publisher?: string | null;
  description?: string | null;
  image?: string | null;
  comicimage?: string | null;
  comicthumb?: string | null;
  count_of_issues?: number;
  issues?: number;
  in_library?: boolean;
  /** Library match from the backend: "No", or the matching library row. */
  haveit?: "No" | { comicid?: string; status?: string } | null;
  deck?: string | null;
  metadata_source?: string;
  url?: string | null;
  status?: string | null;
  content_rating?: string | null;
}

/**
 * Live-sticky acquisition annotation on a Wanted row (#490).
 * Latest search `acquisition_run_items` row for this IssueID, or null when
 * the issue has never been accepted into a search run.
 */
export interface WantedAcquisitionAnnotation {
  state: string | null;
  attempt_count: number;
  reason?: string | null;
  run_id?: string | null;
  entity_type?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
}

/** Wanted issue (issue with extra fields from wanted queue) */
export interface WantedIssue extends Issue {
  QueueType?: string;
  Provider?: string;
  /** Latest search run-item annotation; null when never searched. */
  acquisition?: WantedAcquisitionAnnotation | null;
}

/** Why a Wanted issue is still missing, from its latest search. */
export type WantedBucket = "not_found" | "searching" | "queued";

/** One series row of GET /api/wanted/series. */
export interface WantedSeries {
  comicid: string;
  comic_name: string;
  comic_year?: string | null;
  publisher?: string | null;
  kind: "comic" | "manga";
  missing: number;
  /** Compressed issue numbers, e.g. "#1-249, #301-310, +12". */
  which: string;
  /** The row's most urgent reason. */
  why: WantedBucket;
  buckets: Record<WantedBucket, number>;
  /** Most search attempts among its not-found issues. */
  max_attempts: number;
  last_searched_at: string | null;
  /** Hours until auto-search reaches this series' last unchecked issue. */
  eta_hours?: number | null;
}

/** How fast auto-search is working through Wanted (RSS watchlist pass). */
export interface WantedPacing {
  state: "checking" | "waiting_for_feed" | "off" | "idle";
  total: number;
  checked: number;
  waiting: number;
  per_hour: number;
  /** False when per_hour is the configured ceiling, not a measurement. */
  measured: boolean;
  per_pass: number;
  interval_minutes: number;
  finishes_in_hours: number | null;
  next_pass_at: string | null;
  new_issue_days: number;
  search_interval_minutes: number;
  next_search_at: string | null;
  indexers: number;
}

export interface WantedSeriesResponse {
  series: WantedSeries[];
  /** Issue counts per reason across the whole filtered set. */
  counts: Record<"all" | WantedBucket, number>;
  pacing?: WantedPacing;
  pagination: {
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
  };
}

/** Upcoming issue */
export interface UpcomingIssue extends Omit<Issue, "Status"> {
  ReleaseComicID?: string;
  ReleaseComicName?: string;
  IssueNumber?: string;
  ReleaseDate?: string;
  Status?: IssueStatus;
  CV_ReleaseDate?: string;
  Store_Date?: string;
  /** Pull-list publisher, or the series' own when the pull list has none. */
  Publisher?: string | null;
  ContentType?: string | null;
  /** The open Needs attention reason for this issue, if any. */
  attention?: string | null;
  /** Its base reason code, to find the cause's one-click fix. */
  attention_reason?: string | null;
  /** An open download: how far along, when its client can say. */
  download?: {
    phase: "downloading" | "importing";
    percent: number | null;
    time_left: string | null;
  } | null;
  /** When the newest import or download of this issue succeeded. */
  downloaded_at?: string | null;
}

/** One missing issue a series-scoped release candidate would satisfy. */
export interface InteractiveSatisfiedIssue {
  entity_type: "issue" | "annual" | "story_arc_issue";
  entity_id: string;
  issue_number?: string | null;
}

/** Fields the interactive-search review sheet actually renders. */
export interface ReleaseReviewIssue {
  IssueNumber?: string | null;
  Issue_Number?: string | null;
  ComicName?: string | null;
  ReleaseComicName?: string | null;
  Status?: string | null;
  annual?: boolean;
  scope?: "issue" | "series";
  missingCount?: number;
  /** Series scope only: the session was an unfiltered all-indexer search. */
  unfiltered?: boolean;
}

export interface InteractiveVerdictReason {
  code: string;
  message: string;
}

export interface InteractiveReleaseCandidate {
  candidate_id: string;
  state:
    | "available"
    | "unavailable"
    | "submitting"
    | "submitted"
    | "failed"
    | "manual_review";
  candidate: {
    title: string;
    provider: string;
    source_kind: string;
    published_at: string | null;
    size_bytes: number | null;
    pack: boolean;
    metrics: Record<string, number>;
  };
  verdict: {
    status: string;
    accepted: boolean;
    overrideable: boolean;
    reason_code: string;
    reasons: InteractiveVerdictReason[];
    match_kind: string;
  };
  satisfies?: InteractiveSatisfiedIssue[];
}

export interface InteractiveProviderFailure {
  provider: string;
  code: string;
  detail: string;
}

export interface InteractiveSearchSession {
  success?: boolean;
  session_id: string;
  entity_type: "issue" | "annual" | "story_arc_issue" | "series";
  entity_id: string;
  series_id: string | null;
  state: "queued" | "running" | "complete" | "failed";
  candidate_count: number;
  progress: {
    provider_total: number;
    provider_completed: number;
    current_provider: string | null;
  };
  provider_failures: InteractiveProviderFailure[];
  created_at: string;
  expires_at: string;
  candidates: InteractiveReleaseCandidate[];
}

export interface InteractiveGrabResult {
  success: boolean;
  status: "submitted" | "failed" | "manual_review";
  candidate_id: string;
  journal_release_key?: string | null;
  journal_managed?: boolean;
  idempotent?: boolean;
  code?: string;
  error?: string;
}

/** Outbound catalog page for the series' metadata (and chapter) provider. */
export interface ProviderPageLink {
  provider: string;
  label: string;
  url: string;
}

export interface ProviderOverride {
  order: string[];
  exclude: string[];
}

/** Enabled search providers in global order, and the Series' override. */
export interface SeriesSearchProviders {
  available: string[];
  override: ProviderOverride | null;
}

/** Series detail response (includes issues) */
export interface SeriesDetail {
  comic: Comic[] | Comic;
  issues: Issue[];
  annuals?: Issue[];
  summary?: SeriesIssueSummary;
  providerLinks?: ProviderPageLink[];
  searchProviders?: SeriesSearchProviders;
}

/** Content type for comic/manga distinction */
export type ContentType = "comic" | "manga";

/** How the operator catalogs a Series; a magazine is a comic for search and downloads */
export type SeriesKind = ContentType | "magazine";

/** Reading direction for manga */
export type ReadingDirection = "ltr" | "rtl";

/** Extended Comic interface with manga support */
export interface ComicOrManga extends Comic {
  ContentType?: SeriesKind | null;
  ReadingDirection?: ReadingDirection;
  MetadataSource?: string | null;
  ExternalID?: string | null;
}

/** Import file entity */
export interface ImportFile {
  impID: string;
  ComicFilename: string;
  ComicLocation: string;
  IssueNumber: string | null;
  ComicYear: string | null;
  Status: string;
  IgnoreFile: number;
  MatchConfidence: number | null;
  SuggestedComicID: string | null;
  SuggestedComicName: string | null;
  SuggestedIssueID: string | null;
  MatchSource: string | null;
}

/** Summary counts returned by GET /api/import */
export interface ImportPendingSummary {
  group_count: number;
  file_count: number;
}

/** Story Arc status for individual issues */
export type ArcIssueStatus =
  "Downloaded" | "Wanted" | "Skipped" | "Archived" | "Read" | "Added";

/** Story Arc summary (list view) */
export interface StoryArc {
  StoryArcID: string;
  StoryArc: string;
  TotalIssues: number;
  Have: number;
  Total: number;
  percent: number;
  SpanYears: string | null;
  CV_ArcID: string | null;
  Publisher: string | null;
  ArcImage: string | null;
}

/** Story Arc issue (detail view) */
export interface ArcIssue {
  IssueArcID: string;
  ReadingOrder: number;
  ComicID: string;
  ComicName: string;
  IssueNumber: string;
  IssueID: string;
  Status: ArcIssueStatus;
  IssueDate: string | null;
  IssueName: string | null;
  IssuePublisher: string | null;
  Location: string | null;
}

export interface MissingArcSeries {
  series_name: string;
  comic_id: string;
  series_year: string | null;
  publisher: string | null;
  issue_count: number;
  issue_numbers: string[];
}

/** Missing arc series resolved to a ComicVine volume for confirmation */
export interface ResolvedArcSeries extends MissingArcSeries {
  match: {
    comic_id: string;
    name: string | null;
    year: string | null;
    publisher: string | null;
    image: string | null;
  } | null;
}

/** Story Arc detail response */
export interface StoryArcDetail {
  arc: StoryArc;
  issues: ArcIssue[];
  missing: MissingArcSeries[];
}

/** Story Arc search result (from CV) */
export interface ArcSearchResult {
  id: string;
  name: string;
  publisher: string | null;
  issues: string;
  description: string | null;
  image: string | null;
  cvarcid: string;
  arclist: string | null;
  haveit: string | null;
}

/** Library scan result (from comic/manga scan-then-select flow) */
export interface ScanResultMatch {
  comicid: string;
  name: string;
  year?: string;
  publisher?: string;
  issues?: string;
  image?: string | null;
  confidence: number;
  source?: string;
}

export interface ScanResult {
  series_name: string;
  file_count: number;
  matched: boolean;
  already_in_library?: boolean;
  reconciled?: boolean;
  existing_comic_id?: string;
  match?: ScanResultMatch | null;
  error?: string;
}

export interface ScanProgress {
  status: string | null;
  progress: {
    total_files: number;
    processed_files: number;
    series_found: number;
    series_matched: number;
    series_reconciled?: number;
    current_series: string | null;
    errors: string[];
  };
  scan_id: string | null;
  results: ScanResult[] | null;
}

/** Import group (grouped by DynamicName + Volume) */
export interface ImportGroup {
  DynamicName: string;
  ComicName: string;
  Volume: string | null;
  ComicYear: string | null;
  FileCount: number;
  Status: string;
  SRID: string | null;
  ComicID: string | null;
  MatchConfidence: number | null;
  SuggestedComicID: string | null;
  SuggestedComicName: string | null;
  files: ImportFile[];
}
