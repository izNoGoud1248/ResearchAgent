# Build the UI, then serve it with nginx, which also forwards /api to the API service.
FROM node:24-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY securityHeaders.conf /etc/nginx/snippets/securityHeaders.conf
COPY --from=build /web/dist /usr/share/nginx/html
