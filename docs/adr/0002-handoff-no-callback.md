# ADR-0002: No handoff route may require the download client to reach back into Comicarr

**Status:** Accepted  
**Date:** 2026-08-07  
**Issues:** [#552](https://github.com/frankieramirez/comicarr/issues/552), [#556](https://github.com/frankieramirez/comicarr/issues/556), [#564](https://github.com/frankieramirez/comicarr/issues/564)  
**Map:** [Wayfinder: working downloads + a dashboard that tells the truth](https://github.com/frankieramirez/comicarr/issues/550)

## Context

The SABnzbd handoff sent `mode=addurl` with a URL pointing back at Comicarr's
own legacy `api?cmd=downloadNZB` endpoint. SAB was expected to call that URL and
fetch the NZB out of Comicarr.

Three things made this fail invisibly:

1. **The endpoint did not exist.** The FastAPI app has no `downloadNZB`
   handler. The SPA catch-all answered it with **HTTP 200 and `index.html`** —
   so there was not even a status code to detect.
2. **The address was a guess.** Building the callback URL required knowing where
   Comicarr is reachable *from SAB*, so the code carried a socket probe to
   `8.8.8.8` for the local IP, a STUN round-trip (`pystun`) for the external one,
   and a `host_return` config key for when both were wrong. Inside Docker the
   discovered address was the container's ephemeral IP.
3. **Nothing could verify it.** The send returned success as soon as SAB
   accepted the URL. Whether SAB ever retrieved anything was unobservable from
   the response.

The result: Comicarr has **never** completed an NZB handoff. Mylar3 ran in
parallel and carried usenet until it shut down 2026-08-01 (#551).

A route audit (#556) confirmed the defect class was confined to this one route:
NZBGet already uploads content via XML-RPC `append`, and no torrent route hands
out a Comicarr address.

## Decision

> **No handoff route may require the download client to reach back into
> Comicarr.** The handoff delivers the content; it never delivers a pointer to
> Comicarr.

**Corollary — verifiable from the response alone.** A handoff is complete only
if the client's own response to the delivering request proves acceptance. A
route that can only be confirmed by a later inbound request is not a handoff;
it is a hope.

**Accepted exceptions.** `blackhole` and `watchdir` deliver a *file to a
directory* and are exempt from the corollary: there is no response to inspect.
They pay for it — neither is in `_RESTART_SAFE_ROUTES`, so every acceptance
lands in manual review rather than claiming an identity it cannot produce
(`handoff.py`). The exemption is from *verifiability*, never from the rule
itself: they still hand out no Comicarr address.

SAB therefore switches to `mode=addfile`, multipart-POSTing the `.nzb` already
cached at `nzbpath`, making it structurally identical to NZBGet. `nzo_id` stays
the acceptance identity consumed by `_acceptance_identity`.

The callback machinery is **deleted, not repaired** — nothing else consumed it:

- the `comicarr_host` / `LOCAL_IP` / `EXT_IP` / STUN host-discovery block
- the one-shot `DOWNLOAD_APIKEY` (minted per snatch; it never had a consumer,
  and `require_api_key("download")` was never applied to any route)
- the `HOST_RETURN` config key, hard-deleted with a `config.ini` scrub at
  `CONFIG_VERSION` 17
- the `pystun` dependency

## Consequences

- A SAB handoff either completes inside one request or reports a failure. There
  is no in-between state that looks like success.
- Comicarr no longer needs to know its own externally reachable address for
  downloads to work. Container IPs, NAT, and reverse proxies stop mattering to
  the acquisition path.
- Operators with `host_return` in `config.ini` lose the key on first start after
  upgrade, with a log line saying why.
- The NZB is read into memory to be posted. NZBs are small (KBs), and NZBGet's
  sender already base64-encodes the whole file, so this matches existing
  behaviour rather than introducing a new cost.
- **No lint gate.** There is no cheap static signal for "this string is a
  callback URL". The rule is enforced by review, and by the fact that a new
  route must produce an acceptance identity to be restart-safe at all.

## What this does not decide

- **The error shape senders return.** Every SAB failure still collapses to
  `{"status": False}`. That is
  [#554](https://github.com/frankieramirez/comicarr/issues/554)'s clean slate.
- **Whether the SPA catch-all should stop answering `/api/*` with 200 HTML.**
  It masks every dead or mistyped API route, not just this one. With the
  callback deleted, no download route depends on it, so it stands alone as a
  diagnostic concern.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Implement the `downloadNZB` endpoint | Repairs the symptom and keeps the address-discovery problem, the one-shot key, and the unverifiable send. Docker still hands out an ephemeral container IP. |
| Keep `addurl`, point it at the provider's original NZB URL | Re-downloads through the indexer, doubling API hits and leaking the provider API key into SAB's queue. Comicarr already has the file. |
| Blackhole for SAB | Loses `nzo_id`, so the route stops being restart-safe and every snatch lands in manual review. |
