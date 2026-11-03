# syntax=docker/dockerfile:1.7

# ---- Build stage: compile the SPA into static files ------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# npm ci installs exactly what package-lock.json says (integrity-checked). --ignore-scripts:
# no dependency gets to run install hooks (none of these need them).
RUN --mount=type=cache,target=/root/.npm \
    npm ci --ignore-scripts --no-audit --no-fund
COPY . .
# Links to the operator UIs, baked in at build time (Vite inlines import.meta.env).
ARG VITE_JAEGER_URL=http://localhost:16686
ARG VITE_FLOWER_URL=http://localhost:5555
RUN VITE_JAEGER_URL=$VITE_JAEGER_URL VITE_FLOWER_URL=$VITE_FLOWER_URL npm run build

# ---- Runtime stage: static files behind nginx, no root, no Node ------------------
FROM nginxinc/nginx-unprivileged:1.30-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
