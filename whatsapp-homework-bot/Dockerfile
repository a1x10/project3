FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    RUNNING_IN_DOCKER=1 \
    DATA_DIR=/app/data \
    HTTP_HOST=0.0.0.0 \
    HTTP_PORT=3000

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY package.json package-lock.json ./
# Зависимости + Chromium для скриншотов дневника BilimClass (ровно та версия, что нужна playwright-core,
# вместе с системными библиотеками) + шрифты, чтобы на скриншоте были видны русские и казахские буквы
RUN npm ci --omit=dev \
  && npx playwright-core install --with-deps chromium \
  && apt-get install -y --no-install-recommends fonts-noto-core fonts-noto-color-emoji \
  && rm -rf /var/lib/apt/lists/* \
  && npm cache clean --force

COPY src ./src
COPY scripts ./scripts
COPY assets ./assets
COPY web ./web
RUN mkdir -p /app/data && chown -R node:node /app/data

USER node
VOLUME ["/app/data"]
EXPOSE 3000

HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.HTTP_PORT||3000)+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "src/index.js"]
