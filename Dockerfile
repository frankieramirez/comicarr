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
RUN useradd --uid 1001 --create-home comicarr
COPY --from=backend-build /app /opt/comicarr
COPY --from=frontend-build /app/frontend/dist /opt/comicarr/frontend/dist
USER comicarr
EXPOSE 8090
VOLUME ["/config", "/comics"]
ENTRYPOINT ["python", "Comicarr.py"]
CMD ["--nolaunch", "--datadir", "/config"]
