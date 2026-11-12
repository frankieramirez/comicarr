/**
 * Mock data for Comicarr UI testing.
 *
 * Enable by appending `?mock=1` to any URL (persisted to localStorage), or
 * run `localStorage.setItem('comicarr:mock', '1')` in the console. Disable
 * with `?mock=0` or `localStorage.removeItem('comicarr:mock')`.
 *
 * The goal is purely presentational: give Library, Series Detail, Dashboard,
 * Releases, Wanted, Story arcs, Issue detail and Chat enough content to look realistic while we iterate on
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

/**
 * Twelve hand-written covers are not enough rows to page through, and the
 * paginated views (Library, Search, Activity) are exactly what needs eyeballing
 * when their footers change. Each cover is repeated as numbered volumes with an
 * id of `${coverId}--v${n}`, which `resolveCoverId` maps back so detail pages
 * still resolve.
 */
const VOLUMES_PER_COVER = 8;

const LIBRARY: Comic[] = COVERS.flatMap((c) =>
  Array.from({ length: VOLUMES_PER_COVER }, (_, i) => {
    const base = coverToComic(c);
    if (i === 0) return base;
    return {
      ...base,
      ComicID: `${c.id}--v${i + 1}`,
      ComicName: `${c.title} Vol. ${i + 1}`,
      ComicYear: String(c.year + i),
    };
  }),
).sort((a, b) => a.ComicName.localeCompare(b.ComicName));

/** Strip the synthetic volume suffix so padded rows share a cover's detail. */
function resolveCoverId(id: string): string {
  return id.replace(/--v\d+$/, "");
}

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

/**
 * Issues for a series id, volume rows included. Volume rows (`x--v2`) carry
 * their own ComicID and IssueID so the issue-detail route, which rejects an
 * issue that belongs to another series, resolves for every row.
 */
function issuesFor(id: string): Issue[] {
  const base = ISSUES_BY_COMIC.get(resolveCoverId(id)) || [];
  if (id === resolveCoverId(id)) return base;
  return base.map((issue) => ({
    ...issue,
    ComicID: id,
    IssueID: `${id}-${issue.Int_IssueNumber}`,
  }));
}

/** One issue by id, for `/api/metadata/issue/:id`. */
function issueMetadata(issueId: string) {
  const match = issueId.match(/^(.*)-(\d+)$/);
  if (!match) return null;
  const issue = issuesFor(match[1]).find((row) => row.IssueID === issueId);
  if (!issue) return null;
  return {
    ...issue,
    ComicSize: issue.Location ? "48.2 MB" : null,
    DigitalDate: issue.IssueDate,
    Type: "issue",
  };
}

/** Story arcs threaded through the mock library. */
const STORY_ARCS = [
  {
    id: "arc-absolute-universe",
    name: "Absolute Universe: Year One",
    publisher: "DC Comics",
    span: "2024 - 2025",
    reads: [
      ["absolute-batman", 1],
      ["absolute-flash", 1],
      ["absolute-batman", 2],
      ["absolute-flash", 2],
      ["absolute-batman", 3],
      ["absolute-flash", 3],
      ["absolute-batman", 4],
      ["absolute-flash", 15],
      ["absolute-batman", 12],
      ["absolute-flash", 16],
    ],
    missing: [
      {
        series_name: "Absolute Wonder Woman",
        comic_id: "",
        series_year: "2024",
        publisher: "DC Comics",
        issue_count: 3,
        issue_numbers: ["1", "2", "3"],
      },
      {
        series_name: "Absolute Superman",
        comic_id: "",
        series_year: "2024",
        publisher: "DC Comics",
        issue_count: 2,
        issue_numbers: ["1", "2"],
      },
    ],
  },
  {
    id: "arc-ultimate-invasion",
    name: "Ultimate Invasion",
    publisher: "Marvel Comics",
    span: "2024",
    reads: [
      ["ultimate-wolverine", 1],
      ["ultimate-wolverine", 2],
      ["ultimate-wolverine", 3],
      ["ultimate-wolverine", 4],
      ["ultimate-wolverine", 13],
      ["ultimate-wolverine", 14],
    ],
    missing: [],
  },
  {
    id: "arc-chainsaw-public-safety",
    name: "Public Safety",
    publisher: "Viz Media",
    span: "2019 - 2020",
    reads: [
      ["chainsaw", 1],
      ["chainsaw", 2],
      ["chainsaw", 3],
      ["chainsaw", 4],
    ],
    missing: [],
  },
] as const;

