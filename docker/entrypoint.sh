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

# Create group — use existing group if GID is already taken (e.g. Alpine's 'users' is GID 100)
if ! getent group comicarr >/dev/null 2>&1; then
    addgroup -g "${PGID}" comicarr 2>/dev/null || true
fi
# Resolve the actual group name for this GID (may be 'users' on Synology)
GROUPNAME=$(getent group "${PGID}" | cut -d: -f1)
GROUPNAME=${GROUPNAME:-comicarr}

# Create user if it doesn't exist
if ! getent passwd comicarr >/dev/null 2>&1; then
    adduser -D -u "${PUID}" -G "${GROUPNAME}" -h /app/comicarr -s /bin/sh comicarr
fi

# Handle timezone
if [ -n "${TZ}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    ln -sf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
fi

# Ensure config directory structure exists
mkdir -p /config/comicarr

# Set ownership on /config top-level (non-recursive)
chown comicarr:"${GROUPNAME}" /config
chown comicarr:"${GROUPNAME}" /config/comicarr

# Recursive ownership only on subdirs that need it (e.g. logs)
if [ -d /config/comicarr/logs ]; then
    chown -R comicarr:"${GROUPNAME}" /config/comicarr/logs
fi

# Verify write access to media volumes (warn only, do NOT chown)
for dir in /comics /downloads /manga; do
    if [ -d "$dir" ]; then
        if ! su-exec comicarr:"${GROUPNAME}" test -w "$dir"; then
            echo "WARNING: ${dir} is not writable by comicarr (PUID=${PUID}/PGID=${PGID}). Fix host permissions."
        fi
    fi
done

# Drop privileges and exec the application
exec su-exec comicarr:"${GROUPNAME}" python3 /app/comicarr/Comicarr.py \
    --nolaunch --quiet --datadir /config/comicarr "$@"
