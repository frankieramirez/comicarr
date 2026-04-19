/**
 * Mock data for Comicarr UI testing.
 *
 * Enable by appending `?mock=1` to any URL (persisted to localStorage), or
 * run `localStorage.setItem('comicarr:mock', '1')` in the console. Disable
 * with `?mock=0` or `localStorage.removeItem('comicarr:mock')`.
 *
 * The goal is purely presentational: give Library, Series Detail, Dashboard,
 * Releases, and Wanted enough content to look realistic while we iterate on
 * the redesign. Nothing here hits the real backend.
 */

import type { Comic, Issue, WantedIssue, SeriesStatus } from "@/types";

interface MockCover {
  id: string;
  title: string;
  author: string;
  publisher: string;
  year: number;
  kind: "comic" | "manga";
  bg: [string, string];
  accent: string;
  have: number;
  total: number;
  status: SeriesStatus;
  description: string;
  genres: string[];
}

const COVERS: MockCover[] = [
  {
    id: "absolute-flash",
    title: "Absolute Flash",
    author: "Jeff Lemire",
    publisher: "DC Comics",
    year: 2024,
    kind: "comic",
    bg: ["#c1281e", "#f5a623"],
    accent: "#ffeb3b",
    have: 14,
    total: 18,
    status: "Active",
    description:
      "The Scarlet Speedster reinvented from the ground up — without the Justice League, without S.T.A.R. Labs, without a safety net.",
    genres: ["Superhero", "Ongoing", "DC-Absolute"],
  },
  {
    id: "ultimate-wolverine",
    title: "Ultimate Wolverine",
    author: "Christopher Cantwell",
    publisher: "Marvel Comics",
    year: 2024,
    kind: "comic",
    bg: ["#2a2f3a", "#6d7685"],
    accent: "#f8c13b",
    have: 12,
    total: 22,
    status: "Active",
    description:
      "Logan wakes in a broken Ultimate universe with no memory, no home, and a whole lot of rage.",
    genres: ["Superhero", "Ongoing", "Ultimate"],
  },
  {
    id: "tmnt",
    title: "Teenage Mutant Ninja Turtles",
    author: "Jason Aaron",
    publisher: "IDW",
    year: 2023,
    kind: "comic",
    bg: ["#0e3a1a", "#58a93a"],
    accent: "#ffffff",
    have: 16,
    total: 16,
    status: "Active",
    description:
      "A new era for the turtles, beginning in the aftermath of the Armageddon Game.",
    genres: ["Action", "Ongoing"],
  },
  {
    id: "transformers",
    title: "Transformers",
    author: "Daniel Warren Johnson",
    publisher: "Image Comics",
    year: 2024,
    kind: "comic",
    bg: ["#1a1148", "#4a2dbb"],
    accent: "#ff4081",
    have: 9,
    total: 22,
    status: "Active",
    description:
      "Energon Universe — Optimus Prime crashes into 1980s Earth with the Decepticons already on his tail.",
    genres: ["Sci-Fi", "Action", "Energon Universe"],
  },
  {
    id: "absolute-batman",
    title: "Absolute Batman",
    author: "Scott Snyder",
    publisher: "DC Comics",
    year: 2024,
    kind: "comic",
    bg: ["#0b0b10", "#2a2d3a"],
    accent: "#f5c842",
    have: 18,
    total: 18,
    status: "Active",
    description:
      "Without his parents' money, mansion, or butler — how does Bruce Wayne become the Batman?",
    genres: ["Superhero", "Dark", "DC-Absolute"],
  },
  {
    id: "20cb",
    title: "20th Century Boys",
    author: "Naoki Urasawa",
    publisher: "Viz",
    year: 1999,
    kind: "manga",
    bg: ["#d4a373", "#1d1d1b"],
    accent: "#e63946",
    have: 22,
    total: 24,
    status: "Active",
    description:
      "A childhood prophecy returns to haunt Kenji Endo when the world starts ending on his birthday.",
    genres: ["Thriller", "Mystery"],
  },
  {
    id: "chainsaw",
    title: "Chainsaw Man",
    author: "Tatsuki Fujimoto",
    publisher: "Viz",
    year: 2018,
    kind: "manga",
    bg: ["#f25c54", "#1a1a1a"],
    accent: "#ffd166",
    have: 14,
    total: 22,
    status: "Active",
    description:
      "A young devil hunter with a chainsaw heart fights demons for rent money — and occasionally, love.",
    genres: ["Action", "Horror", "Shonen"],
  },
  {
    id: "fujimoto",
    title: "17-21: Fujimoto Tatsuki Tanpenshuu",
    author: "Tatsuki Fujimoto",
    publisher: "Viz",
    year: 2014,
    kind: "manga",
    bg: ["#2a1a3a", "#d4a3ff"],
    accent: "#ffd166",
    have: 0,
    total: 1,
    status: "Active",
    description: "Short works by Fujimoto, collected.",
    genres: ["Anthology"],
  },
  {
    id: "monster",
    title: "Monster",
    author: "Naoki Urasawa",
    publisher: "Viz",
    year: 1994,
    kind: "manga",
    bg: ["#3a2a1a", "#d4c4a3"],
    accent: "#8a5a3a",
    have: 9,
    total: 18,
    status: "Active",
    description:
      "Dr. Tenma saves a boy's life — and spends the next decade learning why he shouldn't have.",
    genres: ["Thriller", "Psychological"],
  },
  {
    id: "ark-m",
    title: "Absolute Batman: Ark-M",
    author: "Dan Watters",
    publisher: "DC Comics",
    year: 2026,
    kind: "comic",
    bg: ["#1a1a24", "#5c3a8a"],
    accent: "#58a93a",
    have: 1,
    total: 1,
    status: "Active",
    description:
      "A one-shot tie-in to Absolute Batman exploring the Ark-M facility.",
    genres: ["Superhero", "One-Shot"],
  },
  {
    id: "annual-25",
    title: "Absolute Batman 2025 Annual",
    author: "Various",
    publisher: "DC Comics",
    year: 2025,
    kind: "comic",
    bg: ["#2a1414", "#c1281e"],
    accent: "#f5c842",
    have: 1,
    total: 1,
    status: "Active",
    description: "Absolute Batman annual — multiple stories, one volume.",
    genres: ["Superhero", "Anthology"],
  },
  {
    id: "21cb",
    title: "21st Century Boys",
    author: "Naoki Urasawa",
    publisher: "Viz",
    year: 2006,
    kind: "manga",
    bg: ["#1a3a5c", "#d4a373"],
    accent: "#e63946",
    have: 0,
    total: 2,
    status: "Active",
    description: "The two-volume sequel wrapping up 20th Century Boys.",
    genres: ["Thriller", "Sequel"],
  },
];

