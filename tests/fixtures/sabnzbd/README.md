# Recorded SABnzbd responses

Each directory is named for the SABnzbd release it was recorded from. Every
file holds one exchange: the `request` Comicarr's code sends (API key
removed), the `status_code`, and the `body` SABnzbd returned. Machine details
(keys, hosts, addresses) are replaced with `<scrubbed>` or `192.0.2.1`.

| Directory | Image | Recorded |
|---|---|---|
| `5.1.3/` | `linuxserver/sabnzbd:5.1.3-ls281` | 2026-11-13 |

`tests/fakes/sabnzbd.py` builds its answers from the newest directory.

## Refreshing

The recorder needs a disposable SABnzbd, because it clears that instance's
history. It runs a small NNTP server on this machine (`tests/fakes/nntp.py`)
so one job completes and one fails on missing articles without Usenet.

```bash
docker run -d --name sab -p 18080:8080 -v "$PWD/sab-config:/config" linuxserver/sabnzbd:<tag>
# wait for sab-config/sabnzbd.ini, then
python -m tests.fakes.record_sabnzbd --url http://127.0.0.1:18080 \
  --apikey "$(sed -n 's/^api_key = //p' sab-config/sabnzbd.ini)" \
  --nntp-host 172.17.0.1   # the address the container uses to reach this machine
```

The recorder writes `tests/fixtures/sabnzbd/<version>/`. Point `VERSION` in
`tests/fakes/sabnzbd.py` at the new directory and run
`pytest tests/unit/test_sab_recorded_responses.py tests/integration/test_acquisition_pipeline.py`.