function storyArcIssues(arc: (typeof STORY_ARCS)[number]) {
  return arc.reads.flatMap(([comicId, number], index) => {
    const issue = (ISSUES_BY_COMIC.get(comicId) || []).find(
      (row) => row.Int_IssueNumber === number,
    );
    if (!issue) return [];
    const status = issue.Status === "Downloaded" ? "Downloaded" : "Wanted";
    return [
      {
        IssueArcID: `${arc.id}-${index + 1}`,
        ReadingOrder: index + 1,
        ComicID: issue.ComicID,
        ComicName: issue.ComicName,
        IssueNumber: issue.Issue_Number,
        IssueID: issue.IssueID,
        Status: index < 2 && status === "Downloaded" ? "Read" : status,
        IssueDate: issue.IssueDate,
        IssueName: issue.IssueName,
        IssuePublisher: arc.publisher,
        Location: issue.Location,
      },
    ];
  });
}

function storyArcSummary(arc: (typeof STORY_ARCS)[number]) {
  const issues = storyArcIssues(arc);
  const missingCount = arc.missing.reduce((n, s) => n + s.issue_count, 0);
  const total = issues.length + missingCount;
  const have = issues.filter(
    (issue) => issue.Status === "Downloaded" || issue.Status === "Read",
  ).length;
  return {
    StoryArcID: arc.id,
    StoryArc: arc.name,
    TotalIssues: total,
    Have: have,
    Total: total,
    percent: total ? Math.round((have / total) * 1000) / 10 : 0,
    SpanYears: arc.span,
    CV_ArcID: null,
    Publisher: arc.publisher,
    ArcImage: null,
  };
}

/** Saved chat threads for the mock AI workspace. */
function chatThreads() {
  const now = Date.now();
  const at = (minutesAgo: number) =>
    new Date(now - minutesAgo * 60_000).toISOString();
  return [
    {
      id: "chat-gaps",
      title: "Which series have the most gaps?",
      created_at: at(40),
      updated_at: at(38),
      message_count: 2,
    },
    {
      id: "chat-manga",
      title: "Manga I haven't finished",
      created_at: at(60 * 26),
      updated_at: at(60 * 26),
      message_count: 2,
    },
    {
      id: "chat-this-week",
      title: "What came out this week?",
      created_at: at(60 * 24 * 4),
      updated_at: at(60 * 24 * 4),
      message_count: 2,
    },
  ];
}

function chatThread(id: string) {
  const summary = chatThreads().find((thread) => thread.id === id);
  if (!summary) return null;
  const gaps = COVERS.filter((c) => c.total > c.have)
    .sort((a, b) => b.total - b.have - (a.total - a.have))
    .slice(0, 4);
  const pick =
    id === "chat-manga"
      ? COVERS.filter((c) => c.kind === "manga" && c.total > c.have)
      : id === "chat-this-week"
        ? COVERS.slice(0, 3)
        : gaps;
  const answer =
    id === "chat-manga"
      ? `You have ${pick.length} manga series with chapters still missing. Monster is closest to done.`
      : id === "chat-this-week"
        ? "Three series you follow shipped an issue this week."
        : `${gaps[0]?.title ?? "Transformers"} has the most missing issues. Here are the four series with the biggest gaps.`;
  return {
    ...summary,
    messages: [
      {
        id: `${id}-q`,
        thread_id: id,
        role: "user",
        content: summary.title,
        status: "complete",
        attachments: [],
        created_at: summary.created_at,
      },
      {
        id: `${id}-a`,
        thread_id: id,
        role: "assistant",
        content: answer,
        status: "complete",
        attachments: [],
        created_at: summary.updated_at,
        results: pick.map((c) => ({
          ComicID: c.id,
          ComicName: c.title,
          ComicYear: String(c.year),
          ComicPublisher: c.publisher,
          ComicImage: coverSvgDataUri(c),
          Have: c.have,
          Total: c.total,
          Status: c.status,
          gaps: c.total - c.have,
        })),
      },
    ],
  };
}

