FROM golang:1.26.1-alpine3.23 as mcp_builder

WORKDIR /server

ARG SERVER_VERSION=1.8.0

RUN apk add --no-cache git make bash && git clone https://github.com/VictoriaMetrics-Community/mcp-victorialogs.git && \
cd mcp-victorialogs && git checkout v${SERVER_VERSION} && CGO_ENABLED=0 GOOS=linux make build

FROM alpine as os_builder

WORKDIR /app 

RUN apk add --no-cache ca-certificates

COPY --from=mcp_builder /server/mcp-victorialogs/mcp-victorialogs /app

ENTRYPOINT ["/app/mcp-victorialogs"]
