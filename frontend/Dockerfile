# ============================================================================
# AI Werewolf — Frontend (Next.js) Dockerfile
# ============================================================================
FROM node:20-alpine AS base

WORKDIR /app

# Dependencies
COPY package.json package-lock.json* ./
RUN npm ci --legacy-peer-deps 2>/dev/null || npm install --legacy-peer-deps

# Build
COPY . ./
RUN npm run build

# Production runtime
FROM node:20-alpine AS runtime

WORKDIR /app

RUN addgroup -S werewolf && adduser -S werewolf -G werewolf

COPY --from=base --chown=werewolf:werewolf /app/package.json ./
COPY --from=base --chown=werewolf:werewolf /app/node_modules ./node_modules
COPY --from=base --chown=werewolf:werewolf /app/.next ./.next
COPY --from=base --chown=werewolf:werewolf /app/public ./public
COPY --from=base --chown=werewolf:werewolf /app/next.config.* ./

USER werewolf

EXPOSE 3001

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:3001 > /dev/null || exit 1

ENV NODE_ENV=production

CMD ["npx", "next", "start", "--port", "3001"]