/** Narrative recent-activity fixture for the dashboard mock (not t_snatched). */
function recentNarrativeEvents() {
  const now = new Date();
  const sample = [COVERS[0], COVERS[1], COVERS[2], COVERS[3], COVERS[6]];
  const cells: Array<{ activity: string; status: string }> = [
    { activity: "download", status: "succeeded" },
    { activity: "grab", status: "failed" },
    { activity: "import", status: "succeeded" },
    { activity: "download", status: "succeeded" },
    { activity: "grab", status: "succeeded" },
    { activity: "import", status: "failed" },
    { activity: "download", status: "succeeded" },
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
  return cells.map((cell, i) => {
    const c = sample[i % sample.length];
    const issueNum = c.have - (i % 3);
    const when = new Date(now.getTime() - i * 9 * 60 * 1000);
    return {
      event_id: i + 1,
      created_at: when.toISOString(),
      activity: cell.activity,
      status: cell.status,
      subject_type: "issue",
      subject_id: `${c.id}-${issueNum}`,
      subject_label: `${c.title} #${issueNum}`,
      provider: providers[i],
      parent_series_id: c.id,
    };
  });
}

/** Two days of timeline events, newest first, for the Activity mock. */
function timelineEvents() {
  const now = Date.now();
  const min = 60 * 1000;
  const hour = 60 * min;
  const rows: Array<
    [
      number,
      string,
      string,
      string,
      string,
      string,
      string | null,
      string | null,
    ]
  > = [
    [
      12 * min,
      "add",
      "succeeded",
      "series",
      COVERS[4].id,
      COVERS[4].title,
      null,
      null,
    ],
    [
      95 * min,
      "search",
      "succeeded",
      "run",
      "run-41",
      "Wanted search",
      null,
      null,
    ],
    [
      3 * hour,
      "grab",
      "succeeded",
      "issue",
      `${COVERS[0].id}-${COVERS[0].have}`,
      `${COVERS[0].title} #${COVERS[0].have}`,
      null,
      null,
    ],
    [
      3 * hour + 4 * min,
      "import",
      "succeeded",
      "issue",
      `${COVERS[0].id}-${COVERS[0].have}`,
      `${COVERS[0].title} #${COVERS[0].have}`,
      null,
      null,
    ],
    [
      5 * hour,
      "refresh",
      "succeeded",
      "series",
      COVERS[2].id,
      COVERS[2].title,
      null,
      null,
    ],
    [
      26 * hour,
      "import",
      "failed",
      "issue",
      `${COVERS[1].id}-${COVERS[1].have + 1}`,
      `${COVERS[1].title} #${COVERS[1].have + 1}`,
      "import_failed",
      "sh: /scripts/comictagger.sh: not found",
    ],
    [
      27 * hour,
      "grab",
      "failed",
      "issue",
      `${COVERS[3].id}-${COVERS[3].have + 1}`,
      `${COVERS[3].title} #${COVERS[3].have + 1}`,
      "provider_error",
      "SABnzbd: duplicate NZB, job skipped",
    ],
    [
      30 * hour,
      "download",
      "succeeded",
      "issue",
      `${COVERS[6].id}-${COVERS[6].have}`,
      `${COVERS[6].title} #${COVERS[6].have}`,
      null,
      null,
    ],
  ];
  return rows.map(
    (
      [
        ago,
        activity,
        status,
        subject_type,
        subject_id,
        subject_label,
        reason_code,
        reason_detail,
      ],
      i,
    ) => ({
      event_id: 100 + i,
      created_at: new Date(now - ago).toISOString(),
      activity,
      status,
      subject_type,
      subject_id,
      subject_label,
      reason_code,
      reason_detail,
      run_id: subject_type === "run" ? subject_id : null,
      parent_series_id:
        subject_type === "issue" ? subject_id.replace(/-\d+$/, "") : null,
    }),
  );
}

/** Pending import groups: a spread of confident, shaky and unmatched guesses. */
function importGroups() {
  const rows: Array<
    [string, string | null, number, string, string | null, number | null]
  > = [
    [
      "BLAME! Master Edition",
      null,
      6,
      "inbox/BLAME! Master Edition",
      "BLAME! (2016)",
      72,
    ],
    ["superman_ann_2025", "2025", 1, "inbox", "Superman Annual (2025)", 41],
    [
      "Ashita no Joe",
      "1968",
      20,
      "library/manga/Ashita no Joe",
      "Ashita no Joe (1968)",
      64,
    ],
    ["Magi", "2018", 1, "inbox", "Magi (2009)", 58],
    ["Scan_0042", null, 1, "inbox", null, null],
  ];
  return rows.map(([name, year, count, folder, suggested, confidence], i) => ({
    DynamicName: `folder:${folder}`,
    ComicName: name,
    Volume: null,
    ComicYear: year,
    FileCount: count,
    Status: suggested ? "Suggested" : "Unmatched",
    SRID: null,
    ComicID: null,
    MatchConfidence: confidence,
    SuggestedComicID: suggested ? `mock-${i}` : null,
    SuggestedComicName: suggested,
    files: Array.from({ length: count }, (_, f) => ({
      impID: `imp-${i}-${f}`,
      ComicFilename: `${name} ${String(f + 1).padStart(2, "0")}.cbz`,
      ComicLocation: `/data/${folder}/${name} ${String(f + 1).padStart(2, "0")}.cbz`,
      IssueNumber: count > 1 ? String(f + 1) : null,
      ComicYear: year,
      Status: "Unmatched",
      IgnoreFile: 0,
      MatchConfidence: confidence,
      SuggestedComicID: suggested ? `mock-${i}` : null,
      SuggestedComicName: suggested,
      SuggestedIssueID: null,
      MatchSource: suggested ? "comicvine" : null,
    })),
  }));
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

function dashboardLibraryPayload() {
  const totalSeries = LIBRARY.length;
  const totalIssues = LIBRARY.reduce((sum, s) => sum + (s.Have || 0), 0);
  const totalExpected = LIBRARY.reduce((sum, s) => sum + (s.Total || 0), 0);
  return {
    stats: {
      total_series: totalSeries,
      total_issues: totalIssues,
      total_expected: totalExpected,
      completion_pct: totalExpected
        ? Math.round((totalIssues / totalExpected) * 1000) / 10
        : 0,
    },
  };
}

function seriesDetail(id: string) {
  const coverId = resolveCoverId(id);
  const cover = COVERS.find((c) => c.id === coverId);
  if (!cover) return null;
  const issues = issuesFor(id);
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

  let paramMock: "1" | "0" | null = null;
  try {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get("mock");
    if (raw === "1") paramMock = "1";
    else if (raw === "0") paramMock = "0";
  } catch (ignored) {
    void ignored;
  }

  try {
    if (paramMock === "1") {
      localStorage.setItem("comicarr:mock", "1");
      return true;
    }
    if (paramMock === "0") {
      localStorage.removeItem("comicarr:mock");
      return false;
    }
    return localStorage.getItem("comicarr:mock") === "1";
  } catch {
    return paramMock === "1";
  }
}

let mockAuthenticated = true;

/** Provider search results. Enough of them to page through. */
function searchResults(query: string, kind: "comic" | "manga") {
  const pool = COVERS.filter((c) => c.kind === kind);
  const source = kind === "manga" ? "mangadex" : "comicvine";
  const q = query.trim().toLowerCase();
  const all = Array.from({ length: 143 }, (_, i) => {
    const c = pool[i % pool.length];
    const volume = Math.floor(i / pool.length) + 1;
    return {
      id: `${c.id}-search-${i}`,
      comicid: `${c.id}-search-${i}`,
      name: volume === 1 ? c.title : `${c.title} Vol. ${volume}`,
      publisher: c.publisher,
      start_year: String(c.year + volume - 1),
      comicyear: String(c.year + volume - 1),
      count_of_issues: c.total + volume,
      deck: c.description,
      comicimage: coverSvgDataUri(c, 80, 120),
      metadata_source: source,
      url: `https://example.invalid/${c.id}`,
      in_library: i % 7 === 0,
      // Open goes to the mock library's own series page.
      haveit: i % 7 === 0 ? { comicid: c.id, status: "Active" } : "No",
    };
  }).filter((r) => !q || r.name.toLowerCase().includes(q));
  return all;
}

/** Queue and history rows for Activity, derived from the mock library. */
function queueItems() {
  return COVERS.flatMap((c, index) =>
    Array.from({ length: 4 }, (_, n) => {
      const issue = c.have + n + 1;
      return {
        ID: `${c.id}-q${n}`,
        series: c.title,
        year: String(c.year),
        filename: `${c.title.replace(/\s+/g, ".")}.${String(issue).padStart(3, "0")}.cbz`,
        size: `${28 + ((index * 7 + n * 3) % 40)} MB`,
        issueid: `${c.id}-${issue}`,
        comicid: c.id,
        link: `https://example.invalid/${c.id}/${issue}`,
        status: ["Snatched", "Downloading", "Post-Processing", "Failed"][n],
        remote_filesize: `${28 + ((index * 7 + n * 3) % 40)} MB`,
        updated_date: new Date(2026, 6, 20 - n, 12 - n).toISOString(),
        site: n % 2 === 0 ? "NZBgeek" : "Torznab",
        submit_date: new Date(2026, 6, 20 - n, 10 - n).toISOString(),
      };
    }),
  );
}

function historyItems() {
  return COVERS.flatMap((c, index) =>
    Array.from({ length: 6 }, (_, n) => {
      const issue = Math.max(1, c.have - n);
      return {
        IssueID: `${c.id}-${issue}`,
        ComicName: c.title,
        Issue_Number: String(issue),
        Size: (30 + ((index + n) % 25)) * 1024 * 1024,
        DateAdded: new Date(2026, 6, 28 - n, 9 + (index % 8)).toISOString(),
        Status: n % 5 === 0 ? "Failed" : "Post-Processed",
        FolderName: `/comics/${c.title}`,
        ComicID: c.id,
        Provider: n % 2 === 0 ? "NZBgeek (Prowlarr)" : "Torznab",
      };
    }),
  );
}

/** Slice a mock collection the way the paginated endpoints do. */
function paginate<T>(all: T[], parsed: URL) {
  const limit = Number(parsed.searchParams.get("limit") ?? 50);
  const offset = Number(parsed.searchParams.get("offset") ?? 0);
  const rows = all.slice(offset, offset + limit);
  return {
    rows,
    pagination: {
      total: all.length,
      limit,
      offset,
      returned: rows.length,
      has_more: offset + rows.length < all.length,
    },
  };
}

/**
 * Match an incoming request to a mock payload. Returns `undefined` to signal
 * "no mock for this endpoint — fall through to the real backend".
 *
 * `body` is the request body of a write — the search endpoints take their
 * query and page window there rather than in the URL.
 */
export function mockApiResponse(
  method: string,
  path: string,
  body?: object | null,
): unknown | undefined {
  const parsed = new URL(path, "http://mock.local");
  const url = parsed.pathname;
  const m = method.toUpperCase();

  if (m === "GET" && url === "/api/auth/check-setup") {
    return { needs_setup: false };
  }
  if (m === "GET" && url === "/api/auth/check-session") {
    return mockAuthenticated
      ? { success: true, authenticated: true, username: "mock-admin" }
      : { success: true, authenticated: false };
  }
  if (m === "POST" && url === "/api/auth/login") {
    mockAuthenticated = true;
    return { success: true, username: "mock-admin" };
  }
  if (m === "POST" && url === "/api/auth/logout") {
    mockAuthenticated = false;
    return { success: true };
  }
  if (m === "GET" && url === "/api/migration/check") {
    return { needs_migration: false };
  }
  if (m === "GET" && url === "/api/system/diagnostics") {
    return { db_empty: false, migration_dismissed: true };
  }
  if (m === "GET" && url === "/api/ai/status") {
    return {
      configured: true,
      circuit_state: "closed",
      model: "mock-model",
      library_series: LIBRARY.length,
      today_tokens: 18240,
      today_requests: 12,
      daily_limit: 200000,
      rpm_limit: 20,
    };
  }
  if (m === "GET" && url === "/api/ai/recommendations") {
    return {
      recommendations: [
        {
          comic_name: "Absolute Wonder Woman",
          publisher: "DC Comics",
          reason:
            "You're reading Absolute Batman and Absolute Flash; this is the third pillar of the same line.",
          because_of: "Absolute Batman",
          comicid: "mock-rec-aww",
          comicyear: "2024",
          issues: 12,
          comicimage: null,
        },
        {
          comic_name: "Ultimate Spider-Man",
          publisher: "Marvel Comics",
          reason: "Same Ultimate universe as Ultimate Wolverine.",
          because_of: "Ultimate Wolverine",
          comicid: "mock-rec-usm",
          comicyear: "2024",
          issues: 14,
          comicimage: null,
        },
        {
          comic_name: "Dandadan",
          publisher: "Viz Media",
          reason: "Fast, strange action manga in the vein of Chainsaw Man.",
          because_of: "Chainsaw Man",
          comicid: "mock-rec-ddd",
          comicyear: "2021",
          issues: 16,
          comicimage: null,
        },
      ],
    };
  }
  if (m === "GET" && url === "/api/ai/chat/threads") {
    return { threads: chatThreads(), next_cursor: null };
  }
  const chatThreadMatch = url.match(/^\/api\/ai\/chat\/threads\/([^/]+)$/);
  if (m === "GET" && chatThreadMatch) {
    return chatThread(chatThreadMatch[1]);
  }
  if (m === "GET" && url === "/api/health") {
    return { status: "ok" };
  }
  if (m === "GET" && url === "/api/activity/timeline") {
    const results = timelineEvents();
    return {
      results,
      total: results.length,
      limit: 100,
      offset: 0,
      has_more: false,
    };
  }
  if (m === "GET" && url === "/api/attention") {
    const group = (
      comicid: string,
      series_label: string,
      base_reason: string,
      reason_phrase: string,
      member_count: number,
      available_actions: string[],
    ) => ({
      group_key: `${comicid}|${base_reason}`,
      comicid,
      series_label,
      base_reason,
      reason_phrase,
      member_count,
      newest_updated_at: "2026-11-11 09:00:00",
      oldest_updated_at: "2026-11-10 09:00:00",
      stage: "failed",
      available_actions,
      members: Array.from({ length: member_count }, (_, i) => ({
        release_key: `${comicid}-rk-${i}`,
        issue_label: `${series_label} #${i + 1}`,
        issueid: `${comicid}-iss-${i}`,
        stage: "failed",
        available_actions,
        updated_date: "2026-11-11 09:00:00",
      })),
    });
    const results = [
      group(
        "mock-1",
        "Absolute Wonder Woman",
        "postprocess_error",
        "post-processing failed",
        12,
        ["retry", "stop_wanting"],
      ),
      group(
        "mock-2",
        "Absolute Batman",
        "postprocess_error",
        "post-processing failed",
        11,
        ["retry", "stop_wanting"],
      ),
      group("mock-3", "Absolute Flash", "search_error", "search failed", 1, [
        "retry",
        "stop_wanting",
      ]),
    ];
    return { results, total: 5, member_total: 27, preview_cap: 3 };
  }
  if (m === "GET" && url === "/api/search/health") {
    const now = Math.floor(Date.now() / 1000);
    return {
      viable_route: true,
      routes: {
        nzb: {
          ready: true,
          reason: "ready",
          downstream: "sabnzbd",
          providers: [
            {
              name: "nzbgeek",
              kind: "newznab",
              blocked: false,
              attempted: true,
            },
            {
              name: "drunkenslug",
              kind: "newznab",
              blocked: false,
              attempted: true,
            },
          ],
        },
      },
      workers: { search: { state: "idle", alive: true, healthy: true } },
      maintenance: { blocked: false },
      blocked_producer_count: 0,
      providers: [{ provider: "nzbgeek", lastrun: now - 6 * 3600 }],
    };
  }
  if (m === "GET" && url === "/api/activity/status") {
    return { in_flight: 2, recovery_pending: 1, attention: 5 };
  }
  if (m === "GET" && url === "/api/activity/in-flight") {
    return {
      results: [
        {
          kind: "run",
          item_id: 1,
          run_id: "run-1",
          state: "running",
          label: "Saga #1",
          entity_type: "issue",
          entity_id: "iss-1",
          comicid: "absolute-flash",
          issueid: "iss-1",
          command_kind: "search_issue",
          updated_at: "2026-07-10 10:01:00",
        },
        {
          kind: "journal",
          release_key: "open-pp",
          stage: "post_processing",
          label: "Invincible #12",
          issueid: "iss-10",
          comicid: "invincible",
          provider: "DDL",
          updated_at: "2026-07-10 12:00:00",
        },
      ],
      total: 2,
    };
  }
  if (m === "GET" && url === "/api/dashboard/library") {
    return dashboardLibraryPayload();
  }
  if (m === "GET" && url === "/api/dashboard/activity") {
    return { days: 30, events: recentNarrativeEvents() };
  }
  if (m === "GET" && url === "/api/dashboard/upcoming") {
    return { releases: upcomingReleases() };
  }
  if (m === "GET" && url === "/api/dashboard/scan-targets") {
    return { comic: false, manga: false };
  }
  if (m === "GET" && url === "/api/series") {
    return LIBRARY;
  }
  if (m === "GET" && url === "/api/wanted") {
    const q = (parsed.searchParams.get("q") ?? "").trim().toLowerCase();
    const all = wantedIssues().filter((issue) => {
      if (!q) return true;
      return (
        issue.ComicName?.toLowerCase().includes(q) ||
        issue.Issue_Number?.toLowerCase().includes(q)
      );
    });
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
    return {
      week: "41",
      year: "2026",
      start: "2026-10-11",
      end: "2026-10-17",
      offset: 0,
      prev: { week: "40", year: "2026" },
      next: { week: "42", year: "2026" },
      source: "stored",
      rows: upcomingReleases().map((u, index) => ({
        COMIC: u.ComicName,
        ISSUE: u.IssueNumber,
        PUBLISHER: u.Publisher,
        SHIPDATE: u.IssueDate,
        STATUS: u.Status,
        ComicID: u.ComicID,
        rowid: index + 1,
        in_library: true,
        library_issue_id: null,
        issue_status: u.Status,
        state: u.Status === "Wanted" ? "wanted" : "in_library",
      })),
    };
  }
  if (m === "GET" && url === "/api/upcoming") {
    return upcomingReleases().map((u) => ({
      IssueID: `${u.ComicID}-upcoming-${u.IssueNumber}`,
      ComicID: u.ComicID,
      ComicName: u.ComicName,
      Issue_Number: u.IssueNumber,
      IssueNumber: u.IssueNumber,
      IssueName: null,
      IssueDate: u.IssueDate,
      Status: u.Status,
      ComicImage: null,
    }));
  }
  if (m === "GET" && url === "/api/storyarcs") {
    return STORY_ARCS.map(storyArcSummary);
  }
  const arcMissingMatch = url.match(/^\/api\/storyarcs\/([^/]+)\/missing$/);
  if (m === "GET" && arcMissingMatch) {
    const arc = STORY_ARCS.find((a) => a.id === arcMissingMatch[1]);
    return {
      success: true,
      series: (arc?.missing ?? []).map((series) => ({
        ...series,
        match: {
          comic_id: `mock-${series.series_name.toLowerCase().replace(/\W+/g, "-")}`,
          name: series.series_name,
          year: series.series_year,
          publisher: series.publisher,
          image: null,
        },
      })),
    };
  }
  const arcMatch = url.match(/^\/api\/storyarcs\/([^/]+)$/);
  if (m === "GET" && arcMatch) {
    const arc = STORY_ARCS.find((a) => a.id === arcMatch[1]);
    if (!arc) return null;
    return {
      arc: storyArcSummary(arc),
      issues: storyArcIssues(arc),
      missing: arc.missing,
    };
  }
  const issueMetaMatch = url.match(/^\/api\/metadata\/issue\/([^/]+)$/);
  if (m === "GET" && issueMetaMatch) {
    return issueMetadata(issueMetaMatch[1]);
  }
  if (m === "GET" && url === "/api/downloads/queue") {
    const q = (parsed.searchParams.get("q") ?? "").trim().toLowerCase();
    const all = queueItems().filter(
      (item) => !q || item.series.toLowerCase().includes(q),
    );
    const { rows, pagination } = paginate(all, parsed);
    return { queue: rows, pagination };
  }
  if (m === "GET" && url === "/api/downloads/history") {
    const q = (parsed.searchParams.get("q") ?? "").trim().toLowerCase();
    const all = historyItems().filter(
      (item) => !q || item.ComicName.toLowerCase().includes(q),
    );
    const { rows, pagination } = paginate(all, parsed);
    return { history: rows, pagination };
  }
  if (
    m === "POST" &&
    (url === "/api/search/comics" || url === "/api/search/manga")
  ) {
    const search = (body ?? {}) as {
      name?: string;
      limit?: number;
      offset?: number;
    };
    const all = searchResults(
      search.name ?? "",
      url.endsWith("manga") ? "manga" : "comic",
    );
    const limit = search.limit ?? 20;
    const offset = search.offset ?? 0;
    const results = all.slice(offset, offset + limit);
    return {
      results,
      pagination: {
        total: all.length,
        limit,
        offset,
        returned: results.length,
        has_more: offset + results.length < all.length,
      },
    };
  }
  if (m === "GET" && url === "/api/config") {
    return {
      import_dir: "/data/downloads/comics/inbox",
      comic_dir: "/data/comics",
      manga_dir: "/data/manga",
    };
  }
  if (m === "GET" && url === "/api/import") {
    const imports = importGroups();
    return {
      imports,
      pagination: {
        total: imports.length,
        limit: 50,
        offset: 0,
        has_more: false,
      },
      summary: {
        group_count: imports.length,
        file_count: imports.reduce((n, g) => n + g.FileCount, 0),
      },
    };
  }

  const detailMatch = url.match(/^\/api\/series\/([^/]+)$/);
  if (m === "GET" && detailMatch) {
    const detail = seriesDetail(detailMatch[1]);
    if (detail) return detail;
    return null;
  }

  const issuesMatch = url.match(/^\/api\/series\/([^/]+)\/issues$/);
  if (m === "GET" && issuesMatch) {
    return issuesFor(issuesMatch[1]);
  }

  const artMatch = url.match(/^\/api\/metadata\/art\/([^/]+)$/);
  if (m === "GET" && artMatch) {
    const cover = COVERS.find((c) => c.id === resolveCoverId(artMatch[1]));
    if (cover) return { image: coverSvgDataUri(cover) };
  }

  return undefined;
}
