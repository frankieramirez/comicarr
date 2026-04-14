import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "@/lib/api";

export interface HistoryItem {
  IssueID: string;
  ComicName: string;
  Issue_Number: string;
  Size: number;
  DateAdded: string;
  Status: string;
  FolderName: string;
  ComicID: string;
  Provider: string;
}

interface HistoryResponse {
  history: HistoryItem[];
  pagination: {
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
  };
}

export interface QueueItem {
  ID: string;
  series: string;
  year: string;
  filename: string;
  size: string;
  issueid: string;
  comicid: string;
  link: string;
  status: string;
  remote_filesize: string;
  updated_date: string;
  site: string;
  submit_date: string;
}

export function useDownloadHistory(limit: number, offset: number) {
  return useQuery<HistoryResponse>({
    queryKey: ["downloads", "history", limit, offset],
    queryFn: () =>
      apiRequest<HistoryResponse>(
        "GET",
        `/api/downloads/history?limit=${limit}&offset=${offset}`,
      ),
    staleTime: 30 * 1000, // 30 seconds
  });
}

export function useDownloadQueue() {
  return useQuery<QueueItem[]>({
    queryKey: ["downloads", "queue"],
    queryFn: () => apiRequest<QueueItem[]>("GET", "/api/downloads/queue"),
    staleTime: 10 * 1000, // 10 seconds — queue data is transient
    refetchInterval: 15 * 1000, // Poll every 15 seconds
  });
}
