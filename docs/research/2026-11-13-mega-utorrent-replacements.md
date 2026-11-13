# Can the vendored Mega and uTorrent code be replaced with clearly licensed code?

## Findings

**Mega.** Comicarr uses very little of the vendored library. `comicarr/downloaders/mega.py` logs in anonymously, calls `get_public_url_info(link)`, and calls `download_url(link, ...)` with a progress hook. That is a public-link download only: no account, upload or folder features.

- The original license cannot be settled from the source. odwyersoftware/mega.py at the pinned base still ships an Apache-2.0 `LICENSE` beside a `setup.py` declaring a Creative Commons non-commercial license, and PyPI's `mega.py` 1.0.8 (2020-06-25, the last release) still reports that Creative Commons license. Nothing new has appeared upstream.
- The best maintained library is **async-mega.py** (NTFSvolume/mega.py, PyPI 3.0.0, Python 3.11+, Apache-2.0 in both `LICENSE` and `pyproject.toml`). Apache-2.0 can be combined into a GPL-3.0 work. It is async, so Comicarr would call it from its existing worker thread. Its repository name and `mega` module name suggest it descends from odwyersoftware/mega.py. If so, it inherits the same license conflict for any original code it kept. This note could not read its fork history (GitHub API access was refused from this session), so lineage must be checked before relying on it.
- **rclone** (MIT) and **megatools** have Mega backends, and Mega's official **SDK** and **MEGAcmd** are BSD-2-Clause. All of them are external binaries or C++ builds, which adds an install dependency for a small feature.
- A clean-room downloader owned by Comicarr is small. A public link carries the file key; the client asks Mega's API for a download URL, then decrypts the stream with AES-CTR. `cryptography` is already a Comicarr dependency. Expect roughly 150 to 250 lines plus fixture tests.

**uTorrent.** Comicarr's adapter uses a thin WebUI client: token fetch, `list`, `start`, `stop`, `pause`, `remove`, `getfiles`, `getprops`, `setprio` and `addfile`.

- The probable base, ftao/py-utorrent, has no license file (both `LICENSE` and `COPYING` return 404), so its license cannot be established.
- Licensed alternatives exist: **micahr/uTorrent.Py** (LGPL-2.1) and **twistedfall/utorrentctl** (LGPL-3.0). Both are compatible with GPL-3.0, but both are old and unmaintained, so adopting one swaps a license problem for a maintenance one.
- The uTorrent WebUI API is a small, publicly documented HTTP interface (`/gui/token.html`, then `?action=...&hash=...`). A clean-room client owned by Comicarr is likely under 150 lines and can reuse the existing adapter fixtures in `comicarr.torrent.contracts`.
- Usage evidence: this note found no primary source on how many people still run uTorrent's WebUI. The roadmap rule says missing reports are not evidence of no users, so it stays a supported client unless the decision ticket rules otherwise.

**Bottom line for the decision ticket.** Neither original license can be established. For both integrations a clean-room rewrite owned by Comicarr is small and removes the question entirely. async-mega.py is a viable shortcut for Mega only if its lineage proves clean. Deprecation is not forced, because a legal path to keep both features exists.

## Sources

- `docs/architecture/vendor-dependencies.md`: unresolved evidence packets for `mega/` and `utorrent/`, and the adapter contract a replacement must preserve.
- `comicarr/downloaders/mega.py` lines 45 to 67: the Mega calls Comicarr makes.
- `comicarr/_vendor/utorrent/client.py` and `comicarr/torrent/clients/utorrent.py`: the uTorrent methods in use.
- https://raw.githubusercontent.com/odwyersoftware/mega.py/34f3e7335992589eed8f08e675c5fb3038139355/LICENSE and `setup.py` at the same revision and at `master`: the Apache-2.0 versus Creative Commons conflict.
- https://pypi.org/pypi/mega.py/json: version 1.0.8, uploaded 2020-06-25, Creative Commons license field.
- https://raw.githubusercontent.com/NTFSvolume/mega.py/master/LICENSE, `pyproject.toml` and `README.md`: Apache-2.0, `async-mega.py` 3.0.0, Python 3.11+, feature list.
- https://pypi.org/pypi/async-mega.py/json: current version 3.0.0.
- https://raw.githubusercontent.com/rclone/rclone/master/COPYING and `docs/content/mega.md`: MIT license and a Mega backend.
- https://raw.githubusercontent.com/meganz/sdk/master/LICENSE and meganz/MEGAcmd `LICENSE`: BSD-2-Clause, Mega Limited.
- https://raw.githubusercontent.com/ftao/py-utorrent/master/LICENSE: 404, no license file.
- https://raw.githubusercontent.com/micahr/uTorrent.Py/master/LICENSE and `setup.py`: LGPL-2.1.
- https://raw.githubusercontent.com/twistedfall/utorrentctl/master/LICENSE: LGPL-3.0.
