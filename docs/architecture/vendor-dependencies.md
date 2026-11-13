# Vendor dependencies and redistribution evidence

This document describes code shipped inside `comicarr._vendor`. The
machine-readable manifest is `comicarr/_vendor/provenance.py`; contract tests
compare it with both the source tree and a built wheel.

Inventory and evidence review date: 2026-07-12. Comicarr commit
`45720b948f8c0cc9153412171dca8891e266f1c8` imported the inherited Mylar3
snapshot. That commit proves chain of custody, not the original copyright or
license authority of every copied component.

## Status vocabulary

- `evidence-recorded` means identifiable license evidence exists as a
  declaration, header, source notice, or bundled license text. It records
  engineering evidence; it does not establish completeness or legal clearance.
- `unresolved` means Comicarr cannot establish redistribution authority for the
  exact bundled snapshot. No contributor may describe it as cleared without
  authoritative rights-holder evidence. A Comicarr project owner may separately
  approve a compatibility-safe replacement or removal without making a
  redistribution-clearance claim.
- `integration_owner = Comicarr` identifies the team responsible for the
  adapter boundary. It does not claim copyright ownership of vendor code.

The root Comicarr GPL license and the historical Mylar3 distribution do not
fill missing third-party notice or source-revision evidence.

## Packaged inventory

| Vendor root | Runtime role | Source/version evidence | License evidence in copied tree | Redistribution status |
| --- | --- | --- | --- | --- |
| `bencode.py` | Torrent bencode/hash support | Mylar3 import; source version marker `20111107` | MIT notice in source | `evidence-recorded` |
| `comictaggerlib/` | ComicTagger metadata/archive behavior | Bundled version `1.3.5` in `ctversion.py` | Apache-2.0 notices in source files | `evidence-recorded` |
| `deluge_client/` | Deluge RPC | Mylar3 import; exact upstream version unidentified | Bundled `LICENSE` (MIT) | `evidence-recorded` |
| `get_image_size.py` | Packaged image-size support; no current first-party import | Mylar3 import; version unidentified | MIT notice in source | `evidence-recorded` |
| `mega/` | Mega downloads through `comicarr.downloaders.mega` | odwyersoftware/mega.py `1.0.8` base at a pinned revision, plus a localized Mylar3 patch | Conflicting license declarations at the identified base; engineering `NOTICE` is not a license | `unresolved` |
| `qbittorrent/` | qBittorrent Web API | Mylar3 import; exact upstream revision unidentified | Bundled `LICENSE` (MIT) | `evidence-recorded` |
| `rtorrent/` | rTorrent XML-RPC/SCGI | Version `0.2.9` in source | Mixed: MIT; GPL-2.0-or-later with OpenSSL exception; embedded Secret Labs terms | `evidence-recorded` |
| `transmissionrpc/` | Transmission RPC | Version `0.11` in source | MIT notice in source | `evidence-recorded` |
| `utorrent/` | uTorrent Web API adapter | Mylar3 custody, a probable pinned py-utorrent base, later Comicarr Python 3 port, and a pinned artifact digest | No license in the probable base or copied client; engineering `NOTICE` is not a license | `unresolved` |

`bencode.py` and `get_image_size.py` are standalone modules, not
packages. They are intentionally part of the manifest and wheel inventory.
Nested rTorrent helpers belong to the `rtorrent` root.

## Unresolved evidence packets

### Mega

Mylar3 commit `9ad1b5d7d1be7c90cd49e6ec4149ade3d05e3292` introduced
`lib/mega`. Its tree is the pre-notice Comicarr vendor tree, and later Mylar3
commits did not change that path. The code base is odwyersoftware/mega.py
version `1.0.8` at commit `34f3e7335992589eed8f08e675c5fb3038139355`:
three source files match byte-for-byte, while `mega.py` has a localized 34-line
Mylar3 delta for redirects and progress hooks.

Source lineage does not resolve redistribution authority. At that pinned
upstream revision, `LICENSE` declares Apache-2.0 while `setup.py` declares a
Creative Commons Attribution-Noncommercial-Share Alike license. The copied
files do not settle the conflict, so the machine record remains `NOASSERTION`
and `unresolved`.

### uTorrent

The bundled client has no author, library version, source repository, or
license metadata. ftao/py-utorrent commit
`35c4298463247165012ef8f8b4647f10a2fd5bd4` is recorded as a probable direct
base: `upload.py` is byte-identical at Comicarr's import revision and
`client.py` has the same API skeleton with a localized Mylar3 patchset. The
candidate repository has no license file or package license metadata, so it
cannot establish redistribution authority.

Separately, `upload.py` attributes only its multipart helper to a historical
PyMOTW URL. The adapter's uTorrent 3.0+ target is daemon compatibility, not a
client-library version. Comicarr's Python 3 port is a local modification, not
an upstream version.

Both unresolved directories include an engineering `NOTICE` in the wheel. The
notice preserves known custody and stop conditions; it grants no rights.

## Import and artifact contract

- Torrent and downloader integrations import through Comicarr-owned adapters
  and namespaced `comicarr._vendor` modules.
- No first-party module imports a vendor package by a top-level name;
  `tests/unit/test_vendor_contracts.py` enforces it.
- Every top-level directory or standalone Python module shipped below
  `comicarr/_vendor` must have exactly one provenance entry.
- Every declared evidence and notice path must exist. Every actual
  `LICENSE`, `COPYING`, or `NOTICE` file must be claimed exactly once.
- Custody sources, identified upstreams, probable origin candidates,
  replacement candidates, and component-only attributions are separate
  machine fields; none may be substituted for another.
- A wheel smoke build must contain the same vendor roots and every declared
  notice. Comicarr's dist-info GPL license does not satisfy a vendor notice.
- Snapshot digests identify the exact packaged bytes and must change whenever
  vendor contents or bundled notices change. They are not upstream revisions.

## Adapter contract and future decisions

`comicarr.torrent.contracts` owns the stable result shapes used by search, RSS,
and recovery. A replacement must preserve connection failures, identifiers,
category/save-path behavior, start/pause/delete semantics, and monitor errors
through adapter fixtures before any dependency swap.

Potential maintained alternatives may be evaluated separately, but this unit
does not select one. Mega and uTorrent remain active compatibility commitments.
Changing either provenance status requires all of the following:

1. an authoritative source repository plus exact version/revision match for
   the bundled snapshot;
2. copyright and license evidence applicable to that snapshot, including any
   required notices;
3. an accountable rights-holder decision that applies to the bundled snapshot.

A Comicarr project owner may instead approve a separate behavior/compatibility
plan for replacement or removal. That governance decision does not upgrade the
historical snapshot's redistribution status.

Until then, `unresolved` is the only honest machine and documentation state.

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
  entry are deleted.
- **Mega, second.** A public-link downloader in `comicarr/downloaders/`: read
  the file key from the link, ask Mega's API for the download URL, decrypt the
  stream with AES-CTR using a crypto library Comicarr already depends on, and
  verify the result. Accounts, uploads and folders are out of scope because
  Comicarr never used them. Then `comicarr/_vendor/mega/` and its provenance
  entry are deleted.

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

