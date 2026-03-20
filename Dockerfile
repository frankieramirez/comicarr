# Stage 1: Build frontend
FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

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

# Install Python dependencies first for layer caching
WORKDIR /app/comicarr
COPY requirements.txt pyproject.toml ./
RUN pip3 install --no-cache-dir -r requirements.txt \
    && apk del .build-deps

# Copy application code
COPY . .

# Copy built frontend from stage 1
COPY --from=frontend-build /build/dist /app/comicarr/frontend/dist

# Make entrypoint executable
RUN chmod +x /app/comicarr/docker/entrypoint.sh

VOLUME /config /comics /manga /downloads
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -sf http://localhost:8090/auth/check_session || exit 1

STOPSIGNAL SIGTERM

ENTRYPOINT ["/app/comicarr/docker/entrypoint.sh"]
