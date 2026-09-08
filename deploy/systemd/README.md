# Running Comicarr with systemd

This example runs Comicarr in the foreground. `Type=simple` matches the
current CLI and lets systemd supervise the Python process directly.

First install Comicarr and build its frontend following the repository
[installation instructions](../../README.md). The example assumes a checkout
at `/opt/comicarr` with dependencies installed into `.venv` using `uv sync`.
The service account needs read access to that installation and write access to
its data, library, and download directories.

1. Create the service and data user, or choose an existing service account:

       sudo useradd --system --user-group --home-dir /opt/comicarr --shell /usr/sbin/nologin comicarr
       sudo install -d -o comicarr -g comicarr /var/lib/comicarr

2. Copy `comicarr.service` to `/etc/systemd/system/comicarr.service` and edit
   `User`, `Group`, `WorkingDirectory`, and `ExecStart` for the installation.
   The command uses the current `Comicarr.py` options. Add `--log-level info`
   or `--log-level debug` to `ExecStart` when more output is needed.

3. Reload systemd, enable the service, and start it:

       sudo systemctl daemon-reload
       sudo systemctl enable --now comicarr

4. Check startup and runtime logs with:

       sudo systemctl status comicarr
       sudo journalctl -u comicarr -f
