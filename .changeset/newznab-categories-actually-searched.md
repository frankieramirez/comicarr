---
"comicarr": patch
---

The Newznab categories you set are now the categories Comicarr searches. Whatever you typed into **Settings → Search → Categories** was being folded into a legacy field that also carries the indexer's RSS user ID, and the searcher could not tell the two apart — so it fell back to its built-in comics category on every Usenet query, and the Settings page displayed the value you entered as though it were in use. Restricting or widening your categories had no effect, and no error said so.

The RSS user ID now has its own field beside Categories, so each means one thing. Existing indexers are re-read on upgrade: if the box shows fewer categories than you remember typing, that is the part that was actually reaching your indexer, and you can now correct it. Newly added indexers default to `7030` (Books/Comics) instead of `5030`, which is a TV category and was never right for this application.

Two related fixes to how providers are stored. An indexer whose *verify TLS* or *enabled* field was written as `True`/`False` rather than `1`/`0` — the shape produced when a legacy `torznab_*` block is absorbed, and present in some configs inherited from Mylar3 — was reported as enabled on the Acquisition tab while the searcher skipped it entirely, or took the search down with an error when it tried to read the TLS setting. Both fields are now normalised wherever configuration is read or written, so every part of Comicarr agrees on what a provider is set to. And an absorbed `torznab_*` entry now verifies TLS certificates by default rather than silently arriving with verification off.

Finally, the log messages about inert `torznab_*` fields no longer point you at a Settings UI that cannot edit Torznab providers. They now name `extra_torznabs` under `[Torznab]` in `config.ini` and show the entry format.
