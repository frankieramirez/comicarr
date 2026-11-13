#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""Generate the benchmark library from a fixed seed.

The library section 7 of ``docs/architecture/foundations-plan.md`` defines:
400 series (350 comic, 50 manga) with a long tail of sizes, 20,000 issues,
15,000 one-byte files, 2,000 wanted issues, 50 story arcs and 5,000 history
rows, in a SQLite database upgraded to the current schema head.

Everything is drawn from one ``random.Random(seed)``, so the same seed gives
the same rows and the same files. The one exception is this week's pull
list: the dashboard and the weekly pull match read the current week, so the
pull rows are stamped with the week the library was generated in.
"""

import configparser
import datetime
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import func, insert, select

ADJECTIVES = (
    "Amber", "Broken", "Crimson", "Distant", "Electric", "Fallen", "Gilded", "Hollow", "Iron", "Jade",
    "Lunar", "Midnight", "Northern", "Obsidian", "Pale", "Quiet", "Rusted", "Silver", "Tidal", "Velvet",
)  # fmt: skip
NOUNS = (
    "Archive", "Beacon", "Circuit", "Dominion", "Ember", "Frontier", "Garden", "Harbor", "Inquest", "Kingdom",
    "Lantern", "Meridian", "Nomad", "Orbit", "Paragon", "Requiem", "Sentinel", "Tempest", "Vanguard", "Wanderer",
)  # fmt: skip
PUBLISHERS = ("Northlight Press", "Harbor Comics", "Ember House", "Meridian Books", "Vanguard Media")
MANGA_PUBLISHERS = ("Kumo Shobo", "Hoshi Press")
PROVIDERS = ("DDL", "experimental", "nzbgeek", "torznab")
HISTORY_STATUSES = ("Snatched", "Post-Processed", "Downloaded", "Failed")


@dataclass(frozen=True)
class Spec:
    """The shape of a generated library; the defaults are the benchmark's."""

    comic_series: int = 350
    manga_series: int = 50
    issues: int = 20_000
    files: int = 15_000
    wanted: int = 2_000
    story_arcs: int = 50
    history: int = 5_000
    largest_series: int = 500
    pull_list: int = 500
    pull_followed: int = 120

    @property
    def series(self):
        return self.comic_series + self.manga_series


BENCHMARK = Spec()
DEFAULT_SEED = 20261113


def series_sizes(rng, spec):
    """Issue counts per series: one ``largest_series``, then a long tail.

    The tail follows a Lomax (shifted Pareto) draw, scaled so the counts sum
    to ``spec.issues`` exactly with every series holding at least one issue:
    most series hold a few dozen issues, a fifth hold five or fewer, and a
    handful run to hundreds.
    """
    rest = spec.issues - spec.largest_series
    others = spec.series - 1
    weights = [rng.paretovariate(1.6) - 1 for _ in range(others)]
    total = sum(weights)
    sizes = [max(1, min(spec.largest_series - 1, int(rest * w / total))) for w in weights]
    # Hand the rounding remainder out one issue at a time, biggest first.
    order = sorted(range(others), key=lambda i: -weights[i])
    i = 0
    while sum(sizes) != rest:
        k = order[i % others]
        step = 1 if sum(sizes) < rest else -1
        if 1 <= sizes[k] + step < spec.largest_series:
            sizes[k] += step
        i += 1
    return [spec.largest_series] + sizes


def _series_rows(rng, spec):
    names = ["%s %s" % (a, n) for a in ADJECTIVES for n in NOUNS]
    rng.shuffle(names)
    sizes = series_sizes(rng, spec)
    rows = []
    for index in range(spec.series):
        manga = index >= spec.comic_series
        year = 1990 + rng.randrange(35)
        rows.append(
            {
                "index": index,
                "ComicID": "md-bench-%04d" % index if manga else str(100000 + index),
                "ComicName": names[index],
                "ComicYear": str(year),
                "ComicPublisher": rng.choice(MANGA_PUBLISHERS if manga else PUBLISHERS),
                "ContentType": "manga" if manga else "comic",
                "size": sizes[index],
            }
        )
    return rows


def _file_name(series, number):
    if series["ContentType"] == "manga":
        return "%s c%03d.cbz" % (series["ComicName"], number)
    return "%s %03d (%s).cbz" % (series["ComicName"], number, series["ComicYear"])


def _folder(root, series):
    kind = "manga" if series["ContentType"] == "manga" else "comics"
    return Path(root) / "library" / kind / ("%s (%s)" % (series["ComicName"], series["ComicYear"]))


