FROM node:24-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci
COPY . .

ARG VITE_API_BASE_URL=/api
ARG VITE_WORKOS_CLIENT_ID=client_01KT21GY6QP06ZC02SWM7JKX20
ARG VITE_WORKOS_REDIRECT_URI=http://localhost:5173
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_WORKOS_CLIENT_ID=${VITE_WORKOS_CLIENT_ID} \
    VITE_WORKOS_REDIRECT_URI=${VITE_WORKOS_REDIRECT_URI}
ARG VITE_WORKOS_DEV_MODE=false
ENV VITE_WORKOS_DEV_MODE=${VITE_WORKOS_DEV_MODE}
RUN npm run build

FROM nginx:stable-alpine AS runtime
ENV BACKEND_ORIGIN=http://host.docker.internal:9000
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
