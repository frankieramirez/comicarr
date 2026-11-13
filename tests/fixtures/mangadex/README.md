# Recorded MangaDex and MyAnimeList responses

These files hold real answers from `api.mangadex.org` and
`api.myanimelist.net/v2`, used by `tests/fakes/manga.py`. Each file is one
exchange (or a list of them): the `request` Comicarr's own client code sent
(method, host, path, query), the `status_code`, and the JSON `body`. Request
headers are never written, so the MAL client ID is not in any fixture.

The series is *Shino-chan wa Jibun no Namae ga Ienai* (Oshimi Shuzo):
MangaDex `be7fd0c5-209a-440c-b20d-8b611be1310c`, MAL `49017`, eleven English
chapters in one volume. It is small enough to keep every chapter.

| Directory | File | What it is |
|---|---|---|
| `mangadex/` | `manga_details.json` | `GET /manga/{id}` with cover, author, artist and tags |
| | `chapters_en.json` | `GET /chapter` for English, first page (all 11 chapters) |
| | `aggregate.json` | `GET /manga/{id}/aggregate`, no language filter |
| | `search_by_title.json` | `GET /manga?title=` for the romaji title |
| | `search_for_mal_add.json` | the title searches a MAL add makes to find the MangaDex series |
| | `manga_not_found.json` | 404 for a well-formed UUID with no series |
| `myanimelist/` | `manga_details.json` | `GET /v2/manga/49017` with the detail fields |
| | `manga_not_found.json` | 404 for an unknown MAL id |
| | `forbidden.json` | 400 for a client ID MAL does not accept |

Recorded 2026-11-13.

## Refreshing

From the repository root, on a machine that can reach both APIs:

```bash
python -m tests.fakes.record_manga --mangadex
MAL_CLIENT_ID=<your client id> python -m tests.fakes.record_manga --mal
```

Then run `pytest tests/unit/test_manga_recorded_responses.py
tests/integration/test_acquisition_pipeline.py -k "manga or mal"`.