def build_rows(spec, seed, root):
    """Return every table's rows and the relative paths of the library files."""
    rng = random.Random(seed)
    series = _series_rows(rng, spec)

    issue_refs = [(s, n) for s in series for n in range(1, s["size"] + 1)]
    order = list(range(len(issue_refs)))
    rng.shuffle(order)
    status_of = {}
    for position, ref_index in enumerate(order):
        if position < spec.files:
            status_of[ref_index] = "Downloaded"
        elif position < spec.files + spec.wanted:
            status_of[ref_index] = "Wanted"
        else:
            status_of[ref_index] = "Skipped"

    base_date = datetime.date(2010, 1, 6)
    comics_rows, issues_rows, files = [], [], []
    have = {s["ComicID"]: 0 for s in series}
    for ref_index, (s, number) in enumerate(issue_refs):
        status = status_of[ref_index]
        issue_id = "%s-%04d" % (s["ComicID"], number)
        date = (base_date + datetime.timedelta(days=7 * (number + s["index"] % 300))).isoformat()
        location = None
        if status == "Downloaded":
            location = _file_name(s, number)
            files.append(str((_folder(root, s) / location).relative_to(root)))
            have[s["ComicID"]] += 1
        manga = s["ContentType"] == "manga"
        issues_rows.append(
            {
                "IssueID": issue_id,
                "ComicID": s["ComicID"],
                "ComicName": s["ComicName"],
                "Issue_Number": str(number),
                "Int_IssueNumber": number * 1000,
                "IssueName": "Chapter %d" % number if manga else None,
                "ChapterNumber": str(number) if manga else None,
                "IssueDate": date,
                "ReleaseDate": date,
                "Status": status,
                "Location": location,
                "DateAdded": "2026-01-01",
            }
        )
    for s in series:
        latest = (base_date + datetime.timedelta(days=7 * (s["size"] + s["index"] % 300))).isoformat()
        comics_rows.append(
            {
                "ComicID": s["ComicID"],
                "ComicName": s["ComicName"],
                "ComicSortName": s["ComicName"],
                "ComicName_Filesafe": s["ComicName"],
                "DynamicComicName": s["ComicName"].lower().replace(" ", ""),
                "ComicYear": s["ComicYear"],
                "ComicPublisher": s["ComicPublisher"],
                "ComicPublished": "%s - Present" % s["ComicYear"],
                "ComicLocation": str(_folder(root, s)),
                "Status": "Active",
                "Type": "Print",
                "ContentType": s["ContentType"],
                "Have": have[s["ComicID"]],
                "Total": s["size"],
                "LatestIssue": str(s["size"]),
                "LatestDate": latest,
                "DateAdded": "2026-01-01",
                "ForceContinuing": 0,
                "BareNumberMode": "chapters" if s["ContentType"] == "manga" else "auto",
            }
        )

    comic_series = [s for s in series if s["ContentType"] == "comic"]
    arcs = []
    for arc in range(spec.story_arcs):
        arc_id = "arc-%03d" % arc
        length = rng.randint(6, 24)
        members = set()
        while len(members) < length:
            s = rng.choice(comic_series)
            number = rng.randint(1, s["size"])
            issue_id = "%s-%04d" % (s["ComicID"], number)
            if issue_id in members:
                continue
            members.add(issue_id)
            order_no = len(members)
            arcs.append(
                {
                    "StoryArcID": arc_id,
                    "StoryArc": "%s %s Saga" % (rng.choice(ADJECTIVES), rng.choice(NOUNS)),
                    "CV_ArcID": str(90000 + arc),
                    "IssueArcID": "%s_%s" % (arc_id, issue_id),
                    "ReadingOrder": order_no,
                    "ComicID": s["ComicID"],
                    "IssueID": issue_id,
                    "ComicName": s["ComicName"],
                    "IssueNumber": str(number),
                    "Int_IssueNumber": number * 1000,
                    "SeriesYear": s["ComicYear"],
                    "TotalIssues": str(length),
                    "Status": rng.choice(("Downloaded", "Wanted", "Skipped")),
                    "Publisher": s["ComicPublisher"],
                }
            )
    # One name per arc, from its first row.
    names = {}
    for row in arcs:
        row["StoryArc"] = names.setdefault(row["StoryArcID"], row["StoryArc"])

    history, events, seen = [], [], set()
    start = datetime.datetime(2024, 11, 1, 12, 0, 0)
    while len(history) < spec.history:
        s, number = issue_refs[rng.randrange(len(issue_refs))]
        status = rng.choice(HISTORY_STATUSES)
        provider = rng.choice(PROVIDERS)
        issue_id = "%s-%04d" % (s["ComicID"], number)
        if (issue_id, status, provider) in seen:
            continue
        seen.add((issue_id, status, provider))
        when = (start + datetime.timedelta(minutes=rng.randrange(60 * 24 * 740))).strftime("%Y-%m-%d %H:%M:%S")
        history.append(
            {
                "IssueID": issue_id,
                "ComicID": s["ComicID"],
                "ComicName": s["ComicName"],
                "Issue_Number": str(number),
                "Size": rng.randrange(20, 90) * 1024 * 1024,
                "DateAdded": when,
                "Status": status,
                "Provider": provider,
            }
        )
        events.append(
            {
                "created_at": when,
                "activity": "download" if status != "Snatched" else "grab",
                "status": "failed" if status == "Failed" else "succeeded",
                "subject_type": "issue",
                "subject_id": issue_id,
                "subject_label": "%s #%d" % (s["ComicName"], number),
                "provider": provider,
                "parent_series_id": s["ComicID"],
            }
        )

    return {
        "series": series,
        "comics": comics_rows,
        "issues": issues_rows,
        "storyarcs": arcs,
        "snatched": history,
        "activity_events": events,
        "files": sorted(files),
        "rng": rng,
    }


