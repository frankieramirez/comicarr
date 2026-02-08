# Stage 1: Build frontend
FROM oven/bun:latest AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/ .
RUN bun run build

# Stage 2: Final image
FROM python:3.11-alpine

# Install system dependencies
RUN apk add --no-cache \
    git \
    unrar \
    su-exec \
    curl \
    tzdata \
    # Build deps for pip packages (removed after install)
    && apk add --no-cache --virtual .build-deps \
    build-base \
    libffi-dev \
    zlib-dev \
    jpeg-dev

# Copy application code
WORKDIR /app/comicarr
COPY . .

# Copy built frontend from stage 1
COPY --from=frontend-build /build/dist /app/comicarr/frontend/dist

# Install Python dependencies and remove build deps
RUN pip3 install --no-cache-dir -r requirements.txt \
    && apk del .build-deps

# Make entrypoint executable
RUN chmod +x /app/comicarr/docker/entrypoint.sh

VOLUME /config /comics /manga /downloads
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -sf http://localhost:8090/auth/check_session || exit 1

ENTRYPOINT ["/app/comicarr/docker/entrypoint.sh"]
