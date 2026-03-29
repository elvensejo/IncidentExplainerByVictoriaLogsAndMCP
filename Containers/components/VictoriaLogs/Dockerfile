FROM golang:1.26.1-bookworm AS db_builder

WORKDIR /db

ARG DB_VERSION=1.48.0

RUN apt-get update && apt-get install -y git make build-essential && git clone https://github.com/VictoriaMetrics/VictoriaLogs && \
cd VictoriaLogs && git checkout v${DB_VERSION} && make victoria-logs

FROM debian:bookworm-slim AS os_builder

WORKDIR /app 

COPY --from=db_builder /db/VictoriaLogs/bin/victoria-logs /app/

ENV PORT=9428

ENTRYPOINT ["/app/victoria-logs"]
CMD ["-storageDataPath=victoria-logs-data"]

EXPOSE ${PORT}