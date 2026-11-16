# Vendor dependencies and redistribution evidence

Comicarr ships no vendored third-party code. `comicarr/_vendor/` is gone
([ADR-0007](../adr/0007-zero-legacy.md)), and
`scripts/check_root_modules.py` fails if it comes back. Third-party code
arrives only as a declared dependency in `pyproject.toml` and `uv.lock`.

Comicarr commit `45720b948f8c0cc9153412171dca8891e266f1c8` imported the
inherited Mylar3 snapshot, vendored trees included. Each tree was later
replaced and deleted:

| Former vendor root | Replaced by | Issue |
| --- | --- | --- |
| `utorrent/` | first-party `comicarr/torrent/clients/utorrent_webui.py` | #1229 |
| `mega/` | first-party `comicarr/downloaders/mega_public.py` | #1230 |
| `bencode.py` | first-party `comicarr/app/common/torrent_hash.py` | #1409 |
| `get_image_size.py` | deleted, nothing imported it | #1409 |
| `qbittorrent/` | the maintained `qbittorrent-api` package | #1410 |
| `deluge_client/` | the maintained `deluge-client` package | #1411 |
| `transmissionrpc/` | the maintained `transmission-rpc` package | #1412 |
| `rtorrent/` | first-party `comicarr/app/downloads/rtorrent_rpc.py` | #1413 |
| `comictaggerlib/` | first-party `comicarr/app/metadata/comicinfo.py` | #1414 |

The uTorrent and Mega trees never had redistribution authority Comicarr could
establish; deleting them ended the question rather than answering it. The
first-party replacements were written from protocol documentation and observed
behavior, not copied from the vendored files, and are GPL-3.0 like the rest of
Comicarr.

Tagging no longer runs ComicTagger: Comicarr writes `ComicInfo.xml` and the
ComicBookLover zip comment itself, from its own ComicVine data. Old
`[Metatagging]` settings that only ComicTagger read (`cmtagger_path`,
`ct_settingspath`) are still accepted in `config.ini` and ignored.

## Selected direction

Decided on the [Foundations map](https://github.com/frankieramirez/comicarr/issues/1197),
using the project-owner route described above. It is a behavior and
compatibility plan. It does not change the redistribution status of either
historical snapshot, which stays `unresolved` until the directory is deleted.

Both integrations stay, and both vendored trees are replaced by first-party
code under Comicarr's own GPL-3.0 license:

- **uTorrent, first.** A WebUI client in `comicarr/torrent/clients/`, written
  from the public WebUI API description (token fetch, `list`, and the
  `action=` calls the adapter uses). The adapter fixtures required by the
  contract above are captured from the current client before the swap and must
  pass unchanged after it. Then `comicarr/_vendor/utorrent/` and its provenance
  entry are deleted. **Done in #1229.**
- **Mega, second.** A public-link downloader in `comicarr/downloaders/`: read
  the file key from the link, ask Mega's API for the download URL, decrypt the
  stream with AES-CTR using a crypto library Comicarr already depends on, and
  verify the result. Accounts, uploads and folders are out of scope because
  Comicarr never used them. Then `comicarr/_vendor/mega/` and its provenance
  entry are deleted. **Done in #1230.**

Rules for both rewrites:

- The new code is written from protocol documentation and observed client
  behavior. Nothing is copied or adapted from the vendored files, and the pull
  request says so.
- Each lands with recorded-response tests. A live check against the real
  service is run once by hand and noted in the pull request.
- If a rewrite turns out not to be practical, and the code cannot legally ship,
  that integration is removed under the legal exception in
  [ADR-0006](../adr/0006-deprecation-policy.md), after a notice in at least one
  prior release. The `unresolved` status alone does not establish that the
  code cannot legally ship; that is a project-owner call. No other fallback is
  approved.

async-mega.py (Apache-2.0) was considered for Mega and not chosen: its
relationship to the odwyersoftware code could not be confirmed, and the feature
is small enough to own. See the
[research note](../research/2026-11-13-mega-utorrent-replacements.md).

This is an engineering decision, not legal advice.

