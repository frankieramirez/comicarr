# Public-repository audit, 2026-09-05

This review covered the README, onboarding instructions, community documents,
and repository artwork. It did not audit application security or change runtime
behavior.

## Corrected in this refresh

- Put Docker Compose and first-run setup ahead of detailed operator instructions.
  The README's Compose configuration matches `docker-compose.yml` after YAML parsing.
- Explain persistent data and shared download folders. Clarify ComicVine's role
  in comic imports and MyAnimeList's client-ID requirement.
- Preserve release review, pack handling, content kind, and logging guidance in
  [the operator guide](../operator-guide.md).
- Remove the Discussions link because the repository has Discussions disabled.
- Update contributor instructions for Base UI, a built frontend, and the Node 24
  requirement for the default portless development command. Raw Vite and builds
  retain the Node 22 path.
- Replace hostile issue-template wording and outdated environment examples.
  Narrow security-practice claims to behavior supported by the code.
- The maintainer enabled GitHub private vulnerability reporting after the audit.
  Verified through GitHub's API; the security policy's private reporting route
  is now available.
- Add a self-contained SVG with an original comic emblem and orange pixel lettering.
  Markdown image syntax lets the Docker Hub sync action rewrite its relative URL.

## Follow-ups outside this checkout

- The [website homepage](https://comicarr.com) labels Comicarr as MIT in several
  places, while this repository's [LICENSE](../../LICENSE) contains GPL v3.
  Correct the website's license labels in its source repository. It also links
  to the disabled Discussions destination.
- The website's [manual-installation](https://comicarr.com/docs/deployment/manual)
  and [updating](https://comicarr.com/docs/deployment/updating) pages still show
  `pip install -r requirements.txt`. The current pip command is `pip install .`;
  `uv sync` uses the committed lock. The README supplies the current commands.
- `npm audit` reports two high-severity transitive dependency findings in the
  existing frontend lockfile: `brace-expansion` and `nanoid`. Dependency updates
  need a separate change and validation. The report does not establish an
  exploitable path in Comicarr. See the
  [brace-expansion advisory](https://github.com/advisories/GHSA-rgw5-rvv9-x895)
  and [nanoid advisory](https://github.com/advisories/GHSA-2v37-7h3g-55p8).

## Validation

- `npm run lint` passed, with 21 existing React Fast Refresh warnings and no errors.
- README local paths and anchors resolve; the SVG parses as XML and contains no
  external resources, fonts, or scripts.
- Previewed GitHub-rendered Markdown in a local GitHub-style layout at 1024px and
  390px, on light and dark backgrounds. The banner loads and the page fits both
  viewport widths.
- Verified the pinned Docker Hub sync action's URL-completion rules support
  Markdown SVG images and relative documentation links. The README is below its
  25,000-byte limit. No registry publication was performed.
- GitHub links resolve; issue forms redirect unauthenticated visitors to login.
  Comicarr documentation destinations were verified through web retrieval.
  Direct scripted requests to Comicarr and ComicVine received HTTP 403; the
  ComicVine account/API destination could not be independently fetched.
