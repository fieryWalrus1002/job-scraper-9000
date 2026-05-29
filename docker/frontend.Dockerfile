# In prod we'll be using Azure Static Web Apps, so a Dockerfile is not used.
# However, I want to do some local integration testing with the front-end and back-end together,
# so this Dockerfile is for local development use only. It will not be used in production.

# STAGE 1: Build the static assets
FROM node:22-alpine AS builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# STAGE 2: Serve them using an ultra-lightweight Nginx container
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
