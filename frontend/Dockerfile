# Medify frontend — Next.js 14 standalone (DOC-07 §١)
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG NEXT_PUBLIC_SHOW_SPEC_IDS=false
ARG NEXT_PUBLIC_WS_BASE=
ARG API_INTERNAL_URL=http://backend:8000
ENV NEXT_PUBLIC_SHOW_SPEC_IDS=$NEXT_PUBLIC_SHOW_SPEC_IDS \
    NEXT_PUBLIC_WS_BASE=$NEXT_PUBLIC_WS_BASE \
    API_INTERNAL_URL=$API_INTERNAL_URL
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
