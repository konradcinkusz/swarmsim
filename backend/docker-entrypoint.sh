#!/bin/sh
# Entrypoint of docker/Dockerfile.api. SwarmApi.Api runs as the image's non-root `app`
# user (P6); the container starts as root only to hand a mounted volume to that user, the
# way the official Postgres image does. Fly.io mounts volumes owned by root, and the
# scenario-run store (ScenarioRuns__Directory, docs/adr/0011) must be able to write there.
set -eu

if [ "$(id -u)" = "0" ]; then
  if [ -n "${ScenarioRuns__Directory:-}" ]; then
    mkdir -p "${ScenarioRuns__Directory}"
    chown app:app "${ScenarioRuns__Directory}"
  fi
  exec setpriv --reuid=app --regid=app --init-groups dotnet SwarmApi.Api.dll "$@"
fi

exec dotnet SwarmApi.Api.dll "$@"
