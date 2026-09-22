#!/usr/bin/env bash
#
# setup.sh — one-command onboarding (architecture-standards REPO-BASELINE.md §3).
#
# Usage:
#   ./scripts/setup.sh            check prerequisites, install the git hook, report
#   ./scripts/setup.sh --check    strict: a missing secret scanner is a failure
#
# What it does: names every prerequisite with an install pointer, says which parts of
# the repository each one unlocks (nothing here needs all of them), installs the
# pre-commit secret-scan hook P5 makes mandatory, and runs the fast checks that need
# no GPU and no simulation image. What it deliberately does not do: build the
# simulation image (tens of minutes, see docs/adr/0004) or create secrets — the only
# secret this repository touches is authservice's signing key, generated per machine
# (docker/.env.example says how).

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

STRICT=0
[ "${1:-}" = "--check" ] && STRICT=1

red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
amber() { printf '\033[0;33m%s\033[0m\n' "$*"; }
dim()   { printf '\033[0;90m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[1m%s\033[0m\n' "$*"; }

DEGRADED=0
HAVE_DOTNET=0
HAVE_PYTHON=0

# ── 1. Prerequisites ─────────────────────────────────────────────────────────
step "1. Prerequisites (each one is optional; each unlocks part of the repo)"

if command -v dotnet >/dev/null 2>&1 && dotnet --list-sdks 2>/dev/null | grep -q '^8\.'; then
  green "  .NET 8 SDK — backend/ builds and tests."
  HAVE_DOTNET=1
else
  amber "  .NET 8 SDK not found — needed for backend/ (SwarmApi.Api)."
  echo  "    Install: https://dotnet.microsoft.com/download/dotnet/8.0"
  dim   "    Ubuntu 24.04: sudo apt-get install dotnet-sdk-8.0 (from the Ubuntu archive)"
fi

if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  green "  python3 $(python3 -c 'import platform; print(platform.python_version())') — swarm_coordination/ and mcp_server/ tests."
  HAVE_PYTHON=1
else
  amber "  python3 >= 3.10 not found — needed for swarm_coordination/ and mcp_server/."
  echo  "    Install: https://www.python.org/downloads/"
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  green "  docker compose — the simulation stack (docker/docker-compose.yml)."
else
  amber "  docker compose v2 not found — needed only for the simulation stack."
  echo  "    Install: https://docs.docker.com/get-docker/"
fi

# ── 2. Secret scanner ────────────────────────────────────────────────────────
step "2. Secret scanner"

if command -v gitleaks >/dev/null 2>&1; then
  green "  gitleaks on PATH — the hook will use it directly."
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  green "  gitleaks not on PATH, but Docker is running — the hook falls back to the"
  dim   "  same container image CI uses (ghcr.io/gitleaks/gitleaks)."
else
  DEGRADED=1
  amber "  No secret scanner available."
  echo  "  The hook installed below REFUSES TO COMMIT without one — that is by design"
  echo  "  (P5), not a bug to work around. Install one of:"
  echo  "    • gitleaks   https://github.com/gitleaks/gitleaks#installing"
  echo  "    • Docker     https://docs.docker.com/get-docker/"
fi

# ── 3. Git hooks ─────────────────────────────────────────────────────────────
step "3. Git hooks"

HOOK_SRC="${REPO_ROOT}/scripts/hooks/pre-commit"
HOOK_DST="$(git rev-parse --git-path hooks)/pre-commit"
mkdir -p "$(dirname "${HOOK_DST}")"

if [ -e "${HOOK_DST}" ] && ! cmp -s "${HOOK_SRC}" "${HOOK_DST}"; then
  cp "${HOOK_DST}" "${HOOK_DST}.backup"
  dim "  Existing hook backed up to pre-commit.backup"
fi
cp "${HOOK_SRC}" "${HOOK_DST}"
chmod +x "${HOOK_DST}"
green "  pre-commit installed → ${HOOK_DST}"

# ── 4. Fast checks ───────────────────────────────────────────────────────────
step "4. Fast checks (no GPU, no simulation image)"

if [ "${HAVE_PYTHON}" -eq 1 ] && python3 -m pytest --version >/dev/null 2>&1; then
  if (cd swarm_coordination && python3 -m pytest -q >/dev/null 2>&1); then
    green "  swarm_coordination: pytest green."
  else
    amber "  swarm_coordination: pytest failed — run it to see why: cd swarm_coordination && pytest"
  fi
else
  dim "  swarm_coordination: skipped (pip install ruff pytest to enable)."
fi

if [ "${HAVE_DOTNET}" -eq 1 ]; then
  dim "  backend: run \`dotnet test backend/SwarmPlatform.sln\` (not run here — it restores packages)."
fi

# ── Summary ──────────────────────────────────────────────────────────────────
step "Ready"

echo "  cd backend && dotnet run --project src/SwarmApi.Api    API + dashboard, simulated swarm"
echo "  cd docker && docker compose up --build                 full simulation stack (headless)"
echo "  ./scripts/scan-secrets.sh                              mirror the CI secret scan"

if [ "${DEGRADED}" -eq 1 ]; then
  echo
  if [ "${STRICT}" -eq 1 ]; then
    red "setup --check: a secret scanner is required and none was found."
    exit 1
  fi
  amber "Setup finished, but committing will be refused until a scanner is installed."
fi
