# Stage 1: Frontend build
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend build
FROM python:3.12-slim AS backend-build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --compile-bytecode
COPY . .

# Stage 3: Runtime
FROM python:3.12-slim AS runtime
WORKDIR /opt/comicarr
RUN apt-get update && apt-get install -y --no-install-recommends \
    git p7zip-full unrar-free gosu \
    && rm -rf /var/lib/apt/lists/*
COPY --from=backend-build /app /opt/comicarr
COPY --from=frontend-build /app/frontend/dist /opt/comicarr/frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENV PATH="/opt/comicarr/.venv/bin:$PATH"
EXPOSE 8090
VOLUME ["/config", "/comics"]
ENTRYPOINT ["/entrypoint.sh"]
CMD []
