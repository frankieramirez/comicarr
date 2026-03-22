/**
 * Central export for all type definitions
 */

// API types
export type {
  ApiResponse,
  PaginationMeta,
  PaginatedResponse,
  LoginResponse,
  LogoutResponse,
  SessionResponse,
  ApiKeyResponse,
  ApiCommand,
  ApiParams,
} from "./api";

// Entity types
export type {
  SeriesStatus,
  IssueStatus,
  Comic,
  Issue,
  SearchResult,
  WantedIssue,
  UpcomingIssue,
  SeriesDetail,
  ContentType,
  ReadingDirection,
  MangaSearchResult,
  MangaChapter,
  ComicOrManga,
  IssueOrChapter,
  VolumeGroup,
  ImportFile,
  ImportGroup,
} from "./entities";

// Auth types
export type {
  User,
  AuthContextValue,
  LoginCredentials,
  AuthState,
} from "./auth";

// Event types
export type {
  SSEEventData,
  AddByIdEventData,
  SchedulerMessageEventData,
  ConfigCheckEventData,
  CheckUpdateEventData,
  SearchProgressEventData,
  SearchCompleteEventData,
  MessageEventData,
  ComicAddedEvent,
} from "./events";

// Config types
export type {
  Config,
  NewznabProvider,
  TorznabProvider,
  ConfigUpdate,
} from "./config";

// Migration types
export type { MigrationStatus } from "../hooks/useMigration";

// Component types
export type {
  StatusBadgeProps,
  ButtonVariant,
  ButtonSize,
  ToastType,
  ToastData,
  ToastContextValue,
  WantedTableProps,
  UpcomingTableProps,
  IssuesTableProps,
  SeriesTableProps,
  ComicCardProps,
  FilterBarProps,
  FilterState,
  BulkActionBarProps,
  LayoutProps,
  ProtectedRouteProps,
  ThemeToggleProps,
  ErrorBoundaryProps,
  ErrorBoundaryState,
} from "./components";
