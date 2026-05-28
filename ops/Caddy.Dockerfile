# Build the SPA and bundle it into a Caddy image that also reverse-proxies the API.
# Build context is the repo root (see ops/docker-compose.prod.yml).
FROM node:20-alpine AS build
WORKDIR /app
RUN npm install -g pnpm@9
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
# No VITE_API_BASE here on purpose: the client defaults to the relative "/api",
# so the SPA calls the same origin Caddy serves it from (keeps auth cookies same-site).
RUN pnpm build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
COPY ops/Caddyfile /etc/caddy/Caddyfile
