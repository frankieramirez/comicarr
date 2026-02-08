#!/bin/sh
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "───────────────────────────────────"
echo "  Comicarr Docker Entrypoint"
echo "───────────────────────────────────"
echo "  PUID: ${PUID}"
echo "  PGID: ${PGID}"
echo "  TZ:   ${TZ:-not set}"
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

# Ensure config directory ownership
chown -R comicarr:comicarr /config

# Drop privileges and exec the application
exec su-exec comicarr:comicarr python3 /app/comicarr/Comicarr.py \
    --nolaunch --quiet --datadir /config/comicarr "$@"
