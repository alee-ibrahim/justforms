# syntax=docker/dockerfile:1
# The build stage runs on the build host (the SPA is the same on every platform), so only the
# small nginx stage runs under emulation when building other architectures.
FROM --platform=$BUILDPLATFORM node:24-alpine AS build
# pnpm is provisioned by corepack from the "packageManager" field in package.json.
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# Unprivileged nginx (uid 101, no root master, pid and temp files under /tmp). nginx.conf still
# listens on port 80: Docker lets non-root processes bind it, and the Helm chart sets the
# net.ipv4.ip_unprivileged_port_start sysctl to 0 for the pod.
FROM nginxinc/nginx-unprivileged:1.29-alpine
# The upstream image lags behind Alpine security updates; take them at build time.
USER root
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY docker/security-headers.inc /etc/nginx/snippets/justforms-security-headers.inc
COPY --chmod=0755 docker/16-justforms-csp.envsh /docker-entrypoint.d/16-justforms-csp.envsh
COPY --chmod=0755 docker/17-justforms-proxy.envsh /docker-entrypoint.d/17-justforms-proxy.envsh
COPY --from=build /app/dist /usr/share/nginx/html
# BACKEND_URL is resolved at request time (resolver from /etc/resolv.conf), so it must be a
# name the DNS server answers for (on Kubernetes: the fully qualified service name).
ENV BACKEND_URL=http://backend:8000 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    JUSTFORMS_THAANA_FONT_CSS_URL="https://dvfonts.yashau.com/css2?family=Faruma&display=swap" \
    JUSTFORMS_CAPTCHA_PROVIDER=none \
    JUSTFORMS_REAL_IP_FROM="" \
    JUSTFORMS_REAL_IP_HEADER=X-Forwarded-For \
    JUSTFORMS_HSTS=auto
EXPOSE 80
USER 101
