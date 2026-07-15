# syntax=docker/dockerfile:1

# ---- Frontend build ----
FROM node:22-slim AS frontend-build
WORKDIR /build
RUN npm install -g pnpm
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ---- Runtime: uv-managed Python + nginx in one container ----
FROM debian:trixie-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

WORKDIR /app/backend

# Dependencies first, project second, so code edits don't bust the dep layer.
ENV UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/opt/uv/python
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY backend/README.md ./
COPY backend/migrations ./migrations
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY --from=frontend-build /build/dist /app/frontend/dist

ENV ORACLE_DB_PATH=/data/oracle.db \
    ORACLE_UPLOADS_DIR=/data/uploads \
    ORACLE_VECTOR_DB_PATH=/data/vectors \
    ORACLE_MODEL_CACHE_DIR=/data/models
VOLUME /data

COPY <<'EOF' /etc/nginx/conf.d/oracle.conf
server {
    listen 80;
    client_max_body_size 100m;

    root /app/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

COPY <<'EOF' /app/start.sh
#!/bin/bash
set -e
/app/backend/.venv/bin/oracle-server &
nginx -g 'daemon off;' &
wait -n
EOF
RUN chmod +x /app/start.sh

EXPOSE 80
CMD ["/app/start.sh"]
