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
  | "Snatched"
  | "Archived"
  | "Failed";

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
  DateAdded?: string | null;
  Description?: string | null;
  DetailURL?: string | null;
  ComicLocation?: string | null;
  Corrected_SeriesYear?: string | null;
  ForceContinuing?: boolean;
  AlternateSearch?: string | null;
  ComicVersion?: string | null;
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
  // Alternative property names used in some API responses
  id?: string;
  number?: string;
  name?: string;
  releaseDate?: string;
  status?: string;
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
  deck?: string | null;
}

/** Wanted issue (issue with extra fields from wanted queue) */
export interface WantedIssue extends Issue {
  QueueType?: string;
  Provider?: string;
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
}

/** Series detail response (includes issues) */
export interface SeriesDetail {
  comic: Comic[] | Comic;
  issues: Issue[];
  annuals?: Issue[];
}

/** Content type for comic/manga distinction */
export type ContentType = "comic" | "manga";

/** Reading direction for manga */
export type ReadingDirection = "ltr" | "rtl";

/** Manga search result with manga-specific fields */
export interface MangaSearchResult extends SearchResult {
  content_type: "manga";
  reading_direction: ReadingDirection;
  metadata_source: "mangadex";
  external_id?: string;
  status?: "ongoing" | "completed" | "hiatus" | "cancelled" | "unknown";
  content_rating?: "safe" | "suggestive" | "erotica" | "pornographic";
}

/** Manga chapter (equivalent to Issue for manga) */
export interface MangaChapter {
  id: string;
  chapter: string | null;
  volume: string | null;
  title: string | null;
  language: string;
  pages: number;
  publish_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  scanlation_group: string | null;
  external_url: string | null;
  // Mapped to Mylar issue structure
  issue_number: string | null;
  issue_name: string | null;
  release_date: string | null;
}

/** Extended Comic interface with manga support */
export interface ComicOrManga extends Comic {
  ContentType?: ContentType;
  ReadingDirection?: ReadingDirection;
  MetadataSource?: string | null;
  ExternalID?: string | null;
}

/** Extended Issue interface with manga chapter support */
export interface IssueOrChapter extends Issue {
  ChapterNumber?: string | null;
  VolumeNumber?: string | null;
}
