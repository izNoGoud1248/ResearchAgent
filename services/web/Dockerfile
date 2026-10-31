# Build the UI, then serve it with nginx, which also forwards /api to the API service.
FROM node:24-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

FROM nginx:1.29-alpine
# The image fills ${...} in templates at startup. nginx's own DNS lookups skip search domains,
# so Kubernetes sets API_HOST to the API service's full name.
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 API_HOST=api
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY securityHeaders.conf /etc/nginx/snippets/securityHeaders.conf
COPY --from=build /web/dist /usr/share/nginx/html
