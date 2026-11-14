FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

ARG VITE_CONSOLE_API_URL=http://localhost:8000
ARG VITE_OWNER_TOKEN=demo-owner-token
ARG VITE_DEMO_OWNER_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
ARG VITE_RIGORIX_HMAC_KEY=bursar-demo-operator-held-evidence-key-4c1f9a
ENV VITE_CONSOLE_API_URL=$VITE_CONSOLE_API_URL \
    VITE_OWNER_TOKEN=$VITE_OWNER_TOKEN \
    VITE_DEMO_OWNER_KEY=$VITE_DEMO_OWNER_KEY \
    VITE_RIGORIX_HMAC_KEY=$VITE_RIGORIX_HMAC_KEY \
    VITE_FORCE_MOCK=0
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
