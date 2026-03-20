#!/bin/sh
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}
UMASK=${UMASK:-002}
umask $UMASK

echo "───────────────────────────────────"
echo "  Comicarr Docker Entrypoint"
echo "───────────────────────────────────"
echo "  PUID:  ${PUID}"
echo "  PGID:  ${PGID}"
echo "  UMASK: ${UMASK}"
echo "  TZ:    ${TZ:-not set}"
echo "───────────────────────────────────"

# Create group if it doesn't exist
if ! getent group comicarr >/dev/null 2>&1; then
    addgroup -g "${PGID}" comicarr
fi

# Create user if it doesn't exist
if ! getent passwd comicarr >/dev/null 2>&1; then
    adduser -D -u "${PUID}" -G comicarr -h /app/comicarr -s /bin/sh comicarr
fi

# Handle timezone
if [ -n "${TZ}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    ln -sf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
fi

# Ensure config directory structure exists
mkdir -p /config/comicarr

# Set ownership on /config top-level (non-recursive)
chown comicarr:comicarr /config
chown comicarr:comicarr /config/comicarr

# Recursive ownership only on subdirs that need it (e.g. logs)
if [ -d /config/comicarr/logs ]; then
    chown -R comicarr:comicarr /config/comicarr/logs
fi

# Verify write access to media volumes (warn only, do NOT chown)
for dir in /comics /downloads /manga; do
    if [ -d "$dir" ]; then
        if ! su-exec comicarr:comicarr test -w "$dir"; then
            echo "WARNING: ${dir} is not writable by comicarr (PUID=${PUID}/PGID=${PGID}). Fix host permissions."
        fi
    fi
done

# Drop privileges and exec the application
exec su-exec comicarr:comicarr python3 /app/comicarr/Comicarr.py \
    --nolaunch --quiet --datadir /config/comicarr "$@"
