# syntax=docker/dockerfile:1

# --- Build stage ------------------------------------------------------------
FROM node:22-alpine AS builder

WORKDIR /build

# Copy manifests first so a dependency install is cached independently of
# source changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines env vars at build time, so the API base URL is a build argument,
# not a runtime one. A different backend means a different image.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build


# --- Runtime stage ----------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null || exit 1