function coverSvgDataUri(c: MockCover, w = 200, h = 300): string {
  const [c1, c2] = c.bg;
  const words = c.title.split(" ").slice(0, 3);
  const titleLines = words
    .map(
      (word, i) =>
        `<text x="${w * 0.08}" y="${h * 0.72 + i * h * 0.08}" fill="${c.accent}" font-family="Inter Tight, sans-serif" font-weight="800" font-size="${Math.max(14, w * 0.11)}" letter-spacing="-0.4">${word.toUpperCase()}</text>`,
    )
    .join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
    <defs>
      <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="${c1}"/>
        <stop offset="1" stop-color="${c2}"/>
      </linearGradient>
      <pattern id="p" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="8" height="8" fill="url(#g)"/>
        <line x1="0" y1="0" x2="0" y2="8" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
      </pattern>
    </defs>
    <rect width="${w}" height="${h}" fill="url(#p)"/>
    <rect x="0" y="${h * 0.62}" width="${w}" height="${h * 0.38}" fill="rgba(0,0,0,0.45)"/>
    ${titleLines}
    <text x="${w * 0.08}" y="${h * 0.95}" fill="rgba(255,255,255,0.7)" font-family="ui-monospace, Menlo, monospace" font-size="${Math.max(10, w * 0.06)}">#${String(c.have).padStart(2, "0")}</text>
  </svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

function coverToComic(c: MockCover): Comic {
  return {
    ComicID: c.id,
    ComicName: c.title,
    ComicYear: String(c.year),
    ComicPublisher: c.publisher,
    ComicImage: coverSvgDataUri(c),
    ComicImageURL: coverSvgDataUri(c),
    Status: c.status,
    Total: c.total,
    Have: c.have,
    LatestDate: `${c.year}-10-09`,
    DateAdded: `${c.year}-01-15`,
    Description: c.description,
    DetailURL: null,
    ComicLocation: `/library/${c.kind}s/${c.id}`,
    Corrected_SeriesYear: null,
    ForceContinuing: false,
    AlternateSearch: null,
    ComicVersion: null,
    ContentType: c.kind === "manga" ? "manga" : "comic",
  };
}

const SERIES: Comic[] = COVERS.map(coverToComic);

function buildIssues(c: MockCover): Issue[] {
  const arcs =
    c.id === "absolute-batman"
      ? ["The Zoo", "The Party", "Black Sands"]
      : ["Arc One", "Arc Two", "Arc Three"];
  const titles = [
    "The Zoo",
    "When They Break",
    "A Boy Scout's Life",
    "The Spot",
    "Here Comes the Chase",
    "Feast",
    "Party Tricks",
    "Not Today",
    "Black Out",
    "Ghost of the Sand",
    "Gotham by Gaslight",
    "Last Call",
    "The Getaway",
    "Sleepers",
    "Red Balloons",
    "Mercy",
    "Fallen",
    "Ascendant",
    "After Hours",
    "The Long Drive",
    "Bookends",
    "Final Light",
  ];
  const issues: Issue[] = [];
  const count = c.total;
  for (let i = 1; i <= count; i++) {
    const haveIt = i <= c.have;
    const arc = arcs[Math.floor((i - 1) / Math.ceil(count / arcs.length))];
    const dateYear = c.year;
    const monthIndex = ((i - 1) % 12) + 1;
    issues.push({
      IssueID: `${c.id}-${i}`,
      ComicID: c.id,
      ComicName: c.title,
      ComicYear: String(dateYear),
      Issue_Number: String(i),
      IssueName: titles[(i - 1) % titles.length],
      IssueDate: `${dateYear}-${String(monthIndex).padStart(2, "0")}-09`,
      ReleaseDate: `${dateYear}-${String(monthIndex).padStart(2, "0")}-09`,
      DateAdded: `${dateYear}-${String(monthIndex).padStart(2, "0")}-10`,
      Status: haveIt ? "Downloaded" : i === c.have + 1 ? "Wanted" : "Skipped",
      Location: haveIt
        ? `/comics/${c.title}/${c.title} - ${String(i).padStart(3, "0")} (${dateYear}).cbz`
        : null,
      ImageURL: coverSvgDataUri(c, 80, 120),
      ImageURL_ALT: null,
      Int_IssueNumber: i,
      Arc: arc,
    });
  }
  return issues;
}

const ISSUES_BY_COMIC = new Map<string, Issue[]>(
  COVERS.map((c) => [c.id, buildIssues(c)]),
);

function recentDownloads() {
  const now = new Date();
  const items: Array<{
    ComicName: string;
    Issue_Number: string;
    DateAdded: string;
    Status: string;
    Provider: string;
    ComicID: string;
    IssueID: string;
    ComicImage: string | null;
  }> = [];
  const sample = [COVERS[0], COVERS[1], COVERS[2], COVERS[3], COVERS[6]];
  const actions = [
    "Downloaded",
    "Downloaded",
    "Post-Processed",
    "Post-Processed",
    "Snatched",
    "Downloaded",
    "Post-Processed",
  ];
  const providers = [
    "NZBgeek (Prowlarr)",
    "NZBgeek (Prowlarr)",
    "Local",
    "NZBgeek",
    "Torznab",
    "NZBgeek (Prowlarr)",
    "Local",
  ];
  for (let i = 0; i < 7; i++) {
    const c = sample[i % sample.length];
    const when = new Date(now.getTime() - i * 9 * 60 * 1000);
    items.push({
      ComicName: c.title,
      Issue_Number: String(c.have - (i % 3)),
      DateAdded: when.toISOString(),
      Status: actions[i],
      Provider: providers[i],
      ComicID: c.id,
      IssueID: `${c.id}-${c.have - (i % 3)}`,
      ComicImage: coverSvgDataUri(c, 60, 90),
    });
  }
  return items;
}

function upcomingReleases() {
  const base = new Date();
  const addDays = (d: Date, n: number) => {
    const nd = new Date(d);
    nd.setDate(nd.getDate() + n);
    return nd;
  };
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  return [
    {
      ComicName: "Absolute Batman",
      IssueNumber: "19",
      IssueDate: fmt(addDays(base, 3)),
      Publisher: "DC Comics",
      ComicID: "absolute-batman",
      Status: "Wanted",
    },
    {
      ComicName: "Ultimate Wolverine",
      IssueNumber: "16",
      IssueDate: fmt(addDays(base, 5)),
      Publisher: "Marvel Comics",
      ComicID: "ultimate-wolverine",
      Status: "Wanted",
    },
    {
      ComicName: "Transformers",
      IssueNumber: "10",
      IssueDate: fmt(addDays(base, 7)),
      Publisher: "Image Comics",
      ComicID: "transformers",
      Status: "Wanted",
    },
  ];
}

function wantedIssues(): WantedIssue[] {
  const out: WantedIssue[] = [];
  for (const c of COVERS) {
    const issues = ISSUES_BY_COMIC.get(c.id) || [];
    for (const i of issues.filter((x) => x.Status === "Wanted")) {
      out.push({
        ...i,
        ComicName: c.title,
        ComicYear: String(c.year),
        ComicPublisher: c.publisher,
        ComicImage: coverSvgDataUri(c, 80, 120),
      } as WantedIssue);
    }
  }
  return out;
}

function dashboardPayload() {
  const totalSeries = SERIES.length;
  const totalIssues = SERIES.reduce((sum, s) => sum + (s.Have || 0), 0);
  const totalExpected = SERIES.reduce((sum, s) => sum + (s.Total || 0), 0);
  return {
    recently_downloaded: recentDownloads(),
    upcoming_releases: upcomingReleases(),
    stats: {
      total_series: totalSeries,
      total_issues: totalIssues,
      total_expected: totalExpected,
      completion_pct: totalExpected
        ? Math.round((totalIssues / totalExpected) * 1000) / 10
        : 0,
    },
    ai_activity: [],
    ai_configured: false,
  };
}

function seriesDetail(id: string) {
  const cover = COVERS.find((c) => c.id === id);
  if (!cover) return null;
  const issues = ISSUES_BY_COMIC.get(id) || [];
  return {
    comic: coverToComic(cover),
    issues,
  };
}

/**
 * Return true when mock mode is enabled via `?mock=1` URL param (persisted
 * in localStorage) or manual `localStorage.setItem('comicarr:mock','1')`.
 */
export function isMockEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("mock") === "1") {
      localStorage.setItem("comicarr:mock", "1");
      return true;
    }
    if (params.get("mock") === "0") {
      localStorage.removeItem("comicarr:mock");
      return false;
    }
    return localStorage.getItem("comicarr:mock") === "1";
  } catch {
    return false;
  }
}

