# Build stage
FROM node:20-slim AS build-stage

WORKDIR /app

COPY apps/web/package*.json ./
RUN npm install

COPY apps/web/. .
RUN npm run build

# Production stage
FROM nginx:stable-alpine

# Copy build artifacts
COPY --from=build-stage /app/dist /usr/share/nginx/html

# Add nginx config for routing and proxying
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
