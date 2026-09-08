# Deployment examples

These files are examples for running Comicarr as a service. They are not
required for source or container installs.

- `systemd/` contains the recommended Linux service definition. It runs
  `Comicarr.py` in the foreground so systemd can supervise it.
- `init.d/` contains legacy Ubuntu SysV init scripts for systems that still
  use `service` and `start-stop-daemon`.
- `centos.init.d` contains the legacy Red Hat and CentOS SysV script.

For a new Linux installation, prefer `systemd/comicarr.service`. The service
uses the current CLI entry point and supports the same `--datadir`, `--config`,
`--port`, and `--log-level` options documented by `python3 Comicarr.py --help`.