def pull_rows(spec, rows, rng, today=None):
    """This week's pull list: some followed series' next issues, the rest unfollowed.

    Rows carry a ComicID, as the pull sources supply one; the weekly match
    pairs rows with followed series by it.
    """
    from comicarr.app.storyarcs.service import get_current_week

    today = today or datetime.date.today()
    week, year = get_current_week(today)
    comic_series = [s for s in rows["series"] if s["ContentType"] == "comic"]
    followed = rng.sample(comic_series, spec.pull_followed)
    pull = []
    for s in followed:
        pull.append(
            {
                "SHIPDATE": today.isoformat(),
                "PUBLISHER": s["ComicPublisher"],
                "ISSUE": str(s["size"] + 1),
                "COMIC": s["ComicName"],
                "STATUS": None,
                "ComicID": s["ComicID"],
                "IssueID": None,
                "DynamicName": s["ComicName"].lower().replace(" ", ""),
                "weeknumber": week,
                "year": year,
            }
        )
    for i in range(spec.pull_list - spec.pull_followed):
        name = "%s %s %s" % (rng.choice(ADJECTIVES), rng.choice(NOUNS), "Unlimited" if i % 2 else "Tales")
        pull.append(
            {
                "SHIPDATE": today.isoformat(),
                "PUBLISHER": rng.choice(PUBLISHERS),
                "ISSUE": str(rng.randint(1, 80)),
                "COMIC": "%s %d" % (name, i),
                "STATUS": None,
                "ComicID": str(200000 + i),
                "IssueID": None,
                "DynamicName": ("%s%d" % (name, i)).lower().replace(" ", ""),
                "weeknumber": week,
                "year": year,
            }
        )
    return pull


def write_config(root):
    """Write a config.ini that points the library folders at the generated tree."""
    config = configparser.ConfigParser()
    config["General"] = {
        "destination_dir": str(Path(root) / "library" / "comics"),
        "manga_destination_dir": str(Path(root) / "library" / "manga"),
        "launch_browser": "False",
    }
    config["Import"] = {
        "comic_dir": str(Path(root) / "library" / "comics"),
        "manga_dir": str(Path(root) / "library" / "manga"),
    }
    path = Path(root) / "data" / "config.ini"
    with open(path, "w") as handle:
        config.write(handle)
    path.chmod(0o600)
    return path


def generate(root, seed=DEFAULT_SEED, spec=BENCHMARK, today=None):
    """Build the library under ``root`` and return its summary.

    ``root/data`` holds ``comicarr.db`` and ``config.ini``; ``root/library``
    holds the one-byte files. ``root`` must be empty or absent.
    """
    import comicarr
    from comicarr import db
    from comicarr.app.core.schema import upgrade_database
    from comicarr.tables import activity_events, comics, issues, snatched, storyarcs, weekly

    root = Path(root).resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit("%s is not empty; generate into a new folder" % root)
    (root / "data").mkdir(parents=True)

    rows = build_rows(spec, seed, root)
    pull = pull_rows(spec, rows, rows["rng"], today=today)

    for s in rows["series"]:
        _folder(root, s).mkdir(parents=True, exist_ok=True)
    for relative in rows["files"]:
        # One byte, not zero: FileChecker skips empty files, so a rescan of
        # zero-byte files would never parse a name.
        (root / relative).write_bytes(b"\0")

    comicarr.DATA_DIR = str(root / "data")
    db.shutdown_engine()
    engine = db.get_engine()
    upgrade_database(engine)
    with engine.begin() as conn:
        conn.execute(insert(comics), rows["comics"])
        conn.execute(insert(issues), rows["issues"])
        conn.execute(insert(storyarcs), rows["storyarcs"])
        conn.execute(insert(snatched), rows["snatched"])
        conn.execute(insert(activity_events), rows["activity_events"])
        conn.execute(insert(weekly), pull)
    write_config(root)

    counts = {}
    with engine.connect() as conn:
        for table in (comics, issues, storyarcs, snatched, activity_events, weekly):
            counts[table.name] = conn.execute(select(func.count()).select_from(table)).scalar_one()
        counts["wanted"] = conn.execute(
            select(func.count()).select_from(issues).where(issues.c.Status == "Wanted")
        ).scalar_one()
    db.shutdown_engine()
    largest = max(rows["series"], key=lambda s: s["size"])
    summary = {
        "seed": seed,
        "spec": asdict(spec),
        "rows": counts,
        "files": len(rows["files"]),
        "largest_series": largest["ComicID"],
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def library_files(root):
    """Every file under ``root/library``, relative and sorted."""
    root = Path(root)
    return sorted(str(p.relative_to(root)) for p in (root / "library").rglob("*") if p.is_file())
