FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    DATA_DIR=/app/data \
    HTTP_HOST=0.0.0.0 \
    HTTP_PORT=3000

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY src ./src
COPY scripts ./scripts
RUN mkdir -p /app/data && chown -R node:node /app/data

USER node
VOLUME ["/app/data"]
EXPOSE 3000

HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.HTTP_PORT||3000)+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "src/index.js"]
