FROM node:20-alpine
WORKDIR /app
COPY package.json server.js db.js ./
COPY public ./public
ENV PORT=8787 HOST=0.0.0.0 DATA_DIR=/data
VOLUME /data
EXPOSE 8787
CMD ["node", "server.js"]
