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

# Create group — use existing group if GID is already taken
if ! getent group comicarr >/dev/null 2>&1; then
    groupadd -g "${PGID}" comicarr 2>/dev/null || true
fi
# Resolve the actual group name for this GID (may be 'users' on Synology)
GROUPNAME=$(getent group "${PGID}" | cut -d: -f1)
GROUPNAME=${GROUPNAME:-comicarr}

# Create or update user
if ! getent passwd comicarr >/dev/null 2>&1; then
    useradd -u "${PUID}" -g "${GROUPNAME}" -d /opt/comicarr -s /bin/sh comicarr
else
    usermod -u "${PUID}" -g "${GROUPNAME}" comicarr 2>/dev/null || true
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
        if ! gosu comicarr test -w "$dir" 2>/dev/null; then
            echo "WARNING: ${dir} is not writable by comicarr (PUID=${PUID}/PGID=${PGID}). Fix host permissions."
        fi
    fi
done

# Drop privileges and exec the application
exec gosu comicarr python /opt/comicarr/Comicarr.py \
    --nolaunch --quiet --datadir /config/comicarr "$@"