/**
 * Match an incoming request to a mock payload. Returns `undefined` to signal
 * "no mock for this endpoint — fall through to the real backend".
 */
export function mockApiResponse(
  method: string,
  path: string,
): unknown | undefined {
  const parsed = new URL(path, "http://mock.local");
  const url = parsed.pathname;
  const m = method.toUpperCase();

  if (m === "GET" && url === "/api/auth/check-setup") {
    return { needs_setup: false };
  }
  if (m === "GET" && url === "/api/auth/check-session") {
    return { success: true, authenticated: true, username: "mock-admin" };
  }
  if (m === "POST" && url === "/api/auth/login") {
    return { success: true, username: "mock-admin" };
  }
  if (m === "POST" && url === "/api/auth/logout") {
    return { success: true };
  }
  if (m === "GET" && url === "/api/migration/check") {
    return { needs_migration: false };
  }
  if (m === "GET" && url === "/api/system/diagnostics") {
    return { db_empty: false, migration_dismissed: true };
  }
  if (m === "GET" && url === "/api/ai/status") {
    return { configured: false };
  }
  if (m === "GET" && url === "/api/dashboard") {
    return dashboardPayload();
  }
  if (m === "GET" && url === "/api/series") {
    return SERIES;
  }
  if (m === "GET" && url === "/api/wanted") {
    const all = wantedIssues();
    const limit = Number(parsed.searchParams.get("limit") ?? 50);
    const offset = Number(parsed.searchParams.get("offset") ?? 0);
    const issues = all.slice(offset, offset + limit);
    return {
      issues,
      pagination: {
        total: all.length,
        limit,
        offset,
        has_more: offset + issues.length < all.length,
      },
    };
  }
  if (m === "GET" && url === "/api/weekly") {
    return upcomingReleases().map((u) => ({
      COMIC: u.ComicName,
      ISSUE: u.IssueNumber,
      PUBLISHER: u.Publisher,
      SHIPDATE: u.IssueDate,
      STATUS: u.Status,
      ComicID: u.ComicID,
    }));
  }
  if (m === "GET" && url === "/api/upcoming") {
    return upcomingReleases().map((u) => ({
      IssueID: `${u.ComicID}-upcoming-${u.IssueNumber}`,
      ComicID: u.ComicID,
      ComicName: u.ComicName,
      Issue_Number: u.IssueNumber,
      IssueName: null,
      IssueDate: u.IssueDate,
      Status: u.Status,
      ComicImage: null,
    }));
  }
  if (m === "GET" && url === "/api/storyarcs") {
    return [];
  }
  if (m === "GET" && url === "/api/downloads/queue") {
    return [];
  }
  if (m === "GET" && url === "/api/config") {
    return {};
  }

  const detailMatch = url.match(/^\/api\/series\/([^/]+)$/);
  if (m === "GET" && detailMatch) {
    const detail = seriesDetail(detailMatch[1]);
    if (detail) return detail;
    return null;
  }

  const issuesMatch = url.match(/^\/api\/series\/([^/]+)\/issues$/);
  if (m === "GET" && issuesMatch) {
    return ISSUES_BY_COMIC.get(issuesMatch[1]) || [];
  }

  // Cover art — return a tiny transparent gif; frontend already falls back
  // gracefully, and the list views synthesize their own SVG covers.
  const artMatch = url.match(/^\/api\/metadata\/art\/([^/]+)$/);
  if (m === "GET" && artMatch) {
    const cover = COVERS.find((c) => c.id === artMatch[1]);
    if (cover) return { image: coverSvgDataUri(cover) };
  }

  return undefined;
}
