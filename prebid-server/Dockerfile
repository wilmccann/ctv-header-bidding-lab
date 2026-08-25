# Builds a custom Prebid Server (Go) image with the ortbvast Bouncer
# (pre-bid bot/IP filter) and Enricher (identity decoration) hooks compiled
# in. PBS modules are compile-time only — there is no plugin-loading
# mechanism at runtime — so any pre-auction logic beyond what pbs.yaml can
# express requires a from-source build like this instead of pulling the
# stock prebid/prebid-server image.
#
# Build: docker compose build   (from prebid-server/, via the compose file's
#   `build:` block below) — first build clones + compiles all of Prebid
#   Server, which takes several minutes and needs network access.
#   Subsequent builds are cached unless modules/ortbvast or PBS_VERSION
#   change.
#
# NOTE: modules/ortbvast/{bouncer,enricher}/module.go import
# github.com/prebid/prebid-server/v4/hooks/hookstage, matching the module
# path declared in go.mod at tag v4.8.0. If PBS_VERSION is bumped to a tag
# with a different major version, update those import paths (and the Go
# toolchain version below, per that tag's go.mod `go` directive) first.

FROM golang:1.25-bookworm AS build

ARG PBS_VERSION=v4.8.0

WORKDIR /src
RUN git clone --depth 1 --branch ${PBS_VERSION} \
      https://github.com/prebid/prebid-server.git .

# Vendor the custom hooks into the module tree PBS's own codegen scans.
COPY modules/ortbvast ./modules/ortbvast

# Regenerate modules/builder.go so it registers ortbvast.bouncer and
# ortbvast.enricher alongside PBS's built-in modules, then compile.
RUN go generate ./modules/... \
 && CGO_ENABLED=0 go build -o /out/prebid-server .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Match the volume-mount layout the repo already used against the stock
# image (./stored_requests → /usr/local/bin/stored_requests,
# ./pbs.yaml → /etc/config/pbs.yaml) so docker-compose.yml's volumes:
# block doesn't need to change.
WORKDIR /usr/local/bin
COPY --from=build /out/prebid-server /usr/local/bin/prebid-server
COPY --from=build /src/static /usr/local/bin/static

EXPOSE 8000 6060
ENTRYPOINT ["/usr/local/bin/prebid-server"]
