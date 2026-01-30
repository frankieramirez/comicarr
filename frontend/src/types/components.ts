/**
 * Component prop type definitions
 */

import type { ReactNode } from "react";
import type {
  Issue,
  WantedIssue,
  UpcomingIssue,
  Comic,
  SearchResult,
  IssueStatus,
  SeriesStatus,
} from "./entities";
import type { PaginationMeta } from "./api";

/** StatusBadge props */
export interface StatusBadgeProps {
  status: IssueStatus | SeriesStatus | string;
  className?: string;
}

/** Button variants */
export type ButtonVariant =
  | "default"
  | "destructive"
  | "outline"
  | "secondary"
  | "ghost"
  | "link";
export type ButtonSize = "default" | "sm" | "lg" | "icon";

/** Toast types */
export type ToastType = "success" | "error" | "info";

/** Toast data */
export interface ToastData {
  id?: string;
  type?: ToastType;
  title?: string;
  description?: string;
  message?: string;
  duration?: number;
}

/** Toast context value */
export interface ToastContextValue {
  addToast: (toast: ToastData) => string;
  removeToast: (id: string) => void;
}

/** WantedTable props */
export interface WantedTableProps {
  issues?: WantedIssue[];
  pagination?: PaginationMeta;
  onNextPage?: () => void;
  onPrevPage?: () => void;
  onSelectionChange?: (selectedIds: string[]) => void;
}

/** UpcomingTable props */
export interface UpcomingTableProps {
  issues?: UpcomingIssue[];
  isLoading?: boolean;
}

/** IssuesTable props */
export interface IssuesTableProps {
  issues?: Issue[];
  isLoading?: boolean;
}

/** SeriesTable props */
export interface SeriesTableProps {
  series?: Comic[];
  isLoading?: boolean;
}

/** ComicCard props */
export interface ComicCardProps {
  comic: SearchResult;
  onAdd?: (comicId: string) => void;
  isAdding?: boolean;
}

/** FilterBar props */
export interface FilterBarProps {
  onFilterChange?: (filters: FilterState) => void;
}

/** Filter state */
export interface FilterState {
  status?: IssueStatus | "all";
  search?: string;
}

/** BulkActionBar props */
export interface BulkActionBarProps {
  selectedIds: string[];
  onQueue?: () => void;
  onUnqueue?: () => void;
  onClear?: () => void;
  isLoading?: boolean;
}

/** Layout props */
export interface LayoutProps {
  children: ReactNode;
}

/** ProtectedRoute props */
export interface ProtectedRouteProps {
  children: ReactNode;
}

/** ThemeToggle props */
export interface ThemeToggleProps {
  className?: string;
}

/** ErrorBoundary props */
export interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

/** ErrorBoundary state */
export interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}
