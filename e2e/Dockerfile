FROM node:20-bookworm

WORKDIR /e2e

COPY package*.json ./
RUN npm install && npx playwright install --with-deps chromium


COPY playwright.config.js ./
COPY tests ./tests

CMD ["npx", "playwright", "test", "--reporter=line"]
