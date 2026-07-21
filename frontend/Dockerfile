FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# Rendered to /etc/nginx/conf.d/default.conf at container start by the nginx
# entrypoint's envsubst step, substituting ${ORCHESTRATOR_URL}.
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE 80
