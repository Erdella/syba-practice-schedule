# SYBA North Fargo Practice Scheduler
# PocketBase serves the static HTML, the REST API, the admin UI, and stores
# data in a SQLite DB at /pb_data (volume-mounted by docker-compose.yml).
FROM alpine:3.19

ARG PB_VERSION=0.22.21

RUN apk add --no-cache ca-certificates unzip wget
RUN ARCH=$(uname -m) \
 && case "$ARCH" in \
        x86_64)  PB_ARCH=amd64 ;; \
        aarch64) PB_ARCH=arm64 ;; \
        armv7l)  PB_ARCH=armv7 ;; \
        *) echo "Unsupported architecture: $ARCH" && exit 1 ;; \
    esac \
 && wget -q -O /tmp/pb.zip \
      "https://github.com/pocketbase/pocketbase/releases/download/v${PB_VERSION}/pocketbase_${PB_VERSION}_linux_${PB_ARCH}.zip" \
 && unzip /tmp/pb.zip -d /usr/local/bin/ \
 && rm /tmp/pb.zip \
 && chmod +x /usr/local/bin/pocketbase

WORKDIR /pb
COPY pb_public/    /pb/pb_public/
COPY pb_migrations/ /pb/pb_migrations/

EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=3s \
  CMD wget -qO- http://127.0.0.1:8090/api/health >/dev/null || exit 1

CMD ["pocketbase", "serve", "--http=0.0.0.0:8090", "--dir=/pb_data", "--publicDir=/pb/pb_public", "--migrationsDir=/pb/pb_migrations"]
