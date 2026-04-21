# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS deps
WORKDIR /app
COPY apps/web/package.json ./package.json
COPY apps/web/.npmrc ./.npmrc
RUN npm install --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ ./
# NEXT_PUBLIC_* vars are inlined into the client bundle at `next build`
# time, so they MUST be present in the builder stage's environment —
# runtime env on the runner stage is too late. compose.yml passes the
# value through `build.args`; the default keeps local dev working when
# building outside compose.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -S atlas && adduser -S atlas -G atlas
COPY --from=builder --chown=atlas:atlas /app/public ./public
COPY --from=builder --chown=atlas:atlas /app/.next/standalone ./
COPY --from=builder --chown=atlas:atlas /app/.next/static ./.next/static

USER atlas
EXPOSE 3000

# Use 127.0.0.1 (not "localhost") because alpine's wget resolves localhost
# to IPv6 first, but Next.js standalone binds IPv4-only on 0.0.0.0 — the
# IPv6 connect attempt gets refused and the healthcheck flaps unhealthy
# even though the app is serving fine.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:3000 || exit 1

CMD ["node", "server.js"]
