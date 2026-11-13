# Recorded NZBGet responses

Each directory is named for the NZBGet release it was recorded from. Every
file holds one exchange: the XML-RPC `method` and `params` Comicarr's code
sends (the NZB itself replaced by a placeholder), and the `result` NZBGet
returned, or the `fault` or `protocol_error` it raised. The `http_*` files hold
the `/jsonrpc/version` call the connection probe makes, as `status_code` and
`body`. Option values that name hosts, accounts or keys are replaced with
`<scrubbed>`.

| Directory | Image | Recorded |
|---|---|---|
| `26.3/` | `linuxserver/nzbget:v26.3-ls271` | 2026-11-13 |

`history.json` holds one job for each way a job ends that Comicarr reads:
`SUCCESS/HEALTH`, `FAILURE/HEALTH` (missing articles), `FAILURE/UNPACK` (a
broken archive), `FAILURE/PAR` (damage the recovery set cannot repair) and
`FAILURE/SCAN` (a file that is not an NZB, which NZBGet still accepts with a
positive NZBID). `tests/fakes/nzbget.py` builds its answers from these files.

## Refreshing

The recorder needs a disposable NZBGet, because it rewrites that instance's
news server and clears its queue and history. It runs a small NNTP server on
this machine (`tests/fakes/nntp.py`) so every job above finishes without
Usenet, and it needs the `par2` command to build the damaged recovery set.

```bash
docker run -d --name nzbget -p 16789:6789 linuxserver/nzbget:<tag>
python -m tests.fakes.record_nzbget --url http://127.0.0.1:16789 \
  --username nzbget --password tegbzn6789 \
  --nntp-host 172.17.0.1   # the address the container uses to reach this machine
```

The recorder writes `tests/fixtures/nzbget/<version>/`. Point `VERSION` in
`tests/fakes/nzbget.py` at the new directory and run
`pytest tests/unit/test_nzbget_recorded_responses.py tests/integration/test_acquisition_pipeline.py`.
