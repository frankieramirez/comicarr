---
"comicarr": patch
---

Fixed usenet downloads never reaching SABnzbd. Instead of sending the NZB, Comicarr sent SAB a link pointing back at itself and expected SAB to come and fetch the file — from an address Comicarr had to guess (a network probe, a STUN lookup, or the `host_return` setting when both guessed wrong), at an endpoint that did not exist. Inside Docker the guessed address was the container's own short-lived IP, and the missing endpoint answered with a web page rather than an error, so nothing anywhere reported a problem: the snatch looked successful and the download simply never happened. Comicarr now uploads the .nzb to SABnzbd directly, the same way it already does for NZBGet, so the handoff finishes in one step and SAB's own reply confirms it. Your SAB category, priority, and certificate-verification settings are unchanged.

Because no download client is ever handed a Comicarr address any more, the `host_return` setting has no purpose and is removed from `config.ini` automatically on first start after upgrading. Comicarr also no longer probes the network at startup to work out its own address.
