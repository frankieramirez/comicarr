# Issue tracker: GitHub

Tracker: github
Project: frankieramirez/comicarr
Adapter flags: --repo frankieramirez/comicarr
Auth: `gh auth login`. A token that can write issues. Nothing in this file.
Keys: `#42`. Issues and pull requests share one number space.
Host: github.com

## Conventions

Every write goes through the adapter script the skills carry (`tickets.sh`): create, wire, next, claim, label, comment, close. Reads may use `gh issue view` and `gh issue list` directly.

## Pull requests as a request surface

No. Set to `yes` when external pull requests should enter triage as requests with attached code. A bare `#42` is then resolved with `gh pr view 42` first and `gh issue view 42` second.

## External authors

Anyone whose `authorAssociation` is `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE`.

## Wayfinding operations

Default. The map is an issue labelled `scry:map`; tickets are its sub-issues, labelled `scry:<type>`, with `Part of #<map>` as the fallback link. Blocking uses GitHub's issue dependencies, with a `Blocked by: #n` line as the fallback. Claim is assignment. Resolve is a comment, a close, and one gist line on the map. The bundled `map.sh` does all of this.
