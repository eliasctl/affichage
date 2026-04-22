FROM node:22-alpine AS builder

WORKDIR /app

RUN apk add --no-cache python3 make g++

COPY package*.json ./
RUN npm ci --omit=dev

FROM node:22-alpine

WORKDIR /app

COPY --from=builder /app/node_modules ./node_modules
COPY . .

RUN mkdir -p static/uploads static/icons static/videos data

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=3s --retries=2 \
  CMD wget -q --spider http://localhost:8000/api/hash || exit 1

CMD ["node", "app.js"]
