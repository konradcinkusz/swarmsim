#!/usr/bin/env bash
# Exercises docker/entrypoint.sh against stub `ros2`, `gz`, `tmux` and `px4`
# executables, so CI can check its logic without the (never CI-built) sim image — see
# docs/adr/0004-ci-scope-for-simulation-stack.md. It proves what the entrypoint
# decides (which configs, which PX4 command lines, which failures it refuses), not
# that PX4 or Gazebo then behave; that is the SITL smoke's job.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENTRYPOINT="${REPO_ROOT}/docker/entrypoint.sh"
FAILURES=0

fail() { echo "FAIL: $*" >&2; FAILURES=$((FAILURES + 1)); }
pass() { echo "ok:   $*"; }

# Builds a fake image layout under $1: /opt/swarmsim, /opt/PX4-Autopilot, a ROS setup
# file, and stub executables on a private PATH. The tmux stub records every call and
# reports every session as gone, so the entrypoint's monitor loop exits right after
# spawning instead of running forever.
make_sandbox() {
  local root="$1"
  mkdir -p "${root}/swarmsim/worlds" "${root}/swarmsim/px4-configs" \
    "${root}/px4/build/px4_sitl_default/bin" "${root}/bin" "${root}/logs"
  cp "${REPO_ROOT}"/simulation/px4-configs/*.env "${REPO_ROOT}"/simulation/px4-configs/px4-rc.params \
    "${root}/swarmsim/px4-configs/"
  cp "${REPO_ROOT}"/simulation/worlds/*.sdf "${root}/swarmsim/worlds/"
  : > "${root}/ros_setup.bash"
  : > "${root}/coordination_setup.bash"
  printf '#!/bin/sh\nexit 0\n' > "${root}/px4/build/px4_sitl_default/bin/px4"

  cat > "${root}/bin/ros2" <<'STUB'
#!/bin/sh
exec sleep 30
STUB
  cat > "${root}/bin/gz" <<STUB
#!/bin/sh
if [ "\$1" = "topic" ]; then echo "/world/swarmsim_empty/clock"; exit 0; fi
echo "gz \$*" >> "${root}/calls.log"
exec sleep 30
STUB
  cat > "${root}/bin/tmux" <<STUB
#!/bin/sh
echo "tmux \$*" >> "${root}/calls.log"
case "\$1" in has-session) exit 1 ;; esac
exit 0
STUB
  chmod +x "${root}"/bin/* "${root}/px4/build/px4_sitl_default/bin/px4"
}

run_entrypoint() {
  local root="$1"; shift
  env -i PATH="${root}/bin:/usr/bin:/bin" HOME="${root}" \
    SWARMSIM_ROOT="${root}/swarmsim" PX4_DIR="${root}/px4" \
    ROS_SETUP="${root}/ros_setup.bash" COORDINATION_SETUP="${root}/coordination_setup.bash" \
    SWARMSIM_LOG_DIR="${root}/logs" \
    GZ_WAIT_SECONDS=5 "$@" \
    bash "${ENTRYPOINT}" > "${root}/out.log" 2>&1 || echo "exit=$?" >> "${root}/out.log"
}

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# check <description> <command...>: pass when the command succeeds.
check() {
  local description="$1"; shift
  if "$@"; then pass "${description}"; else fail "${description}"; fi
}
# refute <description> <command...>: pass when the command fails.
refute() {
  local description="$1"; shift
  if "$@"; then fail "${description}"; else pass "${description}"; fi
}
spawn_count() { grep -c 'tmux new-session -d -s drone_' "$1/calls.log" || true; }
spawned_sessions() {
  grep -o 'new-session -d -s drone_[0-9]*' "$1/calls.log" | awk '{print $4}' | tr '\n' ' '
}

# 1. All five configs spawn, each as `px4 -i N` in standalone mode at its own pose.
make_sandbox "${WORK}/all"
run_entrypoint "${WORK}/all"
check "five drones spawn by default" test "$(spawn_count "${WORK}/all")" = 5
check "drone_3 runs as instance 2 at y=6 in standalone mode" \
  grep -q 'new-session -d -s drone_3 .*PX4_GZ_STANDALONE=1 .*PX4_GZ_MODEL_POSE=0\\,6\\,0\\,0\\,0\\,0 .*px4 -i 2' \
  "${WORK}/all/calls.log"
check "PX4 finds the swarm's px4-rc.params first on its PATH" \
  grep -q 'new-session -d -s drone_1 .*env PATH=[^ ]*/swarmsim/px4-configs:' "${WORK}/all/calls.log"
check "one Gazebo server on the configured world" \
  grep -q 'gz sim --verbose=1 -r -s .*/swarmsim_empty.sdf' "${WORK}/all/calls.log"
refute "no GUI by default" grep -q 'gz sim -g' "${WORK}/all/calls.log"

check "coordination starts for all five drones, with MAVROS, from the same configs" \
  grep -q 'new-session -d -s coordination .*spawn_swarm.launch.py.*with_mavros:=true.*px4-configs.*drone_count:=5' \
  "${WORK}/all/calls.log"

# 2. SWARM_DRONE_COUNT limits the swarm, in numeric order.
make_sandbox "${WORK}/two"
run_entrypoint "${WORK}/two" SWARM_DRONE_COUNT=2
check "SWARM_DRONE_COUNT=2 spawns drone_1 and drone_2" \
  test "$(spawned_sessions "${WORK}/two")" = "drone_1 drone_2 "
check "coordination is told the same count" \
  grep -q 'new-session -d -s coordination .*drone_count:=2' "${WORK}/two/calls.log"

# 2b. SWARM_COORDINATION=0 leaves PX4 bare.
make_sandbox "${WORK}/bare"
run_entrypoint "${WORK}/bare" SWARM_COORDINATION=0
refute "SWARM_COORDINATION=0 starts no coordination session" \
  grep -q 'new-session -d -s coordination' "${WORK}/bare/calls.log"

# 3. HEADLESS=0 adds the GUI.
make_sandbox "${WORK}/gui"
run_entrypoint "${WORK}/gui" HEADLESS=0
check "HEADLESS=0 starts the GUI" grep -q 'gz sim -g' "${WORK}/gui/calls.log"

# 4. Refusals: no drone configs, a bad HEADLESS, and a count larger than the configs.
make_sandbox "${WORK}/empty"
rm "${WORK}"/empty/swarmsim/px4-configs/drone_*.env
run_entrypoint "${WORK}/empty"
check "missing drone configs are refused" grep -q 'no drone_\*.env found' "${WORK}/empty/out.log"
check "missing drone configs exit non-zero" grep -q 'exit=1' "${WORK}/empty/out.log"

make_sandbox "${WORK}/noparams"
rm "${WORK}/noparams/swarmsim/px4-configs/px4-rc.params"
run_entrypoint "${WORK}/noparams"
check "a missing px4-rc.params is refused" grep -q 'px4-rc.params is missing' "${WORK}/noparams/out.log"
refute "and no drone is spawned without it" grep -qs 'new-session -d -s drone_' "${WORK}/noparams/calls.log"

make_sandbox "${WORK}/badheadless"
run_entrypoint "${WORK}/badheadless" HEADLESS=maybe
check "invalid HEADLESS is refused" grep -q 'HEADLESS must be 1' "${WORK}/badheadless/out.log"

make_sandbox "${WORK}/toomany"
run_entrypoint "${WORK}/toomany" SWARM_DRONE_COUNT=9
check "SWARM_DRONE_COUNT above the config count is refused" \
  grep -q 'only 5 drone config' "${WORK}/toomany/out.log"

if (( FAILURES > 0 )); then
  echo "${FAILURES} entrypoint check(s) failed" >&2
  exit 1
fi
echo "all entrypoint checks passed"
